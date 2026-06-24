"""추세추종 전략 비용 포함 백테스트 — 3모드(gainers/largecap/watchlist) 검증.

종가매매 백테스트 인프라 재사용:
  - backtest_dynamic.get_broad_universe / get_ohlcv (KOSPI 시총 상위 캐시 + FDR OHLCV)
  - backtest_walkforward.Costs / metrics (왕복비용 차감, 기대값/손익비/PF/P90)
  - trend_mcp.signals (진입 게이트·점수·손절/목표, 청산은 트레일+MA50이탈)

진입(신호일 익일 시가) → 첫 목표 30% 익절 + 나머지 ATR 트레일/MA50 이탈 청산 → net 손익.
재료/실적/뉴스/외인수급은 point-in-time 한계로 백테스트 제외(차트+거래량+RS 코어만).

사용:
  python scripts/backtest_trend.py --mode largecap --start 2025-01-01 --end 2026-05-31
  python scripts/backtest_trend.py --mode gainers
  python scripts/backtest_trend.py --mode watchlist --watchlist 005930,000660
"""
from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    import FinanceDataReader as fdr

from backtest_dynamic import get_broad_universe, get_ohlcv  # noqa: E402
from backtest_walkforward import Costs, metrics              # noqa: E402
from src.mcp_servers.closing_bet_mcp.exit_rules import ratchet_stop, init_stop_price  # noqa: E402
from src.mcp_servers.trend_mcp.signals import (  # noqa: E402
    TrendConfig, entry_signal, atr, moving_average, relative_strength,
)

MIN_VALUE_KRW = 1_000 * 10**8   # 거래대금 floor 1,000억


def _gap_pct(full: list[dict], i: int) -> float:
    if i < 1 or full[i - 1]["close"] <= 0:
        return 0.0
    return (full[i]["close"] - full[i - 1]["close"]) / full[i - 1]["close"] * 100.0


# ─── A/B 변형 노브(검증대기 항목 비교용) ─────────────────────────────────────
V_FIRST_PARTIAL_R: float | None = None   # 첫 30% 익절 지점(R배수). None=cfg.rr(1:3). 1.0=1:1
V_EXIT_MA: int | None = None             # 청산 이평선. None=cfg.ma_support(50). 120 등
V_HARD_STOP_PCT: float = 0.0             # 진입가 -X% 하드 손절(트레일 floor). 0=off
V_RS_TOP_PCT: float | None = None        # RS 게이트: None=절대값(>KOSPI). 0.3=그날 유니버스 RS 상위 30%
# 피라미딩(승자 불타기): 초기 진입 후 +N×R 마다 유닛 추가. 각 유닛=별도 거래로 집계.
V_USE_UNITS: bool = False                 # True=유닛 시뮬(부분익절 off, 트레일/MA 청산). 피라미딩 비교용.
V_PYRAMID_ADDS: int = 0                   # 추가 유닛 수(0=초기 1유닛만)
V_PYRAMID_STEP_R: float = 1.0             # 추가 트리거 간격(R배수): 진입+ k×step×R 도달 시 추가
V_PYRAMID_REGIME_MA: int | None = None    # 피라미딩 레짐 게이트: KOSPI>MA(N)일 때만 불타기 허용. None=항상
V_PYRAMID_REGIME_MOM: tuple | None = None  # 모멘텀 게이트 (days, pct): KOSPI days수익률>pct% 일 때만 불타기
V_PYRAMID_RISING_DAY: bool = False        # True=추가 유닛은 해당 영업일이 양봉(close>open)일 때만 (라이브 _is_rising 의 backtest 대응)
V_BREAKEVEN_TRIGGER_PCT: float | None = None  # 진입가 +X% 도달 시 stop 을 BE(entry)로 끌어올림. None=off
V_BREADTH_MIN_PCT: float | None = None    # 시장 breadth 게이트: 일별 universe 상승비율 < 이 값 일 때 신규진입 차단. None=off


