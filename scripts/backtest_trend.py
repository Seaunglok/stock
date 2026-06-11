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
    TrendConfig, entry_signal, atr, moving_average,
)

MIN_VALUE_KRW = 1_000 * 10**8   # 거래대금 floor 1,000억


def _gap_pct(full: list[dict], i: int) -> float:
    if i < 1 or full[i - 1]["close"] <= 0:
        return 0.0
    return (full[i]["close"] - full[i - 1]["close"]) / full[i - 1]["close"] * 100.0


def simulate_trade(full: list[dict], i: int, cfg: TrendConfig, costs: Costs) -> float | None:
    """신호 봉 i 다음날 시가 진입 → 트레일/목표/MA50 청산. net 수익률(%) 반환."""
    if i + 1 >= len(full):
        return None
    entry = full[i + 1]["open"]
    if entry <= 0:
        return None
    a = atr(full[:i + 1], cfg.atr_period)
    stop = init_stop_price(entry, a, cfg.atr_k, -cfg.stop_pct)
    target = entry + cfg.rr * (entry - stop)
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
        if not partial and b["high"] >= target:
            realized += (cfg.partial_pct / 100) * (target - entry) / entry * 100
            rem -= cfg.partial_pct / 100
            partial = True
        # 트레일 갱신(종가)
        peak, stop = ratchet_stop(entry, peak, stop, b["close"], a, cfg.atr_k, -cfg.stop_pct)
        # 손절/트레일 이탈(장중 저가)
        if b["low"] <= stop:
            realized += rem * (stop - entry) / entry * 100
            rem = 0.0
            break
        # MA50 이평선 하방 돌파(종가)
        ma50 = moving_average(closes[:j + 1], cfg.ma_support)
        if ma50 is not None and b["close"] < ma50:
            realized += rem * (b["close"] - entry) / entry * 100
            rem = 0.0
            break
    if rem > 0:   # 미청산분 → 마지막 종가 청산
        realized += rem * (closes[last_j] - entry) / entry * 100
    return realized - costs.roundtrip_pct


def run(mode: str, start: str, end: str, watchlist: list[str], costs: Costs, cfg: TrendConfig) -> list[tuple[float, float]]:
    """반환: 진입별 (gap_pct, net_pct). gap_pct = 진입일 시가 / 신호일 종가 − 1 (프리장 갭의 백테스트 대용)."""
    kospi = fdr.DataReader("^KS11", start, end)
    dates = [d.strftime("%Y%m%d") for d in kospi.index]
    kospi_close = [float(c) for c in kospi["Close"].values]
    kdate_close = dict(zip(dates, kospi_close))
    print(f"기간 {start}~{end}: {len(dates)} 영업일 | mode={mode} | {costs}")

    if mode == "watchlist":
        universe = watchlist
    else:
        universe = get_broad_universe()           # KOSPI 시총 상위 ~150 (cap 정렬)
        if mode == "largecap":
            universe = universe[:cfg_top]
    broad: dict[str, list[dict]] = {}
    for idx, code in enumerate(universe, 1):
        h = get_ohlcv(code, dates[-1] if dates else end.replace("-", ""), days=320)
        if h:
            broad[code] = h
        if idx % 40 == 0:
            print(f"  유니버스 로드 {idx}/{len(universe)}")
    print(f"  → {len(broad)}종목 로드 완료")

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

        for code, full, idx in day_rows:
            sig = entry_signal(full[:idx + 1], kospi_upto, cfg)
            if not sig.passed:
                continue
            if idx + 1 >= len(full) or full[idx]["close"] <= 0:
                continue
            gap = (full[idx + 1]["open"] - full[idx]["close"]) / full[idx]["close"] * 100.0
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
    args = p.parse_args()

    cfg = TrendConfig(mode=args.mode)
    cfg_top = args.top_n or (30 if args.mode == "gainers" else 100)
    costs = Costs(args.tax_bps, args.fee_bps, args.slippage_bps)
    watch = [c.strip() for c in args.watchlist.split(",") if c.strip()]

    trades = run(args.mode, args.start, args.end, watch, costs, cfg)
    nets = [net for _, net in trades]
    report(nets, f"mode={args.mode} top_n={cfg_top}")
    if args.gapdown_sweep:
        report_gapdown_sweep(trades, f"mode={args.mode} top_n={cfg_top}")
    print("\n주의: 익일 시가 진입·일봉 청산 근사. 재료/실적/외인수급 미반영(코어 검증).")


if __name__ == "__main__":
    main()
