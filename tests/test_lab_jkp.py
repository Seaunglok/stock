"""한국 팩터 기울기 판정대(lab_jkp) — 구성·가드·판정 규칙, 시험 횟수 장부 (2026-11-18 선언 전 작성)."""
from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import lab_calendar as C  # noqa: E402
import lab_jkp as J  # noqa: E402
import lab_trials as T  # noqa: E402


def months(a: str = "1996-01", b: str = "2025-12") -> list[str]:
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def synth(alpha: float = 0.004, beta: float = 1.0, mkt_mean: float = 0.005, seed: int = 7, noise: float = 0.01) -> dict:
    """'Low Risk' 주제 2 특성(방향 −1·+1) — 사는 쪽 = α + β·시장 + 잡음, 파는 쪽 = 시장 − 0.002."""
    rnd = random.Random(seed)
    ms = months()
    mkt = {m: mkt_mean + rnd.gauss(0, 0.05) for m in ms}
    data = {"factors": {}, "pf": {}, "mkt": mkt, "themes": {"low_risk": {}},
            "clusters": {"lowvol_a": "Low Risk", "lowvol_b": "Low Risk"}, "dirs": {"lowvol_a": -1, "lowvol_b": 1}}
    for c, d in data["dirs"].items():
        for m in ms:
            lo = alpha + beta * mkt[m] + rnd.gauss(0, noise)
            sh = mkt[m] - 0.002 + rnd.gauss(0, noise)
            legs = {J.long_pf(d): lo, 2: mkt[m], J.short_pf(d): sh}
            data["pf"].setdefault(c, {})[m] = legs
            data["factors"].setdefault(c, {})[m] = lo - sh
    for m in ms:
        ls = [data["factors"][c][m] for c in data["dirs"]]
        data["themes"]["low_risk"][m] = (sum(ls) / len(ls), len(ls))
    return data


# ── 구성 ─────────────────────────────────────────────────────────────────────
def test_long_short_side_follows_paper_direction():
    assert (J.long_pf(1), J.short_pf(1)) == (3, 1)      # 높을수록 좋다 → 높은 3분위를 산다
    assert (J.long_pf(-1), J.short_pf(-1)) == (1, 3)    # 낮을수록 좋다(변동성·베타) → 낮은 3분위
    assert J.theme_key("Short-Term Reversal") == "short_term_reversal" and J.theme_key("Low Risk") == "low_risk"


def test_series_averages_only_members_present_that_month():
    data = synth()
    m0, m1 = "1996-01", "1996-02"
    del data["factors"]["lowvol_b"][m1]                     # 그 달 팩터 수익이 없으면(다리 5종목 미만) 빼고 평균
    ser = J.series(("theme", "Low Risk"), data)
    a, b = data["pf"]["lowvol_a"], data["pf"]["lowvol_b"]
    assert ser[m0][2] == 2 and ser[m0][0] == pytest.approx((a[m0][1] + b[m0][3]) / 2)   # a 는 방향 −1 → pf1, b 는 +1 → pf3
    assert ser[m1][2] == 1 and ser[m1][0] == pytest.approx(a[m1][1])
    one = J.series(("char", "lowvol_b"), data)
    assert one[m0][0] == pytest.approx(b[m0][3]) and m1 not in one


# ── 가드: 일부러 깨뜨린다 ───────────────────────────────────────────────────────
def test_guards_pass_on_consistent_data():
    data = synth()
    assert J.guard_legs(data)["ok"] and J.guard_themes(data)["ok"]
    J.guards(data)                                          # 예외 없음


def test_guard_legs_catches_wrong_direction():
    data = synth()
    data["dirs"]["lowvol_a"] = 1                            # 방향을 거꾸로 읽으면 롱숏이 사는 쪽 − 파는 쪽과 다르다
    g = J.guard_legs(data)
    assert not g["ok"] and g["worst"] > 1e-3
    with pytest.raises(RuntimeError, match="가드"):
        J.measure(data)


def test_guard_legs_catches_missing_leg():
    data = synth()
    del data["pf"]["lowvol_b"]["2001-05"][J.long_pf(1)]
    g = J.guard_legs(data)
    assert not g["ok"] and g["missing"] == 1


def test_guard_themes_catches_wrong_membership():
    data = synth()
    data["clusters"]["lowvol_b"] = "Value"                  # 구성이 JKP 와 다르면 주제 롱숏이 안 맞는다
    g = J.guard_themes(data)
    assert not g["ok"]
    data2 = synth()
    m = "2010-03"
    r, k = data2["themes"]["low_risk"][m]
    data2["themes"]["low_risk"][m] = (r + 1e-4, k)
    assert not J.guard_themes(data2)["ok"]


