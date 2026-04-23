#!/bin/bash
# MCP 서버 로컬 기동 스크립트 (Docker 없이)
# 사용법: bash run_mcp_local.sh [start|stop|status]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_DIR="/tmp/mcp_pids"
mkdir -p "$PID_DIR"

start_server() {
    local name="$1"
    local module="$2"
    local log="/tmp/mcp_${name}.log"
    local pid_file="$PID_DIR/${name}.pid"

    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "[SKIP] $name 이미 실행 중 (PID=$(cat "$pid_file"))"
        return
    fi

    # load_dotenv()를 먼저 호출한 뒤 모듈을 __main__으로 실행
    python -c "
from dotenv import load_dotenv
load_dotenv()
import runpy
runpy.run_module('$module', run_name='__main__', alter_sys=True)
" > "$log" 2>&1 &
    local pid=$!
    echo $pid > "$pid_file"
    echo "[START] $name (PID=$pid) → $log"
}

stop_server() {
    local name="$1"
    local pid_file="$PID_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            taskkill //F //PID $pid 2>/dev/null || kill "$pid"
            echo "[STOP] $name (PID=$pid)"
        else
            echo "[SKIP] $name (PID=$pid) 이미 종료됨"
        fi
        rm -f "$pid_file"
    else
        echo "[SKIP] $name - PID 파일 없음"
    fi
}

status_server() {
    local name="$1"
    local pid_file="$PID_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "[UP]   $name (PID=$pid)"
        else
            echo "[DOWN] $name (PID=$pid, 종료됨)"
        fi
    else
        echo "[DOWN] $name (미시작)"
    fi
}

# name  module
SERVERS=(
    "tavily       src.mcp_servers.tavily_search_mcp.server"
    "naver_news   src.mcp_servers.naver_news_mcp.server"
    "stock        src.mcp_servers.stock_analysis_mcp.server"
    "financial    src.mcp_servers.financial_analysis_mcp.server"
    "macro        src.mcp_servers.macroeconomic_analysis_mcp.server"
    "kiwoom_mkt   src.mcp_servers.kiwoom_mcp.domains.market_domain"
    "kiwoom_info  src.mcp_servers.kiwoom_mcp.domains.info_domain"
    "kiwoom_trade src.mcp_servers.kiwoom_mcp.domains.trading_domain"
    "kiwoom_inv   src.mcp_servers.kiwoom_mcp.domains.investor_domain"
    "kiwoom_port  src.mcp_servers.kiwoom_mcp.domains.portfolio_domain"
)

CMD="${1:-start}"

for entry in "${SERVERS[@]}"; do
    name=$(echo $entry | awk '{print $1}')
    module=$(echo $entry | awk '{print $2}')
    case "$CMD" in
        start)  start_server "$name" "$module" ;;
        stop)   stop_server "$name" ;;
        status) status_server "$name" ;;
    esac
done

if [ "$CMD" = "start" ]; then
    echo ""
    echo "3초 후 상태 확인..."
    sleep 3
    for entry in "${SERVERS[@]}"; do
        name=$(echo $entry | awk '{print $1}')
        status_server "$name"
    done
    echo ""
    echo "로그 확인: tail -f /tmp/mcp_<name>.log"
fi
