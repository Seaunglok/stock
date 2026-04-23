"""
키움 Market Domain 서버

시장 데이터 관련 도구들을 통합한 도메인 서버:
- 실시간 시세 (현재가, 호가, 체결)
- 차트 데이터 (틱, 분봉, 일봉)
- 순위 정보 (상승률, 거래량, 거래대금)
- 기존 MCP 서버들의 시장 관련 기능 통합

포트: 8031

Beginner notes:
    - 모든 종목코드는 6자리 숫자 형식을 강제합니다. 클라이언트에서 미리
      포맷을 보정하면 서버 에러를 줄일 수 있습니다.
    - 실시간 구독 API는 샘플 구조를 반환하며, 실제 WebSocket 브로커/구독
      관리는 추후 구현 포인트입니다.
"""

import argparse
import asyncio
import logging
from datetime import datetime

from pydantic import BaseModel, Field

from src.mcp_servers.base.base_mcp_server import StandardResponse
from src.mcp_servers.kiwoom_mcp.common.constants.api_types import KiwoomAPIID
from src.mcp_servers.kiwoom_mcp.common.domain_base import KiwoomDomainServer

logger = logging.getLogger(__name__)


# === 입력 모델들 ===


class RealTimePriceRequest(BaseModel):
    """실시간 시세 조회 요청"""

    stock_codes: list[str] = Field(description="종목 코드들 (최대 20개)", max_length=20)
    fields: list[str] | None = Field(default=None, description="조회할 필드들")


class OrderBookRequest(BaseModel):
    """호가 조회 요청"""

    stock_code: str = Field(description="종목 코드")


class ChartDataRequest(BaseModel):
    """차트 데이터 조회 요청"""

    stock_code: str = Field(description="종목 코드")
    period: str = Field(description="조회 기간 ('1D', '1W', '1M', '3M', '6M', '1Y')")
    interval: str = Field(
        description="차트 간격 ('tick', '1min', '5min', '30min', '1day')"
    )
    count: int | None = Field(default=100, description="데이터 개수")


class MarketStatusRequest(BaseModel):
    """장 상태 조회 요청"""

    market_type: str | None = Field(
        default="ALL", description="시장 타입 (KOSPI, KOSDAQ, ALL)"
    )


class VolumeRankingRequest(BaseModel):
    """거래량 순위 요청"""

    market_type: str = Field(default="ALL", description="시장 타입")
    count: int | None = Field(default=50, description="조회 개수")


class PriceChangeRankingRequest(BaseModel):
    """등락률 순위 요청"""

    ranking_type: str = Field(description="순위 타입 ('up', 'down')")
    market_type: str = Field(default="ALL", description="시장 타입")
    count: int | None = Field(default=50, description="조회 개수")


class TickChartRequest(BaseModel):
    """틱 차트 조회 요청"""

    stock_code: str = Field(description="종목 코드")
    count: int | None = Field(default=100, description="조회할 틱 개수")


class MinuteChartRequest(BaseModel):
    """분봉 차트 조회 요청"""

    stock_code: str = Field(description="종목 코드")
    interval: int = Field(description="분봉 간격 (1, 3, 5, 10, 15, 30, 60)")
    count: int | None = Field(default=100, description="조회할 데이터 개수")


class DailyChartRequest(BaseModel):
    """일봉 차트 조회 요청"""

    stock_code: str = Field(description="종목 코드")
    start_date: str | None = Field(default=None, description="시작일 (YYYYMMDD)")
    end_date: str | None = Field(default=None, description="종료일 (YYYYMMDD)")


class ChartVisualizationRequest(BaseModel):
    """차트 시각화 요청"""

    stock_code: str = Field(description="종목 코드")
    chart_type: str = Field(description="차트 타입 ('candlestick', 'line', 'bar')")
    period: str = Field(description="조회 기간")
    indicators: list[str] | None = Field(default=None, description="기술적 지표들")


