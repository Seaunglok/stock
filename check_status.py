"""
서비스 상태 모니터링 스크립트

사용법:
  python check_status.py          # 한 번 확인
  python check_status.py --watch  # 10초마다 자동 갱신
"""

import sys
import time
import datetime
import socket
import urllib.request
import urllib.error

SERVICES = [
    # (이름, 포트, 종류, 확인URL)  — A2A 에이전트(8000~8003) 제거: 종가매매 트랙은 MCP만 사용.
    ("kiwoom-trading",   8030, "mcp",    "http://localhost:8030/mcp/"),
    ("kiwoom-market",    8031, "mcp",    "http://localhost:8031/mcp/"),
    ("kiwoom-info",      8032, "mcp",    "http://localhost:8032/mcp/"),
    ("kiwoom-investor",  8033, "mcp",    "http://localhost:8033/mcp/"),
    ("kiwoom-portfolio", 8034, "mcp",    "http://localhost:8034/mcp/"),
    ("financial",        8040, "mcp",    "http://localhost:8040/mcp"),
    ("macro",            8041, "mcp",    "http://localhost:8041/mcp"),
    ("stock-analysis",   8042, "mcp",    "http://localhost:8042/mcp"),
    ("naver-news",       8050, "mcp",    "http://localhost:8050/mcp"),
    ("tavily-search",    3020, "mcp",    "http://localhost:3020/mcp"),
    ("closing-bet",      8060, "mcp",    "http://localhost:8060/mcp"),
]

def check(url: str, timeout: float = 2.0) -> tuple[bool, int]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        # 4xx는 서버가 살아있음 (MCP는 GET에 405/406 정상 반환)
        if e.code < 500:
            return True, e.code
        return False, e.code
    except Exception:
        return False, 0

def print_status():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 터미널 지우기 (--watch 모드)
    if "--watch" in sys.argv:
        print("\033[2J\033[H", end="")

    print(f"{'='*52}")
    print(f"  서비스 상태 모니터  [{now}]")
    print(f"{'='*52}")

    agent_ok = mcp_ok = 0
    agent_total = mcp_total = 0

    print(f"\n[ A2A 에이전트 ]\n")
    for name, port, kind, url in SERVICES:
        if kind != "agent":
            continue
        ok, code = check(url)
        icon = "UP  " if ok else "DOWN"
        mark = "v" if ok else "x"
        print(f"  [{mark}] {icon}  {name:<18} :{port}")
        agent_total += 1
        if ok:
            agent_ok += 1

    print(f"\n[ MCP 서버 ]\n")
    for name, port, kind, url in SERVICES:
        if kind != "mcp":
            continue
        ok, code = check(url)
        icon = "UP  " if ok else "DOWN"
        mark = "v" if ok else "x"
        note = f"  (HTTP {code})" if not ok and code else ""
        print(f"  [{mark}] {icon}  {name:<18} :{port}{note}")
        mcp_total += 1
        if ok:
            mcp_ok += 1

    print(f"\n{'─'*52}")
    print(f"  에이전트 {agent_ok}/{agent_total}  |  MCP 서버 {mcp_ok}/{mcp_total}")
    print(f"{'='*52}")

    if "--watch" in sys.argv:
        print("\n  Ctrl+C 로 종료")

if __name__ == "__main__":
    if "--watch" in sys.argv:
        interval = 10
        try:
            while True:
                print_status()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n모니터링 종료.")
    else:
        print_status()
