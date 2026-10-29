"""공격형 리그(aggr_shadow)·공포 매수(lab_fear) — 선언한 규칙이 적힌 대로 도는지. 합성 자료만 쓴다."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aggr_shadow as S  # noqa: E402
import lab_downside as D  # noqa: E402
import lab_fear as F  # noqa: E402


def _days(start: str, n: int) -> list[str]:
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range(n)]


def _px(vix: list[float], opens: list[float], kospi_moves: float = 0.0) -> dict:
    """ANCHOR 부터 len(opens) 일. KOSPI 는 그 전 30일 + 같은 기간(±kospi_moves 번갈아)."""
    days = _days(F.ANCHOR, len(opens))
    kd = _days("2026-09-20", 38 + len(opens))
    k, ks = 1000.0, {}
    for j, d in enumerate(kd):
        k *= 1 + (kospi_moves if j % 2 else -kospi_moves)
        ks[d] = {"open": k, "close": k}
    bars = {d: {"open": o, "close": o} for d, o in zip(days, opens)}
    flat = {d: {"open": 100.0, "close": 100.0} for d in days}
    return {F.BASE: bars, F.LONGS["2"]: bars, F.CASH: flat, "^KS11": ks,
            "^VIX": {d: {"open": v, "close": v} for d, v in zip(days, vix)}}


def test_declared_constants_reuse_downside_defaults():
    """새 숫자를 고르지 않는다 — lab_downside 선언 기본값(V1 30 · K2 25)을 그대로 쓴다."""
    assert F.SIGNALS["V"][0] == "V1" and D.CANDIDATES["V1"][2] == 30
    assert F.SIGNALS["K"][0] == "K2" and D.CANDIDATES["K2"][2] == 25
    assert F.MEMBERS == ("FEAR-V1", "FEAR-V2", "FEAR-K1", "FEAR-K2")
    assert F.LONGS == {"1": "069500", "2": "122630"} and F.CASH == "488770"
    assert (F.ANCHOR, F.F_EQUITY, F.F_JUDGE_DAYS, F.F_MIN_HELD, F.F_MAX_MDD_PCT) == \
        ("2026-10-28", 500_000.0, 60, 20, 30.0)
    assert S.MEMBERS == ("ORB-B1", "ORB-B2") + F.MEMBERS + ("HH1",) and S.STOP_PCT == 30.0


def test_fear_buys_next_open_and_exits_when_fear_ends():
    """공포인 날 종가 판단 → 다음 날 시가 매수 · 공포가 끝난 날 종가 판단 → 다음 날 시가 매도."""
    px = _px(vix=[35, 20, 20, 20], opens=[100, 100, 110, 120])
    r = F.run(px, "V", "1", "2026-10-31")
    assert r["held"] == ["2026-10-29"] and r["entries"] == 1 and r["on_today"] is False
    nav = r["curve"][-1][1]
    assert 500_000 * 1.09 < nav < 500_000 * 1.10           # 100 → 110 한 번, 비용 차감 · 110 → 120 은 못 먹음


def test_no_fear_stays_in_cash():
    px = _px(vix=[15, 15, 15], opens=[100, 120, 140])
    r = F.run(px, "V", "2", "2026-10-30")
    assert r["held"] == [] and r["entries"] == 0 and abs(r["curve"][-1][1] - 500_000) < 2_000


def test_korean_volatility_signal():
    calm, wild = _px([15] * 3, [100] * 3, 0.001), _px([15] * 3, [100] * 3, 0.03)
    assert F.run(calm, "K", "1", "2026-10-30")["on_today"] is False
    assert F.run(wild, "K", "1", "2026-10-30")["on_today"] is True      # 하루 ±3% → 연율 ~48%


def test_fear_verdict_waits_for_days_and_held():
    days = _days(F.ANCHOR, 70)
    base = {d: {"open": 100.0 + k, "close": 100.0 + k} for k, d in enumerate(days)}
    curve = [(d, 500_000 + k * 1000) for k, d in enumerate(days)]
    assert F.verdict(curve[:30], days[1:25], base, days)["judged"] is False         # 기록 부족
    assert F.verdict(curve, days[1:10], base, days)["judged"] is False              # 보유일 부족
    v = F.verdict(curve, days[1:30], base, days)
    assert v["judged"] and v["checks"]["누적>0"] and v["checks"]["MDD≤30%"]
    # 가격이 일정하게 오르면 보유일 수익률(앞쪽, 더 큼) > 전체 평균 → 실력 O
    assert v["checks"]["공포일 실력"] is True


def test_orb_run_marks_missing_minute_days():
    rows = [("2026-10-29", {"side": "long", "ret": 0.01, "size": 1.0, "how": "종가"}),
            ("2026-11-02", {"side": None, "ret": 0.0, "why": "첫 5분 시가=종가(쉼)"})]
    fake = lambda v, s, e: [x for x in rows if s <= x[0] <= e]            # noqa: E731
    dates = ["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"]
    r = S.orb_run("B1", dates, "2026-11-02", 500_000, fake)
    assert r["missing"] == ["2026-10-30"] and r["days"] == 2
    assert r["curve"][0] == (F.ANCHOR, 500_000) and abs(r["curve"][-1][1] - 505_000) < 1e-6
    assert S.orb_verdict(r["curve"])["judged"] is False


def test_stop_alert_only_once():
    models = {"FEAR-K2": {"mdd": 31.0, "ret": -20.0}, "ORB-B1": {"mdd": 5.0, "ret": 1.0}}
    stopped, msgs = S.stop_alerts(models, {}, "2026-11-20")
    assert stopped == {"FEAR-K2": "2026-11-20"} and len(msgs) == 1
    _, again = S.stop_alerts(models, stopped, "2026-11-21")
    assert again == []


def test_summary_before_start_shows_tomorrow_plan():
    rec = {"asof": "2026-10-28", "gauges": {"vix": 17.5, "kospi_vol": 48.0},
           "models": {"FEAR-K1": {"ret": 0.0, "on_today": True}, "FEAR-V1": {"ret": 0.0, "on_today": False}}}
    line = S.summary_line(rec)
    assert "기록 준비" in line and "FEAR-K1 매수" in line and "FEAR-V1" not in line.split("내일 시가:")[1]


def test_hh1_is_an_operator_exception_member():
    assert "HH1" in S.MEMBERS and S.HH_START == "2026-10-29"
    assert "운용자 예외" in S.EXCEPTIONS["HH1"] and set(S.EXCEPTIONS) == {"HH1"}      # 예외는 운용자 결정 건만


def test_hh1_starts_fresh_on_start_day_and_holds_both_halves():
    """엔진·예산은 과거부터 재생하고 start 일에 50만원으로 새로 출발 — 다음 날 시가에 한국 2배 90%·나스닥 100% 체결."""
    days = _days("2026-08-01", 100)
    rise = {d: {"open": 100.0 + k, "close": 100.0 + k} for k, d in enumerate(days)}
    flat = {d: {"open": 100.0, "close": 100.0} for d in days}
    px = {F.BASE: rise, F.LONGS["2"]: rise, S.NDQ: rise, F.CASH: flat, "^KS11": rise}
    start, upto = "2026-10-29", days[-1]
    r = S.hh1_run(px, upto, 500_000, start)
    assert r["curve"][0] == (start, 500_000) and r["curve"][-1][1] > 500_000
    assert abs(r["w_kr"] - 0.9) < 1e-9 and r["w_us"] == 1.0                     # 한국 3 × 30% · 나스닥 min(1, 6 × 18%)
    assert S.hh1_run(px, "2026-10-28", 500_000, start)["curve"] == []            # 시작 전엔 기록 없음


def test_decide_task_runs_aggr_league_after_minutes_and_keeps_decide_exit_code():
    """ORB 는 그날 분봉이 있어야 한다 → 분봉 수집 뒤. 공격형 리그 실패가 판단 실패로 보이면 안 된다."""
    txt = (_ROOT / "scripts" / "i3_decide.cmd").read_text(encoding="utf-8")
    i_rc, i_min, i_aggr = txt.index("set RC=%ERRORLEVEL%"), txt.index("collect_i3_minutes.py"), txt.index("aggr_shadow.py")
    assert i_rc < i_min < i_aggr and txt.rstrip().endswith("exit /b %RC%")


def test_history_rewrites_same_date(tmp_path):
    p = tmp_path / "h.csv"
    S.append_history({"date": "2026-10-29", "orb-b1_nav": 1}, p)
    S.append_history({"date": "2026-10-29", "orb-b1_nav": 2}, p)
    S.append_history({"date": "2026-10-30", "orb-b1_nav": 3}, p)
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3 and lines[1].startswith("2026-10-29,2")
