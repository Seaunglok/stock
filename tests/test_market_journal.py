"""시장 일지(market_journal) — 순수 함수가 적힌 대로 도는지. 키움 응답 모양은 2026-11-06 실제 응답에서 땄다."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_journal as M  # noqa: E402

KOSPI_ROW = {"inds_cd": "001_AL", "inds_nm": "종합(KOSPI)", "cur_prc": "-505969", "flu_rt": "-602",
             "sc_netprps": "+17583", "endw_netprps": "+2867", "etc_corp_netprps": "+5184", "ind_netprps": "+2570",
             "frgnr_netprps": "-26435", "orgn_netprps": "+18564"}
BIG_ROW = {**KOSPI_ROW, "inds_cd": "002_AL", "inds_nm": "대형주"}
PROG = [{"cntr_tm": "20261106000000", "dfrt_trde_netprps": "+109031", "ndiffpro_trde_netprps": "-1593953",
         "all_netprps": "-1484921", "kospi200": "+783.23", "basis": "-0.28"},
        {"cntr_tm": "20261105000000", "all_netprps": "-1636801", "kospi200": "+837.78", "basis": "-0.53"}]


def _item(title, link, when):
    return {"title": title, "originallink": link, "link": link, "pubDate": when}


def test_num_and_index_flows_from_real_shape():
    assert M._num("+17583") == 17583 and M._num("-505969") == -505969 and M._num("") is None
    f = M.index_flows([BIG_ROW, KOSPI_ROW])
    assert abs(f["지수"] - 5059.69) < 1e-9 and abs(f["등락(%)"] + 6.02) < 1e-9
    assert (f["외국인"], f["기관"], f["개인"], f["단위"]) == (-26435, 18564, 2570, "억원")
    assert M.index_flows([BIG_ROW]) is None                 # 종합 행이 없으면 만들지 않는다


def test_program_flows_picks_the_day():
    p = M.program_flows(PROG, "2026-11-06")
    assert (p["전체"], p["차익"], p["비차익"], p["베이시스"], p["단위"]) == (-1484921, 109031, -1593953, -0.28, "백만원")
    assert M.program_flows(PROG, "2026-11-07") is None


def test_amount_text_units():
    assert M._signed_jo(-26435, "억원") == "-2.64조"
    assert M._signed_jo(-1484921, "백만원") == "-1.48조"
    assert M._signed_jo(2570, "억원") == "+2,570억" and M._signed_jo(None, "억원") == "-"


def test_news_window_dedupes_and_filters():
    by_kw = {
        "반도체": [_item("<b>반도체</b> 급락 &quot;충격&quot;", "u1", "Thu, 05 Nov 2026 20:00:00 +0900"),
                 _item("옛 기사", "u0", "Wed, 04 Nov 2026 10:00:00 +0900")],
        "엔비디아": [_item("<b>반도체</b> 급락 &quot;충격&quot;", "u1", "Thu, 05 Nov 2026 20:00:00 +0900"),
                  _item("엔비디아 9% 하락", "u2", "Fri, 06 Nov 2026 06:30:00 +0900")],
    }
    news = M.news_in_window(by_kw, datetime(2026, 11, 5, 15, 30), datetime(2026, 11, 6, 8, 30))
    assert [n["link"] for n in news] == ["u2", "u1"]                     # 최신순 · 창 밖(u0) 제외
    assert news[1]["title"] == '반도체 급락 "충격"' and news[1]["keywords"] == ["반도체", "엔비디아"]
    assert M.topic_counts(news) == {"엔비디아": 2, "반도체": 1}
    heads = M.pick_headlines(news, 5)
    assert [h["topic"] for h in heads] == ["엔비디아", "반도체"] and heads[0]["link"] == "u2"
    assert len({h["title"] for h in heads}) == len(heads)              # 같은 제목은 한 번


def test_headline_prefers_title_containing_topic():
    by_kw = {"코스피": [_item("비트코인 7주 만에 최저", "b1", "Fri, 06 Nov 2026 22:10:00 +0900"),
                      _item("코스피 서킷브레이커 발동", "k1", "Fri, 06 Nov 2026 09:10:00 +0900")],
             "외국인 순매도": [_item("외국인 2.6조 순매도 폭탄", "f1", "Fri, 06 Nov 2026 15:40:00 +0900")]}
    news = M.news_in_window(by_kw, datetime(2026, 11, 6, 8, 30), datetime(2026, 11, 6, 23, 0))
    heads = {h["topic"]: h["link"] for h in M.pick_headlines(news)}
    assert heads == {"코스피": "k1", "외국인 순매도": "f1"}       # 더 최근인 비트코인 기사(b1)가 아니라 제목에 주제어가 있는 기사


def test_topics_text_marks_capped():
    assert M.topics_text({"코스피": 812, "반도체": 240}, ["코스피"]) == "코스피 812+ · 반도체 240"
    assert M.topics_text({}, None) == ""


def test_error_label_keeps_http_status():
    class R:
        status_code = 429

    class E(Exception):
        response = R()
    assert M._err(E()) == "E 429" and M._err(ValueError()) == "ValueError"


def test_paging_stops_when_page_reaches_window_start():
    page = [_item("a", "x", "Fri, 06 Nov 2026 07:00:00 +0900"), _item("b", "y", "Thu, 05 Nov 2026 12:00:00 +0900")]
    assert M._older_than(page, datetime(2026, 11, 5, 15, 30)) is True
    assert M._older_than(page[:1], datetime(2026, 11, 5, 15, 30)) is False


def test_calendar_second_thursday_and_manual():
    assert M.second_thursday(2026, 11).isoformat() == "2026-11-12"
    assert M.second_thursday(2026, 12).isoformat() == "2026-12-10"
    manual = [{"date": "2026-11-19", "event": "수능", "source": "s"}, {"date": "2027-01-05", "event": "먼 일", "source": "s"}]
    ev = M.calendar_events("2026-11-06", manual, 14)
    assert [(e["date"], e["event"]) for e in ev] == [("2026-11-12", "옵션 만기"), ("2026-11-19", "수능")]
    assert any(e["event"] == "선물옵션 동시만기" for e in M.calendar_events("2026-12-01", [], 14))


def test_morning_since_spans_weekend():
    assert M.morning_since("2026-11-09", "2026-11-06") == datetime(2026, 11, 6, 15, 30)
    assert M.morning_since("2026-11-06", None) == datetime(2026, 11, 5, 15, 30)


def _day_rec():
    morning = {"overseas_asof": "2026-11-05", "overseas": {
        "^GSPC": {"close": 7353.73, "chg_pct": -4.36}, "^SOX": {"close": 9011.14, "chg_pct": -12.25},
        "^VIX": {"close": 28.18, "chg_pct": 69.7}, "USD/KRW": {"close": 1340.07, "chg_pct": -0.2}},
        "topics": {"반도체": 12}, "headlines": [{"topic": "반도체", "title": "반도체 급락"}],
        "calendar": [{"date": "2026-11-12", "event": "옵션 만기"}], "errors": []}
    close = {"kospi": M.index_flows([KOSPI_ROW]), "program": M.program_flows(PROG, "2026-11-06"),
             "topics": {"코스피": 30, "반도체": 20}, "headlines": [{"topic": "코스피", "title": "서킷브레이커"}],
             "dart": [{"corp_name": "가나", "report_nm": "유상증자결정"}]}
    return morning, close


def test_morning_summary_is_rule_based_text():
    morning, close = _day_rec()
    t = M.morning_summary("2026-11-06", morning, "2026-11-05", close)
    assert "밤사이 미국(11-05): S&P500 -4.4% · 필라델피아 반도체 -12.2% · VIX 28.18 · 원/달러 1,340" in t
    assert "외국인 -2.64조" in t and "프로그램 -1.48조" in t and "· [반도체] 반도체 급락" in t
    assert "11-12 옵션 만기" in t
    assert "조회 실패" in M.morning_summary("2026-11-06", {**morning, "errors": ["뉴스(HTTPError)"]}, None, None)


def test_notion_row_needs_close_and_uses_full_names():
    morning, close = _day_rec()
    assert M.notion_row("2026-11-06", {"morning": morning}) is None      # 장 마감 값이 없으면 행을 만들지 않는다
    r = M.notion_row("2026-11-06", {"morning": morning, "close": close})
    assert r["날짜"] == "11-06(금) 코스피(KOSPI) -6.02%" and r["일자"] == "2026-11-06"
    assert r["외국인 순매수(억원)"] == -26435 and r["프로그램 순매수(억원)"] == -14849     # 백만원 → 억원
    assert r["변동성 지수(VIX)"] == 28.18 and r["필라델피아 반도체지수(%)"] == -12.25
    assert "미국 나스닥(%)" not in r                                        # 값이 없으면 넣지 않는다
    assert r["주요사항 공시"].startswith("1건 — 가나 유상증자결정")
    assert "VIX" not in [k for k in r if k == "VIX"]                       # 줄임말 단독 속성 없음


def test_prev_trading_day_uses_exchange_calendar():
    days = ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"]
    assert M.prev_trading_day("2026-11-09", days) == "2026-11-06"           # 주말 건너뜀
    assert M.prev_trading_day("2026-11-10", days) == "2026-11-09"
    assert M.prev_trading_day("2026-11-04", days) is None


def test_notion_row_ignores_preliminary_flows():
    morning, close = _day_rec()
    prelim_only = {k: v for k, v in close.items() if k not in ("kospi", "program")}
    prelim_only["flows_prelim"] = {"kospi": close["kospi"], "program": close["program"]}
    assert M.notion_row("2026-11-06", {"morning": morning, "close": prelim_only}) is None   # 잠정치로 행을 만들지 않는다


def test_fill_final_flows_writes_prev_day_and_heals_recent_gaps(tmp_path, monkeypatch):
    """전 거래일엔 파일이 없어도 만들고, 그 전 날은 '일지 파일이 있는데 확정 수급이 빠진 날'만 다시 채운다."""
    import asyncio
    tds = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    monkeypatch.setattr(M, "_trading_days", lambda day: tds)
    calls = []

    async def fake(d):
        calls.append(d)
        return {"kospi": {**M.index_flows([KOSPI_ROW]), "지수": float(d[-2:])}, "kospi_nxt": None, "kosdaq": None,
                "program": None}
    monkeypatch.setattr(M, "fetch_flows", fake)
    monkeypatch.setattr(M, "_ks_window", lambda day: {"2026-11-04": 4.0, "2026-11-06": 9.0})   # 11-06 은 일부러 어긋나게
    M.save_section("2026-11-04", "close", {"news": [], "dart": []}, tmp_path)               # 확정 수급 빠짐 → 다시 채움
    M.save_section("2026-11-05", "close", {"kospi": {"지수": 1.0}}, tmp_path)              # 이미 있음 → 건드리지 않음
    ff = tmp_path / "flows.csv"
    prev, errs = asyncio.run(M.fill_final_flows("2026-11-09", datetime(2026, 11, 9, 8, 30), tmp_path, ff))
    assert prev == "2026-11-06" and sorted(calls) == ["2026-11-04", "2026-11-06"]
    assert errs == ["확정 수급 11-06 날짜 대조 bad:-33.33%"]                                   # 가드가 실제로 걸린다
    import market_flows as MF                                                                  # 연구용 이력에도 한 줄씩
    rows = MF.load_rows(ff)
    assert list(rows) == ["2026-11-04", "2026-11-06"] and rows["2026-11-04"]["check"] == "ok"
    assert M.load_day("2026-11-04", tmp_path)["close"]["news"] == []                         # 덧쓰기 — 뉴스는 그대로
    assert M.load_day("2026-11-04", tmp_path)["close"]["kospi"]["지수"] == 4.0
    assert M.load_day("2026-11-05", tmp_path)["close"]["kospi"] == {"지수": 1.0}
    assert not (tmp_path / "2026-11-03.json").exists()                                         # 일지 없던 날은 만들지 않음


def test_decide_task_runs_journal_before_notion_and_keeps_decide_exit_code():
    """Notion 단계가 그날 시장 일지 행을 넣으려면 장 마감 수집이 먼저 끝나야 한다. 실패해도 판단 결과 코드는 그대로."""
    txt = (_ROOT / "scripts" / "i3_decide.cmd").read_text(encoding="utf-8")
    i_rc, i_j, i_n = txt.index("set RC=%ERRORLEVEL%"), txt.index("market_journal.py --phase close"), txt.index("i3_notion.cmd")
    assert i_rc < i_j < i_n and txt.rstrip().endswith("exit /b %RC%")


def test_save_section_keeps_other_section(tmp_path):
    M.save_section("2026-11-06", "morning", {"a": 1}, tmp_path)
    M.save_section("2026-11-06", "close", {"b": 2}, tmp_path)
    M.save_section("2026-11-06", "close", {"b": 3}, tmp_path)
    rec = M.load_day("2026-11-06", tmp_path)
    assert rec["morning"] == {"a": 1} and rec["close"] == {"b": 3}
    assert M.prev_journal_day("2026-11-09", tmp_path) == "2026-11-06" and M.prev_journal_day("2026-11-06", tmp_path) is None
    assert M.notion_rows("2026-11-01", tmp_path) == []          # 장 마감 수급(kospi)이 없으면 Notion 행을 만들지 않는다
    morning, close = _day_rec()
    M.save_section("2026-11-05", "close", close, tmp_path)
    assert [r["일자"] for r in M.notion_rows("2026-11-01", tmp_path)] == ["2026-11-05"]
    assert M.notion_rows("2026-11-06", tmp_path) == []          # since 이전 날은 빼고
