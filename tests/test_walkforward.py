"""워크포워드 하니스 자체의 회귀 — 2026-08-28.

이 하니스는 "측정이 조용히 틀리는 것"을 막으려고 만들었다. 그러니 하니스의 안전장치가
실제로 발동하는지를 먼저 잠가야 한다. 안전장치가 죽어 있으면 없느니만 못하다 —
통과했다는 사실이 근거로 쓰이기 때문이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import walkforward_trend as W  # noqa: E402


class _FakeRes:
    def __init__(self, n_days, entry_dates=()):
        self.n_days = n_days
        self.entry_dates = list(entry_dates)


def _dates(*years):
    """연도별 영업일 근사 — 각 연도 250일."""
    out = []
    for y in years:
        for i in range(250):
            out.append(f"{y}-{(i // 21) + 1:02d}-{(i % 21) + 1:02d}")
    return sorted(out)


# ─── 폴드 경계 ────────────────────────────────────────────────────────────────
def test_folds_never_overlap():
    """★ 학습 종료 < 검증 시작. 겹치면 그 순간 워크포워드가 아니다."""
    folds = W._folds(_dates(2015, 2016, 2017, 2018, 2019, 2020, 2021), 4, 1)
    assert folds, "폴드가 하나도 안 만들어졌다"
    W._assert_folds(folds)                       # 예외 없이 통과해야
    for tr_lo, tr_hi, te_lo, te_hi in folds:
        assert tr_hi < te_lo


def test_assert_folds_rejects_overlap():
    """겹치는 폴드를 넣으면 반드시 실패해야 한다(안전장치 생존 확인)."""
    with pytest.raises(AssertionError, match="겹친다|경계"):
        W._assert_folds([("2015-01-01", "2019-12-31", "2019-01-01", "2019-12-31")])


def test_assert_folds_rejects_reversed():
    with pytest.raises(AssertionError):
        W._assert_folds([("2019-01-01", "2015-12-31", "2020-01-01", "2020-12-31")])


def test_folds_roll_forward_by_test_years():
    folds = W._folds(_dates(2015, 2016, 2017, 2018, 2019, 2020, 2021), 4, 1)
    tests = [f[2][:4] for f in folds]
    assert tests == sorted(tests), "검증구간이 시간순이 아니다"
    assert len(set(tests)) == len(tests), "같은 검증구간이 두 번 쓰였다"


# ─── 구간 truncation (2026-08-27 결함) ────────────────────────────────────────
def test_assert_window_catches_truncation():
    """★ `--start` 무시로 구간이 조용히 잘리던 결함의 재발 방지."""
    ds = _dates(2020, 2021)
    with pytest.raises(AssertionError, match="영업일 불일치"):
        W._assert_window(_FakeRes(120), "2020-01-01", "2021-12-31", ds, "테스트")


def test_assert_window_passes_when_exact():
    ds = _dates(2020, 2021)
    n = sum(1 for d in ds if "2020-01-01" <= d <= "2021-12-31")
    W._assert_window(_FakeRes(n), "2020-01-01", "2021-12-31", ds, "테스트")


def test_assert_window_rejects_too_short():
    ds = _dates(2020)
    with pytest.raises(AssertionError, match="너무 짧다"):
        W._assert_window(_FakeRes(10), "2020-01-01", "2020-01-10", ds, "테스트")


# ─── 학습/검증 누수 ───────────────────────────────────────────────────────────
def test_assert_no_leak_catches_out_of_window_entry():
    """★ 검증구간 밖에서 진입한 거래가 섞이면 실패해야 한다."""
    res = _FakeRes(250, ["2020-06-01", "2019-12-30"])
    with pytest.raises(AssertionError, match="구간 밖 진입"):
        W._assert_no_leak(res, "2020-01-01", "2020-12-31", "테스트")


def test_assert_no_leak_passes_when_clean():
    W._assert_no_leak(_FakeRes(250, ["2020-06-01", "2020-11-20"]),
                      "2020-01-01", "2020-12-31", "테스트")


# ─── 선택 규칙 ────────────────────────────────────────────────────────────────
def test_select_is_deterministic_and_picks_best():
    a, b, c = W.GRID[0], W.GRID[1], W.GRID[2]
    scored = [(a, {"n": 5, "mar": 0.10}), (b, {"n": 5, "mar": 0.30}), (c, {"n": 5, "mar": 0.20})]
    assert W.select(scored, "mar")[0] is b
    # 순서를 섞어도 같은 답 — 재현 가능해야 한다
    assert W.select(list(reversed(scored)), "mar")[0] is b


def test_select_breaks_ties_by_declared_order():
    """동점이면 **사전 선언 순서**(GRID)가 이긴다 — 결과가 재현 가능해야 하므로."""
    a, b = W.GRID[0], W.GRID[3]
    picked = W.select([(b, {"n": 5, "mar": 0.2}), (a, {"n": 5, "mar": 0.2})], "mar")[0]
    assert picked is a, "동점 처리에 순서 의존성이 있다 — 실행마다 답이 달라진다"


def test_select_handles_empty_and_nan():
    """거래 0건·NaN·inf 후보가 섞여도 터지지 않고 정상 후보를 고른다."""
    a, b, c = W.GRID[0], W.GRID[1], W.GRID[2]
    scored = [(a, {"n": 0}), (b, {"n": 3, "mar": float("nan")}), (c, {"n": 4, "mar": 0.05})]
    assert W.select(scored, "mar")[0] is c


def test_select_picks_least_bad_when_all_negative():
    """학습구간이 전부 손실이어도 규칙대로 고른다 — 실제 운용의 그 시점 판단과 같다."""
    a, b = W.GRID[0], W.GRID[1]
    assert W.select([(a, {"n": 5, "mar": -0.5}), (b, {"n": 5, "mar": -0.1})], "mar")[0] is b


# ─── 격자 무결성 ──────────────────────────────────────────────────────────────
def test_grid_includes_live_configuration():
    """★ 현행 라이브 구성이 후보에 없으면 '개선했다'는 주장의 기준점이 사라진다."""
    live = [c for c in W.GRID if set(c.exits) == {"partial", "trail", "ma", "hold"}]
    assert live, "현행 사다리가 후보 격자에 없다"
    assert any(c.max_pos == 5 for c in live), "현행 슬롯 수(5) 구성이 없다"


def test_grid_labels_unique():
    labels = [c.label for c in W.GRID]
    assert len(labels) == len(set(labels)), "라벨 중복 — 선택 결과 집계가 어긋난다"


def test_grid_is_small_enough():
    """후보가 많을수록 학습구간 과적합이 커진다 — 격자 크기를 의식적으로 제한한다."""
    assert len(W.GRID) <= 12, f"후보 {len(W.GRID)}개 — 격자를 늘리려면 근거를 문서에 남길 것"


def test_grid_is_frozen():
    """Candidate 가 불변이어야 실행 중 조용히 바뀌지 않는다."""
    with pytest.raises(Exception):
        W.GRID[0].max_pos = 99


# ─── 벤치마크 ────────────────────────────────────────────────────────────────
def test_benchmark_equal_weight_math():
    """동일가중 보유 수익률이 산술평균으로 계산되는지."""
    dates = ["2020-01-01", "2020-06-01", "2020-12-31"]
    bars = {
        "A": {d: {"close": v} for d, v in zip(dates, [100.0, 110.0, 120.0])},   # +20%
        "B": {d: {"close": v} for d, v in zip(dates, [50.0, 45.0, 40.0])},      # -20%
    }
    assert W._benchmark(bars, dates, "2020-01-01", "2020-12-31") == pytest.approx(0.0)


def test_benchmark_ignores_stocks_without_data():
    dates = ["2020-01-01", "2020-12-31"]
    bars = {"A": {d: {"close": v} for d, v in zip(dates, [100.0, 150.0])}, "B": {}}
    assert W._benchmark(bars, dates, "2020-01-01", "2020-12-31") == pytest.approx(50.0)


def test_benchmark_empty_window_is_zero():
    assert W._benchmark({}, ["2020-01-01"], "2021-01-01", "2021-12-31") == 0.0


# ─── 판정 기준 (2026-08-28 사용자 선언: "위험이 절반이면 채택") ────────────────
def test_criteria_are_module_constants():
    """★ 기준이 코드 상수여야 git 이력이 '사후에 안 고쳤다'는 증거가 된다."""
    assert W.MDD_RATIO == 0.5, "선언된 '위험 절반'이 바뀌었다 — 변경은 문서에 근거를 남길 것"
    assert 0 < W.MIN_WIN_YEARS <= 1


# ─── 곡선 이어붙이기 ──────────────────────────────────────────────────────────
def test_stitch_compounds_across_folds():
    """★ 폴드는 직전 폴드가 끝난 자산에서 출발해야 한다(복리)."""
    f1 = [100.0, 110.0]          # +10%
    f2 = [50.0, 60.0]            # +20% (스케일 무관)
    out = W._stitch([f1, f2])
    assert out[0] == pytest.approx(100.0)
    assert out[-1] == pytest.approx(100.0 * 1.10 * 1.20)


def test_stitch_skips_degenerate_folds():
    assert W._stitch([[100.0], [], [100.0, 120.0]])[-1] == pytest.approx(120.0)


def test_stitch_empty_is_empty():
    assert W._stitch([]) == []


def test_stitch_preserves_intra_fold_shape():
    """폴드 내부의 오르내림이 보존돼야 MDD 를 잴 수 있다."""
    out = W._stitch([[100.0, 80.0, 120.0]])
    assert out == pytest.approx([100.0, 80.0, 120.0])


# ─── MDD ─────────────────────────────────────────────────────────────────────
def test_mdd_basic():
    assert W._mdd([100.0, 150.0, 75.0, 200.0]) == pytest.approx(50.0)


def test_mdd_monotonic_rise_is_zero():
    assert W._mdd([100.0, 110.0, 120.0]) == pytest.approx(0.0)


def test_mdd_spans_fold_boundary():
    """★ 폴드 경계를 넘는 연속 하락이 하나의 큰 낙폭으로 잡혀야 한다.

    폴드별 MDD 평균을 쓰면 -20%/-20% 두 개의 작은 낙폭으로 보이지만,
    운용자가 실제로 겪는 것은 -36% 한 번이다.
    """
    f1 = [100.0, 80.0]       # 폴드1: -20%
    f2 = [100.0, 80.0]       # 폴드2: 다시 -20%
    stitched = W._stitch([f1, f2])
    assert W._mdd(stitched) == pytest.approx(36.0)   # 1 - 0.8*0.8
    assert W._mdd(f1) == pytest.approx(20.0)         # 폴드별로 보면 20% 에 불과


def test_mdd_empty_is_zero():
    assert W._mdd([]) == 0.0


# ─── CAGR ────────────────────────────────────────────────────────────────────
def test_cagr_one_year():
    assert W._cagr([100.0, 120.0], 252) == pytest.approx(20.0, abs=0.01)


def test_cagr_two_years_annualizes():
    assert W._cagr([100.0, 144.0], 504) == pytest.approx(20.0, abs=0.01)


def test_cagr_guards_bad_input():
    assert W._cagr([100.0], 252) == 0.0
    assert W._cagr([100.0, 120.0], 0) == 0.0


# ─── 벤치마크 일별 곡선 ───────────────────────────────────────────────────────
def test_benchmark_curve_is_daily_and_starts_at_100():
    dates = ["2020-01-01", "2020-06-01", "2020-12-31"]
    bars = {"A": {d: {"close": v} for d, v in zip(dates, [100.0, 120.0, 150.0])}}
    c = W._benchmark_curve(bars, dates, "2020-01-01", "2020-12-31")
    assert len(c) == 3
    assert c[0] == pytest.approx(100.0)
    assert c[-1] == pytest.approx(150.0)


def test_benchmark_curve_carries_forward_on_missing_day():
    """거래 없는 날은 직전 값을 유지 — 곡선에 구멍이 나면 MDD 가 왜곡된다."""
    dates = ["2020-01-01", "2020-06-01", "2020-12-31"]
    bars = {"A": {dates[0]: {"close": 100.0}, dates[2]: {"close": 90.0}}}
    c = W._benchmark_curve(bars, dates, "2020-01-01", "2020-12-31")
    assert len(c) == 3 and c[1] == pytest.approx(100.0)


def test_benchmark_curve_mdd_matches_underlying():
    dates = ["2020-01-01", "2020-06-01", "2020-12-31"]
    bars = {"A": {d: {"close": v} for d, v in zip(dates, [100.0, 60.0, 90.0])}}
    assert W._mdd(W._benchmark_curve(bars, dates, "2020-01-01", "2020-12-31")) == pytest.approx(40.0)


# ─── 노출 축 (2026-08-28 2차) ─────────────────────────────────────────────────
def test_exposure_is_global_not_in_grid():
    """★ 노출은 **후보 격자에 없어야** 한다.

    노출은 학습으로 찾을 전략 파라미터가 아니라 운용자의 위험 선호다. 격자에 넣으면
    폴드마다 위험 선호를 다시 고르게 되고(과적합), MAR 이 노출에 거의 불변이라
    그 선택은 사실상 난수가 된다.
    """
    exposures = {c.max_pos * c.position_pct for c in W.GRID}
    assert exposures == {100.0}, f"격자에 노출 축이 섞였다: {sorted(exposures)}"
    assert hasattr(W, "EXPOSURE"), "전역 노출 배수가 없다"


def test_exposure_default_is_full():
    assert W.EXPOSURE == 1.0
