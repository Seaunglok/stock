"""무소식 감시(㉑, 11-19) — 신호가 실제 HTTP 로 나가는지, 실패해도 매매 단계를 막지 않는지.

목 대신 진짜 경계: 로컬 HTTP 서버가 받은 경로로 확인한다(규칙 3 · test-real-boundary).
"""
from __future__ import annotations

import asyncio
import http.server
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import heartbeat as HB  # noqa: E402
import i3_live as LV  # noqa: E402


class _Srv:
    """요청 경로를 모으는 로컬 서버. status 로 응답 코드를 바꾼다."""

    def __init__(self, status: int = 200):
        self.paths: list[str] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.paths.append(self.path)
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.status = status
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/uuid-abc"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def srv(monkeypatch):
    s = _Srv()
    monkeypatch.setenv("HEARTBEAT_TRADE_URL", s.url)
    monkeypatch.delenv("HEARTBEAT_DECIDE_URL", raising=False)
    yield s
    s.close()


def test_success_and_fail_paths_reach_server(srv):
    assert HB.ping_now("trade") is True
    assert HB.ping_now("trade", fail=True) is True
    assert srv.paths == ["/uuid-abc", "/uuid-abc/fail"]


def test_no_url_sends_nothing(srv):
    assert HB.ping_now("decide") is False          # 판단 주소는 비어 있다
    assert HB.ping("decide") is None
    assert srv.paths == []


def test_server_error_and_unreachable_do_not_raise(monkeypatch):
    bad = _Srv(status=500)
    monkeypatch.setenv("HEARTBEAT_TRADE_URL", bad.url)
    try:
        assert HB.ping_now("trade", timeout=2) is False
        assert len(bad.paths) == HB.TRIES          # 다시 시도했다
    finally:
        bad.close()
    monkeypatch.setenv("HEARTBEAT_TRADE_URL", bad.url)   # 닫힌 포트
    assert HB.ping_now("trade", timeout=2) is False


def test_main_phase_pings_start_then_fail_on_exception(srv, monkeypatch):
    """i3_live._main 이 단계 시작에 신호, 예외면 /fail — 텔레그램 critical 은 그대로."""
    sent: list[tuple[str, bool]] = []

    async def fake_notify(msg, critical=False):
        sent.append((msg, critical))

    async def ok_phase(phase):
        return 0

    monkeypatch.setattr(LV, "_notify", fake_notify)
    monkeypatch.setattr(LV, "_run_phase", ok_phase)
    assert asyncio.run(LV._main("trade")) == 0
    assert srv.paths == ["/uuid-abc"]

    async def boom(phase):
        raise RuntimeError("일부러")

    monkeypatch.setattr(LV, "_run_phase", boom)
    assert asyncio.run(LV._main("trade")) == 1
    assert srv.paths == ["/uuid-abc", "/uuid-abc", "/uuid-abc/fail"]
    assert sent and sent[-1][1] is True and "예외" in sent[-1][0]


def test_status_and_flow_do_not_ping(srv, monkeypatch, tmp_path):
    monkeypatch.setattr(LV, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(LV, "load_state", lambda path=None: {})
    asyncio.run(LV._main("status"))
    assert srv.paths == []
