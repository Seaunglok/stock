"""주문 시간 훅(㉓, 11-19) — 막을 것은 막고, 읽기·시간 밖은 통과. 실제 stdin→stdout 경계(서브프로세스)까지 지난다."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import claude_guard as G  # noqa: E402

MON_0855 = datetime(2026, 11, 23, 8, 55)     # 월요일 매매 시간대
MON_1555 = datetime(2026, 11, 23, 15, 55)
MON_0925 = datetime(2026, 11, 23, 9, 25)     # 시간대 뒤
MON_1600 = datetime(2026, 11, 23, 16, 0)     # 오후 끝(16:00 부터 허용)
SAT_0855 = datetime(2026, 11, 21, 8, 55)
P = "D:\\kiwoom_rest_study\\multi_agent_kiwoom\\"


@pytest.mark.parametrize("cmd", [
    r"cmd /c scripts\i3_decide.cmd",
    ".venv\\Scripts\\python.exe scripts/i3_live.py --phase trade",
    "python run_mcp_local.py stop",
    "Get-Process python | Stop-Process -Force",
    "taskkill /F /PID 1234",
    "Start-ScheduledTask -TaskName I3Trade",
    "schtasks /Run /TN I3Decide",
    "git pull origin master",
    "git checkout -- scripts/i3_core.py",
    "Restart-Computer",
])
def test_blocks_ops_in_order_window(cmd):
    assert G.decide("PowerShell", {"command": cmd}, MON_0855)
    assert G.decide("Bash", {"command": cmd}, MON_1555)


@pytest.mark.parametrize("cmd", [
    "Get-Content logs\\i3\\i3_live.log -Tail 20",
    "git status --short",
    "git log -3 --oneline",
    "python -m pytest tests/ -q",
    "Get-ScheduledTask -TaskName I3Trade | Get-ScheduledTaskInfo",
    "Select-String -Path logs/market_journal/x.log -Pattern ok",
])
def test_allows_reads_in_order_window(cmd):
    assert G.decide("PowerShell", {"command": cmd}, MON_0855) is None


def test_write_tools_only_project_ops_paths():
    for f in ("scripts\\i3_core.py", "src\\mcp_servers\\x.py", "data\\i3\\state.json", ".env", "run_mcp_local.py"):
        assert G.decide("Edit", {"file_path": P + f}, MON_0855), f
    assert G.decide("Write", {"file_path": P + "docs\\a.md"}, MON_0855) is None
    assert G.decide("Edit", {"file_path": P + ".claude\\settings.json"}, MON_0855) is None   # 훅을 고칠 길은 남긴다
    assert G.decide("Write", {"file_path": "C:\\Users\\x\\AppData\\Local\\Temp\\a.py"}, MON_0855) is None
    assert G.decide("Read", {"file_path": P + ".env"}, MON_0855) is None   # 읽기 도구는 이 훅의 일이 아니다


@pytest.mark.parametrize("now", [MON_0925, MON_1600, SAT_0855, datetime(2026, 11, 23, 8, 29)])
def test_outside_window_everything_passes(now):
    assert G.decide("PowerShell", {"command": "python run_mcp_local.py stop"}, now) is None
    assert G.decide("Edit", {"file_path": P + "scripts\\i3_live.py"}, now) is None


def _hook(payload, now: str | None, raw: bytes | None = None):
    args = [sys.executable, str(_ROOT / "scripts" / "claude_guard.py")] + (["--now", now] if now else [])
    data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return subprocess.run(args, input=data, capture_output=True, timeout=30)


def test_subprocess_deny_json_and_passthrough():
    r = _hook({"tool_name": "PowerShell", "tool_input": {"command": "python run_mcp_local.py stop"}},
              "2026-11-23T08:55:00")
    assert r.returncode == 0
    out = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"
    assert "주문 시간" in out["permissionDecisionReason"]

    r = _hook({"tool_name": "PowerShell", "tool_input": {"command": "python run_mcp_local.py stop"}},
              "2026-11-23T10:00:00")
    assert r.returncode == 0 and r.stdout == b""


def test_subprocess_fail_open_on_garbage():
    r = _hook(None, "2026-11-23T08:55:00", raw=b"\xff not json")
    assert r.returncode == 0 and r.stdout == b""
