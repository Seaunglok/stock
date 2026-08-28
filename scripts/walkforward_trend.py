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

        bench = _benchmark(bars, dates, te_lo, te_hi)
        oos_returns.append(te["total"])
        oos_bench.append(bench)
        picks.append(best.label)
        tr_mar = "inf" if tm["mar"] == float("inf") else f"{tm['mar']:.2f}"
        print(f"  {te_lo[:4]:11} {tr_lo[:7]}~{tr_hi[:7]:<15} {best.label:22} "
              f"{tr_mar:>8} {te['total']:>+8.1f}% {te['mdd']:>7.1f}% {bench:>+8.1f}%")

    print("  " + "-" * 100)
    _summary(oos_returns, oos_bench, picks)
    return 0


def _benchmark(bars: dict, dates: list[str], lo: str, hi: str) -> float:
    """같은 구간·같은 유니버스 동일가중 매수후보유. 생존편향을 전략과 공유한다."""
    win = [d for d in dates if lo <= d <= hi]
    if not win:
        return 0.0
    rets = []
    for dm in bars.values():
        a = next((dm[d]["close"] for d in win if d in dm), None)
        b = next((dm[d]["close"] for d in reversed(win) if d in dm), None)
        if a and b and a > 0:
            rets.append((b / a - 1) * 100)
    return sum(rets) / len(rets) if rets else 0.0


def _summary(rets: list[float], bench: list[float], picks: list[str]) -> None:
    n = len(rets)
    if not n:
        print("  폴드 없음")
        return
    comp = 1.0
    for r in rets:
        comp *= (1 + r / 100)
    bcomp = 1.0
    for r in bench:
        bcomp *= (1 + r / 100)
    wins = sum(1 for r in rets if r > 0)
    beats = sum(1 for r, b in zip(rets, bench) if r > b)
    print(f"  OOS 누적(복리)      전략 {(comp - 1) * 100:+.1f}%   벤치마크 {(bcomp - 1) * 100:+.1f}%")
    print(f"  플러스 연도         {wins}/{n}")
    print(f"  벤치마크 상회 연도   {beats}/{n}")
    print(f"  연 평균             전략 {sum(rets) / n:+.1f}%   벤치마크 {sum(bench) / n:+.1f}%")
    uniq = {}
    for p in picks:
        uniq[p] = uniq.get(p, 0) + 1
    print(f"  선택된 규칙          " + " · ".join(f"{k}×{v}" for k, v in
                                               sorted(uniq.items(), key=lambda x: -x[1])))
    if len(uniq) > 1:
        print("    ※ 폴드마다 다른 규칙이 뽑혔다 = 학습구간 최적값이 불안정하다는 뜻.")
        print("      이 경우 개별 규칙의 in-sample 성적은 채택 근거가 되지 못한다.")
    print()
    print("  판정 — 신규진입 재개는 아래를 **전부** 충족해야 한다(2026-08-28 선언):")
    ok1, ok2 = (comp > bcomp), (wins >= n * 0.6)
    print(f"    [{'O' if ok1 else 'X'}] OOS 누적이 동일가중 벤치마크 초과")
    print(f"    [{'O' if ok2 else 'X'}] 플러스 연도 ≥ 60% ({wins}/{n})")
    print(f"    → {'조건 충족 — 다음 단계(모의운용) 검토' if ok1 and ok2 else '조건 미충족 — 신규진입 정지 유지'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
