"""데몬 단일 인스턴스 락 — **PID 재사용에 안전한** 소유권 판정.

2026-08-11 장애 배경: 락 파일에 PID 숫자만 적고 `psutil.pid_exists(pid)` 로만 생존을 봤다.
08-10 22:51 데몬(PID 6536)이 죽고 락이 남았는데, 08-11 08:20 **vmware-authd.exe 가 PID 6536 을
재할당**받았다. 그 뒤 기동하는 데몬마다 "이미 실행 중" 으로 거부돼 거래일 내내 데몬이 못 떴다
(watchdog 은 5분마다 재시도 → 무한 루프). 게다가 watchdog 의 hung 처리 로직이 그 PID 를
`taskkill /F /T` 로 죽이려 했다 — 남의 프로세스를 트리째 죽일 뻔했다.

해법: PID 만으로 판단하지 않고 **프로세스 기동시각(create_time)** 을 같이 적어 대조한다.
PID 는 재사용돼도 기동시각까지 같을 수는 없다. 구형식(숫자만) 락은 커맨드라인으로 폴백 판정.

stdlib + psutil(선택) 만 의존 — watchdog 이 무겁게 import 하지 않도록 trend_config 를 안 쓴다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

MARKER = "trend_follow.py"      # 커맨드라인 판별용(구형식 락 폴백)
_CREATE_TIME_TOL = 1.0          # 기동시각 허용 오차(초) — 플랫폼별 반올림 대비


def _create_time(pid: int) -> float | None:
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:
        return None


def write_lock(path: Path, pid: int | None = None) -> None:
    """락 획득 기록 — PID + 기동시각 + 마커. 기동시각을 못 구해도 PID 는 남긴다."""
    pid = pid or os.getpid()
    rec = {"pid": pid, "created": _create_time(pid), "marker": MARKER,
           "ts": datetime.now().isoformat(timespec="seconds")}
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def read_lock(path: Path) -> dict | None:
    """락 파일 파싱. 구형식(숫자만)도 읽는다 → {"pid": n, "created": None, "legacy": True}."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        rec = json.loads(raw)
        if isinstance(rec, dict) and rec.get("pid"):
            return rec
    except Exception:
        pass
    try:                                    # 구형식: PID 숫자만
        return {"pid": int(raw), "created": None, "legacy": True}
    except Exception:
        return None


def owner_alive(rec: dict | None) -> bool:
    """락 소유자가 **정말 우리 데몬으로** 살아있는지. PID 재사용이면 False.

    판정 불가(psutil 없음)일 때만 구동작(pid_exists)으로 폴백한다 — 그 경우에도
    최소한 락이 영구 고착되지는 않게 호출부가 heartbeat 로 2차 판정한다.
    """
    if not rec:
        return False
    pid = int(rec.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        import psutil
    except Exception:                       # psutil 없음 → 구동작(보수적으로 살아있다고 봄)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return True
    if not psutil.pid_exists(pid):
        return False
    created = rec.get("created")
    if created:
        # 핵심 방어: PID 가 같아도 기동시각이 다르면 **재사용된 남의 프로세스**다.
        actual = _create_time(pid)
        return actual is not None and abs(actual - float(created)) <= _CREATE_TIME_TOL
    # 구형식 락 → 커맨드라인으로 판별. 접근 거부(다른 계정 프로세스)면 우리 것이 아니다.
    try:
        return MARKER in " ".join(psutil.Process(pid).cmdline() or [])
    except Exception:
        return False


def owned_by_me(rec: dict | None) -> bool:
    """락이 현재 프로세스 소유인지 — release 시 남의 락을 지우지 않기 위한 확인."""
    if not rec:
        return False
    if int(rec.get("pid") or 0) != os.getpid():
        return False
    created = rec.get("created")
    if not created:
        return True                         # 구형식 → PID 일치로 충분
    actual = _create_time(os.getpid())
    return actual is None or abs(actual - float(created)) <= _CREATE_TIME_TOL


def describe(rec: dict | None) -> str:
    """로그용 요약 — 누가 락을 쥐고 있는지 사람이 읽을 수 있게."""
    if not rec:
        return "(없음)"
    pid = rec.get("pid")
    who = ""
    try:
        import psutil
        p = psutil.Process(int(pid))
        who = f" name={p.name()}"
    except Exception:
        pass
    return f"PID={pid}{who} 기록시각={rec.get('ts', '?')}{' (구형식)' if rec.get('legacy') else ''}"
