"""주문 수락/재전송 회귀 — 2026-08-17.

두 가지를 잠근다.

① `_order_accepted` — success:true 라도 return_code!=0(8005 등)이면 거부로 봐야 하는 유령주문
   게이트. 실주문의 성패를 가르는 단일 판정인데 테스트가 0개였다.

② **재전송 금지** — 과거 `_place(retries=1)` 은 타임아웃 시 같은 시장가 주문을 다시 보냈다.
   브로커가 이미 접수했는데 응답만 늦은 경우 그대로 이중 체결이다(멱등키 없음). 매도는
   `_sell_with_retry` 가 겹쳐 최대 4회까지 나갈 수 있었다. 거부(접수 안 됨 확실)와
   불명(접수 여부 모름)을 구분해, 불명일 땐 재전송하지 않고 잔고로 대조한다.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import trend_kiwoom_io as io  # noqa: E402


# ─── _order_accepted: 유령주문 게이트 ──────────────────────────────────────
@pytest.mark.parametrize("resp", [
    {"success": True, "data": {"return_code": 0}},
    {"success": True, "data": {"return_code": "0"}},
    {"success": True, "data": {}},                       # rc 부재 → 통과(구 응답 호환)
    {"return_code": 0},                                  # data 래핑 없음
])
def test_accepted(resp):
    ok, _ = io._order_accepted(resp)
    assert ok is True


@pytest.mark.parametrize("resp,frag", [
    ({"success": True, "data": {"return_code": 8005, "return_msg": "토큰만료"}}, "8005"),
    ({"success": True, "data": {"return_code": "20", "return_msg": "505217 장종료"}}, "20"),
    ({"success": False, "error": "타임아웃"}, "타임아웃"),
])
def test_rejected(resp, frag):
    """★ success:true + rc!=0 을 통과시키면 유령 포지션이 생긴다."""
    ok, why = io._order_accepted(resp)
    assert ok is False and frag in why


@pytest.mark.parametrize("resp", [None, "문자열", 42, []])
def test_malformed_is_rejected(resp):
    assert io._order_accepted(resp)[0] is False


# ─── _is_unknown: 거부 vs 불명 구분 ────────────────────────────────────────
def test_unknown_flagged():
    assert io._is_unknown({"success": False, "unknown": True}) is True


@pytest.mark.parametrize("resp", [
    {"success": False, "error": "rc=8005"},              # 명시적 거부 — 재시도 안전
    {"success": True, "data": {"return_code": 0}},
    {}, None, "x",
])
def test_not_unknown(resp):
    assert io._is_unknown(resp) is False


# ─── _place: 1회 전송 + 불명 표시 ──────────────────────────────────────────
class _MCP:
    """call_tool 호출 횟수를 세는 스텁."""
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, 0

    async def call_tool(self, tool, args):
        self.calls += 1
        if self.behavior == "hang":
            await asyncio.sleep(5)                       # timeout 유발
        if self.behavior == "raise":
            raise ConnectionError("소켓 끊김")
        return {"success": True, "data": {"return_code": 0, "cntr_pric": "70000"}}


def test_place_sends_once_on_success():
    m = _MCP("ok")
    resp = asyncio.run(io._place(m, "buy", "005930", 10))
    assert m.calls == 1 and io._order_accepted(resp)[0] is True


def test_place_does_not_resend_on_timeout():
    """★ 핵심 회귀: 타임아웃에 같은 시장가 주문을 다시 보내면 이중 체결이다."""
    m = _MCP("hang")
    resp = asyncio.run(io._place(m, "buy", "005930", 10, timeout=0.05))
    assert m.calls == 1, "타임아웃 후 재전송했다 — 중복체결 경로"
    assert io._is_unknown(resp) is True
    assert io._order_accepted(resp)[0] is False


def test_place_does_not_resend_on_exception():
    m = _MCP("raise")
    resp = asyncio.run(io._place(m, "sell", "005930", 10))
    assert m.calls == 1 and io._is_unknown(resp) is True


def test_place_has_no_retries_parameter():
    """retries 인자가 되살아나면 호출부가 무심코 재전송을 켤 수 있다."""
    import inspect
    assert "retries" not in inspect.signature(io._place).parameters


def test_place_uses_market_order():
    m = _MCP("ok")
    captured = {}

    async def spy(tool, args):
        captured.update({"tool": tool, **args})
        return {"success": True, "data": {"return_code": 0}}
    m.call_tool = spy
    asyncio.run(io._place(m, "sell", "000660", 3))
    assert captured["tool"] == "place_sell_order"
    assert captured["order_type"] == "03" and captured["quantity"] == 3
