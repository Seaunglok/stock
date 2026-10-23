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


def _curve_from(start_idx, vals):
    return [(f"2027-{1 + (start_idx + i) // 28:02d}-{1 + (start_idx + i) % 28:02d}", v) for i, v in enumerate(vals)]


def _res(vals, w=None):
    c = _curve_from(0, vals)
    return {"curve": c, "w_hist": {d: (w if w is not None else 1.0) for d, _ in c}}


def _m(name, reg="2027-01-01"):
    return S.Member(name, "시험", reg, "시험", "", (), lambda *a: {})


def test_relegation_rules_as_declared():
    """★ 일부러 깨뜨리기 — 위험(MDD>25%)은 언제든, 부진(−10%p)은 월간 점검 + 60일 뒤에만."""
    champ = _res([100 + i * 0.01 for i in range(80)])
    crash = _res([100.0] * 10 + [70.0] * 70)                      # MDD 30%
    assert "위험" in S.relegation(champ, crash, "2027-01-01", review=False)
    lag = _res([100 - i * 0.2 for i in range(80)])                # 약 −16%, MDD 16% (위험 아님)
    assert S.relegation(champ, lag, "2027-01-01", review=False) is None           # 월간 점검 아님
    assert "부진" in S.relegation(champ, lag, "2027-01-01", review=True)
    short = _res([100 - i * 0.2 for i in range(40)])
    assert S.relegation(champ, short, "2027-01-01", review=True) is None          # 60일 전
    ok = _res([100 + i * 0.02 for i in range(80)])
    assert S.relegation(champ, ok, "2027-01-01", review=True) is None


def test_duplicates_are_only_suspected_never_retired():
    """중복은 알림만 — 재진입 때만 다른 R1·R6 가 차이가 드러나기 전에 잘리면 안 된다."""
    same = [100 + (i % 3) for i in range(80)]
    res = {"I3": _res(same), "R6": _res(same), "B": _res([100 + (i % 5) * 0.7 for i in range(80)])}
    members = (_m("I3"), _m("R6"), _m("B"))
    st, msgs = S.govern({}, res, members, "2027-03-25", [])
    assert "R6" not in st["retired"] and any("중복 의심" in t and "R6" in t for t, _ in msgs)
    assert st["reviews"]["2027-03"]["duplicate_suspects"][0][:2] == ["R6", "I3"]


def test_promotion_needs_two_consecutive_monthly_reviews():
    n = S.PROMO_MIN_DAYS + 5
    champ = {"curve": _curve_from(0, [100 + i * 0.01 for i in range(n)]), "w_hist": {}}
    champ["w_hist"] = {d: 0.5 for d, _ in champ["curve"]}
    good = {"curve": _curve_from(0, [100 + i * 0.05 for i in range(n)]), "w_hist": {d: 1.0 for d, _ in champ["curve"]}}
    members = (_m("I3"), _m("X"))
    st, msgs = S.govern({}, {"I3": champ, "X": good}, members, "2027-06-01", [])
    assert st["promo_streak"]["X"] == 1 and not any("승격 후보" in t for t, _ in msgs)
    st, msgs = S.govern(st, {"I3": champ, "X": good}, members, "2027-06-15", [])          # 같은 달 — 점검 아님
    assert st["promo_streak"]["X"] == 1
    st, msgs = S.govern(st, {"I3": champ, "X": good}, members, "2027-07-01", [])
    assert any("승격 후보" in t and c for t, c in msgs)                                   # critical


def test_down_runs_retire_and_champion_alert():
    members = (_m("I3"), _m("X"))
    st = {}
    for i in range(S.DOWN_RUNS):
        st, msgs = S.govern(st, {"I3": _res([100, 101]), "X": {"error": "데이터 없음"}}, members,
                            f"2027-01-{10 + i:02d}", [])
    assert "운용 불가" in st["retired"]["X"]["reason"]
    navs = [["2027-01-02", 100.0], ["2027-02-02", 120.0], ["2027-03-02", 95.0]]           # 낙폭 20.8%
    _, msgs = S.govern({}, {"I3": _res([100, 101])}, (members[0],), "2027-03-02", navs)
    assert any("챔피언 긴급 점검" in t and c for t, c in msgs)


def test_registry_respects_capacity_and_monthly_intake():
    """정원·월 신규 상한. 상한 밖 멤버는 INTAKE_EXCEPTIONS 에 운용자 예외로 적힌 것만(조용히 넘치지 않게)."""
    from collections import Counter
    assert len(S.MEMBERS) <= S.CAPACITY
    names = {m.name for m in S.MEMBERS}
    assert set(S.INTAKE_EXCEPTIONS) <= names and all("운용자 예외" in v for v in S.INTAKE_EXCEPTIONS.values())
    by_month = Counter(m.registered[:7] for m in S.MEMBERS
                       if m.registered != S.FOUNDING_DATE and m.name not in S.INTAKE_EXCEPTIONS)
    assert all(n <= S.MAX_NEW_PER_MONTH for n in by_month.values()), by_month


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
    members = tuple(m for m in S.MEMBERS if m.name not in ("추세추종", "저베타", "퀄리티"))   # 종목형은 별도 시험
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


