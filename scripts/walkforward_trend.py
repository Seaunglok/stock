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
import math
import sys
from dataclasses import dataclass, replace
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

# ── 유니버스 — 시점별(PIT) 이 기본 (2026-10-21 선언, 측정 전) ─────────────────
#
# 08-28 ~ 10-20 의 정본 수치는 **현재** 시총 상위 100 을 과거에 소급한 유니버스로 쟀다.
# 10-21 스냅샷을 갱신해 경계 3종목(96~111위)만 바뀌었는데 MAR 0.96→0.66, 기준 ① 미달이 됐다
# (docs/2026-10-21-universe-refresh-revalidation.md). 스냅샷마다 과거 성적이 바뀌는 하니스로는
# 운용 판정을 할 수 없다. 현재 시총 상위 PIT_POOL 풀을 받아 두고 **매일 그날 종가 × 상장주식수로
# 상위 TOP_N 을 다시 뽑는다**(backtest_trend.py 의 V_PIT_UNIVERSE 와 같은 방식).
# 남는 편향: 풀이 '현재' 상위 350 이라 그 밖으로 떨어진 종목은 복원 안 됨 · 상장주식수 현재값 고정.
PIT_POOL = 350           # 0 = 구 동작(소급 유니버스, `--no-pit`)
SNAPSHOT = ""            # 풀을 뽑을 스냅샷(YYYYMMDD). 빈 값 = 최신

# PIT 하니스의 **강건성** — 스냅샷을 바꿔도 결과가 거의 같아야 판정에 쓸 수 있다.
# 소급 하니스는 08-28→10-21 에서 MAR 0.30 · MDD 4.0%p 움직였다. 그 1/3 수준 이내를 요구한다.
# 미달이면 PIT 하니스로도 판정할 수 없다는 뜻이므로 **보수적으로 신규진입 정지**한다.
PIT_ROBUST_MAR_TOL = 0.10
PIT_ROBUST_MDD_TOL_PP = 2.0


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

# ── 노출(exposure) 축 — **폴드별로 고르지 않는다** (2026-08-28 2차) ──────────
#
# 1차 검증에서 ①(위험 절반)만 미충족이었다(MDD 34.1% vs 목표 22.7%). 격자가 전부
# 사실상 만기 투자(슬롯5×20% / 20×5% = 100%)라 노출을 낮출 방법이 아예 없었다.
#
# 노출을 **후보 격자에 넣어 폴드마다 고르게 하지 않는다.** 노출은 학습으로 찾을 전략
# 파라미터가 아니라 **운용자의 위험 선호**다. 폴드별로 고르면 위험 선호를 과적합하게 되고,
# 게다가 MAR 은 노출에 대략 불변이라(수익·MDD 가 함께 비례 축소) 선택이 사실상 난수가 된다.
#
# 대신 전역 배수로 두고 **같은 절차를 여러 노출에서 돌려 프론티어를 보고**한다.
# 어느 점을 택할지는 사람이 정한다 — 그게 위험 선호의 정의다.
#
# ⚠️ 예상되는 결과를 미리 적어 둔다(측정 전 선언): MDD 는 노출에 거의 비례하므로
#    노출 ~0.65 에서 ① 이 충족될 가능성이 높다. 그렇게 통과한다면 그것은
#    **"전략이 좋아졌다"가 아니라 "크기를 줄였다"** 는 뜻이다. ① 은 이 축을 열면
#    산술적으로 거의 자동 충족되므로, 판단의 무게는 ②(MAR) 에 두어야 한다.
EXPOSURE = 1.0           # 전 후보의 position_pct 에 곱하는 배수(운영 결정, 학습 대상 아님)


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
    entry: str = "pullback"          # TrendConfig.entry_mode — 진입 타점 A/B(2026-10-12)


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


