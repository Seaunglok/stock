"""I3 도전자 리그(i3_shadow) — 챔피언 모델이 실전 판단과 같은지, 승격 규칙이 적힌 대로 판정하는지."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import i3_shadow as S  # noqa: E402

START, UPTO = "2024-09-02", "2026-08-24"     # 머니마켓(488770) 상장 뒤 — 실전 현금 자리 그대로


@pytest.fixture(scope="module")
def real():
    import strategy_lab as L
    cache = _ROOT / "docs_cache" / "lab"
    need = ("069500_2026-08-24.json", "IDX_KS11_2026-08-24.json", "488770_2026-10-21.json")
    if not all((cache / n).exists() for n in need):
        pytest.skip("검증 캐시 없음")
    k = L.load_bars("069500", "2014-01-01", "2026-08-24")
    ks = L.load_bars("^KS11", "1996-01-01", "2026-08-24")
    c = L.load_bars("488770", "2014-01-01", "2026-10-21")
    return k, ks, c, S.run_models(k, ks, c, START, 3_640_000.0, UPTO)


def test_champion_model_matches_live_decisions(real):
    """★ 챔피언 모델의 매매일·목표 비중 == 실전 판단 코드(i3_core) — 같은 자산 이력이면 같아야 한다.
    어긋나면 '모델 vs 실계좌'·'도전자 vs 챔피언' 비교가 전부 무의미해진다."""
    k, ks, _, res = real
    ch = res[S.CHAMPION]
    navs, prev, checked = [], None, 0
    for d, nav in ch["nav_hist"].items():
        if d >= UPTO:
            break
        navs.append(nav)
        eng = K.engine_state(k, ks, d)
        w, need, _ = K.decide(eng, navs, prev)
        assert need == (d in ch["trade_days"]), f"{d} 매매 여부 불일치"
        if need:
            assert w == pytest.approx(ch["w_hist"][d], abs=1e-6), f"{d} 비중 불일치"
            prev = w
        checked += 1
    assert checked > 400 and len(ch["trade_days"]) >= 10


def test_challenger_equals_champion_until_first_reentry(real):
    """R1 은 '손실 뒤 재진입'에서만 달라진다 — 그 전까지는 챔피언과 비중이 같아야 한다(다르면 구현 결함)."""
    k, ks, _, res = real
    flips = []
    prev_hold = None
    for d in sorted(res[S.CHAMPION]["w_hist"]):
        hold = K.engine_state(k, ks, d).holding
        if prev_hold is False and hold:
            flips.append(d)
        prev_hold = hold
    assert flips, "이 구간에 재진입이 없다 — 시험 구간을 바꿀 것"
    first = flips[0]
    for d, w in res[S.CHAMPION]["w_hist"].items():
        if d < first:
            assert res["R1"]["w_hist"][d] == pytest.approx(w)
    assert any(abs(res["R1"]["w_hist"][d] - res[S.CHAMPION]["w_hist"][d]) >= S.DIVERGE_PP
               for d in res[S.CHAMPION]["w_hist"] if d >= first)


def _curve(days, vals):
    return [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", v) for i, v in zip(range(days), vals)]


def _model(vals, ws):
    curve = _curve(len(vals), vals)
    return {"curve": curve, "w_hist": {d: w for (d, _), w in zip(curve, ws)}}


def test_promotion_rule_as_declared():
    """★ 일부러 깨뜨리기 — 조건 하나씩 빼면 승격되지 않는다."""
    n = S.PROMO_MIN_DAYS + 5
    champ = _model([100 + i * 0.01 for i in range(n)], [0.5] * n)
    good = _model([100 + i * 0.05 for i in range(n)], [1.0] * n)
    assert S.promotion(champ, good, "2026-01-01")["ok"]
    short = _model([100 + i * 0.05 for i in range(30)], [1.0] * 30)
    assert not S.promotion(champ, short, "2026-01-01")["ok"]                          # 기록 부족
    same = _model([100 + i * 0.05 for i in range(n)], [0.5] * n)
    assert not S.promotion(champ, same, "2026-01-01")["ok"]                           # 다르게 행동한 날 부족
    small = _model([100 + i * 0.0105 for i in range(n)], [1.0] * n)
    assert not S.promotion(champ, small, "2026-01-01")["ok"]                          # 수익 차 부족
    crash = _model([100 + i * 0.05 if i < n - 10 else 75 + i * 0.05 for i in range(n)], [1.0] * n)
    assert not S.promotion(champ, crash, "2026-01-01")["ok"]                          # MDD 초과


def test_history_is_one_row_per_day(tmp_path):
    p = tmp_path / "h.csv"
    S.append_history({"date": "2026-10-22", "i3_nav": 1}, p)
    S.append_history({"date": "2026-10-22", "i3_nav": 2}, p)
    S.append_history({"date": "2026-10-21", "i3_nav": 3}, p)
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert [r["date"] for r in rows] == ["2026-10-21", "2026-10-22"] and rows[1]["i3_nav"] == "2"


@pytest.fixture(scope="module")
def league_data():
    import strategy_lab as L
    cache = _ROOT / "docs_cache" / "lab"
    codes = {"069500": "2026-08-24", "133690": "2026-08-24", "114260": "2026-08-24", "148070": "2026-08-24",
             "132030": "2026-08-24", "138230": "2026-08-24", "488770": "2026-10-21"}
    if not all((cache / f"{c}_{e}.json").exists() for c, e in codes.items()) or \
            not (cache / "IDX_KS11_2026-08-24.json").exists():
        pytest.skip("검증 캐시 없음")
    data = {c: L.load_bars(c, "2010-01-01", e) for c, e in codes.items()}
    data[S.KOSPI] = L.load_bars("^KS11", "1996-01-01", "2026-08-24")
    if not (cache / "ohlc_069500_2026-10-21.json").exists():
        pytest.skip("OHLC 캐시 없음")
    import lab_classics as C
    data["ohlc:069500"] = C.load_ohlc("069500", "2010-01-01", "2026-10-21")
    return data


def test_audit_catches_source_mismatch():
    """★ 일부러 깨뜨리기 — 키움 원자료가 장기 이력과 1% 어긋나면 잡아낸다(한도 0.5%)."""
    hist = {f"2026-10-{d:02d}": {"open": 100.0, "close": 100.0} for d in range(1, 21)}
    same = {k: dict(v) for k, v in hist.items()}
    off = {k: {"open": 101.0, "close": 101.0} for k in hist}
    assert S.audit_sources(hist, same, "2026-10-30") == 0.0
    gap = S.audit_sources(hist, off, "2026-10-30")
    assert gap == pytest.approx(0.01) and gap > S.AUDIT_TOL
    assert S.audit_sources(hist, {k: hist[k] for k in list(hist)[:3]}, "2026-10-30") is None


def test_every_member_starts_from_the_same_line(league_data):
    """★ 공정한 경쟁 — 모든 멤버가 실전 시작일에 같은 자산으로 출발하고, 비중은 0~100% 안이다(실데이터)."""
    eq = 3_640_000.0
    members = tuple(m for m in S.MEMBERS if m.name != "추세추종")     # 종목형은 전 종목 로드라 별도
    res = S.run_league(league_data, START, eq, UPTO, members)
    for m in members:
        r = res[m.name]
        assert "error" not in r, f"{m.name}: {r.get('error')}"
        assert r["curve"][0] == (START, round(eq)), f"{m.name} 출발선이 다르다"
        assert all(v > 0 for _, v in r["curve"]) and len(r["curve"]) > 400
        assert all(-1e-9 <= w <= 1 + 1e-9 for w in r["w_hist"].values()), f"{m.name} 비중 범위"
    assert res["I3"]["curve"] == S.run_models(league_data["069500"], league_data[S.KOSPI], league_data["488770"],
                                              START, eq, UPTO)["I3"]["curve"]


def test_r6_member_is_the_declared_design_and_marked_as_exception(league_data):
    """R6 는 lab_challengers 선언(a580dbe)의 설계 그대로이고, 입장이 규칙 밖 결정임이 기록돼 있어야 한다."""
    import lab_challengers as CH
    r6 = next(m for m in S.MEMBERS if m.name == "R6")
    assert CH.SPECS["R6"] == {"reset": "once", "reset_trend_ma": 250, "reset_trend_lag": 20}
    assert "예외" in r6.admitted and "규칙 밖" in r6.admitted
    res = S.run_league(league_data, START, 3_640_000.0, UPTO, (S.MEMBERS[0], r6))
    i3, x = res["I3"]["w_hist"], res["R6"]["w_hist"]
    assert x[START] == pytest.approx(i3[START])            # 출발일 판단은 같다(리셋은 재진입 때만)


def test_one_failing_member_does_not_stop_the_league(league_data):
    def boom(*a):
        raise RuntimeError("데이터 없음")
    bad = S.Member("고장", "시험", "2026-10-22", "시험", "", ("069500",), boom)
    res = S.run_league(league_data, START, 3_640_000.0, UPTO, (bad, S.MEMBERS[0]))
    assert "error" in res["고장"] and "curve" in res["I3"]


def test_cash_fill_and_remap():
    t = S.cash_fill(lambda i, d: {"069500": 0.6})
    assert t(0, "d") == {"069500": 0.6, S.K.CASH: pytest.approx(0.4)}
    assert S.cash_fill(lambda i, d: None)(0, "d") is None
    r = S.remap(lambda i, d: {"153130": 0.3, "069500": 0.7}, {"153130": S.K.CASH})
    assert r(0, "d") == {S.K.CASH: 0.3, "069500": 0.7}


def test_summary_line_ranks_members():
    rec = {"asof": "2026-10-23", "start": "2026-10-22", "live": {"ret": 0.1},
           "models": {"I3": {"ret": 0.1}, "R1": {"ret": 0.5}, "고장": {"error": "x"}}}
    line = S.summary_line(rec)
    assert line.index("R1") < line.index("👑I3") and "오류 고장" in line


def test_decide_task_runs_league_after_decide_and_keeps_its_exit_code():
    """리그는 판단 뒤에 돌고, 작업 결과 코드는 판단의 것이어야 한다(리그 실패가 판단 실패로 보이면 안 된다)."""
    txt = (_ROOT / "scripts" / "i3_decide.cmd").read_text(encoding="utf-8")
    i_decide, i_rc, i_shadow = txt.index("--phase decide"), txt.index("set RC=%ERRORLEVEL%"), txt.index("i3_shadow.py")
    assert i_decide < i_rc < i_shadow and txt.rstrip().endswith("exit /b %RC%")
