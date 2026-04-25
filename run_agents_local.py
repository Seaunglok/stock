"""A2A 에이전트 로컬 기동 런처 (Docker 없이)
사용법:
  python run_agents_local.py start   # 모든 A2A 에이전트 기동
  python run_agents_local.py stop    # 모든 A2A 에이전트 종료
  python run_agents_local.py status  # 상태 확인
"""
import os
import sys
import subprocess
import json
from pathlib import Path

_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
PID_FILE = _TEMP / "agent_pids.json"
LOG_DIR = _TEMP / "mcp_logs"

AGENTS = [
    ("supervisor",     "src.a2a_agents.supervisor",     8000),
    ("data_collector", "src.a2a_agents.data_collector", 8001),
    ("analysis",       "src.a2a_agents.analysis",       8002),
    ("trading",        "src.a2a_agents.trading",        8003),
]

LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> dict:
    from dotenv import load_dotenv
    load_dotenv()
    return dict(os.environ)


def load_pids() -> dict:
    if PID_FILE.exists():
        return json.loads(PID_FILE.read_text())
    return {}


def save_pids(pids: dict):
    PID_FILE.write_text(json.dumps(pids))


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def start_agents():
    env = load_env()
    pids = load_pids()

    for name, module, port in AGENTS:
        pid = pids.get(name)
        if pid and is_running(pid):
            print(f"[SKIP] {name} 이미 실행 중 (PID={pid})")
            continue

        agent_env = dict(env)
        agent_env["AGENT_HOST"] = "localhost"
        agent_env["AGENT_PORT"] = str(port)

        log_path = LOG_DIR / f"agent_{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            env=agent_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent),
        )
        pids[name] = proc.pid
        print(f"[START] {name} (PID={proc.pid}) port={port} → {log_path}")

    save_pids(pids)

    import time
    print("\n5초 후 상태 확인...")
    time.sleep(5)
    check_status()


def stop_agents():
    pids = load_pids()
    for name, _, _ in AGENTS:
        pid = pids.get(name)
        if not pid:
            print(f"[SKIP] {name} - PID 없음")
            continue
        if is_running(pid):
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True)
                else:
                    os.kill(pid, 15)
                print(f"[STOP] {name} (PID={pid})")
            except Exception as e:
                print(f"[ERR]  {name}: {e}")
        else:
            print(f"[SKIP] {name} (PID={pid}) 이미 종료됨")
    PID_FILE.unlink(missing_ok=True)


def check_status():
    pids = load_pids()
    for name, _, port in AGENTS:
        pid = pids.get(name)
        if pid and is_running(pid):
            print(f"[UP]   {name} (PID={pid}) port={port}")
        elif pid:
            print(f"[DOWN] {name} (PID={pid}, 종료됨)")
        else:
            print(f"[DOWN] {name} (미시작)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        start_agents()
    elif cmd == "stop":
        stop_agents()
    elif cmd == "status":
        check_status()
    else:
        print(__doc__)
