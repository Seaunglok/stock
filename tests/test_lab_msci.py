"""MSCI 한국 정기변경 판정대(lab_msci) — 목록 읽기·창·판정·장부가 선언대로 (11-23, 측정 전)."""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_msci as X  # noqa: E402
import lab_msci_map as MM  # noqa: E402
import lab_trials as T  # noqa: E402

SAMPLE = """Page 1 MSCI Global Standard Indexes - May 12, 2015
Geneva, May 12, 2015
The following are changes in constituents for the MSCI Global Standard Indexes
which will take place as of the close of May 29, 2015.
MSCI TAIWAN INDEX
Additions                               Deletions
CASETEK HOLDINGS                        CLEVO COMPANY
MSCI KOREA INDEX
Additions                               Deletions
AMOREPAC CORP PREF (NEW)                HITE JINRO CO
HANMI PHARM CO (NEW)
MSCI INDIA INDEX
Additions                               Deletions
BHARAT FORGE                            RELIANCE INFRASTRUCTURE
"""


def test_parse_text_korea_section_and_dates():
    r = X.parse_text(SAMPLE)
    assert r == {"announced": "2015-05-12", "effective": "2015-05-29",
                 "add": ["AMOREPAC CORP PREF (NEW)", "HANMI PHARM CO (NEW)"], "del": ["HITE JINRO CO"]}
    no_korea = SAMPLE.split("MSCI KOREA INDEX")[0]
    assert X.parse_text(no_korea)["add"] == [] and X.parse_text(no_korea)["del"] == []
    with pytest.raises(ValueError):
        X.parse_text("MSCI KOREA INDEX")


def _wdays(start, n, closed=()):
    d, out = dt.date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in closed:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_windows_follow_declared_timing():
    days = _wdays("2015-05-01", 40, closed={"2015-05-29"})                 # 시행일이 휴장이면 그 전 거래일 종가
    rev = {"announced": "2015-05-12", "effective": "2015-05-29", "add": ["A"], "del": ["B"]}
    (a, fa), (e, fe) = X.window(days, rev, "M1")
    assert days[a] == "2015-05-13" and fa == "open" and days[e] == "2015-05-28" and fe == "close"
    (a, fa), (b, fb) = X.window(days, rev, "M2")
    assert days[a] == "2015-05-28" and fa == "close" and b - a == X.POST_DAYS
    assert X.window(days, rev, "PRE") is None                              # 발표 전 20거래일이 자료 밖
    long = _wdays("2015-03-02", 70)
    (p, _), (q, _) = X.window(long, rev, "PRE")
    assert long[q] == "2015-05-12" and q - p == X.PRE_DAYS


def _bars(days, f):
    return {d: {"open": f(k, "o"), "close": f(k, "c")} for k, d in enumerate(days)}


def test_review_excess_averages_stocks_and_skips_missing(monkeypatch):
    days = _wdays("2015-05-01", 40)
    monkeypatch.setattr(MM, "MSCI_TO_CODE", {"A": "000001", "B": "000002", "C": "000003"})
    bench = _bars(days, lambda k, s: 100.0)
    px = {"000001": _bars(days, lambda k, s: 100.0 + k), "000002": _bars(days, lambda k, s: 100.0)}
    rev = {"announced": "2015-05-12", "effective": "2015-05-29", "add": ["A", "B", "C"], "del": []}
    r = X.review_excess(rev, "add", "M1", px, days, bench)
    a = days.index("2015-05-13")
    e = days.index("2015-05-29")
    assert r["n"] == 2 and r["skipped"] == ["C"]
    assert r["excess"] == pytest.approx(((100.0 + e) / (100.0 + a) - 1 + 0.0) / 2)


def _world(effect: float, n_years=12):
    """2014-11~2026-08 분기마다 리뷰 하나 — 편입 종목이 진입~시행일에 effect 만큼(해마다 조금씩 다르게) 더 오른다."""
    days = _wdays("2014-09-01", 3200)
    reviews, px = {}, {}
    bench = _bars(days, lambda k, s: 100.0 * (1 + 0.0002 * math.sin(k)))
    codes = {}
    k = 0
    for y in range(2014, 2027):
        for m in (2, 5, 8, 11):
            ann = dt.date(y, m, 10).isoformat()
            eff = dt.date(y, m, 27).isoformat()
            if ann < "2014-11-01" or ann > "2026-08-31":
                continue
            name = f"S{k}"
            codes[name] = f"{k:06d}"
            a = X.first_after(days, ann)
            e = X.last_on_or_before(days, eff)
            bump = effect * (1 + 0.2 * math.sin(k))

            def f(i, s, a=a, e=e, bump=bump):
                if i < a or (i == a and s == "o"):
                    return 100.0
                return 100.0 * (1 + bump) if i >= e else 100.0 * (1 + bump * (i - a) / max(1, e - a))
            px[codes[name]] = _bars(days, f)
            reviews[f"R{k}"] = {"announced": ann, "effective": eff, "add": [name], "del": []}
            k += 1
    return reviews, px, days, bench, codes


def test_judge_passes_injected_effect_and_fails_without(monkeypatch):
    reviews, px, days, bench, codes = _world(0.03)
    monkeypatch.setattr(MM, "MSCI_TO_CODE", codes)
    r = X.judge(reviews, "M1", px, days, bench, h=3.5, cost=X.round_trip())
    assert r["pass"] and all(s["checks"]["P1"] and s["checks"]["P3"] for s in r["periods"].values())
    r = X.judge(reviews, "M1", px, days, bench, h=3.5, cost=0.05)                # 비용이 효과보다 크면 P3 탈락
    assert not r["pass"]
    reviews, px, days, bench, codes = _world(0.0)
    monkeypatch.setattr(MM, "MSCI_TO_CODE", codes)
    r = X.judge(reviews, "M1", px, days, bench, h=3.5, cost=X.round_trip())
    assert not r["pass"] and not r["pooled"]["P4"]


def test_trials_and_hurdle_registered_before_measuring():
    row = [r for r in T.TRIALS if r[3] == X.SOURCE]
    assert len(row) == 1 and row[0][2] == len(X.CANDIDATES) == 2 and row[0][0] == X.DECLARED_ON
    assert X.trials() == 107 and X.hurdle() == pytest.approx(3.50, abs=0.01)
    assert T.total_through("scripts/lab_flow_fwd.py") == 105                      # 앞 묶음 통과선 그대로
    assert X.round_trip() == pytest.approx(X.L.side_cost(True, False) + X.L.side_cost(True, True))


@pytest.mark.skipif(not X.PDF_DIR.exists(), reason="MSCI 목록 PDF 없음(docs_cache)")
def test_real_pdfs_parse_and_every_name_has_a_code():
    revs = X.load_reviews()
    assert len(revs) == 59 and revs["May15"]["announced"] == "2015-05-12" and revs["May15"]["effective"] == "2015-05-29"
    assert (len(revs["May15"]["add"]), len(revs["May15"]["del"])) == (2, 1)
    assert (len(revs["Feb25"]["add"]), len(revs["Feb25"]["del"])) == (0, 11)
    names = {n for r in revs.values() for n in r["add"] + r["del"]}
    assert names <= set(MM.MSCI_TO_CODE) and len(names) == 146
    assert all(len(c) == 6 for c in MM.MSCI_TO_CODE.values())