class RankingRequest(BaseModel):
    """순위 조회 공통 요청"""

    ranking_type: str = Field(description="순위 타입")
    market_type: str = Field(default="ALL", description="시장 타입")
    count: int | None = Field(default=50, description="조회 개수")


class TradeValueTopRequest(BaseModel):
    """거래대금 상위 요청"""

    market_type: str = Field(default="ALL", description="시장 타입")
    count: int | None = Field(default=50, description="조회 개수")


# === Market Domain 서버 클래스 ===


# === Request Models ===


class StockBasicInfoRequest(BaseModel):
    """주식 기본정보 요청"""

    stock_code: str = Field(..., description="종목코드")


class ExecutionInfoRequest(BaseModel):
    """체결정보 요청"""

    stock_code: str = Field(..., description="종목코드")


class DailyPriceHistoryRequest(BaseModel):
    """일별 주가 이력 요청"""

    stock_code: str = Field(..., description="종목코드")
    query_date: str | None = Field(None, description="조회일자 (YYYYMMDD)")
    indicator_type: str | None = Field(None, description="지표구분")


class VolumeSurgeRequest(BaseModel):
    """거래량 급증 요청"""

    market_type: str | None = Field("ALL", description="시장구분 (ALL, KOSPI, KOSDAQ)")
    time_type: str | None = Field("1", description="시간구분")


class TradeValueRankingRequest(BaseModel):
    """거래대금 순위 요청"""

    market_type: str | None = Field("ALL", description="시장구분")


class RealtimeSubscriptionRequest(BaseModel):
    """실시간 구독 요청"""

    stock_codes: list[str] = Field(..., description="종목코드 리스트")


class MarketDomainServer(KiwoomDomainServer):
    """
    키움 Market Domain 서버 - 실시간 시장 데이터 허브.

    ️ 아키텍처 위치:
    - **Layer 1 (MCP Server)**: 시장 데이터 제공자
    - **Port**: 8031
    - **Domain**: market_domain

     주요 기능:
    1. **실시간 시세 데이터**:
       - 현재가, 등락률, 거래량
       - 호가 정보 (매수/매도 10단계)
       - 체결 정보 (실시간 거래 내역)

    2. **차트 데이터**:
       - 틱 차트 (체결 단위)
       - 분봉 차트 (1, 3, 5, 10, 15, 30, 60분)
       - 일봉 차트 (일/주/월)

    3. **시장 순위 정보**:
       - 거래량 순위 (상위 50종목)
       - 등락률 순위 (상승/하락)
       - 거래대금 순위

     LangGraph Agent 연동:
    - **DataCollectorAgent**: 실시간 시세 수집
    - **AnalysisAgent**: 차트 데이터 기반 기술적 분석
    - **TradingAgent**: 현재가 기반 주문 가격 결정

     MCP Tools (15개):
    - get_stock_basic_info: 종목 기본정보
    - get_stock_orderbook: 호가 정보
    - get_stock_execution_info: 체결 정보
    - get_tick_chart: 틱 차트
    - get_minute_chart: 분봉 차트
    - get_daily_chart: 일봉 차트
    - get_volume_ranking: 거래량 순위
    - get_price_change_ranking: 등락률 순위
    - get_trade_value_top: 거래대금 상위
    - get_market_status: 장 상태 확인

     특징:
    - 실시간 WebSocket 스트리밍 지원
    - 차트 데이터 캐싱으로 성능 최적화
    - Rate limiting으로 API 할당량 관리
    - 시장 상태별 자동 데이터 갱신 주기 조절

    Note:
        - 키움 API의 ka10xxx 시리즈 활용
        - 실시간 데이터는 WebSocket으로 푸시
        - 차트 데이터는 최대 2년치 제공
    """

    def __init__(self, debug: bool = False):
        """
        Market Domain 서버 초기화.

        Args:
            debug: 디버그 모드 활성화 여부

        Note:
            - 포트 8031에서 실행
            - WebSocket 엔드포인트 자동 설정
            - 캐시 및 rate limiter 초기화
        """
        super().__init__(
            domain_name="market",
            server_name="kiwoom-market-domain",
            port=8031,
            debug=debug,
        )

        logger.info("Market Domain Server initialized")

    def _initialize_clients(self) -> None:
        """클라이언트 초기화 (BaseMCPServer 요구사항)"""
        # 부모 클래스 호출
        super()._initialize_clients()
        # 추가적인 클라이언트 초기화가 필요한 경우 여기서 구현
        logger.info("Market domain clients initialized")

    def _register_tools(self) -> None:
        """도구 등록 (BaseMCPServer 요구사항)"""
        # 시장 관련 도구 등록
        self._register_market_tools()
        # 공통 리소스 등록
        self.register_common_resources()
        logger.info("Market domain tools registered")

    def _register_market_tools(self):
        """
        시장 데이터 MCP 도구들 등록.

        등록되는 도구 카테고리:
        1. 실시간 시세 도구 (3개)
        2. 차트 데이터 도구 (4개)
        3. 순위 정보 도구 (3개)
        4. 시장 상태 도구 (2개)
        5. 기술적 지표 도구 (3개)

        Note:
            - 모든 도구는 @self.mcp.tool() 데코레이터로 등록
            - StandardResponse 형식으로 통일된 응답
            - 비동기 처리로 성능 최적화
        """

        # === 1. 실시간 시세 도구들 ===

        @self.mcp.tool()
        async def get_stock_basic_info(stock_code: str) -> StandardResponse:
            """
            주식 기본정보 조회 (현재가, 등락률, 거래량 등)

            Args:
                stock_code: 종목코드 (6자리 숫자)

            Returns:
                StandardResponse: 주식 기본정보 데이터

            API: ka10001 (주식기본정보요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_stock_basic_info",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            query = f"주식 기본정보 조회: {stock_code}"
            params = {"stk_cd": stock_code}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_BASIC_INFO, query=query, params=params
            )

        @self.mcp.tool()
        async def get_stock_orderbook(stock_code: str) -> StandardResponse:
            """
            주식 호가 조회

            Args:
                stock_code: 종목코드 (6자리 숫자)

            Returns:
                StandardResponse: 호가 정보 데이터 (매수/매도 10단계)

            API: ka10004 (주식호가요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_stock_orderbook",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            query = f"호가 조회: {stock_code}"
            params = {"stk_cd": stock_code}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_ORDERBOOK, query=query, params=params
            )

        @self.mcp.tool()
        async def get_stock_execution_info(stock_code: str) -> StandardResponse:
            """
            체결정보 조회

            Args:
                stock_code: 종목코드 (6자리 숫자)

            Returns:
                StandardResponse: 체결 정보 데이터 (실시간 거래 내역)

            API: ka10003 (체결정보요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_stock_execution_info",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            query = f"체결정보 조회: {stock_code}"
            params = {"stk_cd": stock_code}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_EXECUTION_INFO, query=query, params=params
            )

        # === 2. 차트 데이터 도구들 ===

        @self.mcp.tool()
        async def get_daily_chart(
            stock_code: str,
            start_date: str | None = None,
            end_date: str | None = None
        ) -> StandardResponse:
            """
            일봉 차트 조회

            Args:
                stock_code: 종목코드 (6자리 숫자)
                start_date: 시작일 (YYYYMMDD 형식, 선택사항)
                end_date: 종료일 (YYYYMMDD 형식, 선택사항)

            Returns:
                StandardResponse: 일봉 차트 데이터

            API: ka10081 (주식일봉차트조회요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_daily_chart",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            # 날짜 형식 검증
            if start_date and (len(start_date) != 8 or not start_date.isdigit()):
                return await self.create_error_response(
                    func_name="get_daily_chart",
                    error="시작일은 YYYYMMDD 형식이어야 합니다"
                )

            if end_date and (len(end_date) != 8 or not end_date.isdigit()):
                return await self.create_error_response(
                    func_name="get_daily_chart",
                    error="종료일은 YYYYMMDD 형식이어야 합니다"
                )

            query = f"일봉 차트 조회: {stock_code}"

            params = {
                "stk_cd": stock_code,
                "base_dt": end_date or datetime.now().strftime("%Y%m%d"),
                "upd_stkpc_tp": "1",  # 수정주가
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_DAILY_CHART, query=query, params=params
            )

        @self.mcp.tool()
        async def get_minute_chart(
            stock_code: str,
            interval: int,
            count: int | None = 100
        ) -> StandardResponse:
            """
            분봉 차트 조회

            Args:
                stock_code: 종목코드 (6자리 숫자)
                interval: 분봉 간격 (1, 3, 5, 10, 15, 30, 60)
                count: 조회할 데이터 개수 (기본값: 100)

            Returns:
                StandardResponse: 분봉 차트 데이터

            API: ka10080 (주식분봉차트조회요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_minute_chart",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            # 분봉 간격 검증
            valid_intervals = [1, 3, 5, 10, 15, 30, 60]
            if interval not in valid_intervals:
                return await self.create_error_response(
                    func_name="get_minute_chart",
                    error=f"분봉 간격은 {valid_intervals} 중 하나여야 합니다"
                )

            # 개수 검증
            if count and (count <= 0 or count > 2000):
                return await self.create_error_response(
                    func_name="get_minute_chart",
                    error="조회 개수는 1~2000 사이여야 합니다"
                )

            query = f"분봉 차트 조회: {stock_code} ({interval}분)"

            params = {
                "stk_cd": stock_code,
                "tic_scope": str(interval),  # 1, 3, 5, 10, 30분
                "upd_stkpc_tp": "1",  # 수정주가
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_MINUTE_CHART, query=query, params=params
            )

        @self.mcp.tool()
        async def get_daily_price_history(
            stock_code: str,
            query_date: str | None = None,
            indicator_type: str | None = None
        ) -> StandardResponse:
            """
            일별 주가 이력 조회

            Args:
                stock_code: 종목코드 (6자리 숫자)
                query_date: 조회일자 (YYYYMMDD 형식, 선택사항)
                indicator_type: 지표구분 (선택사항)

            Returns:
                StandardResponse: 일별 주가 이력 데이터

            API: ka10086 (일별주가요청)
            """
            # 입력 검증
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return await self.create_error_response(
                    func_name="get_daily_price_history",
                    error="종목코드는 6자리 숫자여야 합니다"
                )

            # 날짜 형식 검증
            if query_date and (len(query_date) != 8 or not query_date.isdigit()):
                return await self.create_error_response(
                    func_name="get_daily_price_history",
                    error="조회일자는 YYYYMMDD 형식이어야 합니다"
                )

            query = f"일별 주가 이력: {stock_code}"

            params = {
                "stk_cd": stock_code,
                "qry_dt": query_date or datetime.now().strftime("%Y%m%d"),
                "indc_tp": indicator_type or "1",
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.DAILY_PRICE, query=query, params=params
            )

        # === 3. 순위 정보 도구들 ===

        @self.mcp.tool()
        async def get_price_change_ranking(
            ranking_type: str,
            market_type: str = "ALL",
            count: int | None = 50
        ) -> StandardResponse:
            """
            전일대비 등락률 순위

            Args:
                ranking_type: 순위 타입 ('up': 상승률, 'down': 하락률)
                market_type: 시장 타입 (ALL, KOSPI, KOSDAQ)
                count: 조회 개수 (기본값: 50)

            Returns:
                StandardResponse: 등락률 순위 데이터

            API: ka10027 (전일대비등락률상위요청)
            """
            # 입력 검증
            if ranking_type not in ["up", "down"]:
                return await self.create_error_response(
                    func_name="get_price_change_ranking",
                    error="순위 타입은 'up' 또는 'down'이어야 합니다"
                )

            if market_type not in ["ALL", "KOSPI", "KOSDAQ"]:
                return await self.create_error_response(
                    func_name="get_price_change_ranking",
                    error="시장 타입은 'ALL', 'KOSPI', 'KOSDAQ' 중 하나여야 합니다"
                )

            if count and (count <= 0 or count > 200):
                return await self.create_error_response(
                    func_name="get_price_change_ranking",
                    error="조회 개수는 1~200 사이여야 합니다"
                )

            query = f"등락률 순위: {market_type} ({ranking_type})"

            params = {
                "mrkt_tp": market_type,  # ALL, KOSPI, KOSDAQ
                "sort_tp": ranking_type,  # up:상승률, down:하락률
                "trde_qty_cnd": "0",
                "stk_cnd": "0",
                "crd_cnd": "0",
                "updown_incls": "Y",
                "pric_cnd": "0",
                "trde_prica_cnd": "0",
                "stex_tp": "0",
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.DAILY_CHANGE_TOP, query=query, params=params
            )

        @self.mcp.tool()
        async def get_volume_top_ranking(
            market_type: str = "ALL",
            count: int | None = 50
        ) -> StandardResponse:
            """
            당일 거래량 상위

            Args:
                market_type: 시장 타입 (ALL, KOSPI, KOSDAQ)
                count: 조회 개수 (기본값: 50)

            Returns:
                StandardResponse: 거래량 상위 데이터

            API: ka10030 (당일거래량상위요청)
            """
            # 입력 검증
            if market_type not in ["ALL", "KOSPI", "KOSDAQ"]:
                return await self.create_error_response(
                    func_name="get_volume_top_ranking",
                    error="시장 타입은 'ALL', 'KOSPI', 'KOSDAQ' 중 하나여야 합니다"
                )

            if count and (count <= 0 or count > 200):
                return await self.create_error_response(
                    func_name="get_volume_top_ranking",
                    error="조회 개수는 1~200 사이여야 합니다"
                )

            query = f"거래량 상위: {market_type}"

            params = {
                "mrkt_tp": market_type,
                "sort_tp": "1",  # 1:거래량순
                "mang_stk_incls": "Y",  # 관리종목 포함
                "crd_tp": "0",
                "trde_qty_tp": "1",
                "pric_tp": "0",
                "trde_prica_tp": "0",
                "mrkt_open_tp": "0",
                "stex_tp": "0",
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.TODAY_VOLUME_TOP, query=query, params=params
            )

        @self.mcp.tool()
        async def get_volume_surge_ranking(
            market_type: str = "ALL",
            time_type: str = "1"
        ) -> StandardResponse:
            """
            거래량 급증 종목

            Args:
                market_type: 시장구분 (ALL, KOSPI, KOSDAQ)
                time_type: 시간구분 (1: 당일)

            Returns:
                StandardResponse: 거래량 급증 종목 데이터

            API: ka10023 (거래량급증요청)
            """
            # 입력 검증
            if market_type not in ["ALL", "KOSPI", "KOSDAQ"]:
                return await self.create_error_response(
                    func_name="get_volume_surge_ranking",
                    error="시장 타입은 'ALL', 'KOSPI', 'KOSDAQ' 중 하나여야 합니다"
                )

            if time_type not in ["1"]:
                return await self.create_error_response(
                    func_name="get_volume_surge_ranking",
                    error="시간구분은 '1'(당일)이어야 합니다"
                )

            query = f"거래량 급증: {market_type}"

            params = {
                "mrkt_tp": market_type,
                "sort_tp": "1",  # 1:급증률순
                "tm_tp": time_type,  # 1:당일
                "trde_qty_tp": "1",
                "stk_cnd": "0",
                "pric_tp": "0",
                "stex_tp": "0",
            }

            # 당일인 경우 현재 시간 추가
            if time_type == "1":
                params["tm"] = datetime.now().strftime("%H%M%S")

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.VOLUME_SURGE, query=query, params=params
            )

        @self.mcp.tool()
        async def get_trade_value_ranking(
            market_type: str = "ALL"
        ) -> StandardResponse:
            """
            거래대금 상위

            Args:
                market_type: 시장구분 (ALL, KOSPI, KOSDAQ)

            Returns:
                StandardResponse: 거래대금 상위 데이터

            API: ka10032 (거래대금상위요청)
            """
            # 입력 검증
            if market_type not in ["ALL", "KOSPI", "KOSDAQ"]:
                return await self.create_error_response(
                    func_name="get_trade_value_ranking",
                    error="시장 타입은 'ALL', 'KOSPI', 'KOSDAQ' 중 하나여야 합니다"
                )

            query = f"거래대금 상위: {market_type}"

            params = {
                "mrkt_tp": market_type,
                "mang_stk_incls": "Y",  # 관리종목 포함
                "stex_tp": "0",
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.TRADE_VALUE_TOP, query=query, params=params
            )

        # === 4. 실시간 WebSocket 도구들 ===

        @self.mcp.tool()
        async def subscribe_realtime_price(
            stock_codes: list[str]
        ) -> StandardResponse:
            """
            실시간 시세 구독 (WebSocket)

            Args:
                stock_codes: 종목코드 리스트 (최대 20개의 6자리 숫자)

            Returns:
                StandardResponse: 구독 상태 데이터

            API: ws_0B (주식체결)
            """
            # 입력 검증
            if not stock_codes or len(stock_codes) == 0:
                return await self.create_error_response(
                    func_name="subscribe_realtime_price",
                    error="종목코드 리스트가 비어있습니다"
                )

            if len(stock_codes) > 20:
                return await self.create_error_response(
                    func_name="subscribe_realtime_price",
                    error="종목코드는 최대 20개까지 가능합니다"
                )

            # 각 종목코드 형식 검증
            for code in stock_codes:
                if not code or len(code) != 6 or not code.isdigit():
                    return await self.create_error_response(
                        func_name="subscribe_realtime_price",
                        error=f"종목코드 '{code}'는 6자리 숫자여야 합니다"
                    )

            query = f"실시간 시세 구독: {', '.join(stock_codes)}"

            # WebSocket 구독 로직
            # 실제 구현시 WebSocket 연결 관리 필요
            {
                "trnm": "REG",
                "grp_no": "1",
                "refresh": "N",
                "data": [{"item": code, "type": "0B"} for code in stock_codes],
            }

            return self.create_standard_response(
                success=True,
                query=query,
                data={
                    "subscription": "active",
                    "stocks": stock_codes,
                    "type": "realtime_price",
                },
            )

        @self.mcp.tool()
        async def subscribe_realtime_orderbook(
            stock_codes: list[str]
        ) -> StandardResponse:
            """
            실시간 호가 구독 (WebSocket)

            Args:
                stock_codes: 종목코드 리스트 (최대 20개의 6자리 숫자)

            Returns:
                StandardResponse: 호가 구독 상태 데이터

            API: ws_0D (주식호가잔량)
            """
            # 입력 검증
            if not stock_codes or len(stock_codes) == 0:
                return await self.create_error_response(
                    func_name="subscribe_realtime_orderbook",
                    error="종목코드 리스트가 비어있습니다"
                )

            if len(stock_codes) > 20:
                return await self.create_error_response(
                    func_name="subscribe_realtime_orderbook",
                    error="종목코드는 최대 20개까지 가능합니다"
                )

            # 각 종목코드 형식 검증
            for code in stock_codes:
                if not code or len(code) != 6 or not code.isdigit():
                    return await self.create_error_response(
                        func_name="subscribe_realtime_orderbook",
                        error=f"종목코드 '{code}'는 6자리 숫자여야 합니다"
                    )

            query = f"실시간 호가 구독: {', '.join(stock_codes)}"

            {
                "trnm": "REG",
                "grp_no": "2",
                "refresh": "N",
                "data": [{"item": code, "type": "0D"} for code in stock_codes],
            }

            return self.create_standard_response(
                success=True,
                query=query,
                data={
                    "subscription": "active",
                    "stocks": stock_codes,
                    "type": "realtime_orderbook",
                },
            )

        # === 5. 통합 조회 도구 ===

        @self.mcp.tool()
        async def get_market_overview() -> StandardResponse:
            """
            시장 전체 개요 (복합 조회)

            여러 API를 조합하여 시장 전반 상황 제공
            """
            query = "시장 전체 개요"

            try:
                # 병렬로 여러 데이터 조회
                tasks = [
                    self.call_api_with_response(
                        KiwoomAPIID.DAILY_CHANGE_TOP,
                        "상승률 TOP5",
                        {
                            "mrkt_tp": "ALL",
                            "sort_tp": "1",
                            "trde_qty_cnd": "0",
                            "stk_cnd": "0",
                            "crd_cnd": "0",
                            "updown_incls": "Y",
                            "pric_cnd": "0",
                            "trde_prica_cnd": "0",
                            "stex_tp": "0",
                        },
                    ),
                    self.call_api_with_response(
                        KiwoomAPIID.TODAY_VOLUME_TOP,
                        "거래량 TOP5",
                        {
                            "mrkt_tp": "ALL",
                            "sort_tp": "1",
                            "mang_stk_incls": "Y",
                            "crd_tp": "0",
                            "trde_qty_tp": "1",
                            "pric_tp": "0",
                            "trde_prica_tp": "0",
                            "mrkt_open_tp": "0",
                            "stex_tp": "0",
                        },
                    ),
                    self.call_api_with_response(
                        KiwoomAPIID.TRADE_VALUE_TOP,
                        "거래대금 TOP5",
                        {"mrkt_tp": "ALL", "mang_stk_incls": "Y", "stex_tp": "0"},
                    ),
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 결과 조합 - 타입 안전성을 위한 길이 체크
                if len(results) >= 3:
                    overview_data = {
                        "price_leaders": results[0].data
                        if isinstance(results[0], StandardResponse)
                        and results[0].success
                        else None,
                        "volume_leaders": results[1].data
                        if isinstance(results[1], StandardResponse)
                        and results[1].success
                        else None,
                        "value_leaders": results[2].data
                        if isinstance(results[2], StandardResponse)
                        and results[2].success
                        else None,
                        "timestamp": datetime.now().isoformat(),
                    }
                else:
                    overview_data = {
                        "error": "Insufficient API responses",
                        "timestamp": datetime.now().isoformat(),
                    }

                return self.create_standard_response(
                    success=True, query=query, data=overview_data
                )

            except Exception as e:
                logger.error(f"Market overview error: {e}")
                return self.create_standard_response(
                    success=False, query=query, error=f"시장 개요 조회 실패: {str(e)}"
                )

        logger.info("Market domain tools registered successfully")


# === 서버 인스턴스 생성 ===


def create_market_domain_server(debug: bool = False) -> MarketDomainServer:
    """Market Domain 서버 인스턴스 생성"""
    return MarketDomainServer(debug=debug)


# === 메인 실행 ===


def main():
    """메인 실행 함수"""
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    parser = argparse.ArgumentParser(description="Kiwoom Market Domain Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=8031, help="Server port")
    args = parser.parse_args()

    # 서버 생성
    server = create_market_domain_server(debug=args.debug)

    # 포트 설정 (필요시)
    if args.port != 8031:
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
        logger.info(f"Starting Market Domain Server on port {server.port} with CORS middleware")
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
        logger.info("Market Domain Server stopped")


if __name__ == "__main__":
    main()
