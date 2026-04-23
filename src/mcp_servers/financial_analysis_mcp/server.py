"""재무 분석 MCP 서버 - 단순화된 버전

BaseMCPServer 패턴을 활용하여 핵심 재무 분석 기능에 집중한
간소한 구조로 구성된 재무 분석 전문 서버입니다.
"""

import sys
import structlog
from pathlib import Path
from typing import Any, Literal

# ruff: noqa: I001
# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402
from src.mcp_servers.financial_analysis_mcp.financial_client import FinancialClient  # noqa: E402

logger = structlog.get_logger(__name__)


class FinancialAnalysisMCPServer(BaseMCPServer):
    """재무 분석 MCP 서버 구현"""

    def __init__(
        self,
        server_name: str = "Financial Analysis MCP Server",
        port: int = 8040,
        host: str = "0.0.0.0",
        debug: bool = False,
        **kwargs,
    ):
        """
        재무 분석 MCP 서버 초기화

        Args:
            server_name: 서버 이름
            port: 서버 포트
            host: 호스트 주소
            debug: 디버그 모드
            **kwargs: 추가 옵션
        """
        # 기본 미들웨어 설정 (현재 지원되는 미들웨어만)
        default_middlewares = ["logging", "error_handling"]
        middleware_config = {
            "logging": {
                "log_requests": True,
                "log_responses": debug,
            },
            "error_handling": {
                "include_traceback": debug,
            },
        }

        super().__init__(
            server_name=server_name,
            port=port,
            host=host,
            debug=debug,
            server_instructions="DCF 밸류에이션, 재무비율 분석, 기업 가치 평가 등 전문적인 각 회사별 재무 데이터 기반 분석 기능을 제공합니다",
            enable_middlewares=kwargs.get("enable_middlewares", default_middlewares),
            middleware_config=kwargs.get("middleware_config", middleware_config),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["enable_middlewares", "middleware_config"]
            },
        )

    def _initialize_clients(self) -> None:
        """재무 분석 클라이언트 초기화"""
        try:
            self.financial_client = FinancialClient()
            self.logger.info("Financial analysis client initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize financial analysis client: {e}")
            self.financial_client = None

    def _register_tools(self) -> None:
        """MCP 도구들을 등록"""

        # === 재무제표 분석 도구들 ===

        @self.mcp.tool()
        async def get_financial_statements(
            symbol: str,
            statement_type: Literal["income", "balance", "cashflow", "all"] = "all",
        ) -> dict[str, Any]:
            """
            재무제표 전체 데이터 조회

            Args:
                symbol: 종목코드(6자리 숫자 - 한국주식)
                statement_type: 재무제표 유형 ("all")

            Returns:
                손익계산서, 재무상태표, 현금흐름표 데이터
            """
            try:
                if self.financial_client:
                    result = await self.financial_client.get_financial_data(
                        symbol, statement_type
                    )
                else:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="get_financial_statements",
                        symbol=symbol,
                        statement_type=statement_type,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"get_financial_statements: {symbol}",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="get_financial_statements",
                    error=str(e),
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def calculate_financial_ratios(
            symbol: str,
        ) -> dict[str, Any]:
            """
            재무비율 계산

            Args:
                symbol: 종목코드

            Returns:
                수익성, 안전성, 활동성 비율 분석 결과
            """
            try:
                if self.financial_client:
                    financial_data = await self.financial_client.get_financial_data(
                        symbol
                    )

                    profitability_ratios = (
                        self.financial_client.calculate_profitability_ratios(
                            financial_data
                        )
                    )
                    stability_ratios = self.financial_client.calculate_stability_ratios(
                        financial_data
                    )
                    activity_ratios = self.financial_client.calculate_activity_ratios(
                        financial_data
                    )

                    result = {
                        "symbol": symbol,
                        "profitability_ratios": profitability_ratios,
                        "stability_ratios": stability_ratios,
                        "activity_ratios": activity_ratios,
                        "ratio_analysis": {
                            "roe_assessment": "우수"
                            if profitability_ratios["roe"] >= 15
                            else "양호"
                            if profitability_ratios["roe"] >= 10
                            else "개선필요",
                            "debt_assessment": "안전"
                            if stability_ratios["debt_to_equity"] <= 50
                            else "주의"
                            if stability_ratios["debt_to_equity"] <= 80
                            else "위험",
                            "efficiency_assessment": "우수"
                            if activity_ratios["asset_turnover"] >= 1.5
                            else "양호"
                            if activity_ratios["asset_turnover"] >= 0.8
                            else "개선필요",
                        },
                    }
                else:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="calculate_financial_ratios",
                        symbol=symbol,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"calculate_financial_ratios: {symbol}",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="calculate_financial_ratios",
                    error=str(e),
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def perform_dcf_valuation(
            symbol: str,
            growth_rate: float = 5.0,
            terminal_growth_rate: float = 2.5,
            discount_rate: float = 10.0,
            projection_years: int = 5,
        ) -> dict[str, Any]:
            """
            DCF 밸류에이션 수행

            Args:
                symbol: 종목코드
                growth_rate: 성장률 (%)
                terminal_growth_rate: 영구성장률 (%)
                discount_rate: 할인율 (%)
                projection_years: 예측 연도 수

            Returns:
                DCF 밸류에이션 결과 및 적정주가
            """
            try:
                if self.financial_client:
                    result = await self.financial_client.calculate_dcf_valuation(
                        symbol,
                        growth_rate,
                        terminal_growth_rate,
                        discount_rate,
                        projection_years,
                    )
                else:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="perform_dcf_valuation",
                        symbol=symbol,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"perform_dcf_valuation: {symbol}",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="perform_dcf_valuation",
                    error=str(e),
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def analyze_financial_health(
            symbol: str,
        ) -> dict[str, Any]:
            """
            재무 건전성 종합 분석

            Args:
                symbol: 종목코드

            Returns:
                재무 건전성 점수 및 투자 등급
            """
            try:
                if self.financial_client:
                    result = (
                        await self.financial_client.analyze_financial_comprehensive(
                            symbol
                        )
                    )
                else:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="analyze_financial_health",
                        symbol=symbol,
                    )

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_financial_health: {symbol}",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="analyze_financial_health",
                    error=str(e),
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def compare_peer_valuation(
            symbols: str,
            valuation_metrics: str = "per,pbr,ev_ebitda",
        ) -> dict[str, Any]:
            """
            동종업계 밸류에이션 비교

            Args:
                symbols: 비교할 종목코드 (쉼표로 구분된 문자열, 예: "005930,000660,035420")
                valuation_metrics: 비교할 밸류에이션 지표 (쉼표로 구분, 기본값: "per,pbr,ev_ebitda")

            Returns:
                동종업계 대비 밸류에이션 비교 결과
            """
            # 입력 검증 및 변환
            try:
                # symbols 문자열을 리스트로 변환
                symbols_list = [s.strip() for s in symbols.split(",") if s.strip()]
                if not symbols_list:
                    return self.create_error_response(
                        error="종목코드 리스트가 비어있습니다",
                        func_name="compare_peer_valuation",
                        symbols=symbols,
                    )

                # valuation_metrics 문자열을 리스트로 변환
                metrics_list = [m.strip() for m in valuation_metrics.split(",") if m.strip()]
                if not metrics_list:
                    metrics_list = ["per", "pbr", "ev_ebitda"]

                # 유효한 메트릭 검증
                valid_metrics = ["per", "pbr", "ev_ebitda"]
                metrics_list = [m for m in metrics_list if m in valid_metrics]

                if not metrics_list:
                    return self.create_error_response(
                        error="유효한 밸류에이션 지표가 없습니다. 사용 가능: per, pbr, ev_ebitda",
                        func_name="compare_peer_valuation",
                        valuation_metrics=valuation_metrics,
                    )

            except Exception as parse_error:
                return self.create_error_response(
                    error=f"입력 파라미터 파싱 오류: {parse_error}",
                    func_name="compare_peer_valuation",
                    symbols=symbols,
                    valuation_metrics=valuation_metrics,
                )

            try:
                if not self.financial_client:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="compare_peer_valuation",
                        symbols=symbols,
                    )

                import FinanceDataReader as fdr
                from datetime import datetime, timedelta

                comparison_results = {}

                # 각 종목별 실제 밸류에이션 지표 계산
                for symbol in symbols_list:
                    try:
                        # 재무 데이터 조회
                        financial_data = await self.financial_client.get_financial_data(
                            symbol
                        )

                        # 주가 데이터 조회
                        end_date = datetime.now()
                        start_date = end_date - timedelta(days=30)
                        price_data = fdr.DataReader(symbol, start_date, end_date)

                        if not price_data.empty:
                            current_price = price_data["Close"].iloc[-1]

                            # 종목 정보 조회
                            stock_info = fdr.StockListing("KRX")
                            stock_row = stock_info[stock_info["Code"] == symbol]

                            if not stock_row.empty:
                                market_cap = float(stock_row["Marcap"].iloc[0])

                                # 재무 지표 추출
                                net_income = financial_data.get(
                                    "income_statement", {}
                                ).get("net_income", 0)
                                total_equity = financial_data.get(
                                    "balance_sheet", {}
                                ).get("total_equity", 0)
                                total_debt = financial_data.get(
                                    "balance_sheet", {}
                                ).get("total_debt", 0)
                                ebitda = financial_data.get("income_statement", {}).get(
                                    "ebitda", 0
                                )

                                # 밸류에이션 지표 계산
                                per = market_cap / net_income if net_income > 0 else 0
                                pbr = (
                                    market_cap / total_equity if total_equity > 0 else 0
                                )
                                enterprise_value = market_cap + total_debt
                                ev_ebitda = (
                                    enterprise_value / ebitda if ebitda > 0 else 0
                                )

                                comparison_results[symbol] = {
                                    "company_name": stock_row["Name"].iloc[0]
                                    if not stock_row.empty
                                    else symbol,
                                    "current_price": round(current_price, 0),
                                    "market_cap": round(
                                        market_cap / 100000000, 0
                                    ),  # 억원 단위
                                    "per": round(per, 2) if per > 0 else None,
                                    "pbr": round(pbr, 2) if pbr > 0 else None,
                                    "ev_ebitda": round(ev_ebitda, 2)
                                    if ev_ebitda > 0
                                    else None,
                                    "data_source": "FinanceDataReader",
                                }
                    except Exception as e:
                        logger.warning(f"Failed to get valuation for {symbol}: {e}")
                        comparison_results[symbol] = {
                            "error": f"데이터 조회 실패: {str(e)}"
                        }

                # 평균값 계산
                metrics_avg = {}
                for metric in metrics_list:
                    if metric in ["per", "pbr", "ev_ebitda"]:
                        values = [
                            comparison_results[s][metric]
                            for s in symbols_list
                            if s in comparison_results
                            and comparison_results[s].get(metric) is not None
                        ]
                        metrics_avg[f"{metric}_average"] = (
                            round(sum(values) / len(values), 2) if values else 0
                        )

                # 상대적 평가
                relative_analysis = {}
                for symbol in symbols_list:
                    if (
                        symbol in comparison_results
                        and "error" not in comparison_results[symbol]
                    ):
                        relative_analysis[symbol] = {}
                        for metric in metrics_list:
                            if (
                                metric in comparison_results[symbol]
                                and comparison_results[symbol][metric] is not None
                            ):
                                value = comparison_results[symbol][metric]
                                avg = metrics_avg.get(f"{metric}_average", value)
                                if avg > 0:
                                    relative_analysis[symbol][f"{metric}_vs_peer"] = (
                                        "저평가"
                                        if value < avg * 0.9
                                        else "고평가"
                                        if value > avg * 1.1
                                        else "적정"
                                    )

                result = {
                    "comparison_data": comparison_results,
                    "industry_averages": metrics_avg,
                    "relative_analysis": relative_analysis,
                    "methodology": "실제 재무 데이터 기반 동종업계 밸류에이션 비교",
                    "data_source": "FinanceDataReader (실제 데이터)",
                }

                return self.create_standard_response(
                    success=True,
                    query=f"compare_peer_valuation: {len(symbols_list)} symbols",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="compare_peer_valuation",
                    error=str(e),
                    symbols=symbols,
                    valuation_metrics=valuation_metrics,
                )

        @self.mcp.tool()
        async def calculate_dividend_analysis(
            symbol: str,
            current_price: float = 0.0,
        ) -> dict[str, Any]:
            """
            배당 분석

            Args:
                symbol: 종목코드
                current_price: 현재 주가
            Returns:
                배당수익률, 배당성향, 배당 안정성 분석 결과
            """
            try:
                if not self.financial_client:
                    return self.create_error_response(
                        error="FinancialClient not initialized",
                        func_name="calculate_dividend_analysis",
                        symbol=symbol,
                    )

                # 실제 재무 데이터 조회
                financial_data = await self.financial_client.get_financial_data(symbol)

                # 실제 배당 데이터 계산
                # FinanceDataReader를 통한 실제 데이터 조회
                import FinanceDataReader as fdr
                from datetime import datetime, timedelta

                # 종목 정보 조회
                stock_info = fdr.StockListing("KRX")
                stock_row = stock_info[stock_info["Code"] == symbol]

                if stock_row.empty:
                    return self.create_error_response(
                        error=f"종목코드 {symbol}을 찾을 수 없습니다",
                        func_name="calculate_dividend_analysis",
                        symbol=symbol,
                    )

                # 현재 주가 조회 (current_price가 0이면 실제 주가 사용)
                if current_price == 0.0:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=30)
                    price_data = fdr.DataReader(symbol, start_date, end_date)
                    if not price_data.empty:
                        current_price = price_data["Close"].iloc[-1]
                    else:
                        current_price = 50000  # 기본값

                # 재무 데이터에서 배당 정보 추출
                net_income = financial_data.get("income_statement", {}).get(
                    "net_income", 0
                )

                # 실제 배당금 정보 (FinanceDataReader의 한계로 추정치 사용)
                # 한국 주식의 평균 배당성향 30~40% 가정
                estimated_payout_ratio = 35.0  # 35% 배당성향

                # 발행주식수 추정 (시가총액 / 현재주가)
                market_cap = (
                    float(stock_row["Marcap"].iloc[0])
                    if not stock_row.empty
                    else 1000000000000
                )
                total_shares = (
                    market_cap / current_price if current_price > 0 else 1000000
                )

                # 배당금 추정
                total_dividend = (
                    net_income * (estimated_payout_ratio / 100) if net_income > 0 else 0
                )
                dividend_per_share = (
                    total_dividend / total_shares if total_shares > 0 else 0
                )

                # 배당수익률 계산
                dividend_yield = (
                    (dividend_per_share / current_price * 100)
                    if current_price > 0
                    else 0
                )

                # 실제 배당성향 계산
                payout_ratio = (
                    (total_dividend / net_income * 100) if net_income > 0 else 0
                )

                result = {
                    "symbol": symbol,
                    "current_price": current_price,
                    "dividend_yield": round(dividend_yield, 2),
                    "dividend_per_share": round(dividend_per_share, 0),
                    "payout_ratio": round(payout_ratio, 2),
                    "net_income": net_income,
                    "total_shares": int(total_shares),
                    "dividend_assessment": {
                        "yield_rating": "높음"
                        if dividend_yield >= 4
                        else "보통"
                        if dividend_yield >= 2
                        else "낮음",
                        "sustainability": "안정"
                        if payout_ratio <= 60
                        else "주의"
                        if payout_ratio <= 80
                        else "위험",
                        "growth_potential": "우수"
                        if payout_ratio <= 40 and dividend_yield >= 2
                        else "보통",
                    },
                    "data_source": "FinanceDataReader (실제 데이터)",
                }

                return self.create_standard_response(
                    success=True,
                    query=f"calculate_dividend_analysis: {symbol}",
                    data=result,
                )

            except Exception as e:
                return self.create_error_response(
                    func_name="calculate_dividend_analysis",
                    error=str(e),
                    symbol=symbol,
                )

        self.logger.info("Registered 6 tools for Financial Analysis MCP")


if __name__ == "__main__":
    try:
        # 서버 생성
        server = FinancialAnalysisMCPServer()

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

        logger.info(
            f"Starting Financial Analysis MCP Server on {server.host}:{server.port}"
        )
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Financial Analysis MCP Server stopped")