def select(scored: list[tuple[Candidate, dict]], metric: str,
           grid: tuple[Candidate, ...] = GRID) -> tuple[Candidate, dict]:
    """학습구간 성적으로 후보 하나를 **기계적으로** 고른다.

    사람이 개입하지 않는다는 것이 요점이다. 동점이면 grid 순서(= 사전 선언 순서)를 따르므로
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
        return (v, -grid.index(cand))
    return max(scored, key=key)


# ── 진입 타점 A/B — **결과를 보기 전에 선언한다** (2026-10-12) ──────────────────
#
# 질문: 눌림(MA20~+12%) 대신 구루 다수가 쓰는 **돌파**로 사면 나은가.
# 근거 문서: docs/2026-10-12-breakout-entry-declaration.md
#
# 측정 전 사실(성과 미열람): 현행 진입 3,161건 중 28.2% 가 이미 20일 고가 돌파일,
# 57.5% 가 20일 고가 3% 이내였다 — 이름만큼 다른 규칙이 아니다.
#
# 절차 4개를 **같은 실행에서** 잰다. 각 절차는 자기 메뉴에서 매년 학습구간으로 하나를 고른다.
#   A   현행 — GRID(눌림 7종). 기준점
#   B   메뉴 추가 — 눌림 7 + 돌파20 7 + 돌파55 7. "고를 수 있게 하면 나은가"
#   C20 교체 — 돌파20 7종. "바꾸면 나은가"(사용자 질문 그대로)
#   C55 교체 — 돌파55 7종
# 돌파 메뉴는 GRID 의 청산·슬롯 구성을 **그대로** 복제하고 진입만 바꾼다(다른 변수 고정).
def _with_entry(grid: tuple[Candidate, ...], entry: str, tag: str) -> tuple[Candidate, ...]:
    return tuple(replace(c, label=f"{c.label}·{tag}", entry=entry) for c in grid)


GRID_B20 = _with_entry(GRID, "breakout20", "돌파20")
GRID_B55 = _with_entry(GRID, "breakout55", "돌파55")
ENTRY_BASELINE = "A"
ENTRY_PROCEDURES: dict[str, tuple[Candidate, ...]] = {
    "A": GRID,
    "B": GRID + GRID_B20 + GRID_B55,
    "C20": GRID_B20,
    "C55": GRID_B55,
}
ENTRY_PROC_LABEL = {"A": "현행(눌림)", "B": "메뉴추가(눌림+돌파)",
                    "C20": "교체(돌파20)", "C55": "교체(돌파55)"}

# 도전자 X 가 A 를 대체하려면 아래를 **전부** 충족해야 한다.
#   ① 기존 절대 기준(MDD_RATIO · MAR≥벤치마크 · MIN_WIN_YEARS) — 08-28 선언 그대로
#   ② MAR(X) ≥ MAR(A) + ENTRY_MAR_MARGIN            ← 개선이 '오차 수준'이 아닐 것
#   ③ MDD(X) ≤ MDD(A) + ENTRY_MDD_SLACK_PP          ← 위험을 의미 있게 늘리지 않을 것
#   ④ 검증연도 수익이 A 보다 높은 폴드 ≥ ENTRY_MIN_FOLD_WIN_RATIO  ← 한두 해 몰림 배제
#   ⑤ PIT 가드 — `backtest_trend.py --entrytest`(시점별 유니버스 12년 거래당)에서 X 가 쓰는
#      돌파 규칙의 기대값·PF 가 눌림 이상일 것. 이 하니스의 유니버스는 **현재** 시총 상위라
#      생존편향이 있는데, 강세를 사는 돌파가 그 편향의 수혜를 더 받을 수 있다. ①~④만으로는
#      '돌파가 낫다'와 '생존자가 돌파를 많이 했다'를 가르지 못한다.
# 여럿이 통과하면 OOS MAR 이 가장 높은 것 — 이 선택 자체가 OOS 를 보는 것이므로 채택 수치는
# 낙관 편향을 갖는다고 함께 적는다. 하나도 통과 못 하면 현행 유지, 돌파 기간을 바꿔 다시 재지 않는다.
#
# ※ 8폴드로는 MAR 차이 0.1 의 통계적 유의성을 보일 수 없다(연 변동 ~20% → MAR 표준오차 ~0.4).
#   이 기준은 '유의한 개선'이 아니라 '바꿀 만한 근거가 있는가'의 최소선이다.
ENTRY_MAR_MARGIN = 0.10
ENTRY_MDD_SLACK_PP = 3.0
ENTRY_MIN_FOLD_WIN_RATIO = 0.60


def judge_entry(base: dict, chal: dict, bench: dict,
                base_folds: list[float], chal_folds: list[float]) -> list[tuple[str, bool, str]]:
    """도전자 판정 ①~④ — [(기준, 통과, 설명)]. ⑤(PIT)는 별도 스크립트라 여기 없다.

    base/chal/bench: _stats() 결과(mdd·mar·wins·n). *_folds: 폴드별 검증 수익(%) — 같은 순서.
    """
    if len(base_folds) != len(chal_folds) or not base_folds:
        raise ValueError("폴드 수가 다르거나 0 — 같은 실행에서 잰 절차끼리만 비교한다")
    n = len(chal_folds)
    abs_ok = (chal["mdd"] <= bench["mdd"] * MDD_RATIO and chal["mar"] >= bench["mar"]
              and chal["wins"] >= n * MIN_WIN_YEARS)
    fold_wins = sum(1 for b, c in zip(base_folds, chal_folds) if c > b)
    need_folds = math.ceil(n * ENTRY_MIN_FOLD_WIN_RATIO)
    return [
        ("① 절대 기준", abs_ok,
         f"MDD {chal['mdd']:.1f}% ≤ {bench['mdd'] * MDD_RATIO:.1f}% · MAR {chal['mar']:.2f} ≥ "
         f"{bench['mar']:.2f} · 플러스 {chal['wins']}/{n}"),
        ("② MAR 개선", chal["mar"] >= base["mar"] + ENTRY_MAR_MARGIN,
         f"{chal['mar']:.2f} ≥ {base['mar']:.2f} + {ENTRY_MAR_MARGIN:g}"),
        ("③ MDD 상한", chal["mdd"] <= base["mdd"] + ENTRY_MDD_SLACK_PP,
         f"{chal['mdd']:.1f}% ≤ {base['mdd']:.1f}% + {ENTRY_MDD_SLACK_PP:g}%p"),
        ("④ 폴드 우위", fold_wins >= need_folds, f"A 보다 나은 폴드 {fold_wins}/{n} ≥ {need_folds}"),
    ]


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
    t.entry_mode = c.entry
    return t


def _run(c: Candidate, lo: str, hi: str, costs: Costs, secmap: dict) -> dict:
    from trend_config import BREADTH_MIN_PCT, RANK_MODE, REGIME_MA
    P._SIG_MEMO.clear()
    res = P.simulate(DATA_START, DATA_END, TOP_N, _cfg(c), costs,
                     P.Sizing(mode="notional", position_pct=c.position_pct * EXPOSURE),
                     c.max_pos, 0, "partial" in c.exits, secmap,
                     hard_stop_pct=c.hard_stop, rank_mode=RANK_MODE,
                     regime_ma=REGIME_MA, breadth_min=BREADTH_MIN_PCT,
                     exits=c.exits, sim_from=lo, sim_to=hi,
                     pit_pool=PIT_POOL, snapshot=SNAPSHOT)
    m = P.pmetrics(res, res.n_days)
    m["_res"] = res
    return m


def _load_key() -> tuple:
    return (DATA_START, DATA_END, TOP_N, PIT_POOL, SNAPSHOT)


def _bench_codes(bars: dict, dates: list[str], lo: str, hi: str) -> frozenset[str] | None:
    """벤치마크 종목 — 시점별이면 **검증구간 첫날의** 시총 상위 TOP_N(그날 살 수 있던 것).

    소급 모드(None)는 로드된 전 종목 = 현재 상위 TOP_N(구 동작). 시점별 모드에서 풀 350 전체를
    벤치마크로 쓰면 전략(상위 100)과 다른 모집단을 비교하게 된다.
    """
    if not PIT_POOL:
        return None
    first = next((d for d in dates if lo <= d <= hi), None)
    if first is None:
        return frozenset()
    return P.day_top(bars, P._SHARES[_load_key()], first, TOP_N, _load_key())


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
    ap.add_argument("--select-now", action="store_true",
                    help="연간 재선택 — 직전 train-years 로 올해 쓸 규칙 하나를 고르고 .env 형식으로 출력")
    ap.add_argument("--exposure", type=float, default=1.0,
                    help="전 후보 노출 배수(1.0=만기투자). 운영 결정이지 학습 대상이 아니다")
    ap.add_argument("--entry-ab", action="store_true",
                    help="진입 타점 A/B — 눌림 vs 돌파 절차 4개를 같은 폴드에서 비교(2026-10-12 선언)")
    ap.add_argument("--no-pit", action="store_true",
                    help="소급 유니버스(현재 시총 상위를 과거에 적용) — 구 동작 재현용, 생존편향 포함")
    ap.add_argument("--snapshot", default="",
                    help="시점별 풀을 뽑을 유니버스 스냅샷 YYYYMMDD(기본 최신)")
    ap.add_argument("--compare-snapshots", default="",
                    help="A,B — 두 스냅샷으로 같은 절차를 돌려 강건성·운용 판정(2026-10-21 선언). "
                         "판정은 마지막(B) 스냅샷 기준")
    args = ap.parse_args()
    global EXPOSURE, PIT_POOL, SNAPSHOT
    EXPOSURE = args.exposure
    if not 0.05 <= EXPOSURE <= 1.5:
        raise SystemExit(f"--exposure 범위 이상: {EXPOSURE}")
    if args.no_pit:
        PIT_POOL = 0
    SNAPSHOT = args.snapshot

    costs = Costs(C.TAX_BPS, C.FEE_BPS, C.SLIPPAGE_BPS)
    secmap = P._sector_map()
    if args.compare_snapshots:
        snaps = [s.strip() for s in args.compare_snapshots.split(",") if s.strip()]
        if len(snaps) != 2 or not PIT_POOL:
            raise SystemExit("--compare-snapshots 는 A,B 두 개 + 시점별 모드에서만")
        return _compare_snapshots(snaps, costs, secmap, args.train_years, args.test_years, args.metric)
    dates, bars, _closes, _ordered = P._load(*_load_key())
    if args.select_now:
        return _select_now(dates, costs, secmap, args.train_years, args.metric)
    if args.entry_ab:
        return _entry_ab(dates, bars, costs, secmap, args.train_years, args.test_years, args.metric)
    folds = _folds(dates, args.train_years, args.test_years)
    _assert_folds(folds)
    _header("워크포워드 검증", dates, folds, args)
    _summary(*_walk(dates, bars, costs, secmap, folds, args.metric))
    return 0


def _universe_label() -> str:
    if not PIT_POOL:
        return f"유니버스 소급(현재 시총상위 {TOP_N}) ⚠️ 생존편향"
    return f"유니버스 시점별(풀 {PIT_POOL}·스냅샷 {SNAPSHOT or '최신'} → 매일 시총상위 {TOP_N})"


def _header(title: str, dates: list[str], folds: list, args) -> None:
    print("=" * 112)
    print(f"{title} — 학습 {args.train_years}년 / 검증 {args.test_years}년 롤링 · "
          f"선택기준 {args.metric.upper()} · 후보 {len(GRID)}개 · 폴드 {len(folds)}개 · "
          f"노출 {EXPOSURE:.0%}")
    print(f"데이터 {dates[0]}~{dates[-1]} ({len(dates)} 영업일) · {_universe_label()}")
    print("=" * 112)


def _walk(dates: list[str], bars: dict, costs: Costs, secmap: dict,
          folds: list[tuple[str, str, str, str]], metric: str) -> tuple:
    """GRID 로 폴드마다 고르고 검증 — `_summary` 인자 튜플을 돌려준다(폴드 표는 여기서 출력)."""
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
        best, tm = select(scored, metric)

        # ── 검증: 선택이 끝난 **뒤에만** 이 구간을 만진다 ──
        te = _run(best, te_lo, te_hi, costs, secmap)
        _assert_window(te["_res"], te_lo, te_hi, dates, f"검증 {te_lo[:4]}")
        _assert_no_leak(te["_res"], te_lo, te_hi, f"검증 {te_lo[:4]}")

        bcurve = _benchmark_curve(bars, dates, te_lo, te_hi, _bench_codes(bars, dates, te_lo, te_hi))
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
    return (oos_returns, oos_bench, picks, _stitch(strat_curves), _stitch(bench_curves), oos_days)


def judge_robust(a: dict, b: dict) -> list[tuple[str, bool, str]]:
    """두 스냅샷 결과(_summary 반환값)의 차이가 선언 허용폭 이내인가 — [(기준, 통과, 설명)]."""
    dm = abs(a["s"]["mar"] - b["s"]["mar"])
    dd = abs(a["s"]["mdd"] - b["s"]["mdd"])
    return [
        ("MAR 차이", dm <= PIT_ROBUST_MAR_TOL,
         f"|{a['s']['mar']:.2f} − {b['s']['mar']:.2f}| = {dm:.2f} ≤ {PIT_ROBUST_MAR_TOL:g}"),
        ("MDD 차이", dd <= PIT_ROBUST_MDD_TOL_PP,
         f"|{a['s']['mdd']:.1f} − {b['s']['mdd']:.1f}| = {dd:.1f}%p ≤ {PIT_ROBUST_MDD_TOL_PP:g}%p"),
    ]


def decide(robust_ok: bool, current_pass: bool) -> str:
    """운용 판정(2026-10-21 선언). 강건성 미달이면 결과와 무관하게 정지 — 판정 근거가 없으므로."""
    if not robust_ok:
        return "HALT"
    return "CONTINUE" if current_pass else "HALT"


def _compare_snapshots(snaps: list[str], costs: Costs, secmap: dict,
                       train_years: int, test_years: int, metric: str) -> int:
    """같은 절차를 두 스냅샷의 시점별 풀로 돌려 강건성을 보고, **B(최신)** 결과로 운용을 판정한다."""
    global SNAPSHOT
    out = {}
    for snap in snaps:
        SNAPSHOT = snap
        dates, bars, _c, _o = P._load(*_load_key())
        folds = _folds(dates, train_years, test_years)
        _assert_folds(folds)
        ns = argparse.Namespace(train_years=train_years, test_years=test_years, metric=metric)
        _header(f"워크포워드 [{snap}]", dates, folds, ns)
        out[snap] = _summary(*_walk(dates, bars, costs, secmap, folds, metric))
    a, b = out[snaps[0]], out[snaps[1]]
    print("=" * 112)
    print(f"강건성 — 스냅샷 {snaps[0]} vs {snaps[1]} (선언 허용폭: MAR ±{PIT_ROBUST_MAR_TOL:g} · "
          f"MDD ±{PIT_ROBUST_MDD_TOL_PP:g}%p)")
    rows = judge_robust(a, b)
    for name, ok, text in rows:
        print(f"    [{'O' if ok else 'X'}] {name}: {text}")
    same = a["picks"] == b["picks"]
    print(f"    (참고) 폴드별 선택 규칙 {'동일' if same else '다름'}")
    robust_ok = all(ok for _, ok, _ in rows)
    verdict = decide(robust_ok, b["pass"])
    print()
    if verdict == "CONTINUE":
        print(f"  → 운용 지속 — 강건성 통과 + 최신 스냅샷({snaps[1]}) 기준 ①②③ 충족")
    elif not robust_ok:
        print("  → 신규진입 정지(TREND_ENTRY_HALT=true) — 시점별 하니스도 스냅샷에 흔들려 판정 근거가 없다")
    else:
        print(f"  → 신규진입 정지(TREND_ENTRY_HALT=true) — 최신 스냅샷({snaps[1]}) 기준 ①②③ 미충족")
    return 0


def _select_now(dates: list[str], costs: Costs, secmap: dict,
                train_years: int, metric: str) -> int:
    """연간 재선택 — 직전 train_years 로 **올해 쓸 규칙 하나**를 고른다.

    워크포워드가 잰 것은 특정 규칙의 성적이 아니라 **"매년 학습구간으로 다시 고르는 절차"**
    의 성적이다(8폴드에서 4종이 뽑혔다). 그 절차를 매년 실행하지 않으면 검증된 것과
    다른 전략을 돌리는 셈이 된다. 그래서 문서가 아니라 **명령**으로 만든다.

    선택 규칙·후보 격자는 워크포워드와 **같은 것을 쓴다**(GRID/select) — 갈리면 검증 무효.
    """
    yr = int(dates[-1][:4])
    lo, hi = f"{yr - train_years}-01-01", f"{yr - 1}-12-31"
    n = sum(1 for d in dates if lo <= d <= hi)
    print("=" * 92)
    print(f"연간 재선택 — {yr}년에 쓸 규칙 (학습 {lo[:7]}~{hi[:7]}, {n} 영업일, 기준 {metric.upper()})")
    print(f"  {_universe_label()}")
    print("=" * 92)
    if n < 250 * train_years * 0.8:
        print(f"  ⚠️ 학습 영업일이 부족하다({n}) — 데이터 범위(DATA_END={DATA_END})를 확인할 것")
    scored = []
    for cand in GRID:
        m = _run(cand, lo, hi, costs, secmap)
        _assert_window(m["_res"], lo, hi, dates, "재선택")
        scored.append((cand, m))
        mar = "inf" if m["mar"] == float("inf") else f"{m['mar']:.2f}"
        print(f"  {cand.label:24} MAR {mar:>6} · 수익 {m['total']:>+8.1f}% · "
              f"MDD {m['mdd']:>5.1f}% · 거래 {m['entries']:>4}")
    best, bm = select(scored, metric)
    print("-" * 92)
    print(f"  선택: **{best.label}**  (학습 {metric.upper()} "
          f"{bm['mar'] if metric == 'mar' else bm.get(metric):.2f})")
    print()
    print("  .env 에 반영할 값:")
    print(f"    TREND_EXITS={','.join(best.exits)}")
    print(f"    TREND_EXIT_MA={best.exit_ma}")
    print(f"    TREND_MAX_HOLD={best.max_hold}")
    print(f"    TREND_MAX_POS={best.max_pos}")
    print(f"    TREND_SIZING_MODE=notional")
    print(f"    TREND_POSITION_PCT={best.position_pct * EXPOSURE:g}   "
          f"# 총 노출 {best.max_pos * best.position_pct * EXPOSURE:.0f}%")
    print()
    print("  ※ 이 출력을 그대로 반영할 것. 결과를 보고 다른 후보를 고르면 워크포워드가 무효가 된다.")
    print("  ※ 반영 후 `pytest tests/test_trend_config.py` 스냅샷도 함께 갱신한다.")
    return 0


def _entry_ab(dates: list[str], bars: dict, costs: Costs, secmap: dict,
              train_years: int, test_years: int, metric: str) -> int:
    """진입 타점 A/B — 사전 선언된 절차(ENTRY_PROCEDURES)를 **같은 폴드**에서 잰다.

    후보의 학습 성적은 폴드당 한 번만 잰다. B 의 메뉴는 A·C20·C55 의 합집합이라 그 결과를
    그대로 나눠 쓴다(같은 후보를 절차마다 다시 돌리면 시간만 4배). 선택·판정 규칙은 모듈
    상수 — 결과를 본 뒤 바꾸면 이 검증은 무효다.
    """
    folds = _folds(dates, train_years, test_years)
    _assert_folds(folds)
    menu: list[Candidate] = []
    for grid in ENTRY_PROCEDURES.values():
        menu.extend(c for c in grid if c not in menu)

    print("=" * 112)
    print(f"진입 타점 A/B — 학습 {train_years}년 / 검증 {test_years}년 롤링 · 선택기준 {metric.upper()} · "
          f"후보 {len(menu)}개 · 폴드 {len(folds)}개 · 노출 {EXPOSURE:.0%}")
    print(f"데이터 {dates[0]}~{dates[-1]} ({len(dates)} 영업일) · 유니버스 시총상위 {TOP_N}")
    print("  절차: " + " · ".join(f"{k}={ENTRY_PROC_LABEL[k]}({len(g)})"
                                for k, g in ENTRY_PROCEDURES.items()))
    print("=" * 112)

    per = {k: {"rets": [], "curves": [], "picks": [], "days": 0} for k in ENTRY_PROCEDURES}
    bench_rets, bench_curves = [], []
    for tr_lo, tr_hi, te_lo, te_hi in folds:
        train = {}
        for cand in menu:
            m = _run(cand, tr_lo, tr_hi, costs, secmap)
            _assert_window(m["_res"], tr_lo, tr_hi, dates, f"학습 {tr_lo[:4]} {cand.label}")
            train[cand] = m
        # ── 검증: 모든 절차의 선택이 끝난 **뒤에만** 이 구간을 만진다 ──
        picks = {k: select([(c, train[c]) for c in g], metric, g)[0]
                 for k, g in ENTRY_PROCEDURES.items()}
        tested = {}
        for cand in dict.fromkeys(picks.values()):
            te = _run(cand, te_lo, te_hi, costs, secmap)
            _assert_window(te["_res"], te_lo, te_hi, dates, f"검증 {te_lo[:4]} {cand.label}")
            _assert_no_leak(te["_res"], te_lo, te_hi, f"검증 {te_lo[:4]} {cand.label}")
            tested[cand] = te
        bcurve = _benchmark_curve(bars, dates, te_lo, te_hi, _bench_codes(bars, dates, te_lo, te_hi))
        bench_curves.append(bcurve)
        bench_rets.append((bcurve[-1] / bcurve[0] - 1) * 100 if len(bcurve) > 1 else 0.0)
        line = []
        for k, cand in picks.items():
            te, p = tested[cand], per[k]
            p["rets"].append(te["total"])
            p["curves"].append(te["_res"].equity_curve)
            p["picks"].append(cand.label)
            p["days"] += te["_res"].n_days
            line.append(f"{k}:{te['total']:+6.1f}%")
        print(f"  {te_lo[:4]}  " + "  ".join(line) + f"  벤치 {bench_rets[-1]:+6.1f}%")
        for k, cand in picks.items():
            print(f"         {k:3} ← {cand.label}")

    days = {p["days"] for p in per.values()}
    if len(days) != 1:
        raise AssertionError(f"절차별 검증 영업일이 다르다 {days} — 같은 구간 비교가 아니다")
    oos_days = days.pop()
    bstat = _curve_stats(_stitch(bench_curves), oos_days)
    stats = {}
    for k, p in per.items():
        stats[k] = {**_curve_stats(_stitch(p["curves"]), oos_days),
                    "wins": sum(1 for r in p["rets"] if r > 0), "n": len(p["rets"])}

    print("  " + "-" * 100)
    print(f"  OOS 이어붙인 자산곡선 ({oos_days} 영업일, {oos_days / 252:.1f}년)")
    print(f"    {'':22}{'누적':>10}{'CAGR':>9}{'MDD':>9}{'MAR':>8}{'플러스':>8}")
    for k, s in stats.items():
        print(f"    {k + ' ' + ENTRY_PROC_LABEL[k]:22}{s['total']:>+9.1f}%{s['cagr']:>+8.1f}%"
              f"{s['mdd']:>8.1f}%{s['mar']:>8.2f}{s['wins']:>5}/{s['n']}")
    print(f"    {'벤치마크':22}{bstat['total']:>+9.1f}%{bstat['cagr']:>+8.1f}%"
          f"{bstat['mdd']:>8.1f}%{bstat['mar']:>8.2f}")
    for k, p in per.items():
        uniq: dict[str, int] = {}
        for lb in p["picks"]:
            uniq[lb] = uniq.get(lb, 0) + 1
        print(f"    {k:3} 선택: " + " · ".join(f"{lb}×{v}" for lb, v in
                                           sorted(uniq.items(), key=lambda x: -x[1])))

    print()
    print("  판정 — 기준은 **결과를 보기 전에** 선언됨(ENTRY_* 상수, 2026-10-12 커밋)")
    base = stats[ENTRY_BASELINE]
    passed = []
    for k in ENTRY_PROCEDURES:
        if k == ENTRY_BASELINE:
            continue
        rows = judge_entry(base, stats[k], bstat, per[ENTRY_BASELINE]["rets"], per[k]["rets"])
        ok = all(r[1] for r in rows)
        print(f"    {k} {ENTRY_PROC_LABEL[k]} → {'①~④ 충족' if ok else '미충족'}")
        for name, good, text in rows:
            print(f"      [{'O' if good else 'X'}] {name}: {text}")
        if ok:
            passed.append(k)
    print()
    if passed:
        best = max(passed, key=lambda k: stats[k]["mar"])
        print(f"  → ①~④ 통과: {', '.join(passed)} · 후보 {best}. **⑤ PIT 가드가 남았다** — "
              "`backtest_trend.py --entrytest` 에서 돌파 규칙 기대값·PF ≥ 눌림이어야 채택.")
        if len(passed) > 1:
            print("    ※ 여럿 중 OOS MAR 로 고른 것이라 그 수치는 낙관 편향을 갖는다.")
    else:
        print("  → 통과한 도전자 없음 — 현행(눌림) 유지. 돌파 기간을 바꿔 다시 재지 않는다(선언).")
    print("  ※ 유니버스 생존편향은 절차들이 공유하지만, 돌파가 그 수혜를 더 받을 수 있다 → ⑤ 필수.")
    return 0


def _curve_stats(curve: list[float], n_days: int) -> dict:
    """이어붙인 자산곡선 → 누적·CAGR·MDD·MAR. 곡선이 2점 미만이면 0."""
    if len(curve) < 2:
        return {"total": 0.0, "cagr": 0.0, "mdd": 0.0, "mar": 0.0}
    mdd, cagr = _mdd(curve), _cagr(curve, n_days)
    return {"total": (curve[-1] / curve[0] - 1) * 100, "cagr": cagr, "mdd": mdd,
            "mar": cagr / mdd if mdd > 0 else float("inf")}


def _benchmark_curve(bars: dict, dates: list[str], lo: str, hi: str,
                     codes: frozenset[str] | None = None) -> list[float]:
    """같은 구간·같은 유니버스 동일가중 매수후보유의 **일별** 지수(시작=100).

    생존편향을 전략과 공유하므로 상대 비교가 유효하다. 일별로 만드는 이유는 MDD 를
    같은 기준으로 재기 위해서다 — 시작·끝 두 점만으로는 낙폭을 알 수 없다.
    codes: 벤치마크 종목 제한(시점별 모드 — `_bench_codes`). None 이면 로드된 전 종목.
    """
    win = [d for d in dates if lo <= d <= hi]
    if not win:
        return []
    base = {}
    for code, dm in bars.items():
        if codes is not None and code not in codes:
            continue
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
             strat: list[float], bmk: list[float], oos_days: int) -> dict:
    """출력 + 판정 결과 반환 {s, b, wins, n, pass, picks, rets}. 곡선이 없으면 pass=False."""
    n = len(rets)
    if not n or len(strat) < 2 or len(bmk) < 2:
        print("  폴드 없음 / 곡선 부족")
        return {"s": _curve_stats([], 0), "b": _curve_stats([], 0), "wins": 0, "n": n,
                "pass": False, "picks": list(picks), "rets": list(rets)}

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
    return {"s": {"total": s_tot, "cagr": s_cagr, "mdd": s_mdd, "mar": s_mar},
            "b": {"total": b_tot, "cagr": b_cagr, "mdd": b_mdd, "mar": b_mar},
            "wins": wins, "n": n, "pass": bool(c1 and c2 and c3),
            "picks": list(picks), "rets": list(rets)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
