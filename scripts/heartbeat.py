"""무소식 감시(백로그 ㉑, 2026-11-19) — 매매·판단 단계가 돌 때마다 PC 밖 감시 서비스에 '살아 있음' 신호.

PC 가 아예 안 켜지거나 예약작업이 안 돌면 텔레그램엔 아무것도 오지 않는다(무소식이 유일한 신호였다). 판단을 못 한
날은 다음 날 아침 「매매 없음 — 대기 판단 없음. 정상」으로까지 보인다. 신호가 정한 시각까지 안 오면 감시 서비스
(Healthchecks.io)가 휴대폰으로 알린다 — PC 밖에서 울리는 유일한 경보다.

- 보내는 것: .env 의 고유 주소로 GET 한 번(본문 없음). 계좌·금액·종목은 보내지 않는다. 주소는 비밀처럼 다룬다(로그에 안 남김).
  `HEARTBEAT_TRADE_URL`(매매, 평일 08:50 — 09:10 까지 없으면 경보) · `HEARTBEAT_DECIDE_URL`(판단, 평일 15:50 — 16:20).
  주소가 없으면 아무것도 안 한다(시험·설정 전).
- 단계 **시작** 때 성공 신호(= PC 켜짐 · 예약작업 실행 · 파이썬·.env 정상). 단계가 예외로 끝나면 `/fail`(텔레그램과 별개 경로).
  단계 안의 판단 중단·매수 건너뜀은 지금처럼 텔레그램 critical 이 맡는다.
- 매매를 막지 않는다: 시작 신호는 별도 스레드(주문보다 먼저 떠나지만 기다리지 않음) · 제한 시간 · 예외는 로그만.

수동 시험: `python scripts/heartbeat.py trade` (또는 decide) — 신호 1번, 결과만 출력(주소는 출력 안 함).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import urllib.request

ENV = {"trade": "HEARTBEAT_TRADE_URL", "decide": "HEARTBEAT_DECIDE_URL"}
TIMEOUT = 10.0
TRIES = 2

log = logging.getLogger("i3")


def url_for(phase: str, fail: bool = False) -> str | None:
    name = ENV.get(phase)
    base = (os.getenv(name) or "").strip() if name else ""
    if not base:
        return None
    return base.rstrip("/") + ("/fail" if fail else "")


def ping_now(phase: str, fail: bool = False, timeout: float = TIMEOUT) -> bool:
    """신호 1번(최대 TRIES 번 시도). 성공 True · 주소 없음·실패 False — 예외는 밖으로 내지 않는다."""
    url = url_for(phase, fail)
    if not url:
        return False
    for attempt in range(1, TRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "heartbeat"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if 200 <= r.status < 300:
                    return True
                log.warning("[heartbeat] %s 신호 응답 %s (%d/%d)", phase, r.status, attempt, TRIES)
        except Exception as e:  # 감시가 매매를 막으면 안 된다
            log.warning("[heartbeat] %s 신호 실패 (%d/%d): %s", phase, attempt, TRIES, type(e).__name__)
    return False


def ping(phase: str, fail: bool = False) -> threading.Thread | None:
    """기다리지 않는 신호 — 스레드를 돌려준다(끝에서 join). 주소가 없으면 None."""
    if not url_for(phase, fail):
        return None
    t = threading.Thread(target=ping_now, args=(phase, fail), daemon=True, name=f"heartbeat-{phase}")
    t.start()
    return t


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 1 or argv[0] not in ENV:
        print("사용법: python scripts/heartbeat.py trade|decide")
        return 2
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    phase = argv[0]
    if not url_for(phase):
        print(f"{ENV[phase]} 가 .env 에 없다 — 신호 안 보냄")
        return 1
    ok = ping_now(phase)
    print(f"{phase} 신호 {'성공' if ok else '실패'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
