"""Tavily 웹 검색 MCP 서버 - BaseMCPServer 기반 구현"""

import logging
import sys
from pathlib import Path
from typing import Any

# ruff: noqa: I001
# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402
from src.mcp_servers.tavily_search_mcp.tavily_search_client import TavilySearchAPI  # noqa: E402

logger = logging.getLogger(__name__)


class TavilySearchMCPServer(BaseMCPServer):
    """Tavily 웹 검색 MCP 서버 구현"""

    def __init__(
        self,
        server_name: str = "Tavily Search MCP Server",
        port: int = 3020,
        host: str = "0.0.0.0",
        debug: bool = False,
        **kwargs,
    ):
        """
        Tavily 검색 MCP 서버 초기화

        Args:
            server_name: 서버 이름
            port: 서버 포트
            host: 호스트 주소
            debug: 디버그 모드
            **kwargs: 추가 옵션
        """
        super().__init__(
            server_name=server_name,
            port=port,
            host=host,
            debug=debug,
            server_instructions="Tavily API를 통한 웹 검색 기능을 제공합니다",
            **kwargs,
        )

    def _initialize_clients(self) -> None:
        """Tavily API 클라이언트 초기화"""
        self.tavily_api = TavilySearchAPI()
        logger.info("Tavily API client initialized")

    def _register_tools(self) -> None:
        """MCP 도구들을 등록"""

        @self.mcp.tool()
        async def search_web(
            query: str,
            max_results: int = 5,
            search_depth: str = "basic",
            topic: str = "general",
            time_range: str | None = None,
            start_date: str | None = None,
            end_date: str | None = None,
            days: int | None = None,
            include_domains: list[str] | None = None,
            exclude_domains: list[str] | None = None,
        ) -> dict[str, Any]:
            """
            Web search via Tavily

            Args:
                query: 검색 쿼리
                max_results: 최대 결과 수 (기본값: 5)
                search_depth: 검색 깊이 ("basic" 또는 "advanced", 기본값: "basic")
                topic: 검색 주제 ("general", "news", "finance" 등, 기본값: "general")
                time_range: 시간 범위 ("day", "week", "month", "year")
                start_date: 시작 날짜 (YYYY-MM-DD 형식)
                end_date: 종료 날짜 (YYYY-MM-DD 형식)
                days: 최근 N일
                include_domains: 포함할 도메인 목록
                exclude_domains: 제외할 도메인 목록

            Returns:
                검색 결과
            """
            try:
                payload = await self.tavily_api.search(
                    query=query,
                    max_results=max_results,
                    search_depth=search_depth,
                    topic=topic,
                    time_range=time_range,
                    start_date=start_date,
                    end_date=end_date,
                    days=days,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
                return self.create_standard_response(
                    success=True,
                    query=f"search_web: {query}",
                    data=payload,
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="search_web",
                    error=e,
                    query=query,
                )

        @self.mcp.tool()
        async def search_news(
            query: str,
            time_range: str = "week",
            max_results: int = 10,
        ) -> dict[str, Any]:
            """
            News search via Tavily

            Args:
                query: 검색 쿼리
                time_range: 시간 범위 (기본값: "week")
                max_results: 최대 결과 수 (기본값: 10)

            Returns:
                뉴스 검색 결과
            """
            try:
                payload = await self.tavily_api.search(
                    query=query,
                    search_depth="advanced",
                    max_results=max_results,
                    topic="news",
                    time_range=time_range,
                )
                return self.create_standard_response(
                    success=True,
                    query=f"search_news: {query}",
                    data=payload,
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="search_news",
                    error=e,
                    query=query,
                )

        @self.mcp.tool()
        async def search_finance(
            query: str,
            max_results: int = 10,
            search_depth: str = "advanced",
            time_range: str = "week",
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> dict[str, Any]:
            """
            Finance-focused search via Tavily

            Args:
                query: 검색 쿼리
                max_results: 최대 결과 수 (기본값: 10)
                search_depth: 검색 깊이 (기본값: "advanced")
                time_range: 시간 범위 (기본값: "week")
                start_date: 시작 날짜 (YYYY-MM-DD 형식)
                end_date: 종료 날짜 (YYYY-MM-DD 형식)

            Returns:
                금융 관련 검색 결과
            """
            try:
                payload = await self.tavily_api.search(
                    query=query,
                    search_depth=search_depth,
                    max_results=max_results,
                    topic="finance",
                    time_range=time_range,
                    start_date=start_date,
                    end_date=end_date,
                )
                return self.create_standard_response(
                    success=True,
                    query=f"search_finance: {query}",
                    data=payload,
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="search_finance",
                    error=e,
                    query=query,
                )

        logger.info("Registered 3 tools for Tavily Search MCP")


if __name__ == "__main__":
    try:
        # 서버 생성
        server = TavilySearchMCPServer()

        # Health 엔드포인트 등록
        @server.mcp.custom_route(
            path="/health",
            methods=["GET", "OPTIONS"],
            include_in_schema=True,
        )
        async def health_check(request):
            """Health check endpoint with CORS support"""
            from starlette.responses import JSONResponse

            # Manual CORS headers for health endpoint
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Expose-Headers": "*",
            }

            response_data = server.create_standard_response(
                success=True,
                query="MCP Server Health check",
                data="OK",
            )
            return JSONResponse(content=response_data, headers=headers)

        # Add global CORS handler for all custom routes
        @server.mcp.custom_route(
            path="/{path:path}",
            methods=["OPTIONS"],
            include_in_schema=False,
        )
        async def handle_options(request):
            """Handle OPTIONS requests for CORS"""
            from starlette.responses import Response
            return Response(
                content="",
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "3600",
                }
            )

        logger.info(f"Starting Tavily Search MCP Server on {server.host}:{server.port}")
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Tavily Search MCP Server stopped")
