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
    ("closing_bet",  "src.mcp_servers.closing_bet_mcp.server"),
    ("trend",        "src.mcp_servers.trend_mcp.server"),
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


def _proc_info(pid: int):
    """(create_time, cmdline) — 조회 불가면 (None, "")."""
    try:
        import psutil
        p = psutil.Process(pid)
        try:
            cmd = " ".join(p.cmdline() or [])
        except Exception:          # 권한 부족해도 존재/기동시각은 대개 읽힌다
            cmd = ""
        return p.create_time(), cmd
    except Exception:
        return None, ""


def is_running(pid: int, module: str = "") -> bool:
    """PID 생존 여부.

    ⚠️ `os.kill(pid, 0)` 을 쓰면 안 된다 — Windows 의 os.kill 은 POSIX 와 달리
    `OpenProcess(PROCESS_ALL_ACCESS)` 를 요구한다. 작업스케줄러(watchdog)가 띄운 서버는
    호출자 토큰으로 그 권한을 못 얻어 PermissionError → **살아있는데 '종료됨'으로 오판**했다.
    그 결과 stop 이 좀비를 안 죽이고(포트 점유 잔존), start 는 중복 세트를 또 띄웠다.
    psutil 은 가벼운 질의(PROCESS_QUERY_LIMITED_INFORMATION)라 이 문제가 없다.

    module 을 주면 커맨드라인까지 대조해 **PID 재사용**을 걸러낸다(읽을 수 있을 때만).
    """
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return False
    except ImportError:            # psutil 없음 → 존재 여부만이라도(구동작 폴백)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    if not module:
        return True
    _created, cmd = _proc_info(pid)
    return module in cmd if cmd else True   # 커맨드라인 조회 불가 시 생존만으로 인정


def start_servers():
    env = load_env()
    pids = load_pids()

    for name, module in SERVERS:
        pid = pids.get(name)
        if pid and is_running(pid, module):
            print(f"[SKIP] {name} 이미 실행 중 (PID={pid})")
            continue

        log_path = LOG_DIR / f"mcp_{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        popen_kwargs = dict(
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent),
        )
        if sys.platform == "win32":
            # 자식 서버를 런처 콘솔에서 분리 — Ctrl+C(KeyboardInterrupt)/콘솔 종료가
            # 자식으로 전파돼 서버가 같이 죽는 것을 방지(런처/하니스 종료에도 서버 생존).
            #   CREATE_NEW_PROCESS_GROUP: Ctrl+C 그룹 분리
            #   DETACHED_PROCESS: 부모 콘솔 미상속(stdout은 로그파일로 리다이렉트됨)
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen([sys.executable, "-m", module], **popen_kwargs)
        pids[name] = proc.pid
        print(f"[START] {name} (PID={proc.pid}) → {log_path}")

    save_pids(pids)

    import time
    print("\n3초 후 상태 확인...")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        # 자식 서버는 분리 기동(detached)되어 이미 독립 — 런처만 빠져나가도 서버는 생존.
        print("\n(대기 중단 — 서버는 백그라운드에서 계속 실행 중)")
    check_status()


def stop_servers():
    pids = load_pids()
    for name, module in SERVERS:
        pid = pids.get(name)
        if not pid:
            print(f"[SKIP] {name} - PID 없음")
            continue
        # PID 재사용 방어: 그 PID 가 정말 이 서버인지 커맨드라인으로 확인한 뒤에만 죽인다.
        # taskkill /T 는 트리째 죽이므로, 남의 PID 를 잡으면 피해가 크다(2026-08-11 데몬 락 사고와 동종).
        _created, cmd = _proc_info(pid)
        if cmd and module not in cmd:
            print(f"[SKIP] {name} (PID={pid}) — 다른 프로세스가 이 PID 사용 중, kill 생략")
            continue
        if is_running(pid, module):
            try:
                if sys.platform == "win32":
                    # /T: 자식 프로세스(uvicorn 등)까지 트리 전체 종료 — 없으면 포트 점유 좀비 잔존
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
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
    for name, module in SERVERS:
        pid = pids.get(name)
        if pid and is_running(pid, module):
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
