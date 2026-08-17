"""추세추종 데몬 watchdog — MCP 서버 + 데몬 생존 보장 (자동 복구).

작업스케줄러가 평일 장중 N분마다 실행. 멱등(idempotent):
  - 필수 MCP 포트가 죽어 있으면 run_mcp_local.py 로 (분리)재기동
  - 데몬(daemon.lock PID)이 죽어 있으면 분리 기동으로 재시작
  - 둘 다 살아있으면 아무것도 안 함

데몬이 보유 중 죽으면 손절·트레일 관리가 멈춰 실포지션이 방치되는 것을 막는다.
실행:  python scripts/trend_watchdog.py   (TREND_UNIVERSE 미지정 시 largecap)
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts/ → trend_lock

from trend_lock import describe, owner_alive, read_lock   # noqa: E402  (stdlib+psutil 만 의존)

# Windows 콘솔/리다이렉트 기본 cp949 → 이모지(⚠️·→) print 시 UnicodeEncodeError 로
# watchdog 자체가 죽어 자동복구가 멈추는 것을 방지. utf-8·errors=replace 로 강제.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOCK_FILE = ROOT / "data" / "trend_follow" / "daemon.lock"
HEARTBEAT_FILE = ROOT / "data" / "trend_follow" / "daemon.heartbeat"
# trend_config.HEARTBEAT_STALE_SEC 과 **같은 값이어야 한다**(= INTERVAL × 10).
# 여기서 import 하지 않는 이유: watchdog 은 설정/도메인이 깨져도 떠야 하므로 stdlib+psutil 만
# 의존한다(trend_config 는 signals→closing_bet→pykrx 까지 끌고 온다).
# 대신 tests/test_trend_follow_helpers.py 가 두 값의 일치를 검증한다.
HEARTBEAT_STALE_SEC = 600   # heartbeat 10분 이상 정체 → hung 판정(정상 screen 은 <2~3분, 60초마다 갱신)
LOG_DIR = ROOT / "logs" / "trend_follow"
LOG_DIR.mkdir(parents=True, exist_ok=True)
WD_LOG = LOG_DIR / "watchdog.log"
DAEMON_OUT = LOG_DIR / "daemon_stdout.log"

# 기본값은 trend_config.UNIVERSE_MODE 와 반드시 일치시킬 것 — watchdog 은 .env 를 읽지 않고
# 재기동 데몬에 env 를 주입하므로, 두 기본값이 갈리면 수동 기동과 자동 기동이 다른 유니버스로 돈다.
UNIVERSE = os.environ.get("TREND_UNIVERSE", "largecap")
# 데몬이 실제로 쓰는 필수 MCP 포트(주문/시세/정보/투자자/포트폴리오)
ESSENTIAL_PORTS = [8030, 8031, 8032, 8033, 8034]


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        print(line)
    except Exception:
        # reconfigure 실패 환경 대비 — print 실패해도 watchdog 은 죽지 않게
        try:
            print(line.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass
    try:
        with open(WD_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def port_up(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def daemon_alive() -> bool:
    """락 소유자가 **우리 데몬으로** 살아있는지. PID 재사용이면 False (2026-08-11 장애)."""
    return owner_alive(read_lock(LOCK_FILE))


def heartbeat_stale() -> bool:
    """heartbeat 가 HEARTBEAT_STALE_SEC 이상 정체면 True(hung 의심).

    파일 없음/파싱 실패는 False(오탐 방지 — heartbeat 미도입 구버전/기동 직후 대비)."""
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(HEARTBEAT_FILE.read_text().strip())
        return (datetime.now() - ts).total_seconds() > HEARTBEAT_STALE_SEC
    except Exception:
        return False


def kill_daemon() -> None:
    """hung 데몬 강제 종료 — **소유권 확인 후에만**.

    2026-08-11: PID 재사용된 vmware-authd.exe 를 `taskkill /F /T` 로 죽이려 했다.
    /T 는 프로세스 트리째 죽이므로, 확인 없는 kill 은 시스템을 망가뜨릴 수 있다.
    """
    rec = read_lock(LOCK_FILE)
    if not rec:
        return
    if not owner_alive(rec):
        # 우리 데몬이 아니거나 이미 죽음 → 죽일 대상 없음. 고착된 락만 치운다.
        log(f"[DAEMON] 락 소유자가 데몬 아님/이미 종료 — kill 생략, 락 정리 ({describe(rec)})")
        try:
            LOCK_FILE.unlink()
        except Exception:
            pass
        return
    pid = int(rec["pid"])
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15)
        log(f"[DAEMON] hung 데몬 PID={pid} 강제 종료")
    except Exception as e:
        log(f"[DAEMON] kill 예외: {e}")


def _detached_kwargs() -> dict:
    """자식이 watchdog 종료/콘솔 신호와 무관하게 독립 생존하도록 분리 기동."""
    kw: dict = {"cwd": str(ROOT)}
    if sys.platform == "win32":
        kw["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kw["start_new_session"] = True
    return kw


def start_servers() -> None:
    log("[MCP] 필수 포트 다운 → stop(정리) 후 start (중복 세트 누적 방지)")
    try:
        # 먼저 추적 중인(죽었을 수 있는) PID 정리 → 중복 서버 세트 누적 방지
        subprocess.run([sys.executable, "run_mcp_local.py", "stop"],
                       cwd=str(ROOT), timeout=60)
        subprocess.run([sys.executable, "run_mcp_local.py", "start"],
                       cwd=str(ROOT), timeout=120)
    except Exception as e:
        log(f"[MCP] start 예외: {e}")
    time.sleep(8)  # 포트 바인딩 대기


def start_daemon() -> None:
    log(f"[DAEMON] 다운 → 재기동 (모드={UNIVERSE}, detached)")
    env = dict(os.environ)
    env["TREND_UNIVERSE"] = UNIVERSE
    try:
        logf = open(DAEMON_OUT, "a", encoding="utf-8")
        subprocess.Popen([sys.executable, "scripts/trend_follow.py", "--daemon"],
                         env=env, stdout=logf, stderr=subprocess.STDOUT,
                         **_detached_kwargs())
    except Exception as e:
        log(f"[DAEMON] 재기동 예외: {e}")


def main() -> None:
    # 주말은 KRX 휴장 → 아무것도 하지 않음(작업스케줄러가 매일 돌아도 무해).
    if datetime.now().weekday() >= 5:
        return

    down = [p for p in ESSENTIAL_PORTS if not port_up(p)]
    if down:
        log(f"[MCP] down={down}")
        start_servers()
        down2 = [p for p in ESSENTIAL_PORTS if not port_up(p)]
        if down2:
            log(f"[MCP] ⚠️ 재기동 후에도 down={down2}")

    if not daemon_alive():
        start_daemon()
    elif heartbeat_stale():
        # PID 는 살아있으나 heartbeat 정체 → 이벤트루프 hang(2026-07-02 screen hang 사례) → 강제 재기동
        log(f"[DAEMON] ⚠️ heartbeat 정체(>{HEARTBEAT_STALE_SEC}s) — hung 판정 → 재기동")
        kill_daemon()
        time.sleep(2)
        start_daemon()
    # 정상일 땐 로그를 남기지 않음(파일 비대화 방지). 이상 시에만 위에서 기록.


if __name__ == "__main__":
    main()
