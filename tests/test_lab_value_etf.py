"""가치 ETF × I3 엔진 등록 선언(lab_value_etf) — 신호가 ETF 자기 가격인지, 리그 규칙·장부와 맞는지 (2026-11-18 선언 전 작성)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import i3_core as K  # noqa: E402
import i3_shadow as S  # noqa: E402
import lab_reentry as R  # noqa: E402
import lab_trials as T  # noqa: E402
import lab_value_etf as V  # noqa: E402


def weekdays(n: int, start: str = "2015-01-05") -> list[str]:
    out, x = [], date.fromisoformat(start)
    while len(out) < n:
        if x.weekday() < 5:
            out.append(x.isoformat())
        x += timedelta(days=1)
    return out


def synth(n: int = 320, drop_at: int = 250):
    """KOSPI·KODEX200 은 꾸준히 오르고, ETF 만 drop_at 에 15% 빠진 뒤 옆걸음."""
    ds = weekdays(n)
    up = {d: {"open": 100 + i * 0.1, "close": 100 + i * 0.1} for i, d in enumerate(ds)}
    etf = {}
    for i, d in enumerate(ds):
        c = 100 + i * 0.1 if i < drop_at else (100 + drop_at * 0.1) * 0.85
        etf[d] = {"open": c, "close": c}
    return ds, {K.BASE: up, V.ETF: etf, V.KOSPI: {d: dict(v) for d, v in up.items()}}


def test_constants_match_league_and_core():
    assert V.KOSPI == S.KOSPI and V.DIVERGE_PP == S.DIVERGE_PP
    assert V.ETF == "223190" and V.REGISTER_ON == "2026-11-20" and V.NAME.isascii() is False   # 한글 이름 — Notion 표시 풀네임 불필요
    assert "fb77fa5" in V.BASIS and "33e666d" in V.BASIS


def test_build_runs_i3_engine_on_the_etf_own_price():
    """★ 신호가 ETF 자기 가격 — ETF 만 15% 빠지면 이 멤버는 나가고, KODEX200 의 I3 는 그대로 있다."""
    ds, data = synth()
    codes, t, needs_nav = V.build(data, ds)
    assert codes == (V.ETF, K.CASH) and needs_nav
    i3 = R.i3r(data[K.BASE], data[V.KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, "I3")
    ref = R.i3r(data[V.ETF], data[V.KOSPI], V.ETF, K.CASH, K.M, K.LOOKBACK, "I3")     # 선언 문장 그대로의 호출
    w_v = w_i3 = None
    out_day = None
    for i, d in enumerate(ds):
        a, b, c = t(i, d, 1_000_000.0), i3(i, d, 1_000_000.0), ref(i, d, 1_000_000.0)
        assert a == c, d                                                   # 같은 엔진·같은 파라미터
        if a is not None:
            w_v = a.get(V.ETF, 0.0)
            assert set(a) <= {V.ETF, K.CASH} and sum(a.values()) == pytest.approx(1.0)
        if b is not None:
            w_i3 = b.get(K.BASE, 0.0)
        if out_day is None and w_v == 0.0:
            out_day = d
    assert out_day == ds[250] and w_v == 0.0 and w_i3 == pytest.approx(1.0)


def test_cash_parameter_is_only_for_the_report():
    ds, data = synth()
    codes, t, _ = V.build(data, ds, cash=V.REPORT_CASH)
    assert codes == (V.ETF, V.REPORT_CASH)
    assert V.build(data, ds)[0][1] == K.CASH == "488770"                  # 리그는 리그 현금 자리


def test_replay_tracks_weights_and_counts_divergence():
    ds, data = synth()
    cash = {d: {"open": 100.0, "close": 100.0} for d in ds}
    r = V.replay(data[K.BASE], data[V.ETF], data[V.KOSPI], cash, start=ds[0], equity=1_000_000.0)
    assert set(r["res"]) == {"I3", V.NAME, "KODEX200 보유", "가치저변동 보유"}
    assert r["dates"] == (ds[0], ds[-1], len(ds))
    last = max(r["w_v"])                                  # simulate 는 마지막 날엔 target 을 부르지 않는다(다음 날 시가 체결)
    assert last == ds[-2] and r["w_v"][last] == 0.0 and r["w_i3"][last] == pytest.approx(1.0)
    assert r["diverge"] == sum(1 for d in ds[:-1] if abs(r["w_v"][d] - r["w_i3"][d]) >= V.DIVERGE_PP) > 0


def test_registration_fits_league_rules():
    """등록(11-20) 전이든 뒤든 — 정원·월 신규 상한 안, 등록 뒤엔 선언과 같은 등록일·자산."""
    names = {m.name for m in S.MEMBERS}
    pending = 0 if V.NAME in names else 1
    assert len(S.MEMBERS) + pending <= S.CAPACITY
    nov = sum(1 for m in S.MEMBERS if m.registered[:7] == "2026-11" and m.name not in S.INTAKE_EXCEPTIONS)
    assert nov + pending <= S.MAX_NEW_PER_MONTH
    if V.NAME in names:
        m = next(x for x in S.MEMBERS if x.name == V.NAME)
        assert m.registered == V.REGISTER_ON and {V.ETF, K.CASH, V.KOSPI} <= set(m.codes)


def test_ledger_row_registered_before_report():
    row = [r for r in T.TRIALS if r[3] == V.SOURCE]
    assert len(row) == 1 and row[0][2] == 1
    assert T.total_through(V.SOURCE) == 99 and T.total_through("scripts/lab_jkp.py") == 98


_CACHE = ROOT / "docs_cache" / "lab"
_FIXED = ("223190_2026-10-21.json", "069500_2026-08-24.json", "IDX_KS11_2026-08-24.json", "488770_2026-10-21.json")


@pytest.mark.skipif(not all((_CACHE / n).exists() for n in _FIXED), reason="고정 기준일 캐시 없음")
def test_real_etf_history_covers_league_replay():
    """실제 223190 이력이 리그 재생 시작(2015-07-28) 전부터 있고, 리그 실행기(현금 488770)로 돌려도 비중이 0~1 안이다
    (성과는 보지 않는다). 고정 기준일 캐시만 쓴다 — 날짜별 캐시는 리그가 매일 받으며 prune_live_cache 가 지운다(11-19 발견)."""
    import strategy_lab as L
    v = L.load_bars(V.ETF, "2015-06-26", "2026-10-21")
    assert min(v) <= "2015-06-30" < K.REPLAY_START
    k = L.load_bars(K.BASE, "2014-01-01", "2026-08-24")
    ks = L.load_bars(V.KOSPI, "1996-01-01", "2026-08-24")
    c = L.load_bars(K.CASH, "2014-01-01", "2026-10-21")
    missing = [d for d in k if d >= K.REPLAY_START and d not in v]
    assert len(missing) <= 5, missing[:10]
    data = {K.BASE: k, V.ETF: v, V.KOSPI: ks, K.CASH: c}
    r = S.std_run(V.build)(data, "2024-09-02", 3_640_000.0, "2026-08-24")
    assert r["curve"][0] == ("2024-09-02", 3_640_000) and all(0 <= w <= 1 + 1e-9 for w in r["w_hist"].values())
