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
from trend_lock import describe, owned_by_me, owner_alive, read_lock, write_lock


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
STATE_BAK = STATE_FILE.with_suffix(STATE_FILE.suffix + ".bak")
STATE_TMP = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")


class StateCorrupted(RuntimeError):
    """state.json 과 .bak 이 모두 읽히지 않음 — 보유 포지션을 알 수 없는 상태.

    **빈 dict 로 대체하면 안 된다.** 데몬이 '보유 0' 으로 착각하면 실제 보유분에 손절·트레일이
    영영 안 걸리고, 다음 save_state 가 그 빈 dict 를 덮어써 손실이 확정된다.
    예외를 올려 phase 를 중단시키고 watchdog 재기동/운영자 개입으로 넘긴다.
    """


def _read_json(path) -> dict | None:
    """JSON 파일 읽기 — 없거나 깨졌으면 None(구분 불필요, 호출자가 폴백 판단)."""
    try:
        if not path.exists():
            return None
        txt = path.read_text(encoding="utf-8")
        if not txt.strip():
            return None                     # 잘린 쓰기의 전형 — 빈 파일
        d = json.loads(txt)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def load_state() -> dict:
    """상태 로드. 본파일이 깨졌으면 .bak 폴백, 둘 다 실패면 StateCorrupted.

    2026-08-17: 과거엔 파싱 실패 시 조용히 {} 를 돌려줬다. watchdog 이 hung 데몬을
    `taskkill /F /T` 로 죽이는데 save_state 는 청산 루프 안에서 매 매도마다 호출되므로,
    강제종료와 쓰기가 겹치면 파일이 잘린다 → 보유 0 착각 → 무방비 방치. 원자적 쓰기(save_state)
    로 발생 자체를 막고, 그래도 깨졌다면 여기서 소리내어 실패한다.
    """
    d = _read_json(STATE_FILE)
    if d is not None:
        return d
    if not STATE_FILE.exists() and not STATE_BAK.exists():
        return {}                           # 최초 기동 — 정상
    d = _read_json(STATE_BAK)
    if d is not None:
        logger.error("[STATE] %s 손상 — .bak 으로 복구(직전 저장 시점)", STATE_FILE.name)
        return d
    raise StateCorrupted(f"{STATE_FILE} 와 {STATE_BAK.name} 모두 읽기 실패 — 보유 포지션 불명. "
                         "HTS 로 실보유분 확인 후 state.json 복구 필요")


def save_state(key: str, content: Any) -> None:
    """상태 저장 — tmp 쓰기 → 원자적 치환. 손상된 state 위에는 덮어쓰지 않는다.

    load_state() 로 시작하므로 본파일·.bak 이 모두 깨졌으면 StateCorrupted 가 올라가
    **손상 파일을 덮어쓰지 않고** 멈춘다(과거엔 {} 를 덮어써 손실을 확정시켰다).
    """
    st = load_state()
    st[key] = content
    st["last_updated"] = datetime.now().isoformat()
    payload = json.dumps(st, ensure_ascii=False, indent=2)
    STATE_TMP.write_text(payload, encoding="utf-8")
    if STATE_FILE.exists():
        try:
            os.replace(STATE_FILE, STATE_BAK)   # 직전 정상본 보존
        except Exception as e:
            logger.warning("[STATE] .bak 갱신 실패(무시): %s", e)
    os.replace(STATE_TMP, STATE_FILE)           # 동일 볼륨 원자적 치환


def get_state(key: str, default=None) -> Any:
    return load_state().get(key, default)


# ─── 단일 인스턴스 락 ───────────────────────────────────────────────────────
def acquire_lock() -> bool:
    """단일 인스턴스 락 획득. 소유권은 PID **+ 기동시각**으로 판정(PID 재사용 방어).

    2026-08-11: PID 만 보다가 죽은 데몬의 PID(6536)를 vmware-authd 가 재할당받아,
    거래일 내내 "이미 실행 중" 으로 기동이 막혔다. 상세 scripts/trend_lock.py.
    """
    rec = read_lock(LOCK_FILE)
    if rec and int(rec.get("pid") or 0) != os.getpid():
        if owner_alive(rec):
            logger.error("[LOCK] 이미 실행 중 — %s", describe(rec))
            return False
        logger.warning("[LOCK] 죽은 락 정리 후 인수 — %s", describe(rec))
    write_lock(LOCK_FILE)
    return True


def release_lock() -> None:
    """내 락일 때만 해제 — 남이 인수한 락을 지워 이중 기동을 만들지 않는다."""
    try:
        if owned_by_me(read_lock(LOCK_FILE)):
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
