"""SupervisorAgent A2A 서버 - Claude SDK 기반."""

import logging
import os

import structlog
import uvicorn

from src.a2a_integration.a2a_lg_utils import (
    build_a2a_starlette_application,
    build_request_handler,
    create_agent_card,
    create_agent_skill,
)
from src.a2a_integration.cors_utils import create_cors_enabled_app
from src.claude_agents.supervisor.executor import SupervisorClaudeExecutor

logger = structlog.get_logger(__name__)


def _build_agent_card(url: str):
    skill = create_agent_skill(
        skill_id="investment_workflow",
        name="주식 투자 워크플로우",
        description=(
            "사용자 요청을 분석하여 데이터 수집 → 분석 → 거래 실행 워크플로우를 자동으로 조율합니다"
        ),
        tags=["supervisor", "orchestration", "workflow", "investment"],
        examples=[
            "삼성전자 투자 분석 전체 워크플로우 실행해주세요",
            "KOSPI 시장 상황 분석 후 매수 추천 종목 알려주세요",
        ],
    )
    return create_agent_card(
        name="SupervisorAgent",
        description="주식 투자 멀티에이전트 오케스트레이터",
        url=url,
        version="2.0.0",
        skills=[skill],
    )


def main():
    logging.basicConfig(level=logging.INFO)

    host = os.getenv("AGENT_HOST", "localhost")
    port = int(os.getenv("AGENT_PORT", "8000"))
    url = f"http://{host}:{port}"

    executor = SupervisorClaudeExecutor()
    handler = build_request_handler(executor)
    server_app = build_a2a_starlette_application(
        agent_card=_build_agent_card(url),
        handler=handler,
    )
    app = create_cors_enabled_app(server_app)

    logger.info("SupervisorAgent A2A 서버 시작", url=url)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        timeout_keep_alive=1000,
        timeout_graceful_shutdown=10,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
