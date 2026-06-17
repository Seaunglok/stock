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

LOCK_FILE = ROOT / "data" / "trend_follow" / "daemon.lock"
LOG_DIR = ROOT / "logs" / "trend_follow"
LOG_DIR.mkdir(parents=True, exist_ok=True)
WD_LOG = LOG_DIR / "watchdog.log"
DAEMON_OUT = LOG_DIR / "daemon_stdout.log"

UNIVERSE = os.environ.get("TREND_UNIVERSE", "largecap")
# 데몬이 실제로 쓰는 필수 MCP 포트(주문/시세/정보/투자자/포트폴리오)
ESSENTIAL_PORTS = [8030, 8031, 8032, 8033, 8034]


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
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


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return True


def daemon_alive() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text().strip() or "0")
    except Exception:
        return False
    return bool(pid) and _pid_alive(pid)


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
    log(f"[MCP] 필수 포트 다운 → stop(정리) 후 start (중복 세트 누적 방지)")
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
    # 정상일 땐 로그를 남기지 않음(파일 비대화 방지). 이상 시에만 위에서 기록.


if __name__ == "__main__":
    main()