def test_verify_files_rejects_missing_or_changed(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("x,y\n1,2\n", encoding="utf-8")
    files = {"a.csv": (J.sha256(p), "url")}
    J.verify_files(tmp_path, files)                          # 같으면 통과
    p.write_text("x,y\n1,3\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="해시"):
        J.verify_files(tmp_path, files)
    with pytest.raises(RuntimeError, match="없음"):
        J.verify_files(tmp_path, {"b.csv": ("0" * 64, "url")})


# ── 판정 ─────────────────────────────────────────────────────────────────────
def test_ols_recovers_alpha_and_beta():
    rnd = random.Random(1)
    x = [rnd.gauss(0, 0.05) for _ in range(400)]
    y = [0.003 + 0.7 * a + rnd.gauss(0, 0.002) for a in x]
    r = J.ols(y, x)
    assert r["alpha"] == pytest.approx(0.003, abs=3e-4) and r["beta"] == pytest.approx(0.7, abs=0.01) and r["t"] > 10
    assert J.months_between("1996-01", "2009-12") == 168 and J.months_between("2021-01", "2025-12") == 60


def test_judge_passes_strong_alpha_and_applies_cost():
    r = J.judge("F1", synth(alpha=0.004), hurdle_t=3.48)
    assert r["pass"] and all(all(s["checks"].values()) for s in r["periods"].values())
    assert r["full"]["alpha"] == pytest.approx(0.004 - 0.005 / 12, abs=5e-4)       # 연 0.5%p 를 월로 뺐다
    weak = J.judge("F1", synth(alpha=0.0003, noise=0.001), hurdle_t=3.48)          # 비용(월 0.042%)보다 작은 우위
    assert weak["full"]["alpha"] == pytest.approx(0.0003 - 0.005 / 12, abs=5e-5)
    assert not weak["pass"] and weak["full"]["alpha"] < 0 and not any(s["checks"]["P2"] for s in weak["periods"].values())
    mom = J.judge("F2", {**synth(alpha=0.0003, noise=0.001), "clusters": {"lowvol_a": "Momentum", "lowvol_b": "Momentum"}},
                  hurdle_t=3.48)                                                   # 모멘텀은 연 1.0%p
    assert mom["full"]["alpha"] == pytest.approx(0.0003 - 0.010 / 12, abs=5e-5)


def test_judge_no_alpha_fails_p4():
    r = J.judge("F1", synth(alpha=0.0005), hurdle_t=3.48)
    assert not r["full"]["P4"] and not r["pass"]


def test_judge_low_beta_without_return_fails_p3():
    """알파는 크지만 β 0.5 로 수익을 내주는 경우 — 위험만 줄이는 쪽은 KODEX200 대신 쓰지 않는다."""
    r = J.judge("F1", synth(alpha=0.002, beta=0.5, mkt_mean=0.012), hurdle_t=3.48)
    assert r["full"]["alpha_t"] > 3.48 and r["full"]["tilt"] < 0
    assert not r["full"]["P3"] and not r["pass"]


def test_judge_needs_coverage_in_every_period():
    data = synth()
    for c in data["factors"]:
        for m in months("2021-01", "2021-12"):              # C 구간 60달 중 12달 빔 → 80% < 90%
            data["factors"][c].pop(m)
    r = J.judge("F1", data, hurdle_t=3.48)
    assert not r["periods"]["C"]["checks"]["P1"] and not r["pass"]


# ── 시험 횟수 장부 ───────────────────────────────────────────────────────────
def test_this_batch_is_registered_before_measuring():
    row = [r for r in T.TRIALS if r[3] == J.SOURCE]
    assert len(row) == 1 and row[0][2] == len(J.CANDIDATES)
    assert J.trials() == 98 and C.trials() == 93                # 같은 날 앞 묶음의 통과선은 그대로
    assert J.hurdle() == T.hurdle_t(98) == pytest.approx(3.48, abs=0.01)


# ── 실제 자료(캐시가 있을 때만) — 구조만 본다 ─────────────────────────────────────
@pytest.mark.skipif(not all((J.DATA_DIR / n).exists() for n in J.FILES), reason="JKP 캐시 없음")
def test_real_data_matches_declaration_and_guards():
    data = J.load()
    g1, g2 = J.guards(data)
    assert g1["checked"] > 50_000 and g2["themes"] == 13
    for n, cov in J.coverage(data).items():
        for p, (k, e) in cov.items():
            assert k >= J.MIN_COVER * e, (n, p, k, e)
    lr = J.members("Low Risk", data)
    assert len(lr) >= 18 and {"betabab_1260d", "ivol_capm_252d", "rvol_21d"} <= set(lr)


@pytest.mark.skipif(not all((J.DATA_DIR / n).exists() for n in J.FILES), reason="JKP 캐시 없음")
def test_real_data_hash_guard_trips_on_edit(tmp_path):
    d = tmp_path / "jkp"
    shutil.copytree(J.DATA_DIR, d)
    with open(d / "kor_mkt_monthly.csv", "a", encoding="utf-8") as f:
        f.write("kor,mkt,monthly,vw_cap,na,1,na,2026-01-31,0.01\n")
    with pytest.raises(RuntimeError, match="해시"):
        J.load(d)
