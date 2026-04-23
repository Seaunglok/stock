"""거시경제 분석 MCP 서버

핵심 거시경제 분석 기능에 집중한 서버입니다.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

# ruff: noqa: I001
# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402
from src.mcp_servers.macroeconomic_analysis_mcp.macro_client import MacroClient  # noqa: E402

logger = logging.getLogger(__name__)


class MacroeconomicMCPServer(BaseMCPServer):
    """거시경제 분석 MCP 서버 구현"""

    def __init__(
        self,
        server_name: str = "Macroeconomic Analysis MCP Server",
        port: int = 8041,
        host: str = "0.0.0.0",
        debug: bool = False,
        **kwargs,
    ):
        """
        거시경제 분석 MCP 서버 초기화

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
            server_instructions="거시경제 지표 분석을 통한 주식 투자 전략 수립 지원 (한국은행(ECOS)/FRED API 기반)",
            **kwargs,
        )

    def _initialize_clients(self) -> None:
        """거시경제 분석 클라이언트 초기화"""
        try:
            # 환경변수 검증
            self._validate_environment()

            # 거시경제 클라이언트 초기화
            self.macro_client = MacroClient()

            logger.info("Macroeconomic analysis client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize macro client: {e}")
            # 환경변수 누락으로 인한 초기화 실패는 서버 시작 중단
            if "필수 환경변수" in str(e):
                raise
            self.macro_client = None

    def _validate_environment(self) -> None:
        """환경변수 검증 - 필수"""
        required_vars = ["FRED_API_KEY"]
        optional_vars = ["ECOS_API_KEY"]  # 한국은행 API는 선택사항

        missing_required = []
        missing_optional = []

        for var in required_vars:
            if not os.getenv(var):
                missing_required.append(var)

        for var in optional_vars:
            if not os.getenv(var):
                missing_optional.append(var)

        if missing_required:
            error_msg = (
                f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing_required)}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        if missing_optional:
            logger.info(
                f"선택적 환경변수 누락: {', '.join(missing_optional)}, 일부 기능 제한"
            )

    def _register_tools(self) -> None:
        """MCP 도구들을 등록"""

        # === 경제지표 조회 도구들 ===

        @self.mcp.tool()
        async def get_interest_rates() -> dict[str, Any]:
            """
            미국의 1년치 금리 데이터 조회

            Returns:
                기준금리, 국채수익률 등 금리 정보
            """
            try:
                if self.macro_client:
                    result = await self.macro_client.get_interest_rates()
                else:
                    return self.create_error_response(
                        error="MacroClient not initialized",
                        func_name="get_interest_rates",
                    )

                return self.create_standard_response(
                    success=True,
                    query="get_interest_rates: 1 year",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_interest_rates",
                    error=e,
                )

        @self.mcp.tool()
        async def get_inflation_data(
            lookback_days: int = 180,
        ) -> dict[str, Any]:
            """
            인플레이션 데이터 조회

            Args:
                lookback_days: 조회 기간 (일, 1-1000 사이)

            Returns:
                소비자물가지수(CPI) 등 인플레이션 정보
            """
            # 입력 검증
            if not isinstance(lookback_days, int) or lookback_days < 1 or lookback_days > 1000:
                return self.create_error_response(
                    error="lookback_days는 1과 1000 사이의 정수여야 합니다",
                    func_name="get_inflation_data",
                    lookback_days=lookback_days,
                )

            try:
                if self.macro_client:
                    result = await self.macro_client.get_inflation_data(lookback_days)
                else:
                    return self.create_error_response(
                        func_name="get_inflation_data",
                        error="MacroClient not initialized",
                        lookback_days=lookback_days,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"get_inflation_data: {lookback_days} days",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_inflation_data",
                    error=e,
                    lookback_days=lookback_days,
                )

        @self.mcp.tool()
        async def get_employment_data(
            lookback_days: int = 90,
        ) -> dict[str, Any]:
            """
            고용 데이터 조회

            Args:
                lookback_days: 조회 기간 (일, 1-365 사이)

            Returns:
                실업률, 고용률 등 노동시장 정보
            """
            # 입력 검증
            if not isinstance(lookback_days, int) or lookback_days < 1 or lookback_days > 365:
                return self.create_error_response(
                    error="lookback_days는 1과 365 사이의 정수여야 합니다",
                    func_name="get_employment_data",
                    lookback_days=lookback_days,
                )

            try:
                if self.macro_client:
                    result = await self.macro_client.get_employment_data(lookback_days)
                else:
                    return self.create_error_response(
                        func_name="get_employment_data",
                        error="MacroClient not initialized",
                        lookback_days=lookback_days,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"get_employment_data: {lookback_days} days",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_employment_data",
                    error=e,
                    lookback_days=lookback_days,
                )

        @self.mcp.tool()
        async def get_gdp_data(
            lookback_quarters: int = 8,
        ) -> dict[str, Any]:
            """
            GDP 데이터 조회

            Args:
                lookback_quarters: 조회 기간 (분기, 1-40 사이)

            Returns:
                GDP 성장률 등 경제 성장 정보
            """
            # 입력 검증
            if not isinstance(lookback_quarters, int) or lookback_quarters < 1 or lookback_quarters > 40:
                return self.create_error_response(
                    error="lookback_quarters는 1과 40 사이의 정수여야 합니다",
                    func_name="get_gdp_data",
                    lookback_quarters=lookback_quarters,
                )

            try:
                if self.macro_client:
                    result = await self.macro_client.get_gdp_data(lookback_quarters)
                else:
                    return self.create_error_response(
                        query=f"get_gdp_data: {lookback_quarters} quarters",
                        func_name="get_gdp_data",
                        error="MacroClient not initialized",
                        lookback_quarters=lookback_quarters,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"get_gdp_data: {lookback_quarters} quarters",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_gdp_data",
                    error=e,
                    lookback_quarters=lookback_quarters,
                )

        # === 분석 도구들 ===

        @self.mcp.tool()
        async def analyze_economic_cycle() -> dict[str, Any]:
            """
            경기 사이클 분석

            Returns:
                현재 경기 단계 및 전망
            """
            try:
                if self.macro_client:
                    result = await self.macro_client.analyze_economic_cycle()
                else:
                    return self.create_error_response(
                        query="analyze_economic_cycle",
                        func_name="analyze_economic_cycle",
                        error="MacroClient not initialized",
                    )

                return self.create_standard_response(
                    success=True,
                    query="analyze_economic_cycle",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_economic_cycle",
                    error=e,
                )

        @self.mcp.tool()
        async def generate_investment_signal() -> dict[str, Any]:
            """
            투자 신호 생성

            Returns:
                거시경제 기반 투자 신호 및 전략
            """
            try:
                if self.macro_client:
                    result = await self.macro_client.generate_investment_signal()
                else:
                    return self.create_error_response(
                        query="generate_investment_signal",
                        func_name="generate_investment_signal",
                        error="MacroClient not initialized",
                    )

                return self.create_standard_response(
                    success=True,
                    query="generate_investment_signal",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="generate_investment_signal",
                    error=e,
                )

        @self.mcp.tool()
        async def analyze_interest_rate_impact(
            lookback_days: int = 90,
        ) -> dict[str, Any]:
            """
            금리 변동이 주식 시장에 미치는 영향 분석

            Args:
                lookback_days: 분석 기간 (일, 1-365 사이)

            Returns:
                금리와 주식시장의 상관관계 분석
            """
            # 입력 검증
            if not isinstance(lookback_days, int) or lookback_days < 1 or lookback_days > 365:
                return self.create_error_response(
                    error="lookback_days는 1과 365 사이의 정수여야 합니다",
                    func_name="analyze_interest_rate_impact",
                    lookback_days=lookback_days,
                )

            try:
                # 금리 데이터 수집
                if self.macro_client:
                    interest_data = await self.macro_client.get_interest_rates(
                        lookback_days
                    )

                    # 간단한 영향 분석
                    if interest_data.get("source") != "mock":
                        # 실제 데이터 기반 분석 로직
                        analysis = {
                            "rate_trend": "rising"
                            if interest_data.get("base_rate", [0])[-1]
                            > interest_data.get("base_rate", [0])[0]
                            else "falling",
                            "market_impact": "negative"
                            if interest_data.get("base_rate", [0])[-1] > 4.0
                            else "neutral",
                            "sector_impact": {
                                "financials": "positive",
                                "growth_stocks": "negative",
                                "utilities": "negative",
                            },
                        }
                    else:
                        analysis = {
                            "rate_trend": "stable",
                            "market_impact": "neutral",
                            "sector_impact": {
                                "financials": "neutral",
                                "growth_stocks": "neutral",
                                "utilities": "neutral",
                            },
                        }
                else:
                    return self.create_error_response(
                        query="analyze_interest_rate_impact",
                        func_name="analyze_interest_rate_impact",
                        error="MacroClient not initialized",
                        lookback_days=lookback_days,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_interest_rate_impact: {lookback_days} days",
                    data=analysis,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_interest_rate_impact",
                    error=e,
                    lookback_days=lookback_days,
                )

        logger.info("Registered 6 tools for Macroeconomic Analysis MCP")


if __name__ == "__main__":
    try:
        # 서버 생성
        server = MacroeconomicMCPServer()

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

        # FastMCP 기본 실행 방식 사용 (Kiwoom 서버와 동일)
        logger.info(
            f"Starting Macroeconomic Analysis MCP Server on {server.host}:{server.port}"
        )
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Macroeconomic Analysis MCP Server stopped")