def simulate_trade(full: list[dict], i: int, cfg: TrendConfig, costs: Costs) -> float | None:
    """신호 봉 i 다음날 시가 진입 → 트레일/목표/MA 청산. net 수익률(%) 반환.

    변형 노브: V_FIRST_PARTIAL_R(첫익절 지점), V_EXIT_MA(청산선), V_HARD_STOP_PCT(하드손절).
    """
    if i + 1 >= len(full):
        return None
    entry = full[i + 1]["open"]
    if entry <= 0:
        return None
    a = atr(full[:i + 1], cfg.atr_period)
    stop = init_stop_price(entry, a, cfg.atr_k, -cfg.stop_pct)
    first_r = V_FIRST_PARTIAL_R if V_FIRST_PARTIAL_R is not None else cfg.rr
    first_target = entry + first_r * (entry - stop)
    exit_ma = V_EXIT_MA if V_EXIT_MA is not None else cfg.ma_support
    hard_floor = entry * (1 - V_HARD_STOP_PCT / 100.0) if V_HARD_STOP_PCT > 0 else None
    closes = [b["close"] for b in full]
    peak = entry
    realized = 0.0       # 가중 실현 수익률(%)
    rem = 1.0
    partial = False

    end = min(i + 1 + cfg.max_hold, len(full))
    last_j = i + 1
    for j in range(i + 1, end):
        b = full[j]
        last_j = j
        # 첫 목표 도달(장중 고가) → 부분 익절
        if not partial and b["high"] >= first_target:
            realized += (cfg.partial_pct / 100) * (first_target - entry) / entry * 100
            rem -= cfg.partial_pct / 100
            partial = True
        # 트레일 갱신(종가)
        peak, stop = ratchet_stop(entry, peak, stop, b["close"], a, cfg.atr_k, -cfg.stop_pct)
        # Break-even: 장중 고가가 entry +X% 도달했으면 stop 을 entry 로 끌어올림(floor) — 손실 진입 방지
        if V_BREAKEVEN_TRIGGER_PCT and b["high"] >= entry * (1 + V_BREAKEVEN_TRIGGER_PCT / 100.0):
            stop = max(stop, entry)
        # 손절/트레일 이탈(장중 저가) — 하드손절은 트레일 floor 로 적용
        eff_stop = max(stop, hard_floor) if hard_floor is not None else stop
        if b["low"] <= eff_stop:
            realized += rem * (eff_stop - entry) / entry * 100
            rem = 0.0
            break
        # 청산 이평선 하방 돌파(종가)
        ma = moving_average(closes[:j + 1], exit_ma)
        if ma is not None and b["close"] < ma:
            realized += rem * (b["close"] - entry) / entry * 100
            rem = 0.0
            break
    if rem > 0:   # 미청산분 → 마지막 종가 청산
        realized += rem * (closes[last_j] - entry) / entry * 100
    return realized - costs.roundtrip_pct


def simulate_units(full: list[dict], i: int, cfg: TrendConfig, costs: Costs,
                   allow_pyramid: bool = True) -> list[float]:
    """피라미딩: 초기 유닛 + 가격 상승 시 추가 유닛. 각 유닛의 net%(공통 트레일/MA 청산) 리스트 반환.

    부분익절 없음(불타기와 상충). 추가 유닛은 진입+ (k+1)×STEP_R×R 도달(장중 고가) 시 그 가격에 진입.
    모든 유닛은 동일 청산(트레일 이탈/MA 하방돌파/보유만기 종가)에서 빠진다 — 공통 트레일 스톱.
    allow_pyramid=False(레짐 게이트 미충족) 면 추가 유닛 없이 초기 1유닛만.
    """
    if i + 1 >= len(full):
        return []
    entry = full[i + 1]["open"]
    if entry <= 0:
        return []
    a = atr(full[:i + 1], cfg.atr_period)
    stop = init_stop_price(entry, a, cfg.atr_k, -cfg.stop_pct)
    exit_ma = V_EXIT_MA if V_EXIT_MA is not None else cfg.ma_support
    closes = [b["close"] for b in full]
    R = entry - stop
    add_prices = ([entry + (k + 1) * V_PYRAMID_STEP_R * R for k in range(V_PYRAMID_ADDS)]
                  if R > 0 and allow_pyramid else [])
    units = [entry]
    nxt = 0
    peak = entry
    end = min(i + 1 + cfg.max_hold, len(full))
    last_j = i + 1
    exit_price = None
    for j in range(i + 1, end):
        b = full[j]; last_j = j
        # rising-day 가드: True 면 양봉(close>open)일 때만 추가 — 라이브 _is_rising(cur,opn) 의 backtest 대응
        can_add = (b["close"] > b["open"]) if V_PYRAMID_RISING_DAY else True
        if can_add:
            while nxt < len(add_prices) and b["high"] >= add_prices[nxt]:
                units.append(add_prices[nxt]); nxt += 1
        peak, stop = ratchet_stop(entry, peak, stop, b["close"], a, cfg.atr_k, -cfg.stop_pct)
        # Break-even floor (단일유닛 모드와 동일 — 초기 진입가 기준)
        if V_BREAKEVEN_TRIGGER_PCT and b["high"] >= entry * (1 + V_BREAKEVEN_TRIGGER_PCT / 100.0):
            stop = max(stop, entry)
        if b["low"] <= stop:
            exit_price = stop; break
        ma = moving_average(closes[:j + 1], exit_ma)
        if ma is not None and b["close"] < ma:
            exit_price = b["close"]; break
    if exit_price is None:
        exit_price = closes[last_j]
    nets = [(exit_price - u) / u * 100 - costs.roundtrip_pct for u in units]
    return nets, (last_j - (i + 1))   # (유닛 net% 리스트, 보유 영업일수)


