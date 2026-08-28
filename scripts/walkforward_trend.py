"""추세추종 워크포워드 검증 — 학습구간에서 고르고, 한 번도 안 본 구간에서 잰다.

왜 필요한가
-----------
2026-08-27~28 에 드러난 것: 이 프로젝트의 A/B 는 전부 **같은 데이터를 반복해서 보고**
그중 좋아 보이는 값을 채택해 왔다. 그렇게 채택한 값이 구간을 바꾸자 뒤집혔다
(`blend` 랭킹: 전체구간 채택 → 3년 재측정에서 4개 중 최악).

in-sample 최적값은 "그 구간에서 뭐가 좋았나"를 말할 뿐, "다음 구간에서 뭐가 좋을까"를
말하지 않는다. 둘을 구분하는 유일한 방법이 워크포워드다:

    [학습 4년] → 규칙 선택 → [검증 1년, 한 번도 안 봄] → 성과 기록
         └ 1년 뒤로 밀어서 반복

검증구간 성과만 이어 붙인 것이 **이 전략을 실제로 운용했다면 얻었을 결과**의 근사다.

이 하니스가 막는 것 (오늘 실제로 겪은 결함들)
--------------------------------------------
1. **구간 truncation** — OHLCV 로더가 종료일 기준 고정 봉수만 가져와 `--start` 가 무시됐다.
   → 시뮬한 영업일 수를 `Result.n_days` 로 돌려받아 요청 구간과 대조(`_assert_window`).
2. **학습/검증 누수** — 검증구간 데이터를 보고 파라미터를 고르는 것.
   → 폴드 경계를 강제 검사하고(`_assert_no_leak`), 진입일이 검증구간 밖이면 실패.
3. **워밍업 부족이 구간 축소로 둔갑** — 긴 이평이 앞머리에서 None 이 되면 그 날들이
   '차단'으로 집계됐다. → 데이터는 전 구간 로드하고 **매매 판단만** 구간 제한(`sim_from/to`).
4. **생존편향** — 현재 시총 상위를 과거에 소급. → 유니버스는 백테스트와 동일 소스를 쓰되
   결과를 **항상 동일 유니버스 벤치마크와 함께** 보고한다(절대값 단독 해석 금지).
5. **사후 선택** — 결과를 보고 "이게 좋네" 하는 것.
   → 후보 격자(`GRID`)와 선택 규칙(`select`)을 **모듈 상수/함수로 미리 고정**한다.
      검증 결과를 보고 이 둘을 고치면 워크포워드가 아니다.

사용법
------
    python scripts/walkforward_trend.py                     # 기본(4년 학습 / 1년 검증)
    python scripts/walkforward_trend.py --train-years 3
    python scripts/walkforward_trend.py --metric total      # 선택 기준 변경(기본 MAR)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import backtest_trend_portfolio as P  # noqa: E402
from backtest_walkforward import Costs  # noqa: E402
from src.mcp_servers.trend_mcp import costs as C  # noqa: E402
from src.mcp_servers.trend_mcp.signals import TrendConfig  # noqa: E402

# ── 데이터 전 구간. 폴드는 이 안에서 잘린다(로드는 1회) ─────────────────────
DATA_START = "2015-01-01"
DATA_END = "2026-08-25"
TOP_N = 100


# ── 재개 판정 기준 — **결과를 보기 전에 선언한다** (2026-08-28) ─────────────
#
# 사용자 결정: "위험이 절반이면 채택".
# 그대로 쓰면 '아무것도 안 사는 전략'이 통과하므로 수익 하한을 함께 건다.
#
#   ① MDD(전략) ≤ MDD_RATIO × MDD(벤치마크)      ← 선언된 '위험 절반'
#   ② MAR(전략) ≥ MAR(벤치마크)                   ← 위험을 줄인 대가로 수익을 더 잃지 않을 것
#   ③ 플러스 연도 ≥ MIN_WIN_YEARS 비율            ← 한두 해에 몰린 결과 배제
#
# MDD·MAR 은 **OOS 검증구간만 이어붙인 일별 자산곡선**에서 잰다. 폴드별 MDD 의 평균이
# 아니다 — 폴드 경계를 넘는 연속 하락은 폴드별로 보면 사라지는데, 실제로는 그걸 겪는다.
# 벤치마크도 같은 구간·같은 방식으로 이어붙여 잰다(동일 조건 비교).
MDD_RATIO = 0.5          # 전략 MDD 가 벤치마크의 이 배수 이하여야 함
MIN_WIN_YEARS = 0.60     # 플러스 검증연도 최소 비율


# ── 후보 격자 — **검증 결과를 보기 전에 고정한다** ──────────────────────────
@dataclass(frozen=True)
class Candidate:
    label: str
    exits: tuple[str, ...]
    max_pos: int
    position_pct: float
    exit_ma: int = 120
    hard_stop: float = 10.0
    max_hold: int = 60


GRID: tuple[Candidate, ...] = (
    # 현행 라이브 구성 — 기준점으로 반드시 포함한다
    Candidate("현행 사다리·슬롯5", ("partial", "trail", "ma", "hold"), 5, 20.0),
    Candidate("현행 사다리·슬롯20", ("partial", "trail", "ma", "hold"), 20, 5.0),
    # 트레일 제거 계열 — 2026-08-28 진단이 지목한 방향
    Candidate("MA120 청산·슬롯5", ("ma",), 5, 20.0),
    Candidate("MA120 청산·슬롯20", ("ma",), 20, 5.0),
    Candidate("MA200 청산·슬롯20", ("ma",), 20, 5.0, exit_ma=200),
    Candidate("시간청산120·슬롯20", ("hold",), 20, 5.0, max_hold=120),
    Candidate("MA120+시간120·슬롯20", ("ma", "hold"), 20, 5.0, max_hold=120),
)


def select(scored: list[tuple[Candidate, dict]], metric: str) -> tuple[Candidate, dict]:
    """학습구간 성적으로 후보 하나를 **기계적으로** 고른다.

    사람이 개입하지 않는다는 것이 요점이다. 동점이면 GRID 순서(= 사전 선언 순서)를 따르므로
    결과가 재현 가능하다. 학습구간에서 전부 손실이어도 규칙대로 '가장 덜 나쁜' 것을 고른다 —
    실제 운용에서 그 시점에 할 수 있는 판단이 그것뿐이기 때문이다.
    """
    def key(item):
        cand, m = item
        if not m.get("n"):
            return (-1e18, 0)
        v = m.get(metric)
        if v is None or v != v or v in (float("inf"), float("-inf")):
            v = -1e17
        return (v, -GRID.index(cand))
    return max(scored, key=key)


# ── 검증 어서션 — 조용한 오측정을 구조적으로 막는다 ─────────────────────────
def _assert_window(res, lo: str, hi: str, all_dates: list[str], what: str) -> None:
    """요청 구간이 **실제로** 시뮬됐는지. `--start` 무시 결함(2026-08-27)의 재발 방지."""
    expected = sum(1 for d in all_dates if lo <= d <= hi)
    if res.n_days != expected:
        raise AssertionError(
            f"[{what}] 시뮬 영업일 불일치: 요청 {lo}~{hi} = {expected}일, 실제 {res.n_days}일. "
            "구간이 조용히 잘렸다 — 결과를 신뢰할 수 없다.")
    if expected < 60:
        raise AssertionError(f"[{what}] 구간이 너무 짧다({expected}영업일) — 폴드 정의를 확인할 것")


def _assert_no_leak(res, lo: str, hi: str, what: str) -> None:
    """검증구간 진입이 그 구간 안에서만 일어났는지."""
    bad = [d for d in res.entry_dates if not (lo <= d <= hi)]
    if bad:
        raise AssertionError(f"[{what}] 구간 밖 진입 {len(bad)}건(예: {bad[:3]}) — 누수")


def _assert_folds(folds: list[tuple[str, str, str, str]]) -> None:
    """학습 종료 < 검증 시작 이 **엄격히** 성립하는지."""
    for tr_lo, tr_hi, te_lo, te_hi in folds:
        if not (tr_lo < tr_hi < te_lo <= te_hi):
            raise AssertionError(f"폴드 경계 이상: 학습 {tr_lo}~{tr_hi} / 검증 {te_lo}~{te_hi}")
        if tr_hi >= te_lo:
            raise AssertionError(f"학습구간이 검증구간과 겹친다: {tr_hi} >= {te_lo}")


# ── 실행 ────────────────────────────────────────────────────────────────────
def _cfg(c: Candidate) -> TrendConfig:
    from trend_config import CFG as LIVE
    t = TrendConfig(mode="largecap")
    t.ma_slow = c.exit_ma
    t.pullback_pct, t.pullback_min_pct = LIVE.pullback_pct, LIVE.pullback_min_pct
    t.atr_k, t.stop_pct, t.rr, t.partial_pct = LIVE.atr_k, LIVE.stop_pct, LIVE.rr, LIVE.partial_pct
    t.max_hold = c.max_hold
    return t


def _run(c: Candidate, lo: str, hi: str, costs: Costs, secmap: dict) -> dict:
    from trend_config import BREADTH_MIN_PCT, RANK_MODE, REGIME_MA
    P._SIG_MEMO.clear()
    res = P.simulate(DATA_START, DATA_END, TOP_N, _cfg(c), costs,
                     P.Sizing(mode="notional", position_pct=c.position_pct),
                     c.max_pos, 0, "partial" in c.exits, secmap,
                     hard_stop_pct=c.hard_stop, rank_mode=RANK_MODE,
                     regime_ma=REGIME_MA, breadth_min=BREADTH_MIN_PCT,
                     exits=c.exits, sim_from=lo, sim_to=hi)
    m = P.pmetrics(res, res.n_days)
    m["_res"] = res
    return m


def _folds(dates: list[str], train_years: int, test_years: int) -> list[tuple[str, str, str, str]]:
    """달력 기준 롤링 폴드. 데이터가 있는 구간만 남긴다."""
    y0 = int(dates[0][:4]) + (1 if dates[0][5:7] > "01" else 0)
    y_end = int(dates[-1][:4])
    out = []
    y = y0
    while True:
        tr_lo = f"{y}-01-01"
        tr_hi = f"{y + train_years - 1}-12-31"
        te_lo = f"{y + train_years}-01-01"
        te_hi = f"{y + train_years + test_years - 1}-12-31"
        if int(te_lo[:4]) > y_end:
            break
        te_hi = min(te_hi, dates[-1])
        if sum(1 for d in dates if te_lo <= d <= te_hi) < 60:
            break
        out.append((tr_lo, tr_hi, te_lo, te_hi))
        y += test_years
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train-years", type=int, default=4)
    ap.add_argument("--test-years", type=int, default=1)
    ap.add_argument("--metric", default="mar", choices=["mar", "total", "sharpe", "cagr"],
                    help="학습구간에서 후보를 고르는 기준(기본 MAR=CAGR/MDD)")
    args = ap.parse_args()

    costs = Costs(C.TAX_BPS, C.FEE_BPS, C.SLIPPAGE_BPS)
    secmap = P._sector_map()
    dates, bars, _closes, _ordered = P._load(DATA_START, DATA_END, TOP_N)
    folds = _folds(dates, args.train_years, args.test_years)
    _assert_folds(folds)

    print("=" * 112)
    print(f"워크포워드 검증 — 학습 {args.train_years}년 / 검증 {args.test_years}년 롤링 · "
          f"선택기준 {args.metric.upper()} · 후보 {len(GRID)}개 · 폴드 {len(folds)}개")
    print(f"데이터 {dates[0]}~{dates[-1]} ({len(dates)} 영업일) · 유니버스 시총상위 {TOP_N}")
    print("=" * 112)
    print(f"  {'검증구간':11} {'학습구간':23} {'선택된 규칙':22} "
          f"{'학습MAR':>8} {'검증수익':>9} {'검증MDD':>8} {'벤치마크':>9}")
    print("  " + "-" * 100)

    oos_returns, oos_bench, picks = [], [], []
    strat_curves, bench_curves = [], []
    oos_days = 0
    for tr_lo, tr_hi, te_lo, te_hi in folds:
        scored = []
        for cand in GRID:
            m = _run(cand, tr_lo, tr_hi, costs, secmap)
            _assert_window(m["_res"], tr_lo, tr_hi, dates, f"학습 {tr_lo[:4]}")
            scored.append((cand, m))
        best, tm = select(scored, args.metric)

        # ── 검증: 선택이 끝난 **뒤에만** 이 구간을 만진다 ──
        te = _run(best, te_lo, te_hi, costs, secmap)
        _assert_window(te["_res"], te_lo, te_hi, dates, f"검증 {te_lo[:4]}")
        _assert_no_leak(te["_res"], te_lo, te_hi, f"검증 {te_lo[:4]}")

        bcurve = _benchmark_curve(bars, dates, te_lo, te_hi)
        bench = (bcurve[-1] / bcurve[0] - 1) * 100 if len(bcurve) > 1 else 0.0
        oos_returns.append(te["total"])
        oos_bench.append(bench)
        picks.append(best.label)
        strat_curves.append(te["_res"].equity_curve)
        bench_curves.append(bcurve)
        oos_days += te["_res"].n_days
        tr_mar = "inf" if tm["mar"] == float("inf") else f"{tm['mar']:.2f}"
        print(f"  {te_lo[:4]:11} {tr_lo[:7]}~{tr_hi[:7]:<15} {best.label:22} "
              f"{tr_mar:>8} {te['total']:>+8.1f}% {te['mdd']:>7.1f}% {bench:>+8.1f}%")

    print("  " + "-" * 100)
    _summary(oos_returns, oos_bench, picks,
             _stitch(strat_curves), _stitch(bench_curves), oos_days)
    return 0


def _benchmark_curve(bars: dict, dates: list[str], lo: str, hi: str) -> list[float]:
    """같은 구간·같은 유니버스 동일가중 매수후보유의 **일별** 지수(시작=100).

    생존편향을 전략과 공유하므로 상대 비교가 유효하다. 일별로 만드는 이유는 MDD 를
    같은 기준으로 재기 위해서다 — 시작·끝 두 점만으로는 낙폭을 알 수 없다.
    """
    win = [d for d in dates if lo <= d <= hi]
    if not win:
        return []
    base = {}
    for code, dm in bars.items():
        first = next((dm[d]["close"] for d in win if d in dm), None)
        if first and first > 0:
            base[code] = first
    if not base:
        return []
    curve = []
    for d in win:
        vals = [bars[c][d]["close"] / base[c] for c in base if d in bars[c]]
        if vals:
            curve.append(sum(vals) / len(vals) * 100.0)
        elif curve:
            curve.append(curve[-1])
    return curve


def _benchmark(bars: dict, dates: list[str], lo: str, hi: str) -> float:
    """구간 총수익률(%) — 표 출력용."""
    c = _benchmark_curve(bars, dates, lo, hi)
    return (c[-1] / c[0] - 1) * 100 if len(c) > 1 else 0.0


def _stitch(curves: list[list[float]]) -> list[float]:
    """폴드별 자산곡선을 **복리로 이어붙인다**. 각 폴드는 직전 폴드가 끝난 자산에서 출발.

    폴드별 지표의 평균이 아니라 이어붙인 곡선에서 재야 한다 — 폴드 경계를 넘어 이어지는
    하락은 폴드별로 보면 두 개의 작은 낙폭으로 쪼개지는데, 운용자는 하나의 큰 낙폭을 겪는다.
    """
    out: list[float] = []
    level = 100.0
    for c in curves:
        if len(c) < 2:
            continue
        for v in c:
            out.append(level * v / c[0])
        level = out[-1]
    return out


def _mdd(curve: list[float]) -> float:
    peak, worst = (curve[0] if curve else 0.0), 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak * 100.0)
    return worst


def _cagr(curve: list[float], n_days: int) -> float:
    if len(curve) < 2 or curve[0] <= 0 or n_days <= 0:
        return 0.0
    return ((curve[-1] / curve[0]) ** (252.0 / n_days) - 1) * 100.0


def _summary(rets: list[float], bench: list[float], picks: list[str],
             strat: list[float], bmk: list[float], oos_days: int) -> None:
    n = len(rets)
    if not n or len(strat) < 2 or len(bmk) < 2:
        print("  폴드 없음 / 곡선 부족")
        return

    s_tot = (strat[-1] / strat[0] - 1) * 100
    b_tot = (bmk[-1] / bmk[0] - 1) * 100
    s_mdd, b_mdd = _mdd(strat), _mdd(bmk)
    s_cagr, b_cagr = _cagr(strat, oos_days), _cagr(bmk, oos_days)
    s_mar = s_cagr / s_mdd if s_mdd > 0 else float("inf")
    b_mar = b_cagr / b_mdd if b_mdd > 0 else float("inf")
    wins = sum(1 for r in rets if r > 0)
    beats = sum(1 for r, b in zip(rets, bench) if r > b)

    print(f"  OOS 이어붙인 자산곡선 ({oos_days} 영업일, {oos_days / 252:.1f}년)")
    print(f"    {'':14}{'누적':>10}{'CAGR':>9}{'MDD':>9}{'MAR':>8}")
    print(f"    {'전략':14}{s_tot:>+9.1f}%{s_cagr:>+8.1f}%{s_mdd:>8.1f}%{s_mar:>8.2f}")
    print(f"    {'벤치마크':14}{b_tot:>+9.1f}%{b_cagr:>+8.1f}%{b_mdd:>8.1f}%{b_mar:>8.2f}")
    print(f"  플러스 연도 {wins}/{n} · 벤치마크 상회 연도 {beats}/{n}")
    uniq: dict[str, int] = {}
    for p_ in picks:
        uniq[p_] = uniq.get(p_, 0) + 1
    print("  선택된 규칙  " + " · ".join(f"{k}×{v}" for k, v in
                                     sorted(uniq.items(), key=lambda x: -x[1])))
    if len(uniq) > 1:
        print("    ※ 폴드마다 다른 규칙이 뽑혔다 = 학습구간 최적값이 불안정.")
        print("      견고한 것은 '어느 계열이 뽑히는가'뿐이고, 세부 파라미터는 근거가 못 된다.")

    print()
    print("  판정 — 기준은 **결과를 보기 전에** 코드 상수로 선언됨(MDD_RATIO/MIN_WIN_YEARS)")
    c1 = s_mdd <= b_mdd * MDD_RATIO
    c2 = s_mar >= b_mar
    c3 = wins >= n * MIN_WIN_YEARS
    print(f"    [{'O' if c1 else 'X'}] ① 위험 절반: 전략 MDD {s_mdd:.1f}% "
          f"≤ 벤치마크 {b_mdd:.1f}% × {MDD_RATIO:g} = {b_mdd * MDD_RATIO:.1f}%")
    print(f"    [{'O' if c2 else 'X'}] ② 수익 하한: 전략 MAR {s_mar:.2f} ≥ 벤치마크 {b_mar:.2f}")
    print(f"    [{'O' if c3 else 'X'}] ③ 플러스 연도 {wins}/{n} ≥ {MIN_WIN_YEARS:.0%}")
    if c1 and c2 and c3:
        print("    → **조건 충족** — 다음 단계(모의운용 후 단계적 재개) 검토 가능")
    else:
        print("    → 조건 미충족 — 신규진입 정지 유지(TREND_ENTRY_HALT=true)")
    print()
    print("  ※ 유니버스 생존편향은 전략·벤치마크가 **공유**한다 → 상대 비교만 유효,")
    print("     절대 수익률은 실제보다 부풀려져 있다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
