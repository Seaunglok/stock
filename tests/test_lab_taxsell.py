"""연말 대주주 매도 판정대(lab_taxsell) — 마감일 규칙·판정·장부가 선언과 같은지 (11-23, 측정 전)."""
from __future__ import annotations

import csv
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_taxsell as X  # noqa: E402
import lab_trials as T  # noqa: E402


def weekdays(a: str, b: str, closed: set[str] = frozenset()) -> list[str]:
    out, x, end = [], date.fromisoformat(a), date.fromisoformat(b)
    while x <= end:
        if x.weekday() < 5 and x.isoformat() not in closed:
            out.append(x.isoformat())
        x += timedelta(days=1)
    return out


# ── 마감일 규칙 ──────────────────────────────────────────────────────────────
def test_deadline_matches_news_dates():
    """기사로 확인한 마감일 — 2021 폐장 12-30 → 12-28 · 2023 폐장 12-28(12-29 휴장) → 12-26 · 2026 폐장 12-30 → 12-28."""
    d21 = weekdays("2021-12-01", "2022-01-10", {"2021-12-31"})
    assert d21[X.deadline_positions(d21, (2021,))[2021]] == "2021-12-28"
    d23 = weekdays("2023-12-01", "2024-01-10", {"2023-12-25", "2023-12-29", "2024-01-01"})
    assert d23[X.deadline_positions(d23, (2023,))[2023]] == "2023-12-26"
    d26 = weekdays("2026-12-01", "2027-01-12", {"2026-12-25", "2026-12-31", "2027-01-01"})
    k = X.deadline_positions(d26, (2026,))[2026]
    assert d26[k] == "2026-12-28"
    assert d26[k - 5] == "2026-12-18" and d26[k + 5] == "2027-01-06"      # 선언문의 2026 연말 일정


def test_deadline_needs_next_year_in_data():
    """폐장일 다음 거래일이 자료에 없으면(자료 끝) 폐장일을 확정할 수 없다 — 뺀다."""
    days = weekdays("2025-12-01", "2025-12-30")
    assert X.deadline_positions(days, (2025,)) == {}


def test_entries_offsets():
    days = weekdays("2021-12-01", "2022-01-20", {"2021-12-31"})
    d = X.deadline_positions(days, (2021,))[2021]
    assert X.CANDIDATES["Y1"][2] == -5 and X.CANDIDATES["Y2"][2] == 0 and X.SHAPE == ("cc", 5)
    y1 = {y: k for y, k in X.entries("Y1", days).items() if y == 2021}
    y2 = {y: k for y, k in X.entries("Y2", days).items() if y == 2021}
    assert days[y1[2021] + 5] == days[d] == "2021-12-28"                   # Y1 창은 D 종가에서 끝난다
    assert days[y2[2021]] == "2021-12-28"                                   # Y2 는 D 종가에서 시작한다


def test_threshold_groups_are_eight_and_eight():
    assert sorted(X.low_years()) == list(range(2015, 2023))
    assert set(X.THRESHOLD_KOSDAQ_EOK) == set(X.YEARS) and len(X.YEARS) == X.MIN_EVENTS_TOTAL == 16


# ── 판정 ────────────────────────────────────────────────────────────────────
def _calendar() -> list[str]:
    closed = {f"{y}-12-31" for y in range(2009, 2027)} | {f"{y}-01-01" for y in range(2010, 2027)}
    return weekdays("2009-10-01", "2026-03-31", closed)


def test_judge_detects_injected_dip_and_rebound():
    """마감일 앞 5일 −3% · 뒤 5일 +3% 를 심으면 Y1(하락 가설, 부호 뒤집음)·Y2 둘 다 통과, 비용이 크면 P3 탈락."""
    days = _calendar()
    ds = X.deadline_positions(days)
    assert sorted(ds) == list(X.YEARS)
    step = {}
    for y, d in ds.items():
        for j in range(d - 4, d + 1):
            step[j] = -0.03 / 5 * (1 + 0.1 * (y % 3))        # 해마다 크기가 조금씩 다르다(표준편차 > 0)
        for j in range(d + 1, d + 6):
            step[j] = +0.03 / 5 * (1 + 0.1 * (y % 2))
    bars, px = {}, 100.0
    for i, d in enumerate(days):
        px *= 1 + step.get(i, 0.0)
        bars[d] = {"close": px}
    for name in X.CANDIDATES:
        r = X.judge(bars, days, name, hurdle_t=3.49, cost=0.00115)
        assert r["pooled"]["n"] == 16 and r["pooled"]["P1"] and r["pooled"]["P4"] and r["pass_index"], name
        assert all(s["checks"]["P2"] and s["checks"]["P3"] for s in r["periods"].values())
        assert {p: s["n"] for p, s in r["periods"].items()} == {"앞": 11, "뒤": 5}
        r2 = X.judge(bars, days, name, hurdle_t=3.49, cost=0.05)
        assert not r2["pass_index"] and not any(s["checks"]["P3"] for s in r2["periods"].values())


