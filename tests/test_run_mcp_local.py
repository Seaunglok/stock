"""MCP 런처 생존판정 회귀 — 2026-08-17 좀비 서버 장애 재현 방지.

장애: `is_running()` 이 `os.kill(pid, 0)` 을 썼다. Windows 의 os.kill 은 POSIX 와 달리
`OpenProcess(PROCESS_ALL_ACCESS)` 를 요구해서, 작업스케줄러(watchdog)가 띄운 서버를
호출자 토큰으로 열지 못하면 PermissionError → **살아있는데 '종료됨'** 으로 오판했다.
그 결과 stop 이 좀비를 안 죽여 포트가 잡힌 채 남고, start 는 중복 세트를 또 띄웠다.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("run_mcp_local", _ROOT / "run_mcp_local.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def rml():
    return _load()


@pytest.fixture
def dummy():
    """살아있는 자식 프로세스 — 판정 대상."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(0.8)
    yield p
    p.kill()
    p.wait(timeout=5)


# ─── 기본 생존 판정 ────────────────────────────────────────────────────────
def test_live_process_is_running(rml, dummy):
    assert rml.is_running(dummy.pid) is True


def test_dead_process_is_not_running(rml, dummy):
    dummy.kill()
    dummy.wait(timeout=5)
    time.sleep(0.3)
    assert rml.is_running(dummy.pid) is False


def test_bogus_pid_is_not_running(rml):
    assert rml.is_running(999_999_998) is False


def test_check_does_not_kill_the_process(rml, dummy):
    """생존을 '묻는' 함수가 프로세스를 죽이면 안 된다 —
    os.kill(pid,0) 은 Windows 에서 TerminateProcess 로 가는 경로라 이 보장이 없다."""
    for _ in range(3):
        rml.is_running(dummy.pid)
    assert dummy.poll() is None, "생존 조회가 대상 프로세스를 종료시켰다"


# ─── ★ 핵심: 접근 권한 없는 프로세스를 죽었다고 오판하지 않는다 ──────────────
@pytest.mark.skipif(sys.platform != "win32", reason="Windows 권한 모델 전용 회귀")
def test_inaccessible_process_still_reported_alive(rml):
    """다른 보안 컨텍스트(SYSTEM 등) 프로세스도 '살아있음'으로 봐야 한다.

    watchdog(작업스케줄러)이 띄운 MCP 서버가 정확히 이 경우였다.
    """
    psutil = pytest.importorskip("psutil")
    target = None
    for p in psutil.process_iter(["pid", "name", "username"]):
        if p.info["pid"] <= 4:
            continue
        try:
            user = (p.info.get("username") or "").upper()
        except Exception:
            continue
        if any(k in user for k in ("SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE")):
            target = p.info["pid"]
            break
    if target is None:
        pytest.skip("접근 불가 프로세스를 찾지 못함")

    def legacy(pid):                       # 구버전 판정(버그 재현)
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    assert psutil.pid_exists(target) is True
    assert rml.is_running(target) is True, "권한 부족을 '종료됨'으로 오판하면 좀비가 남는다"
    if legacy(target) is True:
        pytest.skip("이 환경에선 구버전도 통과 — 회귀 검증 불가")


# ─── PID 재사용 방어 ───────────────────────────────────────────────────────
def test_module_mismatch_rejected(rml):
    """PID 는 살아있지만 그 모듈이 아니면 False — taskkill /T 오발사 방지."""
    assert rml.is_running(os.getpid(), "src.mcp_servers.trend_mcp.server") is False


def test_module_match_accepted(rml, dummy):
    """커맨드라인에 마커가 있으면 True (더미는 -c 스크립트로 확인)."""
    assert rml.is_running(dummy.pid, "time.sleep") is True


def test_no_module_arg_checks_liveness_only(rml):
    assert rml.is_running(os.getpid()) is True


# ─── 프로세스 정보 조회 ────────────────────────────────────────────────────
def test_proc_info_returns_create_time_and_cmdline(rml, dummy):
    created, cmd = rml._proc_info(dummy.pid)
    assert created is not None and created > 0
    assert "time.sleep" in cmd


def test_proc_info_on_dead_pid(rml):
    created, cmd = rml._proc_info(999_999_998)
    assert created is None and cmd == ""