_UNIV_CACHE: dict = {}   # A/B 스윕에서 유니버스 재로드 방지


def run(mode: str, start: str, end: str, watchlist: list[str], costs: Costs, cfg: TrendConfig) -> list[tuple[float, float]]:
    """반환: 진입별 (gap_pct, net_pct). gap_pct = 진입일 시가 / 신호일 종가 − 1 (프리장 갭의 백테스트 대용)."""
    key = (mode, tuple(watchlist), start, end, cfg_top)
    if key in _UNIV_CACHE:
        dates, kospi_close, broad = _UNIV_CACHE[key]
        print(f"기간 {start}~{end}: {len(dates)} 영업일 | mode={mode} | {costs} (캐시 재사용 {len(broad)}종목)")
    else:
        kospi = fdr.DataReader("^KS11", start, end)
        dates = [d.strftime("%Y%m%d") for d in kospi.index]
        kospi_close = [float(c) for c in kospi["Close"].values]
        print(f"기간 {start}~{end}: {len(dates)} 영업일 | mode={mode} | {costs}")

        if mode == "watchlist":
            universe = watchlist
        else:
            universe = get_broad_universe()           # KOSPI 시총 상위 ~150 (cap 정렬)
            if mode == "largecap":
                universe = universe[:cfg_top]
        broad = {}
        for idx, code in enumerate(universe, 1):
            h = get_ohlcv(code, dates[-1] if dates else end.replace("-", ""), days=320)
            if h:
                broad[code] = h
            if idx % 40 == 0:
                print(f"  유니버스 로드 {idx}/{len(universe)}")
        print(f"  → {len(broad)}종목 로드 완료")
        _UNIV_CACHE[key] = (dates, kospi_close, broad)

    trades: list[tuple[float, float]] = []
    need = (cfg.ma_trend if mode == "gainers" else cfg.ma_slow) + 1
    # KOSPI 종가 시계열(상대강도용)
    for i_day, date_str in enumerate(dates[:-1]):
        if i_day < need:
            continue
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        kospi_upto = kospi_close[:i_day + 1]

        # 후보 종목 모으기
        day_rows = []
        for code, full in broad.items():
            idx = next((k for k, b in enumerate(full) if b["date"] == date_fmt), None)
            if idx is None or idx < need:
                continue
            if full[idx]["value"] < MIN_VALUE_KRW:
                continue
            day_rows.append((code, full, idx))

        if mode == "gainers":   # 당일 등락률 상위 N 로 좁힘
            day_rows.sort(key=lambda r: -_gap_pct(r[1], r[2]))
            day_rows = day_rows[:cfg_top]

        # 시장 breadth 게이트(라이브 _sector_index_rows 의 backtest 대응) —
        # 그날 universe 의 close>open(양봉) 비율로 근사. < V_BREADTH_MIN_PCT 면 신규진입 전부 차단.
        if V_BREADTH_MIN_PCT is not None and day_rows:
            rising = sum(1 for _, full, idx in day_rows if full[idx]["close"] > full[idx]["open"])
            breadth = rising / len(day_rows) if day_rows else 0.0
            if breadth < V_BREADTH_MIN_PCT:
                if (i_day + 1) % 40 == 0:
                    print(f"  [{i_day+1}/{len(dates)}] {date_fmt}: breadth {breadth:.2f} < {V_BREADTH_MIN_PCT} → 진입 차단")
                continue

        # RS 랭킹 모드: 그날 유니버스 RS 상위 N% 만 RS 게이트 통과
        rs_pass_set = None
        if V_RS_TOP_PCT is not None and day_rows:
            rs_vals = [(code, relative_strength([b["close"] for b in full[:idx + 1]], kospi_upto, cfg.rs_days))
                       for code, full, idx in day_rows]
            rs_vals.sort(key=lambda x: -x[1])
            keep = max(1, int(len(rs_vals) * V_RS_TOP_PCT))
            rs_pass_set = {c for c, _ in rs_vals[:keep]}

        for code, full, idx in day_rows:
            rs_pass = (code in rs_pass_set) if rs_pass_set is not None else None
            sig = entry_signal(full[:idx + 1], kospi_upto, cfg, rs_pass=rs_pass)
            if not sig.passed:
                continue
            if idx + 1 >= len(full) or full[idx]["close"] <= 0:
                continue
            gap = (full[idx + 1]["open"] - full[idx]["close"]) / full[idx]["close"] * 100.0
            if V_USE_UNITS:
                allow = True
                if V_PYRAMID_REGIME_MA:
                    kma = moving_average(kospi_upto, V_PYRAMID_REGIME_MA)
                    allow = kma is not None and kospi_upto[-1] > kma
                elif V_PYRAMID_REGIME_MOM:
                    d, pct = V_PYRAMID_REGIME_MOM
                    allow = (len(kospi_upto) > d and kospi_upto[-d - 1] > 0
                             and (kospi_upto[-1] - kospi_upto[-d - 1]) / kospi_upto[-d - 1] * 100 > pct)
                nets_u, _ = simulate_units(full, idx, cfg, costs, allow_pyramid=allow)
                for u_net in nets_u:
                    trades.append((gap, u_net))
            else:
                net = simulate_trade(full, idx, cfg, costs)
                if net is not None:
                    trades.append((gap, net))
        if (i_day + 1) % 40 == 0:
            print(f"  [{i_day+1}/{len(dates)}] {date_fmt}: 누적 진입 {len(trades)}건")
    return trades


