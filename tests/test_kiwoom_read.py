"""키움 조회 한 곳(kiwoom_read) — MCP 서버가 보내던 그대로 요청하고, 실패 원인을 버리지 않는다(11-12 리팩터링 1번)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kiwoom_read as KR  # noqa: E402

REAL_8050 = {"return_msg": "인증에 실패했습니다[8050:IP가 등록되지 않았습니다. 키움 REST API 홈페이지 > API 사용신청 "
                           "화면에서 IP를 등록해주세요.]", "return_code": 3}


@pytest.fixture
def fake_kiwoom(monkeypatch):
    """raw_call 을 바꿔 요청을 기록하고 정해 둔 응답을 차례로 돌려준다 — 쉬는 시간은 기록만."""
    calls, slept, answers = [], [], []

    async def raw(api_id, params):
        calls.append((api_id, dict(params)))
        return answers.pop(0) if answers else ({"return_code": 0}, None)

    async def sleep(s):
        slept.append(s)
    monkeypatch.setattr(KR, "raw_call", raw)
    monkeypatch.setattr(KR.asyncio, "sleep", sleep)
    KR._last["t"] = 0.0
    return calls, slept, answers


def run(c):
    return asyncio.run(c)


def test_requests_are_what_the_mcp_server_sent(fake_kiwoom):
    """★ 요청 = MCP market/trading 서버가 보내던 API·인자(market_domain.get_daily_chart 등). 11-12 실데이터 16건 대조 일치."""
    calls, _, answers = fake_kiwoom
    answers += [({"return_code": 0, "stk_dt_pole_chart_qry": []}, None),
                ({"return_code": 0, "inds_dt_pole_qry": []}, None),
                ({"return_code": 0, "cur_prc": "-84240"}, None),
                ({"return_code": 0, "ord_alowa": "000000045577"}, None),
                ({"return_code": 0, "stk_min_pole_chart_qry": []}, None)]
    run(KR.daily_bars("069500", "20261112"))
    run(KR.daily_bars("KOSPI", "20261112"))
    px, _ = run(KR.current_price("069500"))
    cash, _ = run(KR.orderable_amount("488770", 107200.0))
    run(KR.minute_rows("114800"))
    assert calls == [("ka10081", {"stk_cd": "069500", "base_dt": "20261112", "upd_stkpc_tp": "1"}),
                     ("ka20006", {"inds_cd": "001", "base_dt": "20261112"}),
                     ("ka10001", {"stk_cd": "069500"}),
                     ("kt00010", {"stk_cd": "488770", "trde_tp": "2", "uv": "107200"}),
                     ("ka10080", {"stk_cd": "114800", "tic_scope": "1", "upd_stkpc_tp": "1"})]
    assert px == 84240.0 and cash == 45577.0


def test_daily_parsing_scale_and_150_limit(fake_kiwoom):
    _, _, answers = fake_kiwoom
    rows = [{"dt": f"2026{m:02d}{d:02d}", "cur_prc": "534273", "open_pric": "538594", "high_pric": "545884",
             "low_pric": "529305"} for m in (6, 7, 8, 9, 10, 11) for d in range(1, 29)]
    answers.append(({"return_code": 0, "inds_dt_pole_qry": rows}, None))
    bars, r = run(KR.daily_bars("KOSPI", "20261112"))
    assert r.ok and len(bars) == KR.DAILY_LIMIT == 150                      # MCP 서버와 같이 최신 150개
    assert bars["2026-06-01"] == {"open": 5385.94, "close": 5342.73, "high": 5458.84, "low": 5293.05}
    assert KR.parse_daily([{"dt": "2026111", "cur_prc": "1"}, {"dt": "20261112", "cur_prc": "0"}]) == {}


def test_8050_is_named_not_swallowed_and_not_retried(fake_kiwoom):
    """★ 일부러 깨뜨린다 — 11-12 실측 8050 원응답: 빈 dict 가 아니라 'ip' + 원인. 다시 해도 같으니 한 번만."""
    calls, slept, answers = fake_kiwoom
    answers.append((REAL_8050, None))
    bars, r = run(KR.daily_bars("069500", "20261112"))
    assert bars == {} and r.status == "ip" and "8050" in r.why() and "공인 IP 등록" in r.why() and len(calls) == 1
    answers.append((None, "KiwoomAPIError: Token acquisition failed (rc=3): 인증에 실패했습니다[8050:IP]"))
    cash, r2 = run(KR.orderable_amount("488770", 107200))
    assert cash is None and r2.status == "ip"                                # 토큰 단계 8050 도


def test_transient_failure_is_retried_then_reported(fake_kiwoom):
    calls, slept, answers = fake_kiwoom
    answers += [(None, "ConnectError: x"), ({"return_code": 0, "cur_prc": "100"}, None)]
    px, r = run(KR.current_price("069500"))
    assert px == 100.0 and r.ok and len(calls) == 2 and KR.RETRY_GAP_S in slept
    answers += [(None, "ConnectError: y")] * (1 + KR.RETRIES)
    px2, r2 = run(KR.current_price("069500"))
    assert px2 is None and r2.status == "fail" and "ConnectError" in r2.why()


def test_orderable_without_field_is_none_not_zero(fake_kiwoom):
    _, _, answers = fake_kiwoom
    answers.append(({"return_code": 0, "return_msg": "정상"}, None))
    cash, r = run(KR.orderable_amount("488770", 107200))
    assert cash is None and r.status == "fail" and "ord_alowa" in r.why()
    assert KR.won(106950.0) == "106950" and KR.won(None) is None


def test_live_market_and_broker_keep_the_cause(monkeypatch):
    """★ i3_live 실제 연결 객체 — 조회가 막히면 빈 값 + errors[code] 에 원인(판단 중단·매수 건너뜀 알림에 붙는다)."""
    import i3_live as LV

    async def blocked(*a, **k):
        return ({}, KR.Result(REAL_8050, "ip", REAL_8050["return_msg"]))

    async def blocked_val(*a, **k):
        return (None, KR.Result(REAL_8050, "ip", REAL_8050["return_msg"]))
    monkeypatch.setattr(KR, "daily_bars", blocked)
    monkeypatch.setattr(KR, "current_price", blocked_val)
    monkeypatch.setattr(KR, "orderable_amount", blocked_val)
    m, b = LV.KiwoomMarket(), LV.KiwoomBroker()
    assert run(m.recent("069500")) == {} and "8050" in m.errors["069500"]
    assert run(b.price("069500")) is None and run(b.orderable("069500", 1000)) is None and "8050" in b.errors["069500"]
    assert "8050" in LV._cause(m, "069500", "KOSPI") and LV._cause(object(), "069500") == ""


def test_decide_abort_reason_carries_kiwoom_cause(tmp_path):
    """★ 판단 중단 사유에 키움 원인이 붙는다 — 11-12 엔 '응답이 비었다'만 남아 원인을 MCP 를 직접 불러 찾았다."""
    import i3_live as LV
    import test_i3_live as T

    class Blocked(T.FakeMarket):
        def __init__(self, days, today):
            super().__init__(days, today)
            self.errors = {}

        async def recent(self, code):
            self.errors[code] = "8050 IP 미등록(키움 REST API 사용신청에서 공인 IP 등록) — 인증에 실패했습니다[8050]"
            return {}
    days = T._days()
    notes = T.Notes()
    paths = (tmp_path / "state.json", tmp_path / "events.jsonl")
    r = run(LV.phase_decide(Blocked(days, days[-1]), T.FakeBroker(), notes,
                            datetime.fromisoformat(days[-1] + "T15:50:00"), *paths))
    assert "8050 IP 미등록" in r["abort"] and "키움:" in r["abort"]
    assert notes.msgs[0][0] is True and "8050" in notes.msgs[0][1]


def test_minute_collection_reports_kiwoom_failure(monkeypatch, tmp_path):
    import collect_i3_minutes as M

    async def blocked(code):
        return [], KR.Result(REAL_8050, "ip", REAL_8050["return_msg"])
    monkeypatch.setattr(KR, "minute_rows", blocked)
    monkeypatch.setattr(M, "OUT_DIR", tmp_path)
    rep = run(M.collect(datetime(2026, 11, 12, 15, 50)))
    assert set(rep) == set(M.CODES) and all("8050" in v["error"] for v in rep.values())