def test_d5a_member_is_the_declared_design_and_marked_as_exception(league_data):
    """D5a 는 lab_gen5 선언(c9f5dfd)의 결합 그대로 — KODEX200 비중은 **매일 챔피언 I3 와 같고**(같은 계좌 자산 경로를 주면),
    남는 돈만 방어 자산·현금 자리로 간다. 연구 현금(153130)이 리그로 새면 안 되고, 입장이 규칙 밖 결정임이 기록돼 있어야 한다."""
    import lab_gen5 as G5
    d5a = next(m for m in S.MEMBERS if m.name == "D5a")
    assert S._DEF3 == G5.DEF3 and "예외" in d5a.admitted and "규칙 밖" in d5a.admitted
    dates = S._calendar(league_data, UPTO)
    _, i3, _ = S._b_i3("I3")(league_data, dates)
    codes, t, needs_nav = S._b_d5a(league_data, dates)
    assert needs_nav and set(codes) == {K.BASE, K.CASH, *G5.DEF3}
    k = league_data[K.BASE]
    w_i3, checked, held_def, partial = None, 0, 0, 0
    for i, d in enumerate(dates):
        nav = 3_640_000.0 * k[d]["close"] / k[dates[0]]["close"]      # 둘 다 같은 경로 — 낙폭 예산이 실제로 깎이는 구간 포함
        a, b = i3(i, d, nav), t(i, d, nav)
        if a is not None:
            w_i3 = a.get(K.BASE, 0.0)
        if b is None:
            continue
        assert b.get(K.BASE, 0.0) == pytest.approx(w_i3), d
        assert set(b) <= set(codes) and "153130" not in b, d
        assert sum(b.values()) == pytest.approx(1.0) and all(w >= -1e-12 for w in b.values()), d
        checked += 1
        held_def += any(b.get(x, 0) > 0 for x in G5.DEF3)
        partial += 0 < w_i3 < 1
    assert checked > 50 and held_def > 0 and partial > 0, (checked, held_def, partial)


def test_t6c_member_is_the_declared_gen6_design(league_data):
    """T6c 는 lab_gen6 선언(1406001)의 설계 그대로 — 같은 i3x 에 선언한 배수만 얹는다. 등록일은 선언(11-02)이 아니라
    운용자 예외로 10-26 — 그 사실이 INTAKE_EXCEPTIONS 와 admitted 에 남아 있어야 한다.
    배수만 다르므로 엔진이 빠져 있는 날(비중 0)은 챔피언과 같아야 한다."""
    import lab_gen6 as G6
    t6c = next(m for m in S.MEMBERS if m.name == "T6c")
    assert G6.REGISTER_ON == "2026-11-02" and t6c.registered == "2026-10-26"
    assert "T6c" in S.INTAKE_EXCEPTIONS and "운용자 예외" in t6c.admitted
    assert G6.SPECS6["T6c"] == {"reset": "none", "m_up": 8, "m_down": 4, "m_trend_ma": 250, "m_trend_lag": 20}
    res = S.run_league(league_data, START, 3_640_000.0, UPTO, (S.MEMBERS[0], t6c))
    i3, x = res["I3"]["w_hist"], res["T6c"]["w_hist"]
    assert set(i3) == set(x) and all((i3[d] == 0) == (x[d] == 0) for d in i3)
    assert any(abs(i3[d] - x[d]) > 0.05 for d in i3)              # 그리고 실제로 다르게 행동한 날이 있다


def test_factor_members_start_from_the_same_line(league_data, monkeypatch):
    """종목형 팩터 멤버(저베타·퀄리티) — 대형주 데이터는 합성으로 바꿔 끼워 배선만 시험: 같은 출발선, 월말에만 매매,
    주식 비중 0~100%, 매도세 있는 자산으로 취급."""
    import backtest_trend_portfolio as P
    days = sorted(d for d in league_data["069500"] if "2023-01-01" <= d <= UPTO)
    synth = {f"S{i:02d}": {d: {"open": 1000 + i + k * (0.1 + i / 100), "close": 1000 + i + k * (0.1 + i / 100)}
                           for k, d in enumerate(days)} for i in range(25)}
    monkeypatch.setattr(P, "_load", lambda *a, **k: (days, synth, {}, {}))
    import lab_factors as F
    monkeypatch.setattr(F, "load_fund", lambda: {c: {"2022": {"avail": "2023-03-01", "equity": 100 + i,
                                                              "net_income": 10 + i, "assets": 300, "op_income": 12 + i,
                                                              "liabilities": 100 - i}} for i, c in enumerate(synth)})
    eq = 3_640_000.0
    res = S.run_league(league_data, START, eq, UPTO, tuple(m for m in S.MEMBERS if m.name in ("저베타", "퀄리티")))
    for name in ("저베타", "퀄리티"):
        r = res[name]
        assert "error" not in r, r.get("error")
        assert r["curve"][0] == (START, round(eq)) and all(0 <= w <= 1 + 1e-9 for w in r["w_hist"].values())
        assert r["trade_days"] and all(d == START or d in S.month_ends_live(sorted(league_data["069500"]))
                                       for d in r["trade_days"])


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
