"""시점별(PIT) 유니버스 — 워크포워드 하니스 (2026-10-21).

10-21 스냅샷 갱신으로 경계 3종목만 바뀌었는데 소급 하니스의 MAR 이 0.96→0.66 으로 움직였다.
시점별 하니스가 그 문제를 실제로 막는지 — 순위가 그날 정보만 쓰는지, 후보·breadth 가 그날
상위로 제한되는지, 판정이 선언대로 내려지는지 — 를 **실제 simulate 를 돌려** 확인한다.
목으로 경계를 대체하지 않는다(simulate 의 데이터 입력만 합성 일봉으로 바꾼다).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import backtest_dynamic as D  # noqa: E402
import backtest_trend_portfolio as P  # noqa: E402
import walkforward_trend as W  # noqa: E402
from backtest_walkforward import Costs  # noqa: E402
from src.mcp_servers.trend_mcp.signals import TrendConfig  # noqa: E402

N_DAYS = 200


def _dates(n: int = N_DAYS) -> list[str]:
    d0 = date(2020, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _series(dates: list[str], start: float, end: float, bullish: bool = True) -> dict:
    """완만한 상승 종가. bullish=False 면 같은 종가에 음봉(시가>종가) — breadth 만 바뀐다."""
    out, n = {}, len(dates)
    for i, d in enumerate(dates):
        c = start + (end - start) * i / (n - 1)
        o = c * (0.995 if bullish else 1.005)
        out[d] = {"date": d, "open": o, "high": max(o, c) * 1.001, "low": min(o, c) * 0.999,
                  "close": c, "volume": 1000, "value": 2e11}
    return out


@pytest.fixture
def universe(monkeypatch):
    """합성 4종목 — A·B 는 대형(상장주식 1000), C·D 는 소형(1). 그날 상위 2 = {A, B}."""
    P._SIG_MEMO.clear()
    P._DAY_TOP.clear()
    monkeypatch.setattr(P, "_kospi_upto", lambda s, e, d: [100.0] * 300)   # RS 기준: KOSPI 횡보

    def install(start: str, bearish_small: bool = False):
        ds = _dates()
        bars = {"A": _series(ds, 100, 200), "B": _series(ds, 100, 190),
                "C": _series(ds, 100, 210, bullish=not bearish_small),
                "D": _series(ds, 100, 205, bullish=not bearish_small)}
        ordered = {c: list(ds) for c in bars}
        closes = {c: [bars[c][d]["close"] for d in ds] for c in bars}
        for pit in (0, 50):
            key = (start, ds[-1], 2, pit, "")
            P._CACHE[key] = (ds, bars, closes, ordered)
        P._SHARES[(start, ds[-1], 2, 50, "")] = {"A": 1000, "B": 1000, "C": 1, "D": 1}
        return ds
    return install


def _sim(ds: list[str], start: str, pit: int, breadth: float = 0.0):
    cfg = TrendConfig(mode="largecap", pullback_pct=12.0)
    return P.simulate(start, ds[-1], 2, cfg, Costs(0, 0, 0), P.Sizing(mode="notional", position_pct=10),
                      10, 0, False, {}, hard_stop_pct=10.0, breadth_min=breadth,
                      exits=("ma",), pit_pool=pit)


def _held(res) -> set[str]:
    return {p["code"] for p in res.open_positions}


# ─── 후보 제한 ────────────────────────────────────────────────────────────────
def test_pit_buys_only_that_days_top(universe):
    """★ 시점별 모드는 그날 시총 상위(A·B)만 산다 — 소형 C·D 는 신호가 나도 후보가 아니다."""
    ds = universe("2020-01-01")
    res = _sim(ds, "2020-01-01", pit=50)
    assert _held(res) == {"A", "B"}, _held(res)


def test_retroactive_mode_buys_outside_top(universe):
    """같은 데이터를 소급 모드로 돌리면 C·D 도 산다 — 위 테스트의 제한이 PIT 코드에서 온다는 확인."""
    ds = universe("2020-01-01")
    res = _sim(ds, "2020-01-01", pit=0)
    assert _held(res) & {"C", "D"}, "소급 모드에서도 C·D 를 안 샀다 — 위 테스트가 아무것도 증명 못 한다"


def test_pit_breadth_uses_only_that_days_top(universe):
    """★ breadth 는 그날 상위(A·B 양봉)로만 잰다. 풀 전체(C·D 음봉 포함)로 재면 0.5 < 0.6 으로 막힌다."""
    ds = universe("2020-02-01", bearish_small=True)
    assert _sim(ds, "2020-02-01", pit=50, breadth=0.6).n_entries > 0
    assert _sim(ds, "2020-02-01", pit=0, breadth=0.6).n_entries == 0   # 4종 전체 → 0.5 → 차단


def test_pit_without_shares_fails_loudly(universe):
    """상장주식수가 없으면 유니버스가 조용히 빈다 — 실행을 멈춰야 한다."""
    ds = universe("2020-03-01")
    P._SHARES.pop(("2020-03-01", ds[-1], 2, 50, ""))
    with pytest.raises(RuntimeError, match="상장주식수"):
        _sim(ds, "2020-03-01", pit=50)


# ─── 순위: 그날 정보만 ────────────────────────────────────────────────────────
def test_day_top_uses_only_that_days_close():
    """★ 미래 바를 바꿔도 과거 날짜의 순위는 그대로 — look-ahead 없음."""
    ds = _dates(3)
    bars = {"A": {d: {"close": 100.0} for d in ds}, "B": {d: {"close": 90.0} for d in ds},
            "C": {d: {"close": 10.0} for d in ds}}
    shares = {"A": 10, "B": 10, "C": 10}
    before = P.day_top(bars, shares, ds[0], 2)
    bars["C"][ds[2]]["close"] = 10_000.0                 # 마지막 날 C 폭등
    assert P.day_top(bars, shares, ds[0], 2) == before == {"A", "B"}
    assert "C" in P.day_top(bars, shares, ds[2], 2)


def test_day_top_skips_missing_bar_and_zero_shares():
    d = "2020-01-01"
    bars = {"A": {d: {"close": 100.0}}, "B": {}, "C": {d: {"close": 500.0}}}
    assert P.day_top(bars, {"A": 10, "B": 10, "C": 0}, d, 3) == {"A"}


def test_pit_pool_snapshot_must_exist():
    """★ 없는 스냅샷을 최신으로 조용히 대체하면 스냅샷 비교가 무의미해진다."""
    with pytest.raises(FileNotFoundError):
        D.get_pit_pool(350, "19990101")


def test_pit_pool_pins_snapshot():
    snaps = sorted((_ROOT / "docs_cache").glob("universe_kiwoom_*.json"))
    if len(snaps) < 2:
        pytest.skip("스냅샷 2개 이상 필요")
    old = snaps[0].stem.replace("universe_kiwoom_", "")
    assert D.get_pit_pool(350, old) is D.get_pit_pool(350, old)          # 스냅샷별 캐시
    assert D.get_pit_pool(350, old) is not D.get_pit_pool(350, "")        # 최신과 별개


# ─── 워크포워드 배선·판정 ──────────────────────────────────────────────────────
def test_walkforward_defaults_to_pit():
    """★ 기본이 소급(생존편향)이면 안 된다 — 10-21 에 스냅샷 하나로 MAR 0.30 이 움직였다."""
    assert W.PIT_POOL == 350
    assert (W.PIT_ROBUST_MAR_TOL, W.PIT_ROBUST_MDD_TOL_PP) == (0.10, 2.0)   # 측정 전 선언값


def test_run_passes_pit_settings_to_simulator(monkeypatch):
    """★ 설정이 simulate 까지 안 가면 '시점별 검증'이 실제론 소급 검증이다."""
    seen = {}

    class _R:
        n_days = 1

    def fake_sim(*a, **kw):
        seen.update(kw)
        return _R()
    monkeypatch.setattr(P, "simulate", fake_sim)
    monkeypatch.setattr(P, "pmetrics", lambda res, n: {})
    monkeypatch.setattr(W, "SNAPSHOT", "20261021")
    W._run(W.GRID[0], "2020-01-01", "2020-12-31", Costs(0, 0, 0), {})
    assert seen["pit_pool"] == 350 and seen["snapshot"] == "20261021"


def test_benchmark_curve_respects_codes():
    ds = ["2020-01-01", "2020-12-31"]
    bars = {"A": {d: {"close": v} for d, v in zip(ds, [100.0, 150.0])},
            "B": {d: {"close": v} for d, v in zip(ds, [100.0, 50.0])}}
    assert W._benchmark_curve(bars, ds, ds[0], ds[1])[-1] == pytest.approx(100.0)
    assert W._benchmark_curve(bars, ds, ds[0], ds[1], frozenset({"A"}))[-1] == pytest.approx(150.0)


def test_bench_codes_are_first_day_top(monkeypatch):
    """시점별 벤치마크 = 검증구간 **첫날**의 상위 TOP_N(그날 살 수 있던 것)."""
    ds = ["2020-01-02", "2020-06-01"]
    bars = {"A": {ds[0]: {"close": 100.0}, ds[1]: {"close": 1.0}},
            "B": {ds[0]: {"close": 1.0}, ds[1]: {"close": 100.0}}}
    monkeypatch.setattr(W, "TOP_N", 1)
    monkeypatch.setattr(W, "SNAPSHOT", "t")
    P._SHARES[W._load_key()] = {"A": 1, "B": 1}
    assert W._bench_codes(bars, ds, "2020-01-01", "2020-12-31") == {"A"}


def test_benchmark_is_kodex200_buy_and_hold(monkeypatch):
    """★ 10-21 결정 — 벤치마크는 실제로 살 수 있는 KODEX200. 구 동일가중은 너무 쉬웠다."""
    import strategy_lab as L
    assert W.BENCHMARK == "kodex200"
    ds = ["2020-01-02", "2020-01-03", "2020-01-06"]
    monkeypatch.setattr(L, "load_bars", lambda code, s, e: {
        "2020-01-03": {"open": 100.0, "close": 100.0}, "2020-01-06": {"open": 100.0, "close": 130.0}})
    c = W._bench_curve({}, ds, ds[0], ds[-1])
    assert len(c) == len(ds), "전략 곡선과 길이가 다르면 MDD·연도 비교가 어긋난다"
    assert c[-1] == pytest.approx(130.0)


def test_ew_benchmark_still_available(monkeypatch):
    ds = ["2020-01-02", "2020-12-31"]
    bars = {"A": {d: {"close": v} for d, v in zip(ds, [100.0, 150.0])}}
    monkeypatch.setattr(W, "BENCHMARK", "ew")
    monkeypatch.setattr(W, "PIT_POOL", 0)
    assert W._bench_curve(bars, ds, ds[0], ds[1])[-1] == pytest.approx(150.0)


def _res(mar, mdd, ok=True):
    return {"s": {"mar": mar, "mdd": mdd}, "pass": ok}


def test_judge_robust_passes_small_difference():
    assert all(ok for _, ok, _ in W.judge_robust(_res(0.80, 20.0), _res(0.75, 21.5)))


@pytest.mark.parametrize("b, failed", [
    (_res(0.65, 20.0), "MAR 차이"),     # 0.15 > 0.10 — 10-21 소급 하니스는 0.30 이었다
    (_res(0.80, 22.5), "MDD 차이"),     # 2.5%p > 2.0
])
def test_judge_robust_each_criterion_fails(b, failed):
    """★ 규칙 3 — 허용폭을 일부러 넘겨 그 기준이 실제로 떨어지는지."""
    rows = {n: ok for n, ok, _ in W.judge_robust(_res(0.80, 20.0), b)}
    assert rows[failed] is False


@pytest.mark.parametrize("robust, current, expected", [
    (True, True, "CONTINUE"),
    (True, False, "HALT"),
    (False, True, "HALT"),     # ★ 하니스가 흔들리면 결과가 좋아도 근거가 없다
    (False, False, "HALT"),
])
def test_decide(robust, current, expected):
    assert W.decide(robust, current) == expected
