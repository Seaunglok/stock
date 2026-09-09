"""watchdog 포트 대기 회귀 — 2026-09-09.

배경: `start_servers()` 가 고정 `time.sleep(8)` 뒤 포트를 확인했다. trading-domain(8030)
이 8초 안에 바인딩되지 않는 날이 있어 **09-04 부터 매일** `⚠️ 재기동 후에도 down=[8030]`
이 찍혔지만, 실제로는 이후 정상 연결됐다(09-09 09:22 tool_count=11).

오탐 로그는 그냥 시끄러운 게 아니다 — 진짜 장애가 났을 때 같은 문구가 찍히므로
**구분이 불가능해진다**. 매일 뜨는 경고는 아무도 안 본다.

고정 대기 → 뜰 때까지 폴링. 빠르면 즉시 끝나고, 느리면 상한까지 기다린다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import trend_watchdog as W  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """폴링 간격을 0 으로 — 테스트가 실제로 기다리지 않게."""
    monkeypatch.setattr(W, "MCP_BIND_POLL", 0)


def _ports_up_after(n_calls: int):
    """처음 n_calls 번은 down, 그 뒤로는 up 인 가짜 port_up."""
    state = {"n": 0}

    def fake(port, *a, **k):
        state["n"] += 1
        return state["n"] > n_calls
    return fake, state


# ─── 즉시 뜨면 기다리지 않는다 ───────────────────────────────────────────────
def test_returns_immediately_when_all_up(monkeypatch):
    monkeypatch.setattr(W, "port_up", lambda *a, **k: True)
    down, took = W.wait_ports([8030, 8031])
    assert down == []
    assert took < 1, f"이미 떠 있는데 {took:.1f}s 기다렸다"


# ─── ★ 8초를 넘겨 뜨는 경우 — 09-04~09 매일 나던 오탐 ───────────────────────
def test_waits_for_slow_port_instead_of_false_alarm(monkeypatch):
    """★ 고정 8초였다면 오탐이 났을 상황에서 정상으로 판정해야 한다."""
    fake, _ = _ports_up_after(3)          # 3번째 확인까지 down
    monkeypatch.setattr(W, "port_up", fake)
    down, _took = W.wait_ports([8030])
    assert down == [], "느리게 뜨는 포트를 down 으로 오판했다"


# ─── 진짜 안 뜨면 상한에서 포기하고 보고한다 ─────────────────────────────────
def test_gives_up_at_timeout_and_reports(monkeypatch):
    monkeypatch.setattr(W, "port_up", lambda *a, **k: False)
    down, took = W.wait_ports([8030, 8034], timeout=0)
    assert down == [8030, 8034], "안 뜬 포트를 보고하지 않는다"
    assert took >= 0


def test_reports_only_the_ports_still_down(monkeypatch):
    """일부만 안 뜨면 그것만 보고 — 전부 나열하면 원인 추적이 어렵다."""
    monkeypatch.setattr(W, "port_up", lambda p, *a, **k: p != 8030)
    down, _ = W.wait_ports([8030, 8031, 8032], timeout=0)
    assert down == [8030]


# ─── 상한이 watchdog 주기 안에 끝나는가 ─────────────────────────────────────
def test_timeout_fits_inside_watchdog_interval():
    """★ watchdog 은 5분마다 돈다. stop+start+대기가 그 안에 끝나야 다음 회차와 겹치지 않는다.

    겹치면 서버 세트가 중복 기동되고, 그게 08:50 전멸 같은 사고의 재료가 된다.
    """
    assert W.MCP_BIND_TIMEOUT + 60 + 120 < 5 * 60, (
        f"stop(60)+start(120)+대기({W.MCP_BIND_TIMEOUT}) 가 5분을 넘는다")
    assert W.MCP_BIND_TIMEOUT > 8, "고정 8초보다 짧으면 고친 의미가 없다"


def test_poll_interval_is_sane():
    """폴링 간격은 **소스에서** 읽는다 — 위 fixture 가 런타임 값을 0 으로 덮기 때문."""
    src = (_ROOT / "scripts" / "trend_watchdog.py").read_text(encoding="utf-8")
    line = next(l for l in src.split(chr(10)) if l.startswith("MCP_BIND_POLL"))
    val = int(line.split("=")[1].split("#")[0].strip())
    assert 0 < val <= 5, f"폴링 간격 {val}s"


# ─── 고정 대기가 되살아나지 않도록 ──────────────────────────────────────────
def test_fixed_sleep_is_gone():
    """★ `time.sleep(8)` 이 돌아오면 오탐도 같이 돌아온다."""
    src = (_ROOT / "scripts" / "trend_watchdog.py").read_text(encoding="utf-8")
    body = src[src.index("def start_servers("):src.index("def start_daemon(")]
    assert "time.sleep(" not in body, "start_servers 에 고정 대기가 다시 들어갔다"
    assert "wait_ports(" in body


def test_start_servers_returns_down_list():
    """main 이 결과를 쓸 수 있어야 한다 — 반환이 없으면 중복 확인이 되살아난다."""
    import inspect
    assert "-> list" in inspect.getsource(W.start_servers).split(chr(10))[0]