def report(nets: list[float], label: str) -> None:
    m = metrics(nets)
    print("\n" + "=" * 78)
    print(f"추세추종 백테스트 — {label} (비용 차감 후)")
    print("=" * 78)
    if not m.get("n"):
        print("  진입 0건")
        return
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
    print(f"  진입 {m['n']}건  승률 {m['win']:.1f}%  기대값 {m['avg']:+.2f}%  중앙 {m['median']:+.2f}%")
    print(f"  손익비(payoff) {po}  PF {pf}  P90 {m['p90']:+.2f}%  P10 {m['p10']:+.2f}%  누적 {m['total']:+.1f}%")
    print("  ※ 비교: closing-bet atr2_h3 OOS 기대값 +1.15% (동일 진입 55/3)")


def report_gapdown_sweep(trades: list[tuple[float, float]], label: str,
                         thresholds=(0.0, 1.0, 2.0, 3.0, 5.0)) -> None:
    """프리장 갭다운 veto 임계값 스윕 — 진입일 시가 갭 < -임계값 인 거래를 제외하고 성과 비교."""
    print("\n" + "=" * 86)
    print(f"갭다운 veto 검증 — {label} (진입일 시가 갭 기준, 비용 차감 후)")
    print("=" * 86)
    print(f"  {'veto(%)':>8} {'진입':>5} {'제외':>4} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>9}")
    base_n = len(trades)
    for thr in thresholds:
        kept = [net for gap, net in trades if thr <= 0 or gap >= -thr]
        m = metrics(kept)
        if not m.get("n"):
            print(f"  {thr:>8.1f} {0:>5} {base_n:>4}  진입 0건")
            continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        tag = "  (veto off)" if thr <= 0 else ""
        print(f"  {thr:>8.1f} {m['n']:>5} {base_n - m['n']:>4} {m['win']:>5.1f}% "
              f"{m['avg']:>+7.2f}% {po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+8.1f}%{tag}")
    print("  ※ veto=0 은 미적용(전체). 임계값↑ → 갭다운 진입 제외. 기대값·손익비·P10(꼬리손실) 개선 여부 확인.")


cfg_top = 100   # 모드별 런타임에 갱신


def report_abtest(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """검증대기 항목 A/B 비교 — 첫익절 1:1 vs 1:3 / 청산선 MA120 vs MA50 / 하드손절 -5% (유니버스 1회 로드)."""
    global V_FIRST_PARTIAL_R, V_EXIT_MA, V_HARD_STOP_PCT
    variants = [
        ("기준(1:3·MA50·ATR)", None, None, 0.0),
        ("첫익절 1:1",          1.0,  None, 0.0),
        ("청산선 MA120",        None, 120,  0.0),
        ("하드손절 -5%",        None, None, 5.0),
        ("PDF종합(1:1·MA120·-5%)", 1.0, 120, 5.0),
    ]
    print("\n" + "=" * 92)
    print(f"검증대기 항목 A/B 비교 — {label} (비용 차감 후)")
    print("=" * 92)
    print(f"  {'변형':24} {'진입':>5} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>10}")
    for vlabel, fp, ma, hard in variants:
        V_FIRST_PARTIAL_R, V_EXIT_MA, V_HARD_STOP_PCT = fp, ma, hard
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:24} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:24} {m['n']:>5} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+9.1f}%")
    V_FIRST_PARTIAL_R, V_EXIT_MA, V_HARD_STOP_PCT = None, None, 0.0
    print("  ※ 기준 = 현재 검증·운영 설정. 변형이 기대값·손익비·P10(꼬리손실)을 개선하는지 확인.")


