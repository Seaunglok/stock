"""리그 판정 통계 기준(league_stats, 백로그 ㉔ — 11-23 선언, 2027-01 점검부터) — 식·시행일·두 리그 연결."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aggr_shadow as A  # noqa: E402
import i3_shadow as SH  # noqa: E402
import league_stats as S  # noqa: E402


# ── 식 ──────────────────────────────────────────────────────────────────────
def test_declared_constants_and_hurdles():
    assert (S.STAT_FROM, S.ALPHA, S.MIN_OBS) == ("2027-01", 0.05, 20)
    assert S.hurdle_z(1) == pytest.approx(1.645, abs=1e-3)
    assert S.hurdle_z(10) == pytest.approx(2.576, abs=1e-3)       # 공격형 10명
    assert S.hurdle_z(29) == pytest.approx(2.92, abs=0.01)         # I3 리그 도전자 29명
    with pytest.raises(ValueError):
        S.hurdle_z(0)


def test_docstring_cost_numbers():
    """선언문의 '알고 정한 대가' — 정규 가정에서 통과에 필요한 연 샤프(N 29·120일 ≈ 4.2 · N 10·60일 ≈ 5.3)."""
    need = lambda n, t: S.hurdle_z(n) / math.sqrt(t - 1) * math.sqrt(252)   # noqa: E731
    assert need(29, 120) == pytest.approx(4.25, abs=0.05)
    assert need(10, 60) == pytest.approx(5.32, abs=0.05)


def test_in_force_from_january_review():
    assert not S.in_force("2026-12-01") and S.in_force("2027-01-04") and S.in_force("2027-01")


def test_edge_stat_cases():
    short = S.edge_stat([0.01] * 10, 1)
    assert short["z"] is None and not short["pass"] and "관측" in short["why"]
    flat = S.edge_stat([0.0] * 50, 1)
    assert flat["z"] == 0.0 and not flat["pass"] and "차이 없음" in flat["why"]
    noise = [0.01 * math.sin(i * 1.7) for i in range(200)]                 # 평균 ≈ 0
    r = S.edge_stat(noise, 29)
    assert not r["pass"] and abs(r["z"]) < 1.5
    strong = [0.004 + 0.002 * math.sin(i * 1.7) for i in range(120)]       # 날마다 거의 같은 방향
    r = S.edge_stat(strong, 29)
    assert r["pass"] and r["z"] > r["hurdle"] and r["more_days"] == 0


def test_one_lucky_day_is_not_skill():
    """★ 챔피언이 한 번 크게 빠진 날만 피한 도전자 — 누적은 +5%p 앞서도 통계로는 우연(이 규칙이 막으려는 것).
    PSR 그대로면 양의 왜도 덕에 z 1.97(단일 시험 통과) — 보정은 불리할 때만 쓰므로 정규 z ≈ 1.0 으로 미달."""
    import lab_i3_overfit as O
    d = [0.0] * 130
    d[50] = 0.05
    sr, g3, g4 = O.moments(d)
    assert O.psr_z(sr, len(d), g3, g4) > S.hurdle_z(1)                    # 옛 식(보정 그대로)은 통과시켰다
    for n in (1, 29):
        r = S.edge_stat(d, n)
        assert not r["pass"] and r["z"] < 1.2, n


def test_daily_rets_and_paired_alignment():
    a = [("2027-01-01", 100.0), ("2027-01-02", 101.0), ("2027-01-03", 100.0), ("2027-01-06", 102.0)]
    b = [("2027-01-02", 50.0), ("2027-01-03", 51.0), ("2027-01-06", 51.0)]
    ra, rb = S.daily_rets(a, "2027-01-02"), S.daily_rets(b)
    assert set(ra) == {"2027-01-03", "2027-01-06"}                       # since 다음 점부터
    assert S.paired(ra, rb) == pytest.approx([(100 / 101 - 1) - 0.02, (102 / 100 - 1) - 0.0])


# ── I3 리그 연결 ─────────────────────────────────────────────────────────────
def _dates(n):
    return [f"2027-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def _model(rets, w):
    v, curve = 100.0, []
    for d, r in zip(_dates(len(rets)), rets):
        v *= 1 + r
        curve.append((d, v))
    return {"curve": curve, "w_hist": {d: w for d, _ in curve}}


def _lucky_pair(n=SH.PROMO_MIN_DAYS + 10):
    base = [0.01 if i % 2 else -0.009 for i in range(n)]
    champ = list(base)
    champ[60] = -0.05                                                      # 챔피언만 크게 빠진 하루
    return _model(champ, 0.5), _model(base, 1.0)


def test_promotion_ok_unchanged_and_stat_attached():
    """옛 길 == 새 길 — 기존 다섯 조건(ok)은 n_tests 를 줘도 같다. stat 만 붙는다."""
    champ, chal = _lucky_pair()
    old = SH.promotion(champ, chal, "2027-01-01")
    new = SH.promotion(champ, chal, "2027-01-01", 29)
    assert "stat" not in old and {k: v for k, v in new.items() if k != "stat"} == old
    assert old["ok"] is True and new["stat"]["pass"] is False             # 기존 조건은 통과, 통계는 미달


def test_govern_holds_promotion_only_from_january():
    """★ 일부러 깨뜨리기 — 같은 기록이 12월 점검에선 연속 1회(옛 규칙), 1월 점검부터는 '보류(통계)'로 0회."""
    champ, chal = _lucky_pair()
    members = (SH.Member("I3", "시험", "2027-01-01", "시험", "", (), lambda *a: {}),
               SH.Member("X", "시험", "2027-01-01", "시험", "", (), lambda *a: {}))
    res = {"I3": champ, "X": chal}
    st, msgs = SH.govern({}, res, members, "2026-12-01", [])
    assert st["promo_streak"]["X"] == 1 and st["reviews"]["2026-12"]["stat_held"] == []
    st, msgs = SH.govern({}, res, members, "2027-06-01", [])
    assert st["promo_streak"]["X"] == 0 and st["reviews"]["2027-06"]["stat_held"] == ["X"]
    assert any("보류" in t and "통계" in t and not c for t, c in msgs)
    assert not any("승격 후보" in t for t, _ in msgs)


def test_n_challengers_excludes_champion_retired_and_broken():
    members = tuple(SH.Member(n, "시험", "2027-01-01", "시험", "", (), lambda *a: {}) for n in ("I3", "A", "B", "C"))
    res = {"I3": {"curve": []}, "A": {"curve": []}, "B": {"error": "x"}, "C": {"curve": []}}
    assert SH.n_challengers(members, {"C": {}}, res) == 1
    assert SH.n_challengers(members[:1], {}, res) == 1                     # 최소 1


# ── 공격형 리그 연결 ─────────────────────────────────────────────────────────
def test_excess_rets_uses_same_two_days_and_skips_missing_cash():
    curve = [("d0", 100.0), ("d1", 102.0), ("d3", 101.0), ("d4", 103.0)]   # d2 분봉 없음(ORB 건너뜀)
    cash = {"d0": {"close": 10.0}, "d1": {"close": 10.01}, "d3": {"close": 10.02}}
    x = A.excess_rets(curve, cash)
    assert x == pytest.approx([0.02 - 0.001, (101 / 102 - 1) - (10.02 / 10.01 - 1)])   # d4 현금 없음 → 빠짐


def _aggr(rets):
    dates = _dates(len(rets) + 1)
    v, curve = 500_000.0, [(dates[0], 500_000.0)]
    for d, r in zip(dates[1:], rets):
        v *= 1 + r
        curve.append((d, v))
    cash = {d: {"close": 100.0} for d in dates}                           # 현금 수익 0
    return curve, cash


def test_aggr_verdict_kept_and_real_money_gated_from_january():
    """선언 판정(pass)은 그대로 — 1월부터 '실계좌 재검토 자격'만 통계로. 잡음 같은 +수익은 연장, 꾸준한 +수익은 자격."""
    curve, cash = _aggr([0.012 if i % 2 else -0.0105 for i in range(70)])
    rec = {"verdict": {"judged": True, "pass": True, "checks": {}}}
    r = A.with_stat(dict(rec, verdict=dict(rec["verdict"])), curve, cash, "2027-01-26")
    assert r["verdict"]["pass"] is True and r["verdict"]["real_money_ok"] is False and "통계 미달" in r["verdict"]["hold_reason"]
    r = A.with_stat(dict(rec, verdict=dict(rec["verdict"])), curve, cash, "2026-12-26")
    assert r["verdict"]["real_money_ok"] is True                           # 시행 전 — 옛 길
    curve2, cash2 = _aggr([0.004 + 0.001 * math.sin(i) for i in range(70)])
    r = A.with_stat(dict(rec, verdict=dict(rec["verdict"])), curve2, cash2, "2027-01-26")
    assert r["stat"]["pass"] and r["verdict"]["real_money_ok"] is True
    r = A.with_stat({"verdict": {"judged": False, "why": "기록 20/60"}}, curve, cash, "2027-01-26")
    assert "real_money_ok" not in r["verdict"] and r["stat"]["n_tests"] == len(A.MEMBERS)
