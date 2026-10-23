"""I3 → Notion 동기화 보조(i3_notion_sync) — 행 계산·평균단가 손익·결과 판정, 그리고 실제 기록 파일을 지나는 prep."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_notion_sync as N  # noqa: E402

FEE = N.FEE_BPS / 1e4


def _fill(day, side, code, qty, px, **kw):
    return {"date": day, "side": side, "code": code, "qty": qty, "order_type": "지정가" if side == "buy" else "시장가",
            "limit": kw.get("limit"), "ref_price": px, "fill_qty": qty if px else None, "fill_price": px,
            "slippage_bp": kw.get("bp"), "parsed": px is not None}


def test_trade_rows_average_cost_realized_pnl():
    fills = [_fill("2026-10-23", "buy", "069500", 10, 100.0, limit=101),
             _fill("2026-10-27", "buy", "069500", 10, 110.0),
             _fill("2026-11-02", "sell", "069500", 5, 120.0, bp=-2.5)]
    plans = {"2026-11-02": {"w": 0.5, "reason": "예산 축소"}}
    rows, warns = N.trade_rows(fills, "2026-10-01", plans)
    assert warns == [] and [r["매매구분"] for r in rows] == ["매수", "매수", "매도"]
    sell = rows[-1]
    avg = 105.0 * (1 + FEE)
    assert sell["실현손익"] == round(120 * 5 * (1 - FEE) - avg * 5)
    assert sell["수익률(%)"] == round((120 * (1 - FEE) / avg - 1) * 100, 2)
    assert sell["매수일자"] == "2026-10-23" and sell["보유기간(일)"] == 10
    assert sell["매매이유"] == "🛡️ 방어형 ETF 자동매매(I3) 매도 — 목표 KODEX200 50% (예산 축소) · 슬리피지 -2.5bp"
    assert rows[0]["매매이유"] == "🛡️ 방어형 ETF 자동매매(I3) 매수 — 지정가 101" and rows[0]["종목명"] == "KODEX 200(069500)"


def test_trade_rows_window_keeps_cost_from_older_fills():
    """창 밖(오래된) 매수도 평균단가에 들어간다 — 창 안 매도만 행이 된다."""
    fills = [_fill("2026-09-01", "buy", "488770", 4, 100.0), _fill("2026-10-20", "sell", "488770", 4, 101.0)]
    rows, _ = N.trade_rows(fills, "2026-10-10", {})
    assert len(rows) == 1 and rows[0]["매매구분"] == "매도"
    assert rows[0]["실현손익"] == round(101 * 4 * (1 - FEE) - 100 * (1 + FEE) * 4)


def test_unparsed_fill_is_warning_not_row():
    """체결가를 못 읽으면 추정가로 장부를 쓰지 않는다."""
    rows, warns = N.trade_rows([_fill("2026-10-23", "buy", "488770", 34, None)], "2026-10-01", {})
    assert rows == [] and "체결가 미확인" in warns[0]


def test_daily_rows_index_returns_flow_and_trade():
    ev = [
        {"ts": "2026-10-22T15:50:20", "event": "decide", "payload": {
            "date": "2026-10-22", "nav": 3647503, "engine_holding": False, "exposure": 1.0, "w": 0.0, "trade": True,
            "reason": "첫 판단", "close": {"069500": 86525.0}}},
        {"ts": "2026-10-23T09:06:00", "event": "trade", "payload": {
            "date": "2026-10-23", "dry_run": False, "results": [["buy", "488770", 34, "ok"]],
            "fills": [_fill("2026-10-23", "buy", "488770", 34, 105950.0, bp=3.2)]}},
        {"ts": "2026-10-23T15:50:20", "event": "decide", "payload": {
            "date": "2026-10-23", "nav": 3650000, "engine_holding": False, "exposure": 1.0, "w": 0.0, "trade": False,
            "reason": "변화 없음", "close": {"069500": 87390.0},
            "flow": {"amount": -100000, "how": "auto-withdrawal", "resid": -100000}}},
    ]
    navs = [["2026-10-22", 1000.0], ["2026-10-23", 1010.0]]
    rows = N.daily_rows(ev, navs, {"2026-10-23": "1위 TSMOM +0.30%"}, "2026-10-01")
    d1, d2 = rows
    assert d1["날짜"] == "2026-10-22 (목)" and d1["판단"] == "내일 매매" and d1["엔진"] == "이탈"
    assert d1["누적(%)"] == 0.0 and d1["일간(%)"] == 0.0 and "KODEX200 일간(%)" in d1 and d1["KODEX200 일간(%)"] is None
    assert d2["일간(%)"] == 1.0 and d2["누적(%)"] == 1.0
    assert d2["KODEX200 일간(%)"] == round((87390 / 86525 - 1) * 100, 2)
    assert d2["매매"] == "매수 KODEX 머니마켓액티브 34주 @105,950(+3.2bp)"
    assert d2["입출금"] == "출금(자동) -100,000원" and d2["리그"] == "1위 TSMOM +0.30%"


def test_daily_rows_skip_and_abort_and_dry_run():
    ev = [{"ts": "2026-10-24T15:50:00", "event": "decide_skip", "payload": {"reason": "오늘 일봉 없음(휴장·미갱신)"}},
          {"ts": "2026-10-27T15:50:00", "event": "decide_abort", "payload": {"reason": "KOSPI 종가 최대 차이 0.9%"}},
          {"ts": "2026-10-27T09:06:00", "event": "trade", "payload": {"date": "2026-10-27", "dry_run": True,
                                                                         "note": "모의 — 주문 미전송"}}]
    rows = N.daily_rows(ev, [], {}, "2026-10-01")
    assert rows[0]["판단"] == "판단 건너뜀" and rows[0]["사유"].startswith("오늘 일봉 없음")
    assert rows[1]["판단"] == "판단 중단" and "0.9%" in rows[1]["특이사항"] and rows[1]["매매"] == "🧪 모의 — 주문 미전송"


def test_league_text_counts_late_members_from_the_common_start():
    """★ 10-23 결함 재현 — 출발 다음 날 추가된 멤버(첫 기록이 10-23)도 공통 출발 자산 대비로 잰다.
    열마다 첫 값을 쓰면 T6c 의 첫날 −0.11% 가 0% 가 되어 챔피언 위로 올라갔다(13위 → 17위로 잘못 표시)."""
    rows = [{"date": "2026-10-22", "live_nav": "100", "i3_nav": "100", "tsmom_nav": "100", "t6c_nav": ""},
            {"date": "2026-10-23", "live_nav": "99.97", "i3_nav": "99.89", "tsmom_nav": "102", "t6c_nav": "99.89"}]
    names = {"i3": N.TRACK, "tsmom": N.DISPLAY["TSMOM"], "t6c": N.DISPLAY["T6c"]}
    assert (N.league_text(rows, "2026-10-23", names)
            == "1위 시계열 모멘텀(TSMOM) +2.00% · 방어형 ETF 자동매매(I3) 2위/3 · 실계좌 -0.03%")


def test_league_text_ties_below_display_precision():
    """1원도 안 되는 차이(한미반반 0.57원)는 순위를 가르지 않는다 — 표시(0.01%p)가 같으면 같은 순위."""
    rows = [{"date": "2026-10-22", "live_nav": "3647503", "i3_nav": "3647503", "한미반반_nav": "3647503"},
            {"date": "2026-10-23", "live_nav": "3646361", "i3_nav": "3643361", "한미반반_nav": "3643361.5685"}]
    txt = N.league_text(rows, "2026-10-23", {"i3": N.TRACK, "한미반반": "한미반반"})
    assert txt.startswith("공동 1위 2개 -0.11%") and "방어형 ETF 자동매매(I3) 1위/2" in txt


def test_league_text_ranks_from_the_common_start():
    rows = [{"date": "2026-10-22", "live_nav": "100", "i3_nav": "100", "tsmom_nav": "100", "저베타_nav": ""},
            {"date": "2026-10-23", "live_nav": "101", "i3_nav": "101", "tsmom_nav": "102", "저베타_nav": "100"},
            {"date": "2026-10-24", "live_nav": "102", "i3_nav": "102", "tsmom_nav": "101", "저베타_nav": "105"}]
    names = {"i3": N.TRACK, "tsmom": N.DISPLAY["TSMOM"], "저베타": "저베타"}
    assert (N.league_text(rows, "2026-10-23", names)
            == "1위 시계열 모멘텀(TSMOM) +2.00% · 방어형 ETF 자동매매(I3) 2위/3 · 실계좌 +1.00%")
    assert N.league_text(rows, "2026-10-24", names).startswith("1위 저베타 +5.00% · 방어형 ETF 자동매매(I3) 2위/3")
    assert N.league_text(rows, "2026-10-25", names) is None
    assert N.league_text(rows, "2026-10-22", names) == "공동 1위 2개 +0.00% · 방어형 ETF 자동매매(I3) 1위/2 · 실계좌 +0.00%"


def test_notion_names_have_no_bare_abbreviation():
    """운용자(10-22): Notion 에선 줄임말을 「풀네임(줄임말)」로. 영문이 들어간 리그 멤버 이름은 전부 풀네임이 있어야 하고,
    그 풀네임은 끝에 (원래 이름)을 단다 — 새 멤버를 등록하면서 빠뜨리면 여기서 걸린다."""
    import re
    import i3_shadow as S
    for m in S.MEMBERS:
        if re.search(r"[A-Za-z]", m.name):
            assert m.name in N.DISPLAY, f"{m.name}: Notion 표시 풀네임 없음 — DISPLAY 에 추가"
            assert N.DISPLAY[m.name].endswith(f"({m.name})"), N.DISPLAY[m.name]
    assert N.DISPLAY[S.CHAMPION] == N.TRACK and N.MARK.endswith(N.TRACK)


def test_task_file_queries_the_same_mark_as_the_code():
    """★ 작업지시서의 조회 키 == 코드가 쓰는 앞머리. 어긋나면 에이전트가 기존 행을 못 찾아 **매일 중복 행**을 넣는다."""
    txt = (_ROOT / "scripts" / "i3_notion_task.md").read_text(encoding="utf-8")
    assert f"LIKE '{N.MARK}%'" in txt and f"`{N.MARK} YYYY년 M월`" in txt
    assert "`운용 자산`" in txt and "I3 자산" not in txt


def test_month_rows_return_uses_previous_month_end():
    navs = [["2026-10-30", 100.0], ["2026-11-02", 101.0], ["2026-11-30", 103.0]]
    trades = [{"매매구분": "매도", "매도일자": "2026-11-02", "총체결금액": 500, "실현손익": 20, "매매비용": 1},
              {"매매구분": "매수", "매수일자": "2026-11-03", "총체결금액": 400, "매매비용": 1}]
    (m,) = N.month_rows([], trades, navs, ["2026-11"])
    assert m["월"] == "🛡️ 방어형 ETF 자동매매(I3) 2026년 11월 (💰 실거래)" and m["월 수익률(%)"] == 3.0
    assert (m["총 매수 금액"], m["총 매도 금액"], m["총 실현손익"], m["총 매매 비용"]) == (400, 500, 20, 2)


@pytest.mark.parametrize("log,ok", [("[i3_notion prep] ...\n", False),
                                    ("결과: 일일 1 추가 · 매매 0 · 결산 갱신\n", True),
                                    ("결과: 일일 1 추가\n결과: ❌ Notion 인증 만료\n", False)])
def test_judge(log, ok):
    assert N.judge(log)[0] is ok


def test_prep_reads_real_writers(tmp_path):
    """실제 writer(i3_live.log_event·save_state, i3_shadow.append_history)가 쓴 파일을 prep 이 읽는다."""
    import i3_live as LV
    import i3_shadow as S
    ev, st = tmp_path / "events.jsonl", tmp_path / "state.json"
    LV.log_event("decide", {"date": "2026-10-22", "nav": 3647503, "engine_holding": False, "exposure": 1.0,
                            "w": 0.0, "trade": True, "reason": "첫 판단", "close": {"069500": 86525.0}}, ev)
    LV.save_state({"navs": [["2026-10-22", 3647503.0]]}, st)
    row = {"date": "2026-10-22", "live_nav": 3647503}
    row.update({f"{S._slug(m.name)}_nav": 3647503 for m in S.MEMBERS})
    S.append_history(row, tmp_path / "shadow_history.csv")
    (tmp_path / "fills.jsonl").write_text(json.dumps(_fill("2026-10-23", "buy", "488770", 34, 105950.0)) + "\n",
                                          encoding="utf-8")
    out = tmp_path / "out.json"
    p = N.prep(datetime(2026, 10, 23, 16, 30), data_dir=tmp_path, out=out)
    assert json.loads(out.read_text(encoding="utf-8")) == p
    assert p["daily"][0]["일자"] == "2026-10-22" and p["daily"][0]["리그"].endswith("· 실계좌 +0.00%")
    assert p["trades"][0]["체결수량"] == 34 and p["months"][0]["key"] == "2026-10"
    assert "결과:" not in N.prep_summary(p)
