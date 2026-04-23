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

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 환경변수 로드
if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
    log_success ".env 환경변수 로드 완료"
else
    log_error ".env 파일이 없습니다. .env.example을 참고하여 생성하세요."
    exit 1
fi

# Frontend 헬스체크
frontend_health_check() {
    log_info "Frontend 헬스체크 시작..."
    
    health_check "Frontend (3000)" "http://localhost:3000" && {
        log_success "Frontend 준비 완료!"
        return 0
    } || {
        log_error "Frontend가 응답하지 않습니다."
        return 1
    }
}

# 기존 컨테이너 정리
cleanup_existing() {
    log_info "기존 컨테이너 정리 중..."
    
    # docker-compose.full.yml 기반 컨테이너 정리
    log_info "기존 Docker 컨테이너 정리 중..."
    docker-compose -f docker-compose.full.yml --profile prod down --remove-orphans 2>/dev/null || true
    docker-compose -f docker-compose.full.yml --profile dev down --remove-orphans 2>/dev/null || true
    
    log_success "기존 컨테이너 및 프로세스 정리 완료"
}

# MCP 서버 및 A2A 에이전트 시작 (통합 실행)
start_integrated_services() {
    local build_flag=""
    if [ "$BUILD_IMAGES" = true ]; then
        build_flag="--build"
        log_info "통합 서비스 이미지 빌드 및 시작 중... (docker-compose.full.yml)"
    else
        log_info "통합 서비스 시작 중 (기존 이미지 사용)... (docker-compose.full.yml)"
    fi
    
    # docker-compose.full.yml을 사용하여 전체 시스템 시작
    docker-compose -f docker-compose.full.yml --profile prod up -d $build_flag
    
    if [ $? -eq 0 ]; then
        log_success "통합 서비스 시작 명령 실행 완료"
    else
        log_error "통합 서비스 시작 실패"
        exit 1
    fi
}

# 메인 실행 플로우
main() {
    # 도움말 표시
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        echo "=================================="
        echo "  한국 주식 투자 자동화 시스템"
        echo "  통합 실행 스크립트"
        echo "=================================="
        echo ""
        echo "사용법:"
        echo "  ./run-all-services.sh          # 빠른 시작 (기존 이미지 사용)"
        echo "  ./run-all-services.sh build    # 이미지 빌드 후 시작"
        echo "  ./run-all-services.sh --help   # 도움말 표시"
        echo ""
        echo "옵션:"
        echo "  build       Docker 이미지를 새로 빌드합니다"
        echo "  --help, -h  이 도움말을 표시합니다"
        echo ""
        echo "실행 후 접속 정보:"
        echo "  Frontend:      http://localhost:3000"
        echo "  MCP Inspector: http://localhost:3001"
        echo ""
        exit 0
    fi
    
    # 빌드 옵션 처리
    BUILD_IMAGES=false
    if [ "$1" = "build" ]; then
        BUILD_IMAGES=true
        log_info " 이미지 빌드 모드로 실행합니다"
    else
        log_info " 빠른 시작 모드로 실행합니다 (기존 이미지 사용)"
        log_info " 이미지를 새로 빌드하려면: ./run-all-services.sh build"
    fi
    
    echo "=================================="
    echo "  FastCampus - MCP & A2A 로 구성하는 Multi Agent"
    echo "  한국 주식 투자 AI Multi Agent 시스템 실습 프로젝트"
    echo "=================================="
    echo ""
    
    # logs 디렉토리 생성
    mkdir -p logs
    
    # 1. 기존 컨테이너 정리
    cleanup_existing
    
    # 2. MCP 서버 및 A2A 에이전트 시작 (통합 실행)
    start_integrated_services
}

# 스크립트 실행
main "$@"