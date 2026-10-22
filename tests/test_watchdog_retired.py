"""추세추종 종료 후 watchdog — MCP 만 지키고 데몬은 재기동하지 않는다 (2026-10-22)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import trend_watchdog as WD  # noqa: E402


class _Thu:
    @staticmethod
    def now():
        return datetime(2026, 10, 22, 10, 0)


@pytest.fixture
def wd(monkeypatch):
    monkeypatch.setattr(WD, "datetime", _Thu)
    calls = {"servers": 0}
    monkeypatch.setattr(WD, "daemon_alive", lambda: False)
    monkeypatch.setattr(WD, "start_servers", lambda: calls.__setitem__("servers", calls["servers"] + 1))
    return calls


def test_retired_watchdog_never_restarts_daemon(wd, monkeypatch):
    """★ off 면 데몬이 죽어 있어도 재기동하지 않는다 — 부르면 실패하게 해 일부러 확인."""
    monkeypatch.setattr(WD, "MANAGE_DAEMON", False)
    monkeypatch.setattr(WD, "port_up", lambda p: True)

    def boom():
        raise AssertionError("종료된 추세추종 데몬을 재기동했다")
    monkeypatch.setattr(WD, "start_daemon", boom)
    WD.main()


def test_retired_watchdog_still_restarts_mcp(wd, monkeypatch):
    """I3 가 MCP 를 쓴다 — 포트가 죽어 있으면 여전히 살린다."""
    monkeypatch.setattr(WD, "MANAGE_DAEMON", False)
    monkeypatch.setattr(WD, "port_up", lambda p: p != 8030)
    monkeypatch.setattr(WD, "recent_boot_sec", lambda: -1)
    monkeypatch.setattr(WD, "start_daemon", lambda: (_ for _ in ()).throw(AssertionError("데몬 재기동")))
    WD.main()
    assert wd["servers"] == 1


def test_default_still_manages_daemon(wd, monkeypatch):
    """스위치 기본값은 on — 환경변수 없이 돌리면 구 동작(데몬 재기동) 그대로."""
    monkeypatch.setattr(WD, "MANAGE_DAEMON", True)
    monkeypatch.setattr(WD, "port_up", lambda p: True)
    started = []
    monkeypatch.setattr(WD, "start_daemon", lambda: started.append(1))
    WD.main()
    assert started == [1]


def test_task_wrapper_turns_daemon_management_off():
    """★ 실제 예약 작업이 부르는 cmd 에 off 가 들어 있어야 한다 — 코드만 바꾸면 아무 일도 안 일어난다."""
    txt = (_ROOT / "scripts" / "trend_watchdog.cmd").read_text(encoding="ascii", errors="replace")
    assert "set TREND_WATCHDOG_DAEMON=off" in txt
