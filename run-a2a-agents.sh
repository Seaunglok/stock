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
  echo "  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:0:10}..." 
  echo "  OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."
  echo "  KIWOOM_API_KEY: ${KIWOOM_API_KEY:0:10}..."
  echo "  DEBUG: ${DEBUG:-false}"
  echo "  MOCK_MODE: ${MOCK_MODE:-true}"
else
  echo ".env 파일이 없습니다. 환경변수를 직접 설정하거나 .env를 생성하세요."
fi

echo "기존 A2A Agents docker-compose 인스턴스가 있으면 종료(down)합니다..."
docker compose --env-file .env -f docker/a2a_agents/docker-compose.yml down || true

echo "A2A Agents docker-compose 인스턴스를 새로 실행합니다..."
echo "실행할 Agents: Supervisor(8000), DataCollector(8001), Analysis(8002), Trading(8003)"
# 환경변수를 docker-compose에 전달하여 실행
docker compose --env-file .env -f docker/a2a_agents/docker-compose.yml up -d --build

echo ""
echo "=========================="
echo "A2A Multi-Agent System 실행 완료!"
echo "=========================="
echo ""
echo "Agent 상태 확인:"
echo "- Supervisor Agent:     http://localhost:8000/.well-known/agent-card.json"
echo "- DataCollector Agent:  http://localhost:8001/.well-known/agent-card.json"
echo "- Analysis Agent:       http://localhost:8002/.well-known/agent-card.json"
echo "- Trading Agent:        http://localhost:8003/.well-known/agent-card.json"
echo ""
echo "로그 확인: docker compose -f docker/a2a_agents/docker-compose.yml logs -f"
echo "종료: docker compose -f docker/a2a_agents/docker-compose.yml down"
echo ""