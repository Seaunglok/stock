"""
키움 Investor Domain 서버

투자자 동향 분석 도메인 서버
- 외국인 매매 동향
- 기관 매매 동향
- 프로그램 매매 현황
- 투자자별 매매 분석

포트: 8033

Beginner notes:
    - 투자자 데이터는 20분 지연될 수 있습니다. 실시간 의사결정에는
      지연 경고를 UI에 표시하는 것을 권장합니다.
    - 일부 도구는 날짜/시장 파라미터 조합이 많아 실수를 유발할 수 있어
      기본값을 제공합니다. 필요 시 명시적으로 덮어쓰세요.
"""

import asyncio
import logging
from datetime import datetime

# from pydantic import BaseModel, Field, field_validator  # 더 이상 사용하지 않음
from src.mcp_servers.base.base_mcp_server import StandardResponse
from src.mcp_servers.kiwoom_mcp.common.constants.api_types import KiwoomAPIID
from src.mcp_servers.kiwoom_mcp.common.domain_base import KiwoomDomainServer

logger = logging.getLogger(__name__)


# === 입력 모델들 ===
# 모든 입력 모델은 직접 파라미터로 변경되어 더 이상 사용하지 않음


# === Investor Domain 서버 클래스 ===


class InvestorDomainServer(KiwoomDomainServer):
    """
    키움 Investor Domain 서버 - 투자자 동향 분석 허브.

    ️ 아키텍처 위치:
    - **Layer 1 (MCP Server)**: 투자자 동향 제공자
    - **Port**: 8033
    - **Domain**: investor_domain

     주요 기능:
    1. **외국인 매매 동향**:
       - 종목별 외국인 매매
       - 외국인 순매수 현황
       - 외국인 보유 비중

    2. **기관 매매 동향**:
       - 기관 종목별 매매
       - 일별 기관 매매 현황
       - 기관 순매수 TOP

    3. **프로그램 매매**:
       - 프로그램 매매 현황
       - 프로그램 순매수 상위 50
       - 자동 매매 비중

    4. **투자자별 분석**:
       - 개인/기관/외국인 비교
       - 투자자별 순매수 현황
       - 투자자별 매매 패턴

     LangGraph Agent 연동:
    - **DataCollectorAgent**: 투자자 동향 데이터 수집
    - **AnalysisAgent**: 투자자 행동 패턴 분석
    - **SupervisorAgent**: 시장 전체 투자자 동향 파악

     MCP Tools (10개):
    - get_foreign_trading_trend: 외국인 매매동향
    - get_institutional_trading: 기관 매매동향
    - get_daily_institutional_trading: 일별 기관매매
    - get_intraday_investor_trading: 장중 투자자별 매매
    - get_program_trading_top50: 프로그램 순매수 TOP50
    - get_same_investor_ranking: 동일 순매매 순위
    - get_investor_daily_trading: 투자자별 일별 매매
    - get_stock_investor_detail: 종목별 투자자 상세

     특징:
    - 실시간 투자자 동향 트래킹
    - 기관/외국인 매매 패턴 분석
    - 투자자별 누적 매매 통계
    - 시장 심리 지표 자동 계산

     분석 지표:
    - 외국인 순매수 추이
    - 기관 순매수 흐름
    - 프로그램 매매 비중
    - 투자자별 매매 강도

    Note:
        - 키움 API의 ka100xx 투자자 시리즈 활용
        - 데이터는 20분 지연 제공
        - 투자자 동향은 시장 심리의 선행지표
    """

    def __init__(self, debug: bool = False):
        """
        Investor Domain 서버 초기화.

        Args:
            debug: 디버그 모드 활성화 여부

        Note:
            - 포트 8033에서 실행
            - 투자자 동향 데이터 캨시 초기화
            - 시장 심리 지표 계산 엔진 활성화
        """
        super().__init__(
            domain_name="investor",
            server_name="kiwoom-investor-domain",
            port=8033,
            debug=debug,
        )

        logger.info("Investor Domain Server initialized")

    def _initialize_clients(self) -> None:
        """클라이언트 초기화"""
        # 부모 클래스 호출
        super()._initialize_clients()
        logger.info("Investor domain clients initialized")

    def _register_tools(self) -> None:
        """도구 등록"""
        # 투자자 관련 도구 등록
        self._register_investor_tools()
        # 공통 리소스 등록
        self.register_common_resources()
        logger.info("Investor domain tools registered")

    def _register_investor_tools(self):
        """
        투자자 동향 MCP 도구들 등록.

        등록되는 도구 카테고리:
        1. 외국인/기관 매매 도구 (2개)
        2. 일별 매매 분석 도구 (2개)
        3. 프로그램 매매 도구 (2개)
        4. 투자자별 비교 도구 (2개)

        Note:
            - 20분 지연 데이터 경고 표시
            - 투자자 구분 코드 자동 파싱
            - 누적 통계 자동 계산
        """

        # === 1. 외국인/기관 매매 도구들 ===

        @self.mcp.tool()
        async def get_foreign_trading_trend(
            stock_code: str,
        ) -> StandardResponse:
            """
            외국인 종목별 매매동향

            Args:
                stock_code: 종목코드 (6자리)

            API: ka10008 (주식외국인종목별매매동향)
            외국인의 특정 종목 매매 패턴 분석
            """
            # 입력값 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return self.create_standard_response(
                    success=False,
                    query="외국인 매매동향 조회",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            query = f"외국인 매매동향: {stock_code}"

            params = {"stk_cd": stock_code}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.FOREIGN_STOCK_TRADE,
                query=query,
                params=params,
            )

        @self.mcp.tool()
        async def get_institutional_trading(
            stock_code: str,
        ) -> StandardResponse:
            """
            기관투자자의 매매동향

            Args:
                stock_code: 종목코드

            API: ka10009 (주식기관요청)
            기관투자자의 매매 동향 분석
            """
            # 입력값 검증
            if not stock_code:
                return self.create_standard_response(
                    success=False,
                    query="기관 매매동향 조회",
                    error="종목코드는 필수입니다"
                )

            query = f"기관 매매동향: {stock_code}"

            params = {"stk_cd": stock_code}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_INSTITUTION,
                query=query,
                params=params,
            )

        # === 2. 일별 매매 분석 도구들 ===

        @self.mcp.tool()
        async def get_daily_institutional_trading(
            start_date: str,
            end_date: str,
            trade_type: str = "0",
            market_type: str = "0",
            stock_exchange: str = "0"
        ) -> StandardResponse:
            """
            일별 기관매매 종목

            Args:
                start_date: 시작일자 (YYYYMMDD)
                end_date: 종료일자 (YYYYMMDD)
                trade_type: 매매구분 (0:전체, 1:매수, 2:매도)
                market_type: 시장구분
                stock_exchange: 거래소구분

            API: ka10044 (일별기관매매종목요청)
            기관의 일별 매매 종목 분석
            """
            # 입력값 검증
            if not start_date or not end_date:
                return self.create_standard_response(
                    success=False,
                    query="일별 기관매매 조회",
                    error="시작일자와 종료일자는 필수입니다"
                )

            query = f"일별 기관매매: {start_date}~{end_date}"

            params = {
                "strt_dt": start_date,
                "end_dt": end_date,
                "trde_tp": trade_type,
                "mrkt_tp": market_type,
                "stex_tp": stock_exchange,
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.DAILY_INST_TRADE,
                query=query,
                params=params,
            )

        @self.mcp.tool()
        async def get_intraday_investor_trading(
            market_type: str = "0",
            amount_type: str = "1",
            investor_type: str = "0",
            foreign_type: str = "0",
            net_type: str = "0",
            stock_exchange: str = "0"
        ) -> StandardResponse:
            """
            장중 투자자별 매매

            Args:
                market_type: 시장구분
                amount_type: 금액수량구분 (1:금액, 2:수량)
                investor_type: 투자자구분
                foreign_type: 외국인구분
                net_type: 순매수매도구분
                stock_exchange: 거래소구분

            API: ka10063 (장중투자자별매매요청)
            실시간 투자자별 매매 현황
            """
            query = "장중 투자자별 매매"

            params = {
                "mrkt_tp": market_type,
                "amt_qty_tp": amount_type,
                "invsr": investor_type,
                "frgn_all": foreign_type,
                "smtm_netprps_tp": net_type,
                "stex_tp": stock_exchange,
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.INTRADAY_INVESTOR_TRADE,
                query=query,
                params=params,
            )

        # === 3. 프로그램 매매 도구들 ===

        @self.mcp.tool()
        async def get_program_trading_top50(
            trade_type: str = "1",
            amount_type: str = "1",
            market_type: str = "0",
            stock_exchange: str = "0"
        ) -> StandardResponse:
            """
            프로그램 순매수 상위 50

            Args:
                trade_type: 매매상위구분
                amount_type: 금액수량구분
                market_type: 시장구분
                stock_exchange: 거래소구분

            API: ka90003 (프로그램순매수상위50요청)
            프로그램 매매 상위 종목
            """
            query = "프로그램 순매수 상위"

            params = {
                "trde_upper_tp": trade_type,
                "amt_qty_tp": amount_type,
                "mrkt_tp": market_type,
                "stex_tp": stock_exchange,
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.PROGRAM_NET_BUY_TOP50,
                query=query,
                params=params,
            )

        # === 4. 투자자별 상세 분석 도구들 ===

        @self.mcp.tool()
        async def get_same_investor_ranking(
            start_date: str,
            market_type: str = "0",
            trade_type: str = "0",
            sort_type: str = "1",
            unit_type: str = "1",
            stock_exchange: str = "0",
            end_date: str | None = None
        ) -> StandardResponse:
            """
            동일 순매매 순위

            Args:
                start_date: 시작일자 (YYYYMMDD)
                market_type: 시장구분
                trade_type: 매매구분
                sort_type: 정렬조건
                unit_type: 단위구분
                stock_exchange: 거래소구분
                end_date: 종료일자 (선택사항)

            API: ka10062 (동일순매매순위요청)
            동일 투자자의 순매매 패턴
            """
            # 입력값 검증
            if not start_date:
                return self.create_standard_response(
                    success=False,
                    query="동일 순매매 조회",
                    error="시작일자는 필수입니다"
                )

            query = f"동일 순매매: {start_date}"

            params = {
                "strt_dt": start_date,
                "mrkt_tp": market_type,
                "trde_tp": trade_type,
                "sort_cnd": sort_type,
                "unit_tp": unit_type,
                "stex_tp": stock_exchange,
                "end_dt": end_date,
            }

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.SAME_NET_TRADE_RANK,
                query=query,
                params=params,
            )

        @self.mcp.tool()
        async def get_investor_daily_trading_stocks(
            start_date: str,
            end_date: str,
            trade_type: str = "0",
            market_type: str = "0",
            investor_type: str = "01",
            stock_exchange: str = "0"
        ) -> StandardResponse:
            """
            투자자별 일별 매매종목

            Args:
                start_date: 시작일자 (YYYYMMDD)
                end_date: 종료일자 (YYYYMMDD)
                trade_type: 매매구분
                market_type: 시장구분
                investor_type: 투자자구분
                stock_exchange: 거래소구분

            API: ka10058 (투자자별일별매매종목요청)
            투자자 유형별 일별 매매 종목 분석
            """
            # 입력값 검증
            if not start_date or not end_date:
                return self.create_standard_response(
                    success=False,
                    query="투자자별 매매 조회",
                    error="시작일자와 종료일자는 필수입니다"
                )

            query = f"투자자별 매매: {start_date}~{end_date}"

            params = {
                "strt_dt": start_date,
                "end_dt": end_date,
                "trde_tp": trade_type,
                "mrkt_tp": market_type,
                "invsr_tp": investor_type,
                "stex_tp": stock_exchange,
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.INVESTOR_DAILY_TRADE,
                query=query,
                params=params,
            )

        @self.mcp.tool()
        async def get_stock_investor_detail(
            date: str,
            stock_code: str,
            amount_type: str = "1",
            trade_type: str = "0",
            unit_type: str = "1"
        ) -> StandardResponse:
            """
            종목별 투자자 기관별 상세

            Args:
                date: 일자 (YYYYMMDD)
                stock_code: 종목코드
                amount_type: 금액수량구분
                trade_type: 매매구분
                unit_type: 단위구분

            API: ka10059 (종목별투자자기관별요청)
            특정 종목의 투자자별 상세 매매 내역
            """
            # 입력값 검증
            if not date or not stock_code:
                return self.create_standard_response(
                    success=False,
                    query="종목별 투자자 조회",
                    error="일자와 종목코드는 필수입니다"
                )

            query = f"종목별 투자자: {stock_code} ({date})"

            params = {
                "dt": date,
                "stk_cd": stock_code,
                "amt_qty_tp": amount_type,
                "trde_tp": trade_type,
                "unit_tp": unit_type,
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_INVESTOR_BY_INST,
                query=query,
                params=params,
            )

        # === 5. 통합 투자자 분석 도구 ===

        @self.mcp.tool()
        async def get_investor_trend_summary() -> StandardResponse:
            """
            투자자 동향 종합 요약

            여러 API를 조합하여 투자자 전반 동향 제공
            """
            query = "투자자 동향 종합"

            try:
                # 병렬로 여러 데이터 조회
                today = datetime.now().strftime("%Y%m%d")

                tasks = [
                    self.call_api_with_response(
                        KiwoomAPIID.INTRADAY_INVESTOR_TRADE,
                        "장중 투자자",
                        {
                            "mrkt_tp": "0",
                            "amt_qty_tp": "1",
                            "invsr": "0",
                            "frgn_all": "0",
                            "smtm_netprps_tp": "0",
                            "stex_tp": "0",
                        },
                    ),
                    self.call_api_with_response(
                        KiwoomAPIID.PROGRAM_NET_BUY_TOP50,
                        "프로그램 매매",
                        {
                            "trde_upper_tp": "1",
                            "amt_qty_tp": "1",
                            "mrkt_tp": "0",
                            "stex_tp": "0",
                        },
                    ),
                    self.call_api_with_response(
                        KiwoomAPIID.DAILY_INST_TRADE,
                        "기관 매매",
                        {
                            "strt_dt": today,
                            "end_dt": today,
                            "trde_tp": "0",
                            "mrkt_tp": "0",
                            "stex_tp": "0",
                        },
                    ),
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 결과 조합 - 타입 안전성을 위한 길이 체크
                if len(results) >= 3:
                    summary_data = {
                        "intraday_investor": results[0].data
                        if isinstance(results[0], StandardResponse)
                        and results[0].success
                        else None,
                        "program_trading": results[1].data
                        if isinstance(results[1], StandardResponse)
                        and results[1].success
                        else None,
                        "institutional_trading": results[2].data
                        if isinstance(results[2], StandardResponse)
                        and results[2].success
                        else None,
                        "analysis_date": today,
                        "timestamp": datetime.now().isoformat(),
                    }
                else:
                    summary_data = {
                        "error": "Insufficient API responses",
                        "analysis_date": today,
                        "timestamp": datetime.now().isoformat(),
                    }

                return self.create_standard_response(
                    success=True,
                    query=query,
                    data=summary_data,
                )

            except Exception as e:
                logger.error(f"Investor trend summary error: {e}")
                return self.create_standard_response(
                    success=False, query=query, error=f"투자자 동향 요약 실패: {str(e)}"
                )

        logger.info("Investor domain tools registered successfully")


# === 서버 인스턴스 생성 ===


def create_investor_domain_server(debug: bool = False) -> InvestorDomainServer:
    """Investor Domain 서버 인스턴스 생성"""
    return InvestorDomainServer(debug=debug)


# === 메인 실행 ===


def main():
    """메인 실행 함수"""
    import argparse

    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    parser = argparse.ArgumentParser(description="Kiwoom Investor Domain Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=8033, help="Server port")
    args = parser.parse_args()

    # 서버 생성
    server = InvestorDomainServer(debug=args.debug or False)

    # 포트 설정 (필요시)
    if args.port != 8033:
        server.port = args.port

    # CORS 미들웨어 정의
    custom_middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
            expose_headers=["*"],
            max_age=600,
        )
    ]

    # Health 엔드포인트 등록 (한 번만)
    @server.mcp.custom_route(
        path="/health",
        methods=["GET", "OPTIONS"],
        include_in_schema=True,
    )
    async def health_check(request):
        """Health check endpoint"""
        from starlette.responses import JSONResponse

        response_data = server.create_standard_response(
            success=True,
            query="MCP Server Health check",
            data="OK",
        )
        return JSONResponse(content=response_data)

    try:
        # FastMCP 실행 - middleware 파라미터 전달이 핵심!
        logger.info(f"Starting Investor Domain Server on port {server.port} with CORS middleware")
        server.mcp.run(
            transport="streamable-http",
            host=server.host,
            port=server.port,
            middleware=custom_middleware  # CORS 미들웨어 전달
        )
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Investor Domain Server stopped")


if __name__ == "__main__":
    main()
