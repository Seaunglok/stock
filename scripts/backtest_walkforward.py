"""비용 포함 워크포워드 백테스트 + 청산정책 비교 — 과적합 없는 OOS 기대값 추정.

기존 backtest_dynamic.py 의 한계 3가지를 보완하고, 거기에 청산정책 실험을 더한다:
  1. 거래비용 미반영        → 매도세 + 수수료 + 슬리피지(시장가) 차감
  2. 단순 시초가 청산        → 라이브(P1) 모델 + 대안 청산정책 다수
  3. 인샘플 그리드서치(과적합) → 워크포워드 OOS
  + (#3) 청산정책 비교: "같은 진입, 다른 청산"으로 기대값/우측꼬리를 격리 평가.

OOS 결론(승률은 비용 후 ~41-47%, 우측꼬리 의존)을 받아들여, 승률보다 **기대값(expectancy)**
과 **우측꼬리 포착**을 최적화하는 청산을 찾는 게 목적이다.

데이터 파이프라인(유니버스/OHLCV/거래대금 top50/MA20·갭 필터)은 backtest_dynamic 재사용.

모드:
  walkforward (기본) — train 구간 파라미터 선택 → test(OOS) 평가, fold 풀링
  compare            — 고정 baseline(55/3) 진입에 청산정책별 기대값 비교표

사용법:
  python scripts/backtest_walkforward.py --start 2025-11-01 --end 2026-05-09
  python scripts/backtest_walkforward.py --mode compare
  python scripts/backtest_walkforward.py --exit-policy hold3 --slippage-bps 15

비용 가정(편도 bps; 1bp=0.01%): --tax-bps 18 / --fee-bps 1.5 / --slippage-bps 10 → 왕복 ≈ 0.41%
청산정책: p1 / close1 / hold2 / hold3 / trail3 / target (아래 POLICIES 참조)
"""
from __future__ import annotations

import argparse
import statistics
import sys
import warnings
from datetime import timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))   # backtest_dynamic 동일 디렉터리 import
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    import FinanceDataReader as fdr

from backtest_dynamic import (  # noqa: E402
    get_broad_universe,
    get_ohlcv,
    get_top50_by_date,
    _above_ma20,
    _gap_pct,
)
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores  # noqa: E402

MAX_FUTURE = 5   # 청산정책이 참조할 익일 이후 최대 봉 수 (hold3/trail 용)


# ─── 비용 모델 ──────────────────────────────────────────────────────────────

class Costs:
    """왕복 거래비용(%) — 매수 1회 + 매도 1회로 근사."""

    def __init__(self, tax_bps: float, fee_bps: float, slippage_bps: float):
        self.tax = tax_bps / 100.0
        self.fee = fee_bps / 100.0
        self.slip = slippage_bps / 100.0

    @property
    def roundtrip_pct(self) -> float:
        return self.tax + 2 * self.fee + 2 * self.slip

    def __repr__(self) -> str:
        return (f"Costs(왕복≈{self.roundtrip_pct:.3f}%  "
                f"tax={self.tax:.3f} fee={self.fee:.3f}x2 slip={self.slip:.3f}x2)")


# ─── ATR (변동성 기반 손절폭) ──────────────────────────────────────────────

def _atr(ohlcv: list[dict], period: int = 14) -> float:
    """평균 True Range (절대값). 진입일까지의 봉으로 계산."""
    if len(ohlcv) < 2:
        return 0.0
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = ohlcv[i]["high"], ohlcv[i]["low"], ohlcv[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    k = trs[-period:]
    return sum(k) / len(k) if k else 0.0


# ─── 청산정책 (gross % 반환; 모두 동일한 진입가/미래봉을 받아 청산만 달리한다) ────────
# 시그니처 통일: (entry, future_bars, stop_pct, atr). 고정손절 정책은 atr 무시.

def _exit_p1(entry: float, fb: list[dict], stop_pct: float, atr: float = 0.0) -> float:
    """라이브 P1: 09:00 시초 부분청산(녹색 33%) + 15:10 종가 강제청산 + 장중 손절. T+1 만 사용."""
    if not fb or entry <= 0:
        return 0.0
    o, h, l, c = fb[0]["open"], fb[0]["high"], fb[0]["low"], fb[0]["close"]
    stop = entry * (1 + stop_pct / 100)
    open_ret = (o - entry) / entry * 100
    if o <= stop:
        return open_ret
    if o > entry:
        realized, rem = 0.33 * open_ret, 0.67
    else:
        realized, rem = 0.0, 1.0
    rem_ret = (stop - entry) / entry * 100 if l <= stop else (c - entry) / entry * 100
    return realized + rem * rem_ret


def _exit_close1(entry: float, fb: list[dict], stop_pct: float, atr: float = 0.0) -> float:
    """T+1 종가 전량 청산 (시초 부분청산 없음). 갭다운/장중 손절 반영."""
    if not fb or entry <= 0:
        return 0.0
    o, l, c = fb[0]["open"], fb[0]["low"], fb[0]["close"]
    stop = entry * (1 + stop_pct / 100)
    if o <= stop:
        return (o - entry) / entry * 100
    if l <= stop:
        return (stop - entry) / entry * 100
    return (c - entry) / entry * 100


def _exit_hold(entry: float, fb: list[dict], stop_pct: float, n: int, atr: float = 0.0) -> float:
    """N영업일 보유 후 종가 청산. 매일 장중 저가가 손절가 이탈 시 손절가 청산(우측꼬리 허용)."""
    if not fb or entry <= 0:
        return 0.0
    stop = entry * (1 + stop_pct / 100)
    bars = fb[:n]
    # 첫날 갭다운 손절
    if bars[0]["open"] <= stop:
        return (bars[0]["open"] - entry) / entry * 100
    for b in bars:
        if b["low"] <= stop:
            return (stop - entry) / entry * 100
    return (bars[-1]["close"] - entry) / entry * 100


def _exit_trail(entry: float, fb: list[dict], stop_pct: float, trail_pct: float, n: int, atr: float = 0.0) -> float:
    """트레일링 스톱: 종가 최고점 대비 trail_pct 하락 시 청산. 하드 손절 병행, 최대 N일 보유.

    우측꼬리(큰 추세)를 끝까지 따라가되, 고점 대비 일정 % 되돌리면 이익을 확정.
    """
    if not fb or entry <= 0:
        return 0.0
    hard = entry * (1 + stop_pct / 100)
    bars = fb[:n]
    if bars[0]["open"] <= hard:
        return (bars[0]["open"] - entry) / entry * 100
    peak = entry
    for b in bars:
        peak = max(peak, b["close"])
        trail_stop = max(hard, peak * (1 + trail_pct / 100))
        if b["low"] <= trail_stop:
            return (trail_stop - entry) / entry * 100
    return (bars[-1]["close"] - entry) / entry * 100


def _exit_target(entry: float, fb: list[dict], stop_pct: float, tp_pct: float, n: int, atr: float = 0.0) -> float:
    """이익목표 + 손절 + 시간청산: 장중 고가가 +tp_pct 도달 시 목표가 익절,
    저가가 손절 이탈 시 손절, 둘 다 아니면 N일 종가 청산."""
    if not fb or entry <= 0:
        return 0.0
    stop = entry * (1 + stop_pct / 100)
    target = entry * (1 + tp_pct / 100)
    bars = fb[:n]
    if bars[0]["open"] <= stop:
        return (bars[0]["open"] - entry) / entry * 100
    for b in bars:
        hit_t = b["high"] >= target
        hit_s = b["low"] <= stop
        if hit_t and hit_s:
            return (stop - entry) / entry * 100   # 보수적: 같은 날 둘 다면 손절 가정
        if hit_t:
            return tp_pct
        if hit_s:
            return (stop - entry) / entry * 100
    return (bars[-1]["close"] - entry) / entry * 100


def _exit_atr_trail(entry: float, fb: list[dict], stop_pct: float, atr: float,
                    atr_k: float = 2.0, n: int = 3) -> float:
    """(#a + #c) N영업일 보유 + ATR 기반 트레일링 스톱.

    - 초기 하드손절 = entry - atr_k*ATR (변동성에 비례 — 고정 -2% 일봉 근사 대체)
    - 종가 최고점이 갱신될 때마다 스톱을 peak - atr_k*ATR 로 끌어올림(상방만)
    - 저가가 스톱 이탈 시 스톱가 청산, 아니면 N일 종가 시간청산
    ATR=0(데이터 부족)이면 고정 stop_pct 로 폴백.
    """
    if not fb or entry <= 0:
        return 0.0
    band = atr_k * atr if atr > 0 else abs(stop_pct) / 100 * entry
    hard0 = entry - band
    bars = fb[:n]
    if bars[0]["open"] <= hard0:
        return (bars[0]["open"] - entry) / entry * 100
    stop = hard0
    peak = entry
    for b in bars:
        peak = max(peak, b["close"])
        stop = max(stop, peak - band)        # 상방만 이동
        if b["low"] <= stop:
            return (stop - entry) / entry * 100
    return (bars[-1]["close"] - entry) / entry * 100


# name → callable(entry, fb, stop_pct, atr) ; stop_pct/atr 런타임 주입
POLICIES: dict[str, callable] = {
    "p1":       lambda e, fb, s, atr: _exit_p1(e, fb, s),
    "close1":   lambda e, fb, s, atr: _exit_close1(e, fb, s),
    "hold2":    lambda e, fb, s, atr: _exit_hold(e, fb, s, 2),
    "hold3":    lambda e, fb, s, atr: _exit_hold(e, fb, s, 3),
    "trail3":   lambda e, fb, s, atr: _exit_trail(e, fb, s, trail_pct=-3.0, n=3),
    "target":   lambda e, fb, s, atr: _exit_target(e, fb, s, tp_pct=4.0, n=3),
    # (#a+#c) ATR 트레일 × 보유기간 조합
    "atr2_h2":  lambda e, fb, s, atr: _exit_atr_trail(e, fb, s, atr, atr_k=2.0, n=2),
    "atr2_h3":  lambda e, fb, s, atr: _exit_atr_trail(e, fb, s, atr, atr_k=2.0, n=3),
    "atr25_h3": lambda e, fb, s, atr: _exit_atr_trail(e, fb, s, atr, atr_k=2.5, n=3),
    "atr3_h3":  lambda e, fb, s, atr: _exit_atr_trail(e, fb, s, atr, atr_k=3.0, n=3),
}


# ─── 일자별 후보 생성 (진입가 + 미래봉; 청산정책 무관하게 한 번만) ───────────────

def build_daily_candidates(start, end, gap_mode, broad=None):
    kospi = fdr.DataReader("^KS11", start, end)
    dates = [d.strftime("%Y%m%d") for d in kospi.index]
    print(f"기간 {start}~{end}: {len(dates)} 영업일 | gap={gap_mode}")

    if broad is None:
        universe = get_broad_universe()
        broad = {}
        for idx, code in enumerate(universe, 1):
            h = get_ohlcv(code, dates[-1] if dates else end.replace("-", ""), days=200)
            if h:
                broad[code] = h
            if idx % 50 == 0:
                print(f"  유니버스 로드 {idx}/{len(universe)}")
        print(f"  → {len(broad)}종목 로드 완료")

    gap_cut = {"strict": 4.0, "current": 8.0, "live": 2.0, "none": None}.get(gap_mode)
    daily: dict[str, list[dict]] = {}
    dates_fmt: list[str] = []

    for i, date_str in enumerate(dates[:-1]):
        if i < 1:
            continue
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        top50 = get_top50_by_date(date_str, broad)
        if not top50:
            continue
        cands = []
        for code, _v in top50:
            full = broad.get(code, [])
            ohlcv = [c for c in full if c["date"] <= date_fmt][-95:]
            if len(ohlcv) < 21 or ohlcv[-1]["date"] != date_fmt:
                continue
            if not _above_ma20(ohlcv):
                continue
            gap = _gap_pct(ohlcv)
            if gap_cut is not None and gap >= gap_cut:
                continue
            entry = ohlcv[-1]["close"]
            future = [c for c in full if c["date"] > date_fmt][:MAX_FUTURE]
            if not future or entry <= 0:
                continue
            score = compute_technical_scores(ohlcv).composite()
            cands.append({"code": code, "score": score, "gap": gap,
                          "entry": entry, "future": future, "atr": _atr(ohlcv)})
        if cands:
            cands.sort(key=lambda x: -x["score"])
            daily[date_fmt] = cands
            dates_fmt.append(date_fmt)
    print(f"  평가 가능 영업일 {len(dates_fmt)}일")
    return dates_fmt, daily


# ─── 평가 ─────────────────────────────────────────────────────────────────────

def pick_net_returns(daily, dates, threshold, top_n, policy_fn, stop_pct, costs) -> list[float]:
    out = []
    for d in dates:
        qualified = [c for c in daily.get(d, []) if c["score"] >= threshold]
        for p in qualified[:top_n]:
            gross = policy_fn(p["entry"], p["future"], stop_pct, p.get("atr", 0.0))
            out.append(gross - costs.roundtrip_pct)
    return out


def metrics(nets: list[float]) -> dict:
    n = len(nets)
    if n == 0:
        return {"n": 0}
    wins = [r for r in nets if r > 0]
    losses = [r for r in nets if r <= 0]
    avg = sum(nets) / n
    gain_sum = sum(wins)
    loss_sum = abs(sum(losses))
    srt = sorted(nets)
    p90 = srt[min(n - 1, int(n * 0.9))]
    p10 = srt[int(n * 0.1)]
    return {
        "n": n,
        "win": len(wins) / n * 100,
        "avg": avg,                                  # = 기대값(expectancy) per trade
        "median": statistics.median(nets),
        "std": statistics.pstdev(nets) if n > 1 else 0.0,
        "total": sum(nets),
        "profit_factor": (gain_sum / loss_sum) if loss_sum > 0 else float("inf"),
        "payoff": ((gain_sum / len(wins)) / (loss_sum / len(losses)))
                  if wins and losses else float("inf"),
        "p90": p90, "p10": p10,
    }


# ─── 워크포워드 ───────────────────────────────────────────────────────────────

THRESHOLD_GRID = [50.0, 55.0, 60.0, 65.0]
TOPN_GRID = [3, 5]
MIN_TRAIN_PICKS = 10
BASELINE = (55.0, 3)


def select_params(daily, train_dates, policy_fn, stop_pct, costs):
    best = None
    for thr in THRESHOLD_GRID:
        for tn in TOPN_GRID:
            m = metrics(pick_net_returns(daily, train_dates, thr, tn, policy_fn, stop_pct, costs))
            if m["n"] < MIN_TRAIN_PICKS:
                continue
            key = (m["avg"], m["n"])
            if best is None or key > best[0]:
                best = (key, thr, tn, m)
    if best is None:
        return BASELINE[0], BASELINE[1], {"n": 0}
    return best[1], best[2], best[3]


def walk_forward(daily, dates_fmt, train_days, test_days, policy_fn, stop_pct, costs):
    folds, oos, base_oos = [], [], []
    t = train_days
    while t + test_days <= len(dates_fmt):
        train_dates = dates_fmt[t - train_days:t]
        test_dates = dates_fmt[t:t + test_days]
        thr, tn, train_m = select_params(daily, train_dates, policy_fn, stop_pct, costs)
        test_nets = pick_net_returns(daily, test_dates, thr, tn, policy_fn, stop_pct, costs)
        base_nets = pick_net_returns(daily, test_dates, *BASELINE, policy_fn, stop_pct, costs)
        oos.extend(test_nets)
        base_oos.extend(base_nets)
        folds.append({"train": (train_dates[0], train_dates[-1]),
                      "test": (test_dates[0], test_dates[-1]),
                      "params": (thr, tn), "train_m": train_m, "test_m": metrics(test_nets)})
        t += test_days
    return folds, oos, base_oos


# ─── 리포트 ───────────────────────────────────────────────────────────────────

def _fmt(m):
    if not m.get("n"):
        return "픽 0"
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    return (f"{m['n']:>4}건  승률 {m['win']:>5.1f}%  기대값 {m['avg']:>+5.2f}%  "
            f"중앙 {m['median']:>+5.2f}%  PF {pf:>4}  P90 {m['p90']:>+5.2f}%  누적 {m['total']:>+6.1f}%")


def report_walkforward(folds, oos, base, policy):
    print("\n" + "=" * 84)
    print(f"워크포워드 — 청산정책={policy} (train 선택 파라미터 → test OOS)")
    print("=" * 84)
    for f in folds:
        thr, tn = f["params"]
        print(f"\n[{f['test'][0]}~{f['test'][1]}] thr={thr:.0f} top_n={tn} "
              f"(train {f['train'][0]}~{f['train'][1]})")
        print(f"   train: {_fmt(f['train_m'])}")
        print(f"   test : {_fmt(f['test_m'])}")
    print("\n" + "=" * 84)
    print("풀링 OOS (비용 차감 후)")
    print("=" * 84)
    print(f"  적응형 파라미터 : {_fmt(metrics(oos))}")
    print(f"  고정 55/3      : {_fmt(metrics(base))}")


def report_compare(daily, dates_fmt, stop_pct, costs):
    thr, tn = BASELINE
    print("\n" + "=" * 84)
    print(f"청산정책 비교 — 동일 진입(baseline {thr:.0f}/{tn}, 전체 평가구간 {len(dates_fmt)}일), 비용 차감 후")
    print("같은 종목·같은 날 진입에 청산만 달리해 기대값/우측꼬리를 격리 비교한다.")
    print("=" * 84)
    print(f"{'정책':>7} | {'건':>4} {'승률':>6} {'기대값':>7} {'중앙':>6} {'PF':>5} "
          f"{'손익비':>6} {'P90':>6} {'P10':>6} {'누적':>7}")
    print("-" * 84)
    rows = []
    for name, fn in POLICIES.items():
        m = metrics(pick_net_returns(daily, dates_fmt, thr, tn, fn, stop_pct, costs))
        if not m.get("n"):
            continue
        rows.append((name, m))
        pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        po = "inf" if m["payoff"] == float("inf") else f"{m['payoff']:.2f}"
        print(f"{name:>7} | {m['n']:>4} {m['win']:>5.1f}% {m['avg']:>+6.2f}% {m['median']:>+5.2f}% "
              f"{pf:>5} {po:>6} {m['p90']:>+5.2f}% {m['p10']:>+5.2f}% {m['total']:>+6.1f}%")
    if rows:
        best_exp = max(rows, key=lambda r: r[1]["avg"])
        best_tot = max(rows, key=lambda r: r[1]["total"])
        print("-" * 84)
        print(f"  기대값 최고: {best_exp[0]} ({best_exp[1]['avg']:+.2f}%/건)  |  "
              f"누적 최고: {best_tot[0]} ({best_tot[1]['total']:+.1f}%)")
    print("\n해석: 승률은 비슷해도 청산정책에 따라 기대값/우측꼬리(P90)/누적이 갈린다.")
    print("우측꼬리 의존 프로필이면 hold/trail 류가 p1(시초 조기청산)보다 기대값이 높을 수 있다.")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--mode", choices=["walkforward", "compare"], default="walkforward")
    p.add_argument("--start", default="2025-11-01")
    p.add_argument("--end", default="2026-05-09")
    p.add_argument("--gap-mode", choices=["strict", "current", "live", "none"], default="live")
    p.add_argument("--exit-policy", choices=list(POLICIES), default="p1")
    p.add_argument("--stop-pct", type=float, default=-2.0)
    p.add_argument("--train-days", type=int, default=60)
    p.add_argument("--test-days", type=int, default=20)
    p.add_argument("--tax-bps", type=float, default=18.0)
    p.add_argument("--fee-bps", type=float, default=1.5)
    p.add_argument("--slippage-bps", type=float, default=10.0)
    args = p.parse_args()

    costs = Costs(args.tax_bps, args.fee_bps, args.slippage_bps)
    print(costs)
    dates_fmt, daily = build_daily_candidates(args.start, args.end, args.gap_mode)

    if args.mode == "compare":
        report_compare(daily, dates_fmt, args.stop_pct, costs)
        return

    if len(dates_fmt) < args.train_days + args.test_days:
        print(f"\n영업일 부족: {len(dates_fmt)} < train+test. 기간을 늘리거나 일수를 줄이세요.")
        return
    policy_fn = POLICIES[args.exit_policy]
    folds, oos, base = walk_forward(daily, dates_fmt, args.train_days, args.test_days,
                                    policy_fn, args.stop_pct, costs)
    report_walkforward(folds, oos, base, args.exit_policy)
    print("\n주의: 단일/다일 청산을 일봉으로 근사 — 실거래 체결·슬리피지는 다를 수 있음.")


if __name__ == "__main__":
    main()
