"""키움 연결 점검 — 네트워크가 바뀌면 바로 (2026-11-12, 운용자 "좋은 생각이야").

왜
--
  11-09·11-12 두 번, 운용자 쪽 공인 IP 가 바뀌어 키움 REST 가 「8050: IP가 등록되지 않았습니다」로 막혔는데 둘 다
  15:50 판단 때 처음 알았다(11-12 는 15:20 인터넷 교체 → 여유 30분). 네트워크가 바뀔 때마다 키움을 한 번 조회해,
  막혔으면 **바로** 텔레그램 긴급 알림 + 새 공인 IP — 장중에 바뀌어도 판단 전에 등록할 시간이 생긴다.

언제 (예약작업 KiwoomNetCheck — scripts/register_kiwoom_net_check.ps1)
  ① Windows 「네트워크 연결됨」(Microsoft-Windows-NetworkProfile/Operational 이벤트 10000 — 11-12 15:20:53 에 찍힌 것)
  ② 로그온 1분 뒤(부팅 때 네트워크 이벤트는 로그온 전이라 놓친다) ③ 평일 15:30(판단 20분 전 안전망)

무엇
  공인 IP 조회 → 키움 REST **직접** 호출 1번(ka10081 KODEX200 일봉) — MCP 서버를 거치지 않는다(부팅 직후 MCP 가 없어도 되고,
  MCP 호출은 오류를 삼켜 빈 결과만 준다). 토큰이 살아 있어도 조회 단계에서 8050 이 오므로(11-12 실측) 토큰만 보지 않는다.
  주문과 무관.

알림
  막힘(8050)            ⛔ critical — 현재 공인 IP · 등록 경로 · 앱키 만료도 같은 문구였던 적(10-06) · 등록 뒤 할 일
  다른 실패(재시도 뒤)   ⛔ critical — 원인 문구 그대로
  같은 상태·같은 IP     COOLDOWN_MIN 안엔 다시 보내지 않는다(네트워크 이벤트는 몇 초 사이 여러 번 온다)
  복구(실패 → 정상)      ✅ 일반 — 15:50 이 지났으면 `scripts\\i3_decide.cmd` 재실행 안내
  IP 만 바뀌고 정상      일반 한 줄(새 IP 도 등록돼 있다는 기록) · 첫 실행 = 점검 시작 알림 · 변화 없음 = 조용히
상태 data/kiwoom_net/state.json · 로그 logs/kiwoom_net/check.log(cmd 래퍼).

    python scripts/kiwoom_net_check.py [--delay 20] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

STATE_FILE = _ROOT / "data" / "kiwoom_net" / "state.json"
IP_URLS = ("https://api.ipify.org", "https://checkip.amazonaws.com")
PROBE_CODE = "069500"
ATTEMPTS = 3                  # 네트워크가 막 붙은 직후엔 DNS·연결이 늦다 — 실패는 이만큼 다시 해 본 뒤에 판정
RETRY_GAP_S = 20.0
COOLDOWN_MIN = 30
DECIDE_AT = dtime(15, 50)
REGISTER_HINT = "키움 REST API 홈페이지 > API 사용신청 화면에서 IP 등록"


# ── 순수 함수 ────────────────────────────────────────────────────────────────
from kiwoom_read import classify  # noqa: E402,F401 — 판정은 키움 조회 모듈 하나에서(11-12 리팩터링)


def decide(prev: dict, status: str, detail: str, ip: str | None, now: datetime,
           cooldown_min: int = COOLDOWN_MIN) -> tuple[list[tuple[str, bool]], dict]:
    """이전 상태 + 이번 결과 → (보낼 알림 [(글, 긴급)], 새 상태). 같은 실패·같은 IP 는 cooldown 안에 한 번만."""
    ip_txt = ip or "조회 실패"
    stamp = now.isoformat(timespec="seconds")
    state = {**prev, "ip": ip or prev.get("ip"), "status": status, "detail": detail[:300], "checked_at": stamp}
    msgs: list[tuple[str, bool]] = []
    if status != "ok":
        key = f"{status}|{ip_txt}"
        last = prev.get("alerted_at")
        fresh = (prev.get("alerted_key") == key and last
                 and now - datetime.fromisoformat(last) < timedelta(minutes=cooldown_min))
        if not fresh:
            if status == "ip":
                msgs.append((f"⛔ [키움 점검] 키움 인증 실패 — 8050 IP 미등록. 현재 공인 IP <b>{ip_txt}</b> → {REGISTER_HINT}. "
                             f"(앱키가 만료돼도 같은 문구였던 적이 있다 10-06 — 등록 뒤에도 막히면 앱키 확인) "
                             f"등록하면 다음 점검이 복구를 알린다. 15:50 판단 전에 등록하면 그날 판단은 그대로 돈다.", True))
            else:
                msgs.append((f"⛔ [키움 점검] 키움 조회 실패(재시도 {ATTEMPTS}번 뒤) — {detail[:200]} · 공인 IP {ip_txt}", True))
            state.update(alerted_at=stamp, alerted_key=key)
        return msgs, state
    state.pop("alerted_key", None)
    if prev.get("status") in ("ip", "fail"):
        tail = (" · 오늘 15:50 판단이 막혔다면 `scripts\\i3_decide.cmd` 를 다시 돌려 메운다(분봉은 다음 날 15:50 전까지 복구 가능)"
                if now.weekday() < 5 and now.time() >= DECIDE_AT else "")
        msgs.append((f"✅ [키움 점검] 키움 연결 복구 — 공인 IP {ip_txt} 정상{tail}", False))
    elif not prev:
        msgs.append((f"✅ [키움 점검] 네트워크 변경 감시 시작 — 공인 IP {ip_txt} · 키움 정상", False))
    elif ip and prev.get("ip") and ip != prev.get("ip"):
        msgs.append((f"ℹ️ [키움 점검] 공인 IP 바뀜 {prev['ip']} → {ip} · 키움 정상(새 IP 도 등록돼 있다)", False))
    return msgs, state


def load_state(path: Path = STATE_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:  # noqa: BLE001 — 깨진 상태 파일은 첫 실행처럼(알림이 한 번 더 갈 뿐)
        return {}


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ── 바깥 ────────────────────────────────────────────────────────────────────
async def public_ip() -> str | None:
    import httpx
    for url in IP_URLS:
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(url)
                ip = r.text.strip()
                if r.status_code == 200 and ip.count(".") == 3 and len(ip) <= 15:
                    return ip
        except Exception:  # noqa: BLE001
            continue
    return None


async def probe_kiwoom(now: datetime) -> tuple[dict | None, str | None]:
    """키움 REST 직접 1번 — (응답, 예외 문구). 재시도는 check() 가 한다(네트워크가 자리 잡을 시간까지 넉넉히)."""
    import kiwoom_read as KR
    return await KR.raw_call(KR.API["daily"], {"stk_cd": PROBE_CODE, "base_dt": now.strftime("%Y%m%d"),
                                               "upd_stkpc_tp": "1"})


async def check(delay: float = 0.0, dry_run: bool = False, state_file: Path = STATE_FILE,
                sleep=asyncio.sleep, clock=datetime.now) -> dict:
    if delay:
        await sleep(delay)          # 네트워크 이벤트 직후 — 주소·DNS 가 자리 잡게
    status, detail, ip = "fail", "", None
    for k in range(ATTEMPTS):
        ip = await public_ip()
        status, detail = classify(*await probe_kiwoom(clock()))
        if status in ("ok", "ip"):  # 8050 은 다시 해도 같다 — 바로 판정
            break
        if k < ATTEMPTS - 1:
            await sleep(RETRY_GAP_S)
    prev = load_state(state_file)
    msgs, state = decide(prev, status, detail, ip, clock())
    print(json.dumps({"at": clock().isoformat(timespec="seconds"), "ip": ip, "status": status,
                      "detail": detail[:200], "alerts": [m for m, _ in msgs]}, ensure_ascii=False), flush=True)
    if not dry_run:
        save_state(state, state_file)
        if msgs:
            from ops_base import notify
            for text, critical in msgs:
                await notify(text, critical=critical)
    return {"status": status, "ip": ip, "msgs": msgs, "state": state}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=0.0, help="시작 전 기다릴 초(네트워크 이벤트 직후 20 권장)")
    ap.add_argument("--dry-run", action="store_true", help="알림·상태 저장 없이 판정만 출력")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    r = asyncio.run(check(args.delay, args.dry_run))
    return 0 if r["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
