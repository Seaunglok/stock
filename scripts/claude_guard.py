"""Claude Code PreToolUse 훅 — 주문 시간엔 매매·배치·서버에 손대지 않는다(백로그 ㉓, 2026-11-19).

CLAUDE.md 규칙 4 "주문 시간(08:30~09:20 · 15:50~16:00)엔 배치 재실행·MCP 재시작을 하지 않는다"를 글이 아니라 훅으로
잠근다. 원격 제어 세션(`ClaudeCliDaily`, 09:00 — 매매 시간대 한가운데)은 휴대폰에서 지시하니 시각을 놓치기 쉽다.
훅의 deny 는 권한 모드(기본·자동·우회)와 상관없이 막는다.

막는 것 — **평일 주문 시간에만**(휴장일도 평일이면 막는다, 보수적):
- 셸(Bash·PowerShell): 운용 배치·실전 스크립트(.py/.cmd) 실행 · MCP 서버 시작·중지 · 프로세스 종료 · 예약작업 변경 ·
  PC 재시작 · git 으로 작업 트리 바꾸기(checkout·reset·pull…)
- 파일 쓰기(Edit·Write·NotebookEdit): 프로젝트의 `scripts/` · `src/` · `data/` · `.env` · `run_mcp_local.py`

막지 않는 것: 읽기 도구(Read·Grep·Glob) · Notion·웹 · 시험(pytest) · 주문 시간 밖의 모든 것 · 프로젝트 밖 파일.
`.claude/` 도 막지 않는다 — 훅을 고치거나 끄는 길은 남겨 둔다(운용자 `/hooks`).

**사고 방지 울타리이지 보안 경계가 아니다** — 계정을 빼앗기면 새 스크립트를 쓰게 해 우회할 수 있다. 계정 보안은
로그인 수단의 2단계 인증이 맡는다. 훅이 스스로 깨지면(입력 이상·예외) 막지 않는다(fail-open — 세션이 멈추지 않게).

설정: `.claude/settings.json` hooks.PreToolUse(matcher `Bash|PowerShell|Edit|Write|NotebookEdit`) →
`.venv/Scripts/python.exe scripts/claude_guard.py`. 시험용 `--now 2026-11-20T08:55:00`.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, time as dtime, timedelta, timezone

KST = timezone(timedelta(hours=9))     # 한국은 일광절약시간이 없다 — tzdata 없이 고정 오프셋
WINDOWS = ((dtime(8, 30), dtime(9, 20)), (dtime(15, 50), dtime(16, 0)))
ROOT = "d:/kiwoom_rest_study/multi_agent_kiwoom/"

SHELL_TOOLS = {"Bash", "PowerShell"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}

_OPS = ("i3_live", "i3_decide", "i3_trade", "i3_notion", "i3_notion_sync", "i3_shadow", "aggr_shadow",
        "collect_i3_minutes", "market_journal", "market_journal_morning", "market_features", "market_flows",
        "market_flows_backfill", "kiwoom_net_check", "trend_watchdog", "run_mcp_local")
SHELL_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(" + "|".join(_OPS) + r")\.(py|cmd)\b", re.I), "운용 배치·실전 스크립트 실행"),
    (re.compile(r"\b(Stop-Process|spps|taskkill|pkill|killall)\b|(^|[;&|]\s*)kill\s", re.I), "프로세스 종료"),
    (re.compile(r"\b(Start|Stop|Register|Unregister|Enable|Disable|Set)-ScheduledTask\b|\bschtasks\b", re.I),
     "예약작업 변경"),
    (re.compile(r"\b(Restart-Computer|Stop-Computer|shutdown(\.exe)?)\b", re.I), "PC 재시작·종료"),
    (re.compile(r"\bgit\s+(checkout|switch|reset|pull|merge|rebase|stash|restore|revert|cherry-pick|am|apply)\b",
                re.I), "git 으로 작업 트리 바꾸기"),
)
WRITE_PREFIXES = ("scripts/", "src/", "data/")
WRITE_FILES = (".env", "run_mcp_local.py")


def in_order_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    return any(a <= t < b for a, b in WINDOWS)


def _rel(path: str) -> str | None:
    p = path.replace("\\", "/").lower()
    return p[len(ROOT):] if p.startswith(ROOT) else None


def decide(tool: str, tool_input: dict, now: datetime) -> str | None:
    """막을 이유(문장) 또는 None(통과)."""
    if not in_order_window(now):
        return None
    if tool in SHELL_TOOLS:
        cmd = str(tool_input.get("command") or "")
        for pat, what in SHELL_RULES:
            if pat.search(cmd):
                return what
        return None
    if tool in WRITE_TOOLS:
        rel = _rel(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
        if rel is not None and (rel.startswith(WRITE_PREFIXES) or rel in WRITE_FILES):
            return f"운용 코드·데이터·.env 쓰기({rel})"
    return None


def reason_text(what: str, now: datetime) -> str:
    return (f"⛔ 주문 시간({now:%H:%M}, 평일 08:30~09:20 · 15:50~16:00)이라 막았다 — {what}. CLAUDE.md 규칙 4: 이 시간엔 "
            f"배치 재실행·MCP 재시작·운용 코드 수정을 하지 않는다. 읽기(Read·Grep·로그)는 된다. 매매 단계는 시작할 때 "
            f".env 를 이미 읽었으니 지금 바꿔도 오늘 매매엔 안 듣는다 — 급하면 HTS·MTS 로 직접. 09:20(오후 16:00) 뒤에 다시.")


def main(argv: list[str]) -> int:
    now = datetime.now(KST).replace(tzinfo=None)
    if len(argv) == 2 and argv[0] == "--now":
        now = datetime.fromisoformat(argv[1])
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        what = decide(str(data.get("tool_name") or ""), data.get("tool_input") or {}, now)
    except Exception:
        return 0                                    # fail-open
    if what:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": reason_text(what, now)}}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
