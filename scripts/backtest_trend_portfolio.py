"""추세추종 **포트폴리오 레벨** 백테스트 — 리스크 사이징·섹터 상한·부분익절 A/B.

기존 backtest_trend.py 는 '거래당 수익률(%)' 기대값 백테스트라 사이징·동시보유 개념이 없어
아래 3개는 측정 자체가 불가능하다:
  #1 리스크 기준 사이징(터틀식): notional 은 거래당 % 를 안 바꾼다 — equity 곡선(MDD)에서만 효과.
  #2 섹터 상한: '5슬롯이 전부 반도체' 같은 동시보유 집중은 슬롯·동시성 시뮬에서만 나타남.
  #3 부분익절 on/off: 거래당 하니스로도 되지만 포트폴리오에서 재확인.

이 파일은 실제 데몬 루프(screen→슬롯 채우기→관리→청산)를 일자별로 시뮬해 **equity 곡선**을 만든다:
  - 진입: 신호일(t) 종가 게이트 통과 → 익일(t+1) 시가 진입 (backtest_trend.simulate_trade 와 동일 타이밍).
  - 관리/청산: 첫목표 30% 부분익절(옵션) → ATR 트레일(종가 갱신·장중 저가 이탈) → MA120 종가 이탈 → max_hold.
  - 슬롯: 최대 MAX_POS 동시보유, 섹터당 SECTOR_CAP(옵션). 랭킹 = entry_signal.score 내림차순.
  - 사이징: notional(예탁 X%) vs risk(예탁 R% ÷ 손절폭). 비용은 매수/매도 체결가에 편도 bps 적용.

지표: 최종수익률·CAGR·MDD·MAR(CAGR/MDD)·일수익 변동성·Sharpe·청산승률·평균 동시보유.

사용:
  python scripts/backtest_trend_portfolio.py                       # 5개 변형 비교(largecap)
  python scripts/backtest_trend_portfolio.py --start 2025-01-01 --end 2026-05-31 --max-pos 5
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import math
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with contextlib.redirect_stdout(io.StringIO()):
    import FinanceDataReader as fdr

from backtest_dynamic import get_broad_universe, get_market_series, get_ohlcv  # noqa: E402
from backtest_walkforward import Costs                       # noqa: E402
from src.mcp_servers.closing_bet_mcp.exit_rules import ratchet_stop  # noqa: E402
from src.mcp_servers.trend_mcp import costs as COSTS  # noqa: E402  거래비용 단일 소스
from src.mcp_servers.trend_mcp.signals import (  # noqa: E402
    RANK_MODES, TrendConfig, assign_rank_scores, atr, entry_signal, levels,
    moving_average, pct_of_52w_high, trend_quality,
)

MIN_VALUE_KRW = 1_000 * 10**8   # 거래대금 floor 1,000억 (backtest_trend 과 동일)
START_EQUITY = 100_000_000.0    # 시작 예탁자산 1억


# ─── 섹터 맵 (유니버스 캐시) ─────────────────────────────────────────────────
def _sector_map() -> dict[str, str]:
    """code→sector (docs_cache/universe_kiwoom_*.json). 없으면 '기타'."""
    files = sorted(glob.glob(str(_ROOT / "docs_cache" / "universe_kiwoom_*.json")), reverse=True)
    if not files:
        return {}
    raw = json.loads(Path(files[0]).read_text(encoding="utf-8"))
    return {str(s["code"]).zfill(6): (s.get("sector") or "기타") for s in raw if s.get("code")}


# ─── 사이징 ──────────────────────────────────────────────────────────────────
@dataclass
class Sizing:
    mode: str = "notional"        # notional=예탁 pct% / risk=예탁 risk_pct% ÷ 손절폭
    position_pct: float = 15.0    # notional 모드: 종목당 예탁 대비 %
    risk_pct: float = 1.0         # risk 모드: 종목당 예탁 대비 감수 리스크 %
    max_notional_pct: float = 25.0  # risk 모드 상한(손절폭 극소 종목이 과대편입되는 것 방지)


def _target_shares(sz: Sizing, equity: float, cash: float, entry: float, stop: float) -> int:
    """사이징 규칙 → 매수 주식수. 현금·상한 한도 내."""
    if entry <= 0:
        return 0
    if sz.mode == "risk" and stop > 0 and entry > stop:
        risk_budget = equity * sz.risk_pct / 100.0
        shares = int(risk_budget / (entry - stop))
        cap_shares = int(equity * sz.max_notional_pct / 100.0 / entry)
        shares = min(shares, cap_shares)
    else:   # notional
        shares = int(equity * sz.position_pct / 100.0 / entry)
    shares = min(shares, int(cash / entry))   # 현금 한도
    return max(0, shares)


# ─── 포지션 ──────────────────────────────────────────────────────────────────
@dataclass
class Position:
    code: str
    sector: str
    entry_idx: int          # 진입 영업일 인덱스(전역 캘린더)
    entry: float
    shares: int
    stop: float
    peak: float
    target: float
    atr0: float
    partial_done: bool = False


# ─── 결과 ────────────────────────────────────────────────────────────────────
@dataclass
class Result:
    equity_curve: list[float] = field(default_factory=list)
    closed: list[float] = field(default_factory=list)   # 청산 거래별 net%(포지션 수익률)
    n_entries: int = 0
    n_rejected_sector: int = 0
    concurrent: list[int] = field(default_factory=list)  # 일별 동시보유 수


# ─── 유니버스 로드(캐시) ──────────────────────────────────────────────────────
_CACHE: dict = {}


def _load(start: str, end: str, top_n: int):
    key = (start, end, top_n)
    if key in _CACHE:
        return _CACHE[key]
    dates, _mkt_close = get_market_series(start, end)
    codes = get_broad_universe()[:top_n]
    bars: dict[str, dict] = {}     # code → {date → bar}
    closes: dict[str, list] = {}   # code → date-ordered close list (동일 캘린더 정렬용)
    ordered: dict[str, list] = {}  # code → date-ordered date list
    end_compact = dates[-1].replace("-", "") if dates else end.replace("-", "")
    for i, code in enumerate(codes, 1):
        h = get_ohlcv(code, end_compact, days=400)
        if not h:
            continue
        bars[code] = {b["date"]: b for b in h}
        ordered[code] = [b["date"] for b in h]
        closes[code] = [b["close"] for b in h]
        if i % 40 == 0:
            print(f"  유니버스 로드 {i}/{len(codes)}")
    print(f"  → {len(bars)}종목 로드 완료 · {len(dates)} 영업일")
    res = (dates, bars, closes, ordered)
    _CACHE[key] = res
    return res


def _closes_upto(closes_list, date_list, date_str):
    """code 의 date_str(포함) 까지 종가 리스트. date_str 이 해당 종목 거래일 아니면 None."""
    idx = _bisect(date_list, date_str)
    if idx is None:
        return None, None
    return closes_list[:idx + 1], idx


def _bisect(date_list, date_str):
    """date_str 의 정확 인덱스(거래일). 없으면 None. (정렬 리스트 이진탐색)"""
    lo, hi = 0, len(date_list)
    while lo < hi:
        mid = (lo + hi) // 2
        if date_list[mid] < date_str:
            lo = mid + 1
        else:
            hi = mid
    if lo < len(date_list) and date_list[lo] == date_str:
        return lo
    return None


# 신호 메모(변형 간 재사용) — entry_signal 은 사이징/슬롯/섹터와 무관하게 (code,date)에 결정적.
# report() 1회당 clear. 값: (composite, atr, tq, hi) 또는 None(게이트 미통과/데이터부족).
_SIG_MEMO: dict = {}

# 랭킹 모드 — **후보 > 슬롯일 때 누구를 사는지**만 바꾼다(게이트·진입건수 불변).
# 현행 composite 는 종가매매(1~3일 보유)용 스코어러 재사용이라 추세추종 시계와 안 맞는다.
#   composite : 0.30 당일거래량 + 0.20 당일윗꼬리 + 0.30 90일눌림회복 (결측 재정규화)
#   tq        : Clenow 연율화 지수회귀 기울기 × R² (90봉) — 추세의 강도×신뢰도
#   high_prox : 120일 고가 근접도 — George-Hwang 52주 신고가 효과의 **단축판**
#               ※ 논문은 252봉이나 현재 캐시가 종목당 320봉이라 warmup 을 253 으로 올리면
#                 평가구간이 199일→67일로 붕괴한다. 120 은 need(121) 안이라 구간 손실 0.
#   blend     : tq 와 high_prox 의 순위 평균(둘 다 정규화 없이 rank 로 합산)
def _signal(code, date_str, full, kospi_upto, cfg):
    k = (code, date_str)
    if k in _SIG_MEMO:
        return _SIG_MEMO[k]
    sig = entry_signal(full, kospi_upto, cfg)
    if not sig.passed:
        _SIG_MEMO[k] = None
        return None
    closes = [b["close"] for b in full]
    val = (sig.score, atr(full, cfg.atr_period),
           trend_quality(closes, 90), pct_of_52w_high(full, 120))
    _SIG_MEMO[k] = val
    return val


# ─── 시뮬레이션 ───────────────────────────────────────────────────────────────
def simulate(start: str, end: str, top_n: int, cfg: TrendConfig, costs: Costs, sz: Sizing,
             max_pos: int, sector_cap: int, partial_on: bool, secmap: dict[str, str],
             hard_stop_pct: float = 0.0, rank_mode: str = "composite",
             regime_ma: int = 0, breadth_min: float = 0.0) -> Result:
    """일자별 포트폴리오 시뮬. sector_cap<=0 이면 상한 없음. partial_on=False 면 순수 트레일.

    hard_stop_pct: 진입가 -X% 하드손절(트레일 floor). 라이브 TREND_HARD_STOP_PCT 미러용.
    """
    dates, bars, closes, ordered = _load(start, end, top_n)
    buy_f = 1 + (costs.fee + costs.slip) / 100.0             # 매수 체결가 가산(수수료+슬리피지)
    sell_f = 1 - (costs.tax + costs.fee + costs.slip) / 100.0  # 매도 체결가 차감(세금+수수료+슬리피지)
    need = cfg.ma_slow + 1

    cash = START_EQUITY
    positions: list[Position] = []
    pending: list[dict] = []   # 전일 종가 신호 → 금일 시가 진입 대기 [{code, score, atr, sector}]
    res = Result()

    def equity_at(date_str: str) -> float:
        eq = cash
        for p in positions:
            b = bars[p.code].get(date_str)
            px = b["close"] if b else p.entry
            eq += p.shares * px
        return eq

    for di, date_str in enumerate(dates):
        # ── 1) 전일 신호 → 금일 시가 진입 (슬롯·섹터·현금 한도) ──
        if pending:
            eq_now = equity_at(date_str)   # 사이징 기준 예탁자산(당일 시가 시점 근사)
            sec_count: dict[str, int] = {}
            for p in positions:
                sec_count[p.sector] = sec_count.get(p.sector, 0) + 1
            for c in pending:
                if len(positions) >= max_pos:
                    break
                b = bars[c["code"]].get(date_str)
                if not b or b["open"] <= 0:
                    continue
                if any(p.code == c["code"] for p in positions):
                    continue
                sec = c["sector"]
                if sector_cap > 0 and sec_count.get(sec, 0) >= sector_cap:
                    res.n_rejected_sector += 1
                    continue
                entry = b["open"] * buy_f
                stop, target = levels(entry, cfg, atr_value=c["atr"])   # 라이브와 동일 공식(단일 정본)
                shares = _target_shares(sz, eq_now, cash, entry, stop)
                if shares < 1:
                    continue
                cash -= shares * entry
                positions.append(Position(
                    code=c["code"], sector=sec, entry_idx=di, entry=entry, shares=shares,
                    stop=stop, peak=entry, target=target, atr0=c["atr"]))
                sec_count[sec] = sec_count.get(sec, 0) + 1
                res.n_entries += 1
        pending = []

        # ── 2) 보유 포지션 관리/청산 (당일 바) ──
        still: list[Position] = []
        for p in positions:
            b = bars[p.code].get(date_str)
            if not b:                      # 당일 미거래(정지 등) → 보유 유지
                still.append(p)
                continue
            exited = False
            # (a) 첫 목표 부분익절 — 장중 고가 도달
            if partial_on and not p.partial_done and b["high"] >= p.target and p.shares > 1:
                part = int(p.shares * cfg.partial_pct / 100)
                if 1 <= part < p.shares:
                    cash += part * p.target * sell_f
                    p.shares -= part
                    p.partial_done = True
            # (b) 트레일 갱신(종가)
            p.peak, p.stop = ratchet_stop(p.entry, p.peak, p.stop, b["close"], p.atr0, cfg.atr_k, -cfg.stop_pct)
            # (c) 트레일/손절 이탈 — 장중 저가. 하드손절은 트레일의 **바닥값**으로 적용
            #     (2026-08-17 추가: 라이브엔 HARD_STOP_PCT=10 이 있는데 이 하니스엔 없었다.
            #      사이징·MDD·Sharpe 를 하드손절 없는 전략으로 측정해 온 셈이다.)
            eff_stop = max(p.stop, p.entry * (1 - hard_stop_pct / 100.0)) if hard_stop_pct > 0 else p.stop
            if b["low"] <= eff_stop:
                cash += p.shares * eff_stop * sell_f
                res.closed.append((eff_stop - p.entry) / p.entry * 100)
                exited = True
            if not exited:
                # (d) MA120 종가 이탈
                cl, idx = _closes_upto(closes[p.code], ordered[p.code], date_str)
                ma = moving_average(cl, cfg.ma_slow) if cl else None
                if ma is not None and b["close"] < ma:
                    cash += p.shares * b["close"] * sell_f
                    res.closed.append((b["close"] - p.entry) / p.entry * 100)
                    exited = True
            if not exited and (di - p.entry_idx) >= cfg.max_hold:
                # (e) 보유기간 만료 — 종가 시간청산
                cash += p.shares * b["close"] * sell_f
                res.closed.append((b["close"] - p.entry) / p.entry * 100)
                exited = True
            if not exited:
                still.append(p)
        positions = still

        # ── 3) 당일 종가 신호 → 익일 진입 후보(랭킹) ──
        # ── 시장 게이트 (2026-08-21 추가) ─────────────────────────────────
        # 이 하니스엔 레짐·breadth 게이트가 없었다. 라이브는 KOSPI<MA60 이면 신규진입을
        # **전면 차단**하는데(08-18 첫 발동 후 진입 0건), 하니스는 하락장에도 자유롭게 들어가
        # 라이브가 하지 않을 거래로 랭킹을 평가하고 있었다. 시장 게이트 없이 잰 결과는
        # 라이브 성과의 대용이 될 수 없다.
        blocked = False
        if regime_ma > 0:
            mk = _kospi_upto(start, end, date_str)
            kma = moving_average(mk, regime_ma) if mk else None
            if kma is None or (mk and mk[-1] < kma):
                blocked = True
        if not blocked and breadth_min > 0:
            # 라이브는 업종지수 상승종목 비율을 쓰지만 하니스엔 없다 → 그날 유니버스 양봉비율로 근사
            # (backtest_trend.py 의 V_BREADTH_MIN_PCT 와 동일 대용).
            day = [dmap.get(date_str) for dmap in bars.values()]
            day = [b for b in day if b]
            if day:
                rising = sum(1 for b in day if b["close"] > b["open"])
                if rising / len(day) < breadth_min:
                    blocked = True
        if blocked:
            pending = []
            res.equity_curve.append(equity_at(date_str))
            res.concurrent.append(len(positions))
            continue

        if di < len(dates) - 1 and len(positions) < max_pos:
            kospi_upto = None   # RS 는 종목 자체 시계열로 계산됨(entry_signal 내부) → KOSPI 필요분만
            cands = []
            for code, dmap in bars.items():
                b = dmap.get(date_str)
                if not b or b["value"] < MIN_VALUE_KRW:
                    continue
                cl, idx = _closes_upto(closes[code], ordered[code], date_str)
                if cl is None or idx < need:
                    continue
                if any(p.code == code for p in positions):
                    continue
                if kospi_upto is None:
                    kospi_upto = _kospi_upto(start, end, date_str)
                full = [dmap[d] for d in ordered[code][:idx + 1]]
                val = _signal(code, date_str, full, kospi_upto, cfg)
                if val is not None:
                    cands.append({"code": code, "score": val[0], "atr": val[1],
                                  "tq": val[2], "hi": val[3],
                                  "sector": secmap.get(code, "기타")})
            assign_rank_scores(cands, rank_mode)
            cands.sort(key=lambda c: -c["rank_score"])
            pending = cands

        res.equity_curve.append(equity_at(date_str))
        res.concurrent.append(len(positions))

    # 종료 시 잔여 포지션 마지막 종가 청산(집계용)
    if positions and dates:
        for p in positions:
            cl = closes[p.code][-1] if closes.get(p.code) else p.entry
            res.closed.append((cl - p.entry) / p.entry * 100)
    return res


_KOSPI_CACHE: dict = {}


def _kospi_upto(start, end, date_str):
    key = (start, end)
    if key not in _KOSPI_CACHE:
        _KOSPI_CACHE[key] = get_market_series(start, end)
    kd, kc = _KOSPI_CACHE[key]
    idx = _bisect(kd, date_str)
    return kc[:idx + 1] if idx is not None else kc


# ─── 포트폴리오 지표 ──────────────────────────────────────────────────────────
def pmetrics(res: Result, dates_len: int) -> dict:
    ec = res.equity_curve
    if not ec:
        return {"n": 0}
    total_ret = (ec[-1] / START_EQUITY - 1) * 100
    years = max(dates_len / 252.0, 1e-9)
    cagr = ((ec[-1] / START_EQUITY) ** (1 / years) - 1) * 100
    peak = ec[0]
    mdd = 0.0
    for v in ec:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    # 일수익률
    rets = [(ec[i] / ec[i - 1] - 1) for i in range(1, len(ec)) if ec[i - 1] > 0]
    vol = (statistics_pstdev(rets) * math.sqrt(252) * 100) if rets else 0.0
    mean_d = (sum(rets) / len(rets)) if rets else 0.0
    sharpe = (mean_d / (statistics_pstdev(rets) or 1e-9) * math.sqrt(252)) if len(rets) > 1 else 0.0
    mar = cagr / mdd if mdd > 0 else float("inf")
    closed = res.closed
    win = (sum(1 for x in closed if x > 0) / len(closed) * 100) if closed else 0.0
    return {"n": len(closed), "total": total_ret, "cagr": cagr, "mdd": mdd, "mar": mar,
            "vol": vol, "sharpe": sharpe, "win": win, "entries": res.n_entries,
            "avg_conc": (sum(res.concurrent) / len(res.concurrent)) if res.concurrent else 0.0,
            "sec_rej": res.n_rejected_sector, "term_eq": ec[-1]}


def statistics_pstdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


# ─── 리포트 ──────────────────────────────────────────────────────────────────
def report_rank(start: str, end: str, top_n: int, cfg: TrendConfig, costs: Costs,
                max_pos: int, risk_pct: float, hard_stop: float,
                regime_ma: int = 0, breadth_min: float = 0.0) -> None:
    """랭킹 A/B — **후보 > 슬롯일 때 누구를 사는가**만 바꿔 비교한다.

    게이트는 전부 동일하므로 '진입 기회'는 같고, 슬롯 경쟁에서의 선택만 달라진다.
    거래당 하니스(backtest_trend.py)로는 측정 불가 — 거기선 게이트 통과분을 전부 세기 때문에
    랭킹이 결과에 영향을 주지 않는다. 슬롯 제약이 있는 이 하니스에서만 의미가 있다.
    """
    secmap = _sector_map()
    _SIG_MEMO.clear()
    dates, *_ = _load(start, end, top_n)
    dl = len(dates)
    sizing = Sizing(mode="risk", risk_pct=risk_pct)
    print()
    print("=" * 108)
    print(f"랭킹 A/B — 슬롯 배분 기준 비교 (max_pos={max_pos} · risk {risk_pct}% · 하드손절 {hard_stop:g}%)")
    print("=" * 108)
    print(f"  {'랭킹':22} {'최종%':>8} {'CAGR':>7} {'MDD':>7} {'MAR':>6} {'Sharpe':>7} "
          f"{'청산승률':>7} {'거래':>5} {'평균보유':>7}")
    print("  " + "-" * 88)
    for mode in RANK_MODES:
        res = simulate(start, end, top_n, cfg, costs, sizing, max_pos, 0, True, secmap,
                       hard_stop_pct=hard_stop, rank_mode=mode,
                       regime_ma=regime_ma, breadth_min=breadth_min)
        m = pmetrics(res, dl)
        mar = "inf" if m["mar"] == float("inf") else f"{m['mar']:.2f}"
        label = mode + (" (현행)" if mode == "composite" else "")
        print(f"  {label:22} {m['total']:>+7.1f}% {m['cagr']:>+6.1f}% {m['mdd']:>6.1f}% "
              f"{mar:>6} {m['sharpe']:>7.2f} {m['win']:>6.1f}% {m['entries']:>5} {m['avg_conc']:>7.2f}")
    print("  " + "-" * 88)
    print("  composite=현행(종가매매 스코어러 재사용) / tq=Clenow 기울기×R²(90봉)")
    print("  high_prox=120일 고가 근접(George-Hwang 단축판) / blend=tq·high_prox 순위합")
    print("  ※ 거래 수가 변형별로 다르면 슬롯 회전율이 달라진 것 — 기대값만 보지 말 것.")
    print("  ※ 유니버스가 현재 시총 스냅샷 고정이라 생존편향이 있다. **변형 간 상대 비교로만** 읽을 것.")


def report(start: str, end: str, top_n: int, cfg: TrendConfig, costs: Costs,
           max_pos: int, base_pct: float, risk_pct: float, sector_cap: int,
           hard_stop: float = 0.0, rank_mode: str = "composite",
           regime_ma: int = 0, breadth_min: float = 0.0) -> None:
    secmap = _sector_map()
    _SIG_MEMO.clear()
    dates, *_ = _load(start, end, top_n)
    dl = len(dates)
    notional = Sizing(mode="notional", position_pct=base_pct)
    risk = Sizing(mode="risk", risk_pct=risk_pct)

    # (label, sizing, sector_cap, partial_on)
    variants = [
        ("기준(notional %d%%·상한off·부분익절on)" % base_pct,  notional, 0,          True),
        ("#1 리스크사이징(risk %.1f%%)" % risk_pct,           risk,     0,          True),
        ("#2 섹터상한(≤%d)" % sector_cap,                      notional, sector_cap, True),
        ("#3 부분익절 off(순수 트레일)",                        notional, 0,          False),
        ("#1+#2+#3 결합",                                       risk,     sector_cap, False),
    ]
    print("\n" + "=" * 116)
    print(f"추세추종 포트폴리오 A/B — mode=largecap top_n={top_n} max_pos={max_pos} "
          f"기간 {start}~{end} · 시작 {START_EQUITY/1e8:.0f}억 · {costs}")
    print("=" * 116)
    print(f"  {'변형':40} {'최종%':>8} {'CAGR':>7} {'MDD':>7} {'MAR':>6} {'Vol':>6} "
          f"{'Sharpe':>7} {'청산승률':>7} {'거래':>5} {'평균보유':>7} {'섹터거절':>7}")
    rows = []
    for label, sizing, cap, partial in variants:
        res = simulate(start, end, top_n, cfg, costs, sizing, max_pos, cap, partial, secmap,
                       hard_stop_pct=hard_stop, rank_mode=rank_mode,
                       regime_ma=regime_ma, breadth_min=breadth_min)
        m = pmetrics(res, dl)
        rows.append((label, m))
        mar = "inf" if m["mar"] == float("inf") else f"{m['mar']:.2f}"
        print(f"  {label:40} {m['total']:>+7.1f}% {m['cagr']:>+6.1f}% {m['mdd']:>6.1f}% "
              f"{mar:>6} {m['vol']:>5.1f}% {m['sharpe']:>7.2f} {m['win']:>6.1f}% "
              f"{m['entries']:>5} {m['avg_conc']:>7.2f} {m['sec_rej']:>7}")
    print("=" * 116)
    print("  ※ MAR=CAGR/MDD (높을수록 위험조정수익 우수). #1·#2 는 기대값이 아니라 MDD/MAR(파산확률) 개선이 목적.")
    print("  ※ notional·risk 평균 노출이 비슷하도록 risk_pct 를 손절폭~7% 기준으로 잡음(≈base_pct 노출).")
    print("  주의: 익일 시가 진입·일봉 청산 근사. 슬리피지/부분체결/공휴일 미세오차 존재.")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--top-n", type=int, default=100)
    p.add_argument("--max-pos", type=int, default=5)
    p.add_argument("--position-pct", type=float, default=15.0)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--sector-cap", type=int, default=2)
    p.add_argument("--tax-bps", type=float, default=COSTS.TAX_BPS)      # 라이브와 단일 소스
    p.add_argument("--fee-bps", type=float, default=COSTS.FEE_BPS)
    p.add_argument("--slippage-bps", type=float, default=COSTS.SLIPPAGE_BPS)
    p.add_argument("--ranktest", action="store_true",
                   help="랭킹 A/B — 슬롯 배분 기준(composite/tq/high_prox/blend) 비교")
    p.add_argument("--legacy-defaults", action="store_true",
                   help="라이브 미러 없이 구 설정(MA50 청산·하드손절 off·눌림 3%%)으로 실행")
    args = p.parse_args()

    cfg = TrendConfig(mode="largecap")
    costs = Costs(args.tax_bps, args.fee_bps, args.slippage_bps)
    # 기본 = 라이브 미러. 이 하니스는 사이징·MDD 판단의 근거라, 라이브와 다른 청산룰로 돌면
    # "리스크 균등 사이징이 MDD 를 줄인다" 같은 결론 자체가 다른 전략의 결론이 된다.
    hard_stop, regime_ma, breadth_min = 0.0, 0, 0.0
    if args.legacy_defaults:
        print("⚠️ --legacy-defaults: 구 설정(MA50·하드손절 off·눌림 3%)으로 실행합니다.")
    else:
        from trend_config import (BREADTH_MIN_PCT, CFG as LIVE, EXIT_MA, HARD_STOP_PCT,
                                  MAX_HOLD_DAYS, REGIME_MA)
        cfg.ma_slow = EXIT_MA                    # 청산 이평선(라이브 MA120)
        cfg.pullback_pct = LIVE.pullback_pct
        cfg.pullback_min_pct = LIVE.pullback_min_pct
        cfg.atr_k, cfg.stop_pct, cfg.rr, cfg.partial_pct = LIVE.atr_k, LIVE.stop_pct, LIVE.rr, LIVE.partial_pct
        if MAX_HOLD_DAYS > 0:
            cfg.max_hold = MAX_HOLD_DAYS
        hard_stop = HARD_STOP_PCT
        regime_ma, breadth_min = REGIME_MA, BREADTH_MIN_PCT
        print(f"라이브 미러: 청산MA{cfg.ma_slow} · 하드손절 {hard_stop:g}% · 눌림 {cfg.pullback_pct:g}% · "
              f"보유상한 {cfg.max_hold}일 · 레짐 MA{regime_ma or 'off'} · breadth {breadth_min or 'off'}"
              f"   ※ 외인 청산은 일봉 재현 불가로 미반영")
    if args.ranktest:
        report_rank(args.start, args.end, args.top_n, cfg, costs, args.max_pos,
                    args.risk_pct, hard_stop, regime_ma, breadth_min)
        return
    report(args.start, args.end, args.top_n, cfg, costs, args.max_pos,
           args.position_pct, args.risk_pct, args.sector_cap, hard_stop=hard_stop,
           regime_ma=regime_ma, breadth_min=breadth_min)


if __name__ == "__main__":
    main()
