"""AnalysisAgent A2A 서버 - Claude SDK 기반."""

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
from src.claude_agents.analysis.executor import AnalysisClaudeExecutor

logger = structlog.get_logger(__name__)


def _build_agent_card(url: str):
    skill = create_agent_skill(
        skill_id="stock_analysis",
        name="주식 4차원 통합 분석",
        description="기술적·기본적·거시경제·감성 4차원 분석으로 투자 신호를 제공합니다",
        tags=["analysis", "technical", "fundamental", "macro", "sentiment"],
        examples=[
            "삼성전자 기술적 분석을 해주세요",
            "SK하이닉스 투자 가치 평가해주세요",
        ],
    )
    return create_agent_card(
        name="AnalysisAgent",
        description="주식 4차원 통합 분석 전문 Agent",
        url=url,
        version="2.0.0",
        skills=[skill],
    )


def main():
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    host = os.getenv("AGENT_HOST", "localhost")
    port = int(os.getenv("AGENT_PORT", "8002"))
    url = f"http://{host}:{port}"

    executor = AnalysisClaudeExecutor()
    handler = build_request_handler(executor)
    server_app = build_a2a_starlette_application(
        agent_card=_build_agent_card(url),
        handler=handler,
    )
    app = create_cors_enabled_app(server_app)

    logger.info("AnalysisAgent A2A 서버 시작", url=url)

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
