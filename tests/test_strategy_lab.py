"""전략 연구소 하니스 회귀 (2026-10-22).

이 하니스의 숫자가 앞으로 모든 전략의 채택 근거가 된다. 체결 시점·비용·정수 주식수·연도 수익·
판정 기준이 적힌 대로 동작하는지 — 특히 판정 기준은 하나씩 **일부러 깨뜨려** 확인한다(규칙 3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402


def _bars(prices: list[tuple[float, float]], start_day: int = 1, month: str = "2020-01") -> dict:
    return {f"{month}-{start_day + i:02d}": {"open": o, "close": c} for i, (o, c) in enumerate(prices)}


# ─── 잣대 ────────────────────────────────────────────────────────────────────
def test_declared_criteria_are_locked():
    """★ 운용자 선언(2026-10-22) — 바뀌면 git 이력에 남는다."""
    assert (L.MAX_MDD_PCT, L.MIN_YEAR_RET_PCT, L.MIN_EXCESS_CAGR_PP) == (20.0, -10.0, 5.0)
    assert L.BENCH_CODE == "069500", "벤치마크는 KODEX200 단순보유(10-21 결정)"
    assert set(L.PERIODS) == {"박스권", "강세장"}


# ─── 체결 ────────────────────────────────────────────────────────────────────
def test_signal_fills_at_next_open_not_same_close():
    """★ 신호일 종가가 아니라 다음 날 시가에 산다 — 같은 날 종가 체결은 미래 정보다."""
    bars = _bars([(100, 100), (110, 120), (120, 130)])
    dates = sorted(bars)
    res = L.simulate({"X": L.Asset("X", bars)}, dates, lambda i, d: {"X": 1.0} if i == 0 else None)
    unit = 110 * (1 + L._side_cost(False, False))            # 둘째 날 시가 + 비용
    assert res.curve[0] == pytest.approx(1.0)                  # 신호일엔 아직 현금
    assert res.curve[1] == pytest.approx(120 / unit)
    assert res.curve[2] == pytest.approx(130 / unit)


def test_stock_sell_pays_tax_etf_does_not():
    bars = _bars([(100, 100), (100, 100), (100, 100), (100, 100)])
    dates = sorted(bars)
    tgt = lambda i, d: {"X": 1.0} if i == 0 else ({} if i == 1 else None)   # noqa: E731
    stock = L.simulate({"X": L.Asset("X", bars, taxed=True)}, dates, tgt)
    etf = L.simulate({"X": L.Asset("X", bars, taxed=False)}, dates, tgt)
    assert stock.curve[-1] < etf.curve[-1], "주식 매도세가 빠졌다"
    gap = etf.curve[-1] - stock.curve[-1]
    assert gap == pytest.approx(L.C.TAX_BPS / 10_000 * etf.curve[-1] / (1 - L._side_cost(False, True)), rel=0.05)


def test_integer_shares_leave_cash_when_price_exceeds_budget():
    """★ 예탁금을 주면 정수 주식수 — 1주 값이 예산보다 비싸면 못 산다(소액 계좌 제약)."""
    bars = _bars([(1000, 1000), (1000, 1000), (1000, 1000)])
    dates = sorted(bars)
    res = L.simulate({"X": L.Asset("X", bars)}, dates, lambda i, d: {"X": 0.5} if i == 0 else None,
                     equity=1500)
    assert res.curve[-1] == pytest.approx(1500, abs=1e-6), "예산 750원으로 1000원짜리를 샀다"


def test_rebalance_reduces_overweight_position():
    bars = _bars([(100, 100), (100, 100), (100, 100), (100, 100)])
    dates = sorted(bars)
    tgt = lambda i, d: {"X": 1.0} if i == 0 else ({"X": 0.5} if i == 1 else None)   # noqa: E731
    res = L.simulate({"X": L.Asset("X", bars)}, dates, tgt)
    assert res.trades == 2


def test_buy_and_hold_tracks_price_minus_entry_cost():
    bars = _bars([(100, 100), (100, 105), (110, 150)])
    dates = sorted(bars)
    res = L.buy_and_hold("X", dates, bars)
    assert res.curve[-1] == pytest.approx(150 / (100 * (1 + L._side_cost(False, False))))


# ─── 지표 ────────────────────────────────────────────────────────────────────
def test_metrics_years_and_worst_year():
    dates = ["2020-01-02", "2020-12-30", "2021-06-01", "2021-12-30"]
    m = L.metrics(dates, [100.0, 120.0, 90.0, 108.0])
    assert m["years"]["2020"] == pytest.approx(20.0)
    assert m["years"]["2021"] == pytest.approx(-10.0)
    assert m["worst_year"] == pytest.approx(-10.0)
    assert m["mdd"] == pytest.approx(25.0)


def test_slice_metrics_uses_window_start_as_base():
    res = L.SimResult(dates=["2018-12-28", "2019-01-02", "2019-12-30"], curve=[50.0, 100.0, 130.0])
    m = L.slice_metrics(res, "2019-01-01", "2019-12-31")
    assert m["total"] == pytest.approx(30.0)


# ─── 판정 ────────────────────────────────────────────────────────────────────
def _m(cagr, mdd=10.0, worst=-5.0):
    return {"cagr": cagr, "mdd": mdd, "mar": cagr / mdd, "total": 0, "years": {}, "worst_year": worst}


_BENCH = {"전체": _m(15.0, 40.0, -20.0), "박스권": _m(4.0), "강세장": _m(23.0)}


def _good():
    return {"전체": _m(21.0, 18.0, -8.0), "박스권": _m(6.0), "강세장": _m(25.0)}


def test_judge_passes_strategy_meeting_all():
    assert L.passed(L.judge(_good(), _BENCH))


@pytest.mark.parametrize("mutate, failed", [
    (lambda s: s["전체"].update(mdd=20.5), "① 최대낙폭"),
    (lambda s: s["전체"].update(worst_year=-10.5), "② 최악 연도"),
    (lambda s: s["전체"].update(cagr=19.9), "③ 초과 수익"),          # 15 + 5 = 20 미만
    (lambda s: s["박스권"].update(cagr=3.9), "④ 박스권"),
    (lambda s: s["강세장"].update(cagr=22.9), "④ 강세장"),
    (lambda s: s.pop("박스권"), "④ 박스권"),                          # 구간 데이터가 없으면 통과 못 한다
])
def test_judge_each_criterion_actually_fails(mutate, failed):
    """★ 규칙 3 — 기준을 하나씩 일부러 깨뜨려 그 기준이 실제로 떨어지는지."""
    s = _good()
    mutate(s)
    rows = {name: ok for name, ok, _ in L.judge(s, _BENCH)}
    assert rows[failed] is False
    assert not L.passed(L.judge(s, _BENCH))


def test_index_candidates_grids_are_declared():
    """★ 10-22 측정 전 선언 — 격자·기본값이 바뀌면 이력에 남는다."""
    import lab_index_candidates as X
    assert X.GRID_MA == (20, 40, 60, 80, 100, 120, 150, 200, 250) and X.DEFAULT_MA == 60
    assert X.GRID_DM == (3, 6, 9, 12) and X.DEFAULT_DM == 12


def test_ma_filter_uses_only_past_closes():
    """★ 미래 종가를 바꿔도 과거 날짜의 신호는 그대로 — look-ahead 없음."""
    import lab_index_candidates as X
    sig = {f"2020-01-{k + 1:02d}": {"open": 100.0, "close": c} for k, c in enumerate([100, 101, 102, 90, 80])}
    t = X.ma_filter(sig, 3, "A")
    before = t(0, "2020-01-03")
    sig["2020-01-05"]["close"] = 1.0
    assert X.ma_filter(sig, 3, "A")(0, "2020-01-03") == before == {"A": 1.0}
    assert t(0, "2020-01-04") == {}                    # 90 < MA3(97.7) → 현금


def test_leveraged_bars_doubles_daily_move():
    bars = {"2020-01-01": {"open": 100.0, "close": 100.0}, "2020-01-02": {"open": 100.0, "close": 110.0}}
    lev = L.leveraged_bars(bars, 2.0, fee_pa=0.0)
    assert lev["2020-01-02"]["close"] == pytest.approx(120.0)


def test_blend_grids_are_declared():
    """★ 10-22 측정 전 선언."""
    import lab_blend as G
    assert G.G1_GRID == (0.3, 0.4, 0.5, 0.6, 0.7) and G.G1_DEFAULT == 0.5
    assert G.G2_GRID == (0.2, 0.3, 0.4, 0.5) and G.G2_DEFAULT == 0.3


def test_blend_reweights_latest_component_weights():
    """한 구성요소만 새 비중을 내도 다른 구성요소의 **최신** 비중과 함께 재조합한다. 합 ≤ 1."""
    import lab_blend as G
    calls = {"a": [{"X": 1.0}, None, {"Y": 1.0}], "b": [{"Z": 1.0}, None, None]}
    fa = lambda i, d: calls["a"][i]   # noqa: E731
    fb = lambda i, d: calls["b"][i]   # noqa: E731
    t = G.blend([(0.3, fa), (0.7, fb)])
    assert t(0, "d0") == pytest.approx({"X": 0.3, "Z": 0.7})
    assert t(1, "d1") is None                                  # 아무도 안 바뀌면 유지
    assert t(2, "d2") == pytest.approx({"Y": 0.3, "Z": 0.7})   # b 는 직전 비중 유지


def test_drawdown_grid_is_declared():
    """★ 10-22 측정 전 선언."""
    import lab_drawdown as H
    assert H.DEFAULT == (10, 20) and len(H.GRID) == 15
    assert {x for x, _ in H.GRID} == {5, 8, 10, 12, 15} and {n for _, n in H.GRID} == {10, 20, 40}


def _dd_bars(closes):
    return {f"2020-01-{k + 1:02d}": {"open": c, "close": c} for k, c in enumerate(closes)}


def test_drawdown_exit_leaves_after_x_percent_from_peak():
    """★ 진입 후 최고 종가 대비 −X% 에서 이탈 — 그 전엔 신호 없음."""
    import lab_drawdown as H
    bars = _dd_bars([100, 110, 104, 99, 98])           # 최고 110 → 99 는 −10%
    t = H.drawdown_exit(bars, "A", 10, 2, "C")
    days = sorted(bars)
    assert t(0, days[0]) == {"A": 1.0}                 # 시작은 보유
    assert t(1, days[1]) is None and t(2, days[2]) is None
    assert t(3, days[3]) == {"C": 1.0}                 # 99 ≤ 110 × 0.9


def test_drawdown_exit_reenters_on_new_n_day_high_only():
    """현금 상태에서 직전 n일 최고 종가를 **넘어야** 재진입 — 같으면 안 된다."""
    import lab_drawdown as H
    bars = _dd_bars([100, 80, 85, 85, 86])
    t = H.drawdown_exit(bars, "A", 10, 2, "C")
    days = sorted(bars)
    t(0, days[0])
    assert t(1, days[1]) == {"C": 1.0}                 # −20% 이탈
    assert t(2, days[2]) is None                       # 85 > max(100,80)? 아니다
    assert t(3, days[3]) is None                       # 85 > max(80,85)? 같으면 아님
    assert t(4, days[4]) == {"A": 1.0}                 # 86 > max(85,85)


def test_drawdown_exit_no_lookahead():
    import lab_drawdown as H
    bars = _dd_bars([100, 110, 104, 99, 98])
    days = sorted(bars)
    t1 = H.drawdown_exit(bars, "A", 10, 2, "C")
    r1 = [t1(i, d) for i, d in enumerate(days[:3])]
    bars[days[4]]["close"] = 1.0                       # 미래 종가 변경
    t2 = H.drawdown_exit(bars, "A", 10, 2, "C")
    assert [t2(i, d) for i, d in enumerate(days[:3])] == r1


def test_dd_control_grids_are_declared():
    """★ 10-22 측정 전 선언."""
    import lab_dd_control as I
    assert I.I1_DEFAULT == (10, 20) and len(I.I1_GRID) == 9 and I.I1_REGIME_MA == 120
    assert I.I2_GRID == (2, 3, 5, 8) and I.I2_DEFAULT == 5
    assert (I.I2_FLOOR_DD, I.I2_BAND) == (18.0, 0.10)


def test_drawdown_budget_exposure_shrinks_with_drawdown():
    """★ 낙폭 예산 — 최고치에선 m×18%, 낙폭이 바닥선(−18%)에 닿으면 0."""
    import lab_dd_control as I
    t = I.drawdown_budget("A", 3, "C")
    assert t(0, "d0", 100.0) == pytest.approx({"A": 0.54, "C": 0.46})
    assert t(1, "d1", 91.0) == pytest.approx({"A": 3 * (91 - 82) / 91, "C": 1 - 3 * (91 - 82) / 91})
    assert t(2, "d2", 82.0) == {"C": 1.0}                     # 바닥 → 위험자산 0
    t5 = I.drawdown_budget("A", 8, "C")
    assert t5(0, "d0", 100.0) == {"A": 1.0}                   # 상한 1(레버리지 없음)


def test_drawdown_budget_trades_only_beyond_band():
    import lab_dd_control as I
    t = I.drawdown_budget("A", 3, "C")
    t(0, "d0", 100.0)                                           # e = 0.54
    assert t(1, "d1", 99.0) is None                             # e ≈ 0.52 → 10%p 미만 변화
    assert t(2, "d2", 95.0) is not None                         # e ≈ 0.41 → 매매


def test_simulate_passes_closing_nav_when_asked():
    bars = _bars([(100, 100), (100, 120), (100, 130)])
    dates = sorted(bars)
    seen = []

    def tgt(i, d, nav):
        seen.append(nav)
        return {"X": 1.0} if i == 0 else None
    L.simulate({"X": L.Asset("X", bars)}, dates, tgt, pass_nav=True)
    assert seen[0] == pytest.approx(1.0) and seen[1] > 1.15     # 둘째 날 종가 반영


def test_reentry_requires_regime_up():
    """★ I1 — n일 고점을 넘어도 KOSPI 가 MA 아래면 재진입하지 않는다."""
    import lab_dd_control as I
    bars = {f"2020-01-{k + 1:02d}": {"open": c, "close": c} for k, c in enumerate([100, 80, 85, 90])}
    days = sorted(bars)
    down = {d: {"open": c, "close": c} for d, c in zip(days, [100, 90, 80, 70])}   # KOSPI 하락
    up = {d: {"open": c, "close": c} for d, c in zip(days, [100, 101, 102, 103])}  # KOSPI 상승
    for kospi, expect in ((down, None), (up, {"A": 1.0})):
        t = I.reentry_confirmed(bars, kospi, "A", 10, 1, "C", regime_ma=2)
        t(0, days[0])
        assert t(1, days[1]) == {"C": 1.0}                    # −20% 이탈
        assert t(2, days[2]) == expect                        # 85 > 80 돌파 — 레짐에 따라


def test_holdout_is_after_training_and_declared():
    """★ 미공개 구간은 학습 구간이 끝난 **뒤**여야 한다 — 겹치면 검증이 아니다."""
    assert L.HOLDOUT == ("2026-08-25", "2026-10-21")
    assert L.FULL[1] < L.HOLDOUT[0]
    assert (L.HO_MDD_RATIO, L.HO_MIN_RET_PCT) == (0.5, -10.0)


@pytest.mark.parametrize("s, failed", [
    ({"total": -16.0, "mdd": 5.0}, "HO① 수익 ≥ 지수"),
    ({"total": -2.0, "mdd": 10.0}, "HO② 낙폭 ≤ 지수×½"),
    ({"total": -11.0, "mdd": 5.0}, "HO③ 수익 ≥ −10%"),
])
def test_judge_holdout_each_criterion_fails(s, failed):
    """★ 규칙 3 — 미공개 기준도 하나씩 일부러 깨뜨린다. 지수 = 수익 −15%, MDD 19%."""
    b = {"total": -15.0, "mdd": 19.0}
    rows = {n: ok for n, ok, _ in L.judge_holdout(s, b)}
    assert rows[failed] is False
    assert L.passed(L.judge_holdout({"total": -2.0, "mdd": 5.0}, b))


def test_i3_grid_declared_and_recovers_after_lookback():
    """★ I3 — 바닥에 닿으면 비중 0, **최근 L일** 최고치가 내려오면 다시 위험을 진다(현금 고착 방지)."""
    import lab_holdout as H3
    assert H3.I3_DEFAULT == (6, 252) and len(H3.I3_GRID) == 9
    days = [f"2020-01-{k + 1:02d}" for k in range(8)]
    bars = {d: {"open": 100.0, "close": 100.0} for d in days}       # 엔진은 계속 보유
    t = H3.i3(bars, bars, "A", "C", m=6, lookback=3, x_pct=50)
    navs = [100, 82, 82, 82, 82, 82]
    ws = [t(i, d, nv) for i, (d, nv) in enumerate(zip(days, navs))]
    assert ws[0] == {"A": 1.0}                                       # 최고치에서 m×18% ≥ 1
    assert ws[1] == {"C": 1.0}                                       # 바닥(−18%) → 0
    assert ws[2] is None                                             # 창 안에 아직 100 → 0 유지
    assert ws[3] == {"A": 1.0}                                       # 최근 3일 최고치 82 → 다시 보유


def test_i3_respects_engine_exit():
    import lab_holdout as H3
    days = ["2020-01-01", "2020-01-02", "2020-01-03"]
    bars = {d: {"open": c, "close": c} for d, c in zip(days, [100, 100, 85])}   # −15% → 엔진 이탈
    t = H3.i3(bars, bars, "A", "C", m=6, lookback=252, x_pct=10)
    t(0, days[0], 100.0)
    t(1, days[1], 100.0)
    assert t(2, days[2], 100.0) == {"C": 1.0}


def test_i4_grids_declared():
    """★ 10-22 측정 전 선언."""
    import lab_i4 as X
    assert X.LEV_DEFAULT == (11, 252) and len(X.LEV_GRID) == 9 and X.LEV_CAP == 2.0
    assert X.ROT_DEFAULT == (6, 252) and len(X.ROT_GRID) == 9


def _flat(days, v=100.0):
    return {d: {"open": v, "close": v} for d in days}


def test_i4_leverage_splits_without_borrowing():
    """★ 실효 노출 e>1 이면 레버리지 (e−1) + 기본 (2−e) — 비중 합 ≤ 1(차입 없음)."""
    import lab_i4 as X
    days = [f"2020-01-{k + 1:02d}" for k in range(3)]
    t = X.i4(_flat(days), _flat(days), 11, 252, lev=True, rotate=False)
    w = t(0, days[0], 100.0)                                   # 최고점: e = min(2, 11×0.18) = 1.98
    assert w[X.LEV] == pytest.approx(0.98) and w[X.BASE] == pytest.approx(0.02)
    assert sum(w.values()) == pytest.approx(1.0)
    w2 = t(1, days[1], 95.0)                                   # 낙폭 5% → e = 11×(95−82)/95 ≈ 1.505
    assert w2[X.LEV] == pytest.approx(11 * 13 / 95 - 1, rel=1e-6)


def test_i4_rotation_picks_stronger_and_never_levers_alt():
    """한·미 교체 — 최근 252일 수익이 큰 쪽. 나스닥이 선택되면 레버리지 없음."""
    import lab_i4 as X
    days = [f"2019-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 26)] + ["2020-01-02"]
    base = {d: {"open": 100.0, "close": 100.0 + i * 0.01} for i, d in enumerate(days)}     # 약한 상승
    alt = {d: {"open": 100.0, "close": 100.0 + i * 0.5} for i, d in enumerate(days)}       # 강한 상승
    t = X.i4(base, base, 11, 252, lev=True, rotate=True, alt_bars=alt)
    ws = [w for w in (t(i, d, 100.0) for i, d in enumerate(days)) if w is not None]
    first_alt = next(w for w in ws if X.ALT in w)                 # 252일 이력이 생긴 뒤 첫 달에 교체
    assert X.LEV not in first_alt and first_alt[X.ALT] <= 1.0
    assert any(X.LEV in w for w in ws[:1]), "교체 전(KODEX200)엔 최고점에서 레버리지를 썼어야 한다"


def test_robustness_uses_median_not_best():
    """★ 가장 좋은 설정 하나가 아니라 중앙값으로 판정한다."""
    grid = [{"전체": _m(c, 15.0, -5.0), "박스권": _m(5.0), "강세장": _m(24.0)} for c in (5.0, 6.0, 40.0)]
    med = L.robustness(grid)
    assert med["전체"]["cagr"] == pytest.approx(6.0)
    assert not L.passed(L.judge(med, _BENCH)), "최고 설정(40%)이 중앙값 판정을 통과시켰다"
