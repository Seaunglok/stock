"""시장 수급 이력(market_flows) — 날짜 대조 가드·저장·프로그램 매매 이어받기. 합성 자료만 쓴다."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_flows as F  # noqa: E402

KOSPI = {"지수": 5059.69, "등락(%)": -6.02, "외국인": -26897.0, "기관": 17091.0, "개인": 5211.0, "기타법인": 4589.0,
         "금융투자": 1.0, "연기금": 2.0}
KOSDAQ = {"지수": 644.27, "등락(%)": -5.03, "외국인": -954.0, "기관": 2096.0, "개인": -1990.0}
PROG = {"차익": 109031.0, "비차익": -1593953.0, "전체": -1484921.0, "KOSPI200": 783.23, "베이시스": -0.28}


def test_check_index_guard():
    """★ 응답에 날짜가 없다 — 요청한 날의 실제 종가와 0.5% 넘게 다르면 믿지 않는다(일부러 깨뜨려 확인)."""
    assert F.check_index(5059.69, 5059.69) == "ok"
    assert F.check_index(5059.69, 5084.0) == "ok"                      # 0.48% — 한도 안
    assert F.check_index(5383.80, 5059.69) == "bad:+6.41%"             # 전날 값을 준 경우
    assert F.check_index(None, 5059.69) == "unchecked" and F.check_index(5059.69, None) == "unchecked"


def test_row_from_maps_columns_and_units():
    r = F.row_from("2026-11-06", KOSPI, KOSDAQ, PROG, 5059.69, "t")
    assert set(r) == set(F.COLS)
    assert (r["kospi"], r["kospi_foreign_eok"], r["kospi_inst_eok"], r["kospi_indiv_eok"]) == (5059.69, -26897.0, 17091.0, 5211.0)
    assert r["kosdaq_foreign_eok"] == -954.0 and r["kosdaq_pension_eok"] is None
    assert (r["prog_total"], r["basis"], r["check"]) == (-1484921.0, -0.28, "ok")
    assert F.row_from("2026-11-06", None, None, None, 5059.69, "t")["check"] == "unchecked"


def test_duplicate_of_previous_day_is_marked():
    a = F.row_from("2026-11-05", KOSPI, KOSDAQ, PROG, 5059.69, "t")
    b = F.row_from("2026-11-06", KOSPI, KOSDAQ, PROG, 5059.69, "t")
    assert F.mark_duplicate(b, a)["check"] == "dup" and F.mark_duplicate(b, None)["check"] == "ok"
    c = F.row_from("2026-11-06", {**KOSPI, "외국인": -1.0}, KOSDAQ, PROG, 5059.69, "t")
    assert F.mark_duplicate(c, a)["check"] == "ok"


def test_unchecked_rows_are_rechecked_when_close_appears():
    have = {"2026-11-09": {**F.row_from("2026-11-09", KOSPI, KOSDAQ, PROG, None, "t"), "kospi": "5059.69"},
            "2026-11-06": {**F.row_from("2026-11-06", KOSPI, KOSDAQ, PROG, 5059.69, "t"), "kospi": "5059.69"}}
    assert [r["check"] for r in F.recheck_unchecked(have, {"2026-11-09": 5059.69})] == ["ok"]
    assert [r["check"] for r in F.recheck_unchecked(have, {"2026-11-09": 4000.0})] == ["bad:+26.49%"]
    assert F.recheck_unchecked(have, {}) == []                        # 아직 종가가 없으면 그대로


def test_verified_day_is_ok_only_for_the_confirmed_close():
    """★ 2021-05-06: 대조값(FDR·키움 일봉 3,160.43)이 틀린 날 — 마감 기사로 확인한 3,178.74 와 **같을 때만** ok.
    다른 값(예: 전날 3,147.37 을 준 응답)은 여전히 bad — 확인 목록이 가드를 끄는 구멍이 되면 안 된다."""
    day = "2021-05-06"
    assert F.VERIFIED[day][0] == 3178.74 and "뉴데일리" in F.VERIFIED[day][1]
    ok = F.row_from(day, {**KOSPI, "지수": 3178.74}, KOSDAQ, PROG, 3160.43, "t")
    stale = F.row_from(day, {**KOSPI, "지수": 3147.37}, KOSDAQ, PROG, 3160.43, "t")
    assert ok["check"] == "ok" and stale["check"].startswith("bad")
    assert F.check_row("2021-05-07", 3178.74, 3160.43).startswith("bad")         # 목록 밖 날짜는 그대로
    have = {day: {**ok, "kospi": "3178.74", "check": "bad:+0.58%"},
            "2021-05-07": {**ok, "date": "2021-05-07", "kospi": "3178.74", "check": "bad:+0.58%"},
            "2021-05-03": {**stale, "date": "2021-05-03", "kospi": "3147.37", "check": "bad:-0.41%"}}
    assert [(r["date"], r["check"]) for r in F.recheck_verified(have)] == [(day, "ok")]
    have[day]["kospi"] = "3147.37"
    assert F.recheck_verified(have) == []


def test_backfill_never_fetches_today():
    """★ 오늘 수급은 잠정치 — 채우기는 어제까지만 받는다(확정치는 다음 날 아침 시장 일지가 넣는다)."""
    days = ["2026-11-06", "2026-11-09", "2026-11-10"]
    assert F.days_to_fetch(days, {}, "2026-11-10") == ["2026-11-06", "2026-11-09"]
    assert F.days_to_fetch(days, {"2026-11-06": {}}, "2026-11-11") == ["2026-11-09", "2026-11-10"]


def test_upsert_replaces_same_date_and_sorts(tmp_path):
    p = tmp_path / "d.csv"
    F.upsert([F.row_from("2026-11-06", KOSPI, KOSDAQ, PROG, 5059.69, "t1")], p)
    F.upsert([F.row_from("2026-11-05", KOSPI, KOSDAQ, PROG, None, "t1")], p)
    n = F.upsert([F.row_from("2026-11-06", {**KOSPI, "외국인": -1.0}, KOSDAQ, PROG, 5059.69, "t2")], p)
    rows = F.load_rows(p)
    assert n == 2 and list(rows) == ["2026-11-05", "2026-11-06"]
    assert rows["2026-11-06"]["kospi_foreign_eok"] == "-1.0" and rows["2026-11-05"]["check"] == "unchecked"


def test_program_history_walks_back_in_pages():
    """ka90010 은 요청일부터 과거로 N일 — 가장 오래된 날 하루 전으로 다시 요청해 이어 받는다."""
    pages = {"20261106": ["20261106", "20261105", "20261104"], "20261103": ["20261103", "20261102", "20261030"],
             "20261029": ["20261029"]}
    asked = []

    class C:
        async def call_api(self, api, params):
            asked.append(params["date"])
            return {"prm_trde_trnsn": [{"cntr_tm": d + "000000", "all_netprps": "-1", "basis": "0.1"}
                                       for d in pages.get(params["date"], [])]}
    F.CALL_PAUSE_S, old = 0.0, F.CALL_PAUSE_S
    try:
        out = asyncio.run(F.program_history(C(), ["2026-10-30", "2026-11-06"]))
    finally:
        F.CALL_PAUSE_S = old
    assert asked == ["20261106", "20261103"]                # 둘째 페이지가 시작일(10-30)까지 덮었다 — 더 부르지 않는다
    assert sorted(out) == ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert out["2026-11-06"]["전체"] == -1.0
