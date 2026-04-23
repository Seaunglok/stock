#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -o allexport
  source .env
  set +o allexport
  echo ".env 환경변수 로드 완료"
  echo "주요 환경변수 확인:"
  echo "  KIWOOM_API_KEY: ${KIWOOM_API_KEY:0:10}..." 
  echo "  NAVER_CLIENT_ID: ${NAVER_CLIENT_ID:0:10}..."
  echo "  TAVILY_API_KEY: ${TAVILY_API_KEY:0:10}..."
  echo "  DART_API_KEY: ${DART_API_KEY:0:10}..."
else
  echo ".env 파일이 없습니다. 환경변수를 직접 설정하거나 .env를 생성하세요."
fi

echo "기존 MCP docker-compose 인스턴스가 있으면 종료(down)합니다..."
docker compose --env-file .env -f docker/mcp_servers/docker-compose.yml down || true

echo "MCP docker-compose 인스턴스를 새로 실행합니다..."
# 환경변수를 docker-compose에 전달하여 실행
docker compose --env-file .env -f docker/mcp_servers/docker-compose.yml up -d --build