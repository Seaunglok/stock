"""TradingAgent A2A 서버 - Claude SDK 기반."""

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
from src.claude_agents.trading.executor import TradingClaudeExecutor

logger = structlog.get_logger(__name__)


def _build_agent_card(url: str):
    skill = create_agent_skill(
        skill_id="stock_trading",
        name="주식 거래 실행",
        description="리스크 평가, Human-in-the-Loop 승인, 주문 실행 및 포트폴리오 관리를 수행합니다",
        tags=["trading", "order", "risk", "portfolio"],
        examples=[
            "삼성전자 100주 매수해주세요",
            "포트폴리오 리밸런싱 해주세요",
        ],
    )
    return create_agent_card(
        name="TradingAgent",
        description="주식 거래 실행 전문 Agent - 리스크 관리 및 주문 실행",
        url=url,
        version="2.0.0",
        skills=[skill],
    )


def main():
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    host = os.getenv("AGENT_HOST", "localhost")
    port = int(os.getenv("AGENT_PORT", "8003"))
    url = f"http://{host}:{port}"

    executor = TradingClaudeExecutor()
    handler = build_request_handler(executor)
    server_app = build_a2a_starlette_application(
        agent_card=_build_agent_card(url),
        handler=handler,
    )
    app = create_cors_enabled_app(server_app)

    logger.info("TradingAgent A2A 서버 시작", url=url)

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
