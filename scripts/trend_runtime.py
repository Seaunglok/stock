"""데몬 런타임 인프라 — 알림·상태·락·이벤트로그·매매일지 append.

**매매 판단이 전혀 없는 계층**이다. trend_follow.py(1300줄, 46함수)에서 분리한 이유:
주문 경로와 섞여 있으면 인프라를 손볼 때마다 실거래 코드를 건드리게 된다.
여기 있는 함수는 도메인 지식 없이 파일/네트워크만 다루므로 단독 테스트가 쉽다.

의존: trend_config(경로·토큰·logger) 만. 다른 trend_* 모듈을 import 하지 않는다(순환 방지).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from trend_config import (
    DATA_DIR, JOURNAL_FILE, LOCK_FILE, STATE_FILE,
    TELEGRAM_CHAT_ID, TELEGRAM_CRITICAL_CHAT_ID, TELEGRAM_TOKEN, logger,
)


# ─── 알림 ──────────────────────────────────────────────────────────────────
def _html_safe(msg: str) -> str:
    """의도한 <b>/</b> 외의 < > & 를 이스케이프 — 사유의 '<'(예: 가격비교) 가 HTML 파싱 깨뜨려
    텔레그램 400(can't parse entities) 되던 문제 방지."""
    return (msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
               .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"))


async def notify(msg: str, critical: bool = False) -> None:
    """텔레그램 알림. critical=True 면 TELEGRAM_CRITICAL_CHAT_ID 로 전송(미설정 시 기본 채팅).

    Critical 용도: 매도거부, 누적실패, 긴급정지 등 즉시대응 필요 알림.
    """
    tag = "[CRITICAL] " if critical else "[NOTIFY] "
    logger.info("%s%s", tag, msg[:200].replace("\n", " "))
    if not TELEGRAM_TOKEN:
        return
    chat = TELEGRAM_CRITICAL_CHAT_ID if critical else TELEGRAM_CHAT_ID
    if not chat:
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                             json={"chat_id": chat, "text": _html_safe(msg), "parse_mode": "HTML"})
            if r.status_code != 200:
                logger.warning("[TELEGRAM%s] 전송 실패 %s: %s",
                               " CRIT" if critical else "", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[TELEGRAM] %s", e)


# ─── 상태 영속화 ────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(key: str, content: Any) -> None:
    st = load_state()
    st[key] = content
    st["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def get_state(key: str, default=None) -> Any:
    return load_state().get(key, default)


# ─── 단일 인스턴스 락 ───────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
        except Exception:
            return True


def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text().strip() or "0")
        except Exception:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            logger.error("[LOCK] 이미 실행 중 (PID=%d)", old)
            return False
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except Exception:
        pass


# ─── 이벤트 로그 / 매매일지 ─────────────────────────────────────────────────
def log_event(event: str, payload: dict) -> None:
    day = DATA_DIR / datetime.now().strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    with (day / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                            "event": event, "payload": payload}, ensure_ascii=False) + "\n")


def journal_append(rec: dict) -> None:
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def journal_note(jid: str, psych: str = "", mistake: str = "", improve: str = "") -> None:
    """매매일지 항목에 심리/실수/개선 메모 추가 (대시보드/CLI)."""
    journal_append({"type": "note", "id": jid,
                    "psych": psych, "mistake": mistake, "improve": improve})
    print(f"매매일지 메모 추가: id={jid}")


def read_journal(date_prefix: str = "") -> list[dict]:
    """매매일지 레코드 로드. date_prefix 주면 그 날짜(ts 접두)만."""
    if not JOURNAL_FILE.exists():
        return []
    out = []
    for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not date_prefix or str(r.get("ts", "")).startswith(date_prefix):
            out.append(r)
    return out


def read_events(date: str) -> list[dict]:
    """그날 events.jsonl 레코드 로드(없으면 빈 리스트)."""
    f = DATA_DIR / date / "events.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