def report_rs_abtest(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """RS 게이트 A/B — 절대값(>KOSPI) vs 그날 유니버스 RS 상위 20/30/40% (유니버스 1회 로드)."""
    global V_RS_TOP_PCT
    variants = [("기준: RS>0 절대(>KOSPI)", None), ("RS 상위 20%", 0.20),
                ("RS 상위 30%", 0.30), ("RS 상위 40%", 0.40), ("RS 게이트 off(상위100%)", 1.00)]
    print("\n" + "=" * 92)
    print(f"RS 게이트 A/B 비교 — {label} (비용 차감 후)")
    print("=" * 92)
    print(f"  {'변형':26} {'진입':>6} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>11}")
    for vlabel, pct in variants:
        V_RS_TOP_PCT = pct
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:26} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:26} {m['n']:>6} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+10.1f}%")
    V_RS_TOP_PCT = None
    print("  ※ 기준 = 현재 운영(RS 절대값). 상위 N%가 진입 수↑ 하면서 기대값·손익비·P10 을 유지/개선하는지 확인.")


def report_pyramid(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """피라미딩 A/B — 승자 불타기 유무·강도 비교. 각 유닛=별도 거래로 집계(누적=총 P&L 대용)."""
    global V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R
    variants = [
        ("현행(부분익절+트레일)",   False, 0, 1.0),
        ("기준2: 단일유닛(부분익절off)", True, 0, 1.0),
        ("피라미딩 +1유닛 @1R",      True, 1, 1.0),
        ("피라미딩 +2유닛 @1R",      True, 2, 1.0),
        ("피라미딩 +2유닛 @1.5R",    True, 2, 1.5),
        ("피라미딩 +3유닛 @1R",      True, 3, 1.0),
    ]
    print("\n" + "=" * 96)
    print(f"피라미딩(승자 불타기) A/B — {label} (비용 차감 후, 각 유닛=별도 거래)")
    print("=" * 96)
    print(f"  {'변형':28} {'유닛수':>6} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>11}")
    for vlabel, use_u, adds, step in variants:
        V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R = use_u, adds, step
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:28} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:28} {m['n']:>6} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+10.1f}%")
    V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R = False, 0, 1.0
    print("  ※ 누적(=Σ유닛 net%) = 총 P&L 대용. 피라미딩이 누적↑ 하면서 기대값·PF·P10(꼬리손실) 을 지키는지 확인.")
    print("  ※ 추가 유닛은 승자에서만 발생 → 유닛수 증가분이 곧 강세장 추가 참여분.")


def _equity_gated_trades(mode, start, end, watch, costs, cfg, lookback, threshold, adds, step):
    """equity-curve 게이트 피라미딩 — 이미 청산된 최근 lookback 거래 평균 net%>threshold 일 때만 불타기.

    look-ahead 방지: 진입일 i_day 시점에 **청산이 끝난** 거래만으로 레짐 판정.
    반환: 유닛 net% 리스트(각 유닛=별도 거래).
    """
    global V_PYRAMID_ADDS, V_PYRAMID_STEP_R
    V_PYRAMID_ADDS, V_PYRAMID_STEP_R = adds, step
    key = (mode, tuple(watch), start, end, cfg_top)
    if key not in _UNIV_CACHE:
        run(mode, start, end, watch, costs, cfg)   # 유니버스 로드(캐시 채움)
    dates, kospi_close, broad = _UNIV_CACHE[key]
    need = (cfg.ma_trend if mode == "gainers" else cfg.ma_slow) + 1

    closed_base: list[float] = []      # 청산 완료 거래의 초기유닛 net%
    pending: list[tuple[int, float]] = []   # (청산 영업일 idx, 초기유닛 net%)
    nets_out: list[float] = []
    for i_day, date_str in enumerate(dates[:-1]):
        # 오늘 이전에 청산된 거래 → closed_base 편입 (look-ahead 방지)
        closed_base.extend(bn for ex, bn in pending if ex <= i_day)
        pending = [(ex, bn) for ex, bn in pending if ex > i_day]
        if i_day < need:
            continue
        recent = closed_base[-lookback:]
        regime_ok = len(recent) >= max(3, lookback // 2) and (sum(recent) / len(recent)) > threshold
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        kospi_upto = kospi_close[:i_day + 1]
        for code, full in broad.items():
            idx = next((k for k, b in enumerate(full) if b["date"] == date_fmt), None)
            if idx is None or idx < need or full[idx]["value"] < MIN_VALUE_KRW:
                continue
            sig = entry_signal(full[:idx + 1], kospi_upto, cfg)
            if not sig.passed or idx + 1 >= len(full) or full[idx]["close"] <= 0:
                continue
            unit_nets, held = simulate_units(full, idx, cfg, costs, allow_pyramid=regime_ok)
            if not unit_nets:
                continue
            nets_out.extend(unit_nets)
            pending.append((i_day + 1 + held, unit_nets[0]))   # 초기유닛으로 레짐 추적
    return nets_out


def report_pyramid_equity(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """equity-curve 레짐 게이트 피라미딩 — 전략이 최근 통할 때만 불타기."""
    global V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_REGIME_MA, V_PYRAMID_REGIME_MOM
    print("\n" + "=" * 100)
    print(f"equity-curve 게이트 피라미딩 A/B — {label} (비용 차감 후, 각 유닛=별도 거래)")
    print("=" * 100)
    print(f"  {'변형':34} {'유닛수':>6} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>11}")

    def show(vlabel, nets):
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:34} 진입 0건"); return
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:34} {m['n']:>6} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+10.1f}%")

    V_USE_UNITS, V_PYRAMID_REGIME_MA, V_PYRAMID_REGIME_MOM = False, None, None
    show("현행(부분익절+트레일)", [n for _, n in run(mode, start, end, watch, costs, cfg)])
    V_USE_UNITS = True; V_PYRAMID_ADDS = 2; V_PYRAMID_STEP_R = 1.0
    show("피라미딩 +2 (게이트 없음)", [n for _, n in run(mode, start, end, watch, costs, cfg)])
    V_USE_UNITS = False
    for lb, th, adds in [(10, 0.0, 2), (20, 0.0, 2), (20, 0.3, 2), (20, 0.0, 3)]:
        show(f"equity게이트 +{adds} (최근{lb}거래 평균>{th})",
             _equity_gated_trades(mode, start, end, watch, costs, cfg, lb, th, adds, 1.0))
    V_PYRAMID_ADDS, V_PYRAMID_STEP_R = 0, 1.0
    print("  ※ '전략이 최근 통할 때만' 불타기 → 횡보장(2025) 억제·추세장(2026) 포착 되는지 두 구간 모두 확인.")


def report_pyramid_regime(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """레짐 게이트 피라미딩 — 시장이 추세(KOSPI>MA)일 때만 불타기. 횡보장 증폭손실 회피 검증."""
    global V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R, V_PYRAMID_REGIME_MA, V_PYRAMID_REGIME_MOM
    V_PYRAMID_STEP_R = 1.0
    # (label, use_units, adds, regime_ma, regime_mom)
    variants = [
        ("현행(부분익절+트레일)",          False, 0, None, None),
        ("피라미딩 +2 (게이트 없음)",       True,  2, None, None),
        ("피라미딩 +2 (KOSPI 60d>5%)",     True,  2, None, (60, 5.0)),
        ("피라미딩 +2 (KOSPI 60d>8%)",     True,  2, None, (60, 8.0)),
        ("피라미딩 +2 (KOSPI 60d>10%)",    True,  2, None, (60, 10.0)),
        ("피라미딩 +3 (KOSPI 60d>8%)",     True,  3, None, (60, 8.0)),
    ]
    print("\n" + "=" * 96)
    print(f"레짐 게이트 피라미딩 A/B — {label} (비용 차감 후, 각 유닛=별도 거래)")
    print("=" * 96)
    print(f"  {'변형':30} {'유닛수':>6} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>11}")
    for vlabel, use_u, adds, rma, rmom in variants:
        V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_REGIME_MA, V_PYRAMID_REGIME_MOM = use_u, adds, rma, rmom
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:30} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:30} {m['n']:>6} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+10.1f}%")
    V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_REGIME_MA, V_PYRAMID_REGIME_MOM = False, 0, None, None
    print("  ※ 레짐 게이트가 횡보장 추가유닛을 억제해 증폭손실을 줄이면서 추세장 상승을 살리는지 확인.")