def test_judge_no_effect_and_missing_year_fail():
    days = _calendar()
    bars, px = {}, 100.0
    for i, d in enumerate(days):                                    # 날짜와 무관한 결정적 흔들림
        r = 0.01 * math.sin(i * 1.7)
        px *= 1 + r
        bars[d] = {"close": px}
    for name in X.CANDIDATES:
        assert not X.judge(bars, days, name, hurdle_t=3.49, cost=0.00115)["pooled"]["P4"]
    k = X.deadline_positions(days)[2015]
    bars[days[k]] = {"close": None}                                 # 한 해의 마감일 종가가 없으면 P1 탈락
    r = X.judge(bars, days, "Y2", hurdle_t=0.0, cost=0.0)
    assert r["pooled"]["n"] == 15 and not r["pooled"]["P1"] and not r["pass_index"]


def test_exec_check_uses_etf_on_index_dates():
    days = _calendar()
    ds = X.deadline_positions(days)
    etf = {d: {"close": 100.0} for d in days if d >= "2016-08-10"}
    for y, d in ds.items():
        if days[d] in etf:
            etf[days[d]] = {"close": 99.0}                          # D 종가만 1% 낮다 → Y2(D 매수 → D+5 매도) +1.01%
    r = X.exec_check(etf, days, "Y2", cost=0.00115)
    assert r["n"] == len([y for y in ds if y >= 2016]) and r["mean"] == pytest.approx(100 / 99 - 1) and r["P5"]
    r1 = X.exec_check(etf, days, "Y1", cost=0.00115)                 # Y1 은 D 에서 판다 → −1%
    assert r1["mean"] == pytest.approx(-0.01) and not r1["P5"]


def test_flows_report_reads_only_ok_rows(tmp_path):
    """R4 — check ok 가 아닌 날은 버리고, 수급이 빠진 창은 계산하지 않는다(실제 CSV 형식으로 쓰고 읽는다)."""
    days = weekdays("2021-12-01", "2022-01-20", {"2021-12-31"})
    p = tmp_path / "daily.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "kosdaq_indiv_eok", "check"])
        w.writeheader()
        for d in days:
            w.writerow({"date": d, "kosdaq_indiv_eok": "-100" if d <= "2021-12-28" else "50",
                        "check": "mismatch" if d == "2022-01-05" else "ok"})
    flows = X.load_indiv_kosdaq(p)
    assert "2022-01-05" not in flows and flows["2021-12-28"] == -100.0
    r1 = X.report_flows(flows, days, "Y1")
    assert r1["years"] == {2021: -500.0}                             # D−4..D 다섯 날 −100
    assert X.report_flows(flows, days, "Y2")["years"] == {}         # D+1..D+5 에 ok 아닌 날 → 그해 빠짐


def test_real_flows_csv_has_kosdaq_individual_column():
    """실제 수급 이력 파일(writer = market_flows)과 이 판정대(reader)의 열 이름이 같다."""
    if not X.FLOWS_CSV.exists():
        pytest.skip("수급 이력 없음")
    with open(X.FLOWS_CSV, encoding="utf-8") as f:
        head = next(csv.reader(f))
    assert "kosdaq_indiv_eok" in head and "check" in head


# ── 시험 횟수 장부 ───────────────────────────────────────────────────────────
def test_this_batch_is_registered_before_measuring():
    row = [r for r in T.TRIALS if r[0] == X.DECLARED_ON and r[3] == X.SOURCE]
    assert len(row) == 1 and row[0][2] == len(X.CANDIDATES)
    assert X.trials() == 104 and X.hurdle() == T.hurdle_t(104)
    assert X.hurdle() == pytest.approx(3.49, abs=0.01)
    assert T.total_through("scripts/lab_gen10.py") == 102           # 앞 묶음들의 통과선은 그대로
