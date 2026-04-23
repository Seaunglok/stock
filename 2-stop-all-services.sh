#!/bin/bash
set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 스크립트 디렉토리 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 로그 함수
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "=================================="
echo "  시스템 종료 스크립트"
echo "=================================="
echo ""

# Frontend 종료
log_info "Frontend 종료 중..."
if [ -f "logs/frontend.pid" ]; then
    FRONTEND_PID=$(cat logs/frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        kill $FRONTEND_PID
        sleep 2
        if ps -p $FRONTEND_PID > /dev/null 2>&1; then
            kill -9 $FRONTEND_PID
        fi
        rm -f logs/frontend.pid
        log_success "Frontend 종료 완료 (PID: $FRONTEND_PID)"
    else
        log_info "Frontend 프로세스가 이미 종료됨"
        rm -f logs/frontend.pid
    fi
else
    # PID 파일이 없는 경우 프로세스 이름으로 종료
    pkill -f "next dev" && log_success "Frontend 프로세스 종료" || log_info "실행 중인 Frontend 프로세스 없음"
fi

# A2A 에이전트 종료
log_info "A2A 에이전트 종료 중..."
docker compose --env-file .env -f docker/a2a_agents/docker-compose.yml down
if [ $? -eq 0 ]; then
    log_success "A2A 에이전트 종료 완료"
else
    log_error "A2A 에이전트 종료 중 오류 발생"
fi

# MCP 서버 종료
log_info "MCP 서버 종료 중..."
docker compose --env-file .env -f docker/mcp_servers/docker-compose.yml down
if [ $? -eq 0 ]; then
    log_success "MCP 서버 종료 완료"
else
    log_error "MCP 서버 종료 중 오류 발생"
fi

echo ""
log_success "모든 서비스가 종료되었습니다."
echo ""

# 옵션: 볼륨 및 네트워크 정리
if [ "$1" == "--clean" ]; then
    log_info "볼륨 및 네트워크 정리 중..."
    docker volume prune -f
    docker network prune -f
    log_success "정리 완료"
fi