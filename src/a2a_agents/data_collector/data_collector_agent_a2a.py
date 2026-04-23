"""DataCollectorAgent A2A 서버 - Claude SDK 기반."""

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
from src.claude_agents.data_collector.executor import DataCollectorClaudeExecutor

logger = structlog.get_logger(__name__)


def _build_agent_card(url: str):
    skill = create_agent_skill(
        skill_id="stock_data_collection",
        name="주식 데이터 수집",
        description="실시간 시세, 차트, 뉴스, 재무정보 등 주식 투자에 필요한 모든 데이터를 수집합니다",
        tags=["stock", "data", "market", "news", "financial"],
        examples=[
            "삼성전자의 현재 시세와 최근 뉴스를 수집해주세요",
            "KOSPI 200 종목들의 실시간 데이터를 가져와주세요",
        ],
    )
    return create_agent_card(
        name="DataCollectorAgent",
        description="주식 데이터 수집 전문 Agent - 실시간 시세, 차트, 뉴스, 재무정보 수집",
        url=url,
        version="2.0.0",
        skills=[skill],
    )


def main():
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    host = os.getenv("AGENT_HOST", "localhost")
    port = int(os.getenv("AGENT_PORT", "8001"))
    url = f"http://{host}:{port}"

    executor = DataCollectorClaudeExecutor()
    handler = build_request_handler(executor)
    server_app = build_a2a_starlette_application(
        agent_card=_build_agent_card(url),
        handler=handler,
    )
    app = create_cors_enabled_app(server_app)

    logger.info("DataCollectorAgent A2A 서버 시작", url=url)

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