def report_hardstop(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """하드손절 임계값 A/B — off / 5% / 7% / 10% / 15% 비교.

    동기: 라이브에서 7% 청산 후 일부 종목 회복 관찰. 임계값 완화/유지/제거 정량 검증.
    """
    global V_HARD_STOP_PCT
    variants = [("off (ATR 트레일만)", 0.0), ("-5%", 5.0), ("-7%", 7.0), ("-10%", 10.0), ("-15%", 15.0)]
    print("\n" + "=" * 92)
    print(f"하드손절 A/B — {label} (비용 차감 후)")
    print("=" * 92)
    print(f"  {'변형':24} {'진입':>5} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'P90':>8} {'누적':>10}")
    for vlabel, hard in variants:
        V_HARD_STOP_PCT = hard
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:24} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:24} {m['n']:>5} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['p90']:>+7.2f}% {m['total']:>+9.1f}%")
    V_HARD_STOP_PCT = 0.0
    print("  ※ 강한 hard stop 일수록 P10(꼬리손실) 작아지지만 진입수·기대값·누적 감소 트레이드오프.")


def report_breadth(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """시장 breadth 게이트 A/B — 일별 universe 양봉비율 < X 일 때 신규진입 차단.

    동기: 06-23 같은 KOSPI 광범위 약세장 9종 동시 hard stop 사고 사전 차단.
    """
    global V_BREADTH_MIN_PCT
    variants = [
        ("기준: breadth off", None),
        ("breadth ≥ 0.30",   0.30),
        ("breadth ≥ 0.40",   0.40),
        ("breadth ≥ 0.50",   0.50),
        ("breadth ≥ 0.60",   0.60),
    ]
    print("\n" + "=" * 96)
    print(f"시장 breadth 게이트 A/B — {label} (비용 차감 후)")
    print("=" * 96)
    print(f"  {'변형':24} {'진입':>5} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>10}")
    for vlabel, pct in variants:
        V_BREADTH_MIN_PCT = pct
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:24} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:24} {m['n']:>5} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+9.1f}%")
    V_BREADTH_MIN_PCT = None
    print("  ※ 약세장 진입 차단이 P10/누적을 개선하는지 확인. 진입 수 감소 폭 트레이드오프.")


def report_breakeven(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """Break-even 트리거 A/B — 진입 +X% 도달 시 stop 을 entry 로 끌어올림(손실 진입 방지).

    동기: 수익 났을 때 일부라도 보호하고 싶은 직관. 1:3 목표·트레일·MA청산 그대로,
    단지 stop floor 만 X% 도달 후 BE 로 강제. 승률↑·평균↓ 기대(BE 청산 0% 거래 늘어남).
    """
    global V_BREAKEVEN_TRIGGER_PCT
    variants = [
        ("기준: BE off",       None),
        ("BE @ +5% 도달",      5.0),
        ("BE @ +7% 도달",      7.0),
        ("BE @ +10% 도달",    10.0),
        ("BE @ +15% 도달",    15.0),
        ("BE @ +20% 도달",    20.0),
    ]
    print("\n" + "=" * 96)
    print(f"Break-even 트리거 A/B — {label} (비용 차감 후)")
    print("=" * 96)
    print(f"  {'변형':24} {'진입':>5} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'P90':>8} {'누적':>10}")
    for vlabel, pct in variants:
        V_BREAKEVEN_TRIGGER_PCT = pct
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:24} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:24} {m['n']:>5} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['p90']:>+7.2f}% {m['total']:>+9.1f}%")
    V_BREAKEVEN_TRIGGER_PCT = None
    print("  ※ BE 가 P10(꼬리손실)을 개선하면서 기대값/누적이 유지/개선되면 채택. 0% 거래 증가(트리거 후 즉시 BE)는 정상.")


def report_pyramid_rising(mode: str, start: str, end: str, watch: list[str], costs: Costs, cfg: TrendConfig, label: str) -> None:
    """피라미딩 rising-day 게이트 A/B — 추가 유닛을 양봉(close>open) 일에만 허용(라이브 _is_rising 의 backtest 대응).

    배경: 2026-06-22 라이브 운영에서 BYPASS_GATE=true 로 retrofit 한 후 9종 일제 추가발동.
    하락 중 종목도 추가매수 → 평단 상승 후 손실 가중. rising-day 가드가 같은 평균기대값을
    유지하면서 P10(꼬리손실)을 개선하는지 검증.
    """
    global V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R, V_PYRAMID_RISING_DAY
    variants = [
        ("기준: 단일유닛(부분익절off)",     True, 0, 1.0, False),
        ("피라미딩 +2유닛 @1R (rising off)", True, 2, 1.0, False),
        ("피라미딩 +2유닛 @1R + RISING",    True, 2, 1.0, True),
        ("피라미딩 +1유닛 @1R + RISING",    True, 1, 1.0, True),
        ("피라미딩 +2유닛 @1.5R + RISING",  True, 2, 1.5, True),
    ]
    print("\n" + "=" * 96)
    print(f"피라미딩 rising-day 게이트 A/B — {label} (비용 차감 후)")
    print("=" * 96)
    print(f"  {'변형':32} {'유닛':>5} {'승률':>6} {'기대값':>8} {'손익비':>7} {'PF':>6} {'P10':>8} {'누적':>11}")
    for vlabel, use_u, adds, step, rising in variants:
        V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R, V_PYRAMID_RISING_DAY = use_u, adds, step, rising
        nets = [n for _, n in run(mode, start, end, watch, costs, cfg)]
        m = metrics(nets)
        if not m.get("n"):
            print(f"  {vlabel:32} 진입 0건"); continue
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {vlabel:32} {m['n']:>5} {m['win']:>5.1f}% {m['avg']:>+7.2f}% "
              f"{po:>7} {pf:>6} {m['p10']:>+7.2f}% {m['total']:>+10.1f}%")
    V_USE_UNITS, V_PYRAMID_ADDS, V_PYRAMID_STEP_R, V_PYRAMID_RISING_DAY = False, 0, 1.0, False
    print("  ※ rising-day 가 같은 기대값에서 P10·누적을 개선하면 채택. 표본 감소 폭 확인.")


def main():
    global cfg_top
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--mode", choices=["gainers", "largecap", "watchlist"], default="largecap")
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--watchlist", default="005930,000660")
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--tax-bps", type=float, default=18.0)
    p.add_argument("--fee-bps", type=float, default=1.5)
    p.add_argument("--slippage-bps", type=float, default=10.0)
    p.add_argument("--gapdown-sweep", action="store_true", help="프리장 갭다운 veto 임계값 스윕 비교")
    p.add_argument("--abtest", action="store_true", help="검증대기 항목 A/B 비교(첫익절/청산선/하드손절)")
    p.add_argument("--rstest", action="store_true", help="RS 게이트 A/B 비교(절대값 vs 상위 20/30/40%)")
    p.add_argument("--pyramidtest", action="store_true", help="피라미딩(승자 불타기) A/B 비교")
    p.add_argument("--pyramidregime", action="store_true", help="레짐 게이트 피라미딩 A/B(KOSPI>MA 일 때만)")
    p.add_argument("--pyramidequity", action="store_true", help="equity-curve 게이트 피라미딩 A/B(전략 최근 성적>0일 때만)")
    p.add_argument("--pyramidrising", action="store_true", help="피라미딩 rising-day 게이트 A/B(양봉일에만 추가)")
    p.add_argument("--breakeven", action="store_true", help="Break-even 트리거 A/B(+X% 도달 시 stop을 entry로 끌어올림)")
    p.add_argument("--breadthtest", action="store_true", help="시장 breadth 게이트 A/B(universe 양봉비율 < X 시 신규진입 차단)")
    p.add_argument("--hardstoptest", action="store_true", help="하드손절 임계값 A/B(off / 5 / 7 / 10 / 15%)")
    args = p.parse_args()

    cfg = TrendConfig(mode=args.mode)
    cfg_top = args.top_n or (30 if args.mode == "gainers" else 100)
    costs = Costs(args.tax_bps, args.fee_bps, args.slippage_bps)
    watch = [c.strip() for c in args.watchlist.split(",") if c.strip()]

    if args.abtest:
        report_abtest(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.rstest:
        report_rs_abtest(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.pyramidtest:
        report_pyramid(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.pyramidregime:
        report_pyramid_regime(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.pyramidequity:
        report_pyramid_equity(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.pyramidrising:
        report_pyramid_rising(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.breakeven:
        report_breakeven(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.breadthtest:
        report_breadth(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    elif args.hardstoptest:
        report_hardstop(args.mode, args.start, args.end, watch, costs, cfg, f"mode={args.mode} top_n={cfg_top}")
    else:
        trades = run(args.mode, args.start, args.end, watch, costs, cfg)
        nets = [net for _, net in trades]
        report(nets, f"mode={args.mode} top_n={cfg_top}")
        if args.gapdown_sweep:
            report_gapdown_sweep(trades, f"mode={args.mode} top_n={cfg_top}")
    print("\n주의: 익일 시가 진입·일봉 청산 근사. 재료/실적/외인수급 미반영(코어 검증).")


if __name__ == "__main__":
    main()
