"""MCP 서버 로컬 기동 런처 (Docker 없이)
사용법:
  python run_mcp_local.py start   # 모든 MCP 서버 기동
  python run_mcp_local.py stop    # 모든 MCP 서버 종료
  python run_mcp_local.py status  # 상태 확인
"""
import os
import sys
import subprocess
import json
from pathlib import Path

_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
PID_FILE = _TEMP / "mcp_pids.json"
LOG_DIR = _TEMP / "mcp_logs"

SERVERS = [
    ("tavily",       "src.mcp_servers.tavily_search_mcp.server"),
    ("naver_news",   "src.mcp_servers.naver_news_mcp.server"),
    ("stock",        "src.mcp_servers.stock_analysis_mcp.server"),
    ("financial",    "src.mcp_servers.financial_analysis_mcp.server"),
    ("macro",        "src.mcp_servers.macroeconomic_analysis_mcp.server"),
    ("kiwoom_mkt",   "src.mcp_servers.kiwoom_mcp.domains.market_domain"),
    ("kiwoom_info",  "src.mcp_servers.kiwoom_mcp.domains.info_domain"),
    ("kiwoom_trade", "src.mcp_servers.kiwoom_mcp.domains.trading_domain"),
    ("kiwoom_inv",   "src.mcp_servers.kiwoom_mcp.domains.investor_domain"),
    ("kiwoom_port",  "src.mcp_servers.kiwoom_mcp.domains.portfolio_domain"),
]


LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> dict:
    """dotenv로 환경변수를 로드해 현재 env에 병합한 dict를 반환"""
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


def start_servers():
    env = load_env()
    pids = load_pids()

    for name, module in SERVERS:
        pid = pids.get(name)
        if pid and is_running(pid):
            print(f"[SKIP] {name} 이미 실행 중 (PID={pid})")
            continue

        log_path = LOG_DIR / f"mcp_{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent),
        )
        pids[name] = proc.pid
        print(f"[START] {name} (PID={proc.pid}) → {log_path}")

    save_pids(pids)

    import time
    print("\n3초 후 상태 확인...")
    time.sleep(3)
    check_status()


def stop_servers():
    pids = load_pids()
    for name, _ in SERVERS:
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
    for name, _ in SERVERS:
        pid = pids.get(name)
        if pid and is_running(pid):
            print(f"[UP]   {name} (PID={pid})")
        elif pid:
            print(f"[DOWN] {name} (PID={pid}, 종료됨)")
        else:
            print(f"[DOWN] {name} (미시작)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        start_servers()
    elif cmd == "stop":
        stop_servers()
    elif cmd == "status":
        check_status()
    else:
        print(__doc__)
