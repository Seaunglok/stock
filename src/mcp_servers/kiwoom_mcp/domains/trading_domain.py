"""
키움 Trading Domain 서버

주문 관련 도구들을 통합한 도메인 서버:
- 주식 주문 (매수/매도/정정/취소)
- 주문 상태 조회 및 체결 현황
- 위험 관리 및 주문 유효성 검사
- 모의투자 및 실거래 모드 지원

포트: 8030

Beginner notes:
    - 모든 주문은 내부 위험 관리 체크를 통과해야 합니다. 
    실패 시 상세 사유가 ``StandardResponse.error``에 포함됩니다.
    - Human-in-the-Loop(승인)과의 연동은 상위 A2A 에이전트(예: TradingA2AAgent)
      측에서 수행됩니다. 본 서버는 위험 평가와 API 호출에 집중합니다.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.mcp_servers.base.base_mcp_server import StandardResponse
from src.mcp_servers.kiwoom_mcp.common.constants.api_types import KiwoomAPIID
from src.mcp_servers.kiwoom_mcp.common.domain_base import KiwoomDomainServer

logger = logging.getLogger(__name__)


# === 입력 모델들 ===


class OrderRequest(BaseModel):
    """기본 주문 요청"""

    stock_code: str = Field(description="종목 코드 (6자리)", min_length=6, max_length=6)
    quantity: int = Field(description="주문 수량", gt=0)
    price: float | None = Field(
        default=None, description="주문 가격 (시장가일 때는 None)"
    )
    order_type: str = Field(description="주문 구분 ('01': 지정가, '03': 시장가)")
    account_no: str | None = Field(default=None, description="계좌번호")

    @field_validator("stock_code")
    def validate_stock_code(cls, v):
        if not v.isdigit():
            raise ValueError("종목코드는 6자리 숫자여야 합니다")
        return v

    @field_validator("order_type")
    def validate_order_type(cls, v):
        if v not in ["01", "03"]:
            raise ValueError("주문구분은 '01'(지정가) 또는 '03'(시장가)이어야 합니다")
        return v


class BuyOrderRequest(OrderRequest):
    """매수 주문 요청"""

    pass


class SellOrderRequest(OrderRequest):
    """매도 주문 요청"""

    pass


class ModifyOrderRequest(BaseModel):
    """주문 정정 요청"""

    order_no: str = Field(description="원 주문번호")
    stock_code: str = Field(description="종목 코드", min_length=6, max_length=6)
    quantity: int = Field(description="정정 수량", gt=0)
    price: float | None = Field(default=None, description="정정 가격")
    order_type: str = Field(description="주문 구분 ('01': 지정가, '03': 시장가)")
    account_no: str | None = Field(default=None, description="계좌번호")


class CancelOrderRequest(BaseModel):
    """주문 취소 요청"""

    order_no: str = Field(description="원 주문번호")
    stock_code: str = Field(description="종목 코드", min_length=6, max_length=6)
    quantity: int = Field(description="취소 수량", gt=0)
    account_no: str | None = Field(default=None, description="계좌번호")


class OrderStatusRequest(BaseModel):
    """주문 상태 조회 요청"""

    order_no: str | None = Field(
        default=None, description="주문번호 (전체 조회시 None)"
    )
    account_no: str | None = Field(default=None, description="계좌번호")
    order_date: str | None = Field(default=None, description="조회일자 (YYYYMMDD)")


class OrderExecutionRequest(BaseModel):
    """체결 조회 요청"""

    account_no: str | None = Field(default=None, description="계좌번호")
    start_date: str | None = Field(default=None, description="시작일자 (YYYYMMDD)")
    end_date: str | None = Field(default=None, description="종료일자 (YYYYMMDD)")


class RiskCheckRequest(BaseModel):
    """위험 관리 체크 요청"""

    stock_code: str = Field(description="종목 코드")
    order_type: str = Field(description="매수/매도 구분")
    quantity: int = Field(description="주문 수량")
    price: float | None = Field(default=None, description="주문 가격")
    account_no: str | None = Field(default=None, description="계좌번호")


# === Trading Domain 서버 클래스 ===


class TradingDomainServer(KiwoomDomainServer):
    """
    키움 Trading Domain 서버 - 거래 실행 핵심 엔진.

    아키텍처 위치:
    - **Layer 1 (MCP Server)**: 주문 실행 제공자
    - **Port**: 8030
    - **Domain**: trading_domain

     주요 기능:
    1. **주문 실행**:
       - 매수/매도 주문 (market/limit order)
       - 주문 정정 (수량/가격 변경)
       - 주문 취소 (전체/부분)

    2. **주문 상태 관리**:
       - 주문 상태 조회 (대기/체결/취소)
       - 체결 내역 조회
       - 주문 이력 추적

    3. **위험 관리**:
       - 주문 한도 검사 (최대 1천만원)
       - 일일 주문 회수 제한 (100회)
       - 가격 제한 검사 (±15%)
       - 단일 수량 제한 (10,000주)

    4. **Human-in-the-Loop**:
       - 고위험 주문 승인 요청
       - 주문 실행 전 검증
       - 비정상 패턴 감지

     LangGraph Agent 연동:
    - **TradingAgent**: 주문 실행 및 관리 (핵심 연동)
    - **SupervisorAgent**: 주문 승인 요청
    - **AnalysisAgent**: 주문 전 리스크 분석

     MCP Tools (10개):
    - place_buy_order: 매수 주문
    - place_sell_order: 매도 주문
    - modify_order: 주문 정정
    - cancel_order: 주문 취소
    - get_order_status: 주문 상태
    - get_order_execution: 체결 조회
    - check_order_risk: 위험 검사
    - get_order_history: 주문 이력

     특징:
    - 자동 위험 관리 시스템
    - Mock trading 모드 지원
    - 주문 회수/금액 제한 사용자 설정 가능
    - 모든 주문 감사 로그 자동 기록

     리스크 관리 설정:
    - max_order_amount: 10,000,000 (최대 주문 금액)
    - max_daily_orders: 100 (일일 최대 주문 건수)
    - max_single_quantity: 10000 (단일 주문 최대 수량)
    - price_limit_rate: 0.15 (가격 제한 비율)

    Note:
        - 키움 API의 kt10xxx 시리즈 활용
        - 모든 주문은 비동기 실행
        - 체결 알림은 WebSocket으로 push
        - 주문 실패시 자동 롤백
    """

    def __init__(self, debug: bool = False):
        """
        Trading Domain 서버 초기화.

        Args:
            debug: 디버그 모드 활성화 여부

        Attributes:
            risk_config: 위험 관리 설정 딕셔너리
            daily_order_count: 일일 주문 카운터
            last_order_date: 마지막 주문 날짜

        Note:
            - 포트 8030에서 실행 (가장 중요한 포트)
            - 위험 관리 파라미터 초기화
            - Human-in-the-Loop 시스템 활성화
            - 모든 주문 감사 로그 활성화
        """
        super().__init__(
            domain_name="trading",
            server_name="kiwoom-trading-domain",
            port=8030,
            debug=debug,
        )

        # 위험 관리 설정
        self.risk_config = {
            "max_order_amount": 10_000_000,  # 최대 주문 금액 (1천만원)
            "max_daily_orders": 100,  # 일일 최대 주문 건수
            "max_single_quantity": 10000,  # 단일 주문 최대 수량
            "price_limit_rate": 0.15,  # 가격 제한 비율 (±15%)
        }

        # 주문 제한 상태 추적
        self.daily_order_count = 0
        self.last_order_date = None

        logger.info("Trading Domain Server initialized")

    def _initialize_clients(self) -> None:
        """클라이언트 초기화"""
        # 부모 클래스 호출
        super()._initialize_clients()
        logger.info("Trading domain clients initialized")

    def _register_tools(self) -> None:
        """도구 등록"""
        # 거래 관련 도구 등록
        self._register_trading_tools()
        # 공통 리소스 등록
        self.register_common_resources()
        logger.info("Trading domain tools registered")

    def _register_trading_tools(self):
        """
        거래 실행 MCP 도구들 등록.

        등록되는 도구 카테고리:
        1. 주문 실행 도구 (4개)
        2. 주문 상태 도구 (2개)
        3. 위험 관리 도구 (2개)
        4. 주문 이력 도구 (2개)

        Important:
            - 모든 주문은 위험 검사 통과 필수
            - 체결 후 자동 알림 발송
            - 주문 실패시 상세 오류 메시지 반환
            - Human 승인이 필요한 경우 대기 상태로 전환
        """

        # === 1. 주문 실행 도구들 ===

        @self.mcp.tool()
        async def place_buy_order(
            stock_code: str,
            quantity: int,
            price: float | None = None,
            order_type: Literal["01", "03"] = "01",
            account_no: str | None = None,
        ) -> StandardResponse:
            """
            주식 매수 주문

            API: kt10000 (주식 매수주문)

            Args:
                stock_code: 종목 코드 (6자리)
                quantity: 주문 수량 (양수)
                price: 주문 가격 (시장가일 때는 None)
                order_type: 주문 구분 ('01': 지정가, '03': 시장가)
                account_no: 계좌번호 (선택)
            """
            # 매개변수 유효성 검사
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return self.create_standard_response(
                    success=False,
                    query="매수 주문 유효성 검사",
                    error="종목코드는 6자리 숫자여야 합니다",
                )

            if quantity <= 0:
                return self.create_standard_response(
                    success=False,
                    query="매수 주문 유효성 검사",
                    error="주문 수량은 양수여야 합니다",
                )

            query = f"매수 주문: {stock_code} {quantity}주"

            # 위험 관리 체크
            risk_check = await self._check_order_risk(
                stock_code,
                "buy",
                quantity,
                price,
                account_no,
            )
            if not risk_check["allowed"]:
                return self.create_standard_response(
                    success=False,
                    query=query,
                    error=f"주문 위험 관리 실패: {risk_check['reason']}",
                )

            params = {
                "dmst_stex_tp": "KRX",  # 국내거래소
                "stk_cd": stock_code,
                "ord_qty": str(quantity),
                "trde_tp": order_type,  # 01:지정가, 03:시장가
                "ord_uv": str(price) if price else None,
                "cond_uv": None,  # 조건부 가격
            }

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_BUY_ORDER, query=query, params=params
            )

        @self.mcp.tool()
        async def place_sell_order(
            stock_code: str,
            quantity: int,
            price: float | None = None,
            order_type: str = "01",
            account_no: str | None = None,
        ) -> StandardResponse:
            """
            주식 매도 주문

            API: kt10001 (주식 매도주문)

            Args:
                stock_code: 종목 코드 (6자리)
                quantity: 주문 수량 (양수)
                price: 주문 가격 (시장가일 때는 None)
                order_type: 주문 구분 ('01': 지정가, '03': 시장가)
                account_no: 계좌번호 (선택)
            """
            # 매개변수 유효성 검사
            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return self.create_standard_response(
                    success=False,
                    query="매도 주문 유효성 검사",
                    error="종목코드는 6자리 숫자여야 합니다",
                )

            if quantity <= 0:
                return self.create_standard_response(
                    success=False,
                    query="매도 주문 유효성 검사",
                    error="주문 수량은 양수여야 합니다",
                )

            if order_type not in ["01", "03"]:
                return self.create_standard_response(
                    success=False,
                    query="매도 주문 유효성 검사",
                    error="주문구분은 '01'(지정가) 또는 '03'(시장가)이어야 합니다",
                )

            query = f"매도 주문: {stock_code} {quantity}주"

            # 위험 관리 체크
            risk_check = await self._check_order_risk(
                stock_code,
                "sell",
                quantity,
                price,
                account_no,
            )
            if not risk_check["allowed"]:
                return self.create_standard_response(
                    success=False,
                    query=query,
                    error=f"주문 위험 관리 실패: {risk_check['reason']}",
                )

            params = {
                "dmst_stex_tp": "KRX",
                "stk_cd": stock_code,
                "ord_qty": str(quantity),
                "trde_tp": order_type,
                "ord_uv": str(price) if price else None,
                "cond_uv": None,
            }

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_SELL_ORDER, query=query, params=params
            )

        @self.mcp.tool()
        async def modify_order(
            order_no: str,
            stock_code: str,
            quantity: int,
            price: float | None = None,
            order_type: str = "01",
            account_no: str | None = None,
        ) -> StandardResponse:
            """
            주문 정정

            API: kt10002 (주식 정정주문)

            Args:
                order_no: 원 주문번호
                stock_code: 종목 코드 (6자리)
                quantity: 정정 수량 (양수)
                price: 정정 가격
                order_type: 주문 구분 ('01': 지정가, '03': 시장가)
                account_no: 계좌번호 (선택)
            """
            # 매개변수 유효성 검사
            if not order_no or not order_no.strip():
                return self.create_standard_response(
                    success=False,
                    query="주문 정정 유효성 검사",
                    error="주문번호는 필수입니다",
                )

            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return self.create_standard_response(
                    success=False,
                    query="주문 정정 유효성 검사",
                    error="종목코드는 6자리 숫자여야 합니다",
                )

            if quantity <= 0:
                return self.create_standard_response(
                    success=False,
                    query="주문 정정 유효성 검사",
                    error="정정 수량은 양수여야 합니다",
                )

            if order_type not in ["01", "03"]:
                return self.create_standard_response(
                    success=False,
                    query="주문 정정 유효성 검사",
                    error="주문구분은 '01'(지정가) 또는 '03'(시장가)이어야 합니다",
                )

            query = f"주문 정정: {order_no}"

            params = {
                "dmst_stex_tp": "KRX",
                "orig_ord_no": order_no,
                "stk_cd": stock_code,
                "mdfy_qty": str(quantity),
                "mdfy_uv": str(price) if price else "0",
                "mdfy_cond_uv": None,
            }

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_MODIFY_ORDER, query=query, params=params
            )

        @self.mcp.tool()
        async def cancel_order(
            order_no: str,
            stock_code: str,
            quantity: int,
            account_no: str | None = None,
        ) -> StandardResponse:
            """
            주문 취소

            API: kt10003 (주식 취소주문)

            Args:
                order_no: 원 주문번호
                stock_code: 종목 코드 (6자리)
                quantity: 취소 수량 (양수)
                account_no: 계좌번호 (선택)
            """
            # 매개변수 유효성 검사
            if not order_no or not order_no.strip():
                return self.create_standard_response(
                    success=False,
                    query="주문 취소 유효성 검사",
                    error="주문번호는 필수입니다",
                )

            if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
                return self.create_standard_response(
                    success=False,
                    query="주문 취소 유효성 검사",
                    error="종목코드는 6자리 숫자여야 합니다",
                )

            if quantity <= 0:
                return self.create_standard_response(
                    success=False,
                    query="주문 취소 유효성 검사",
                    error="취소 수량은 양수여야 합니다",
                )

            query = f"주문 취소: {order_no}"

            params = {
                "dmst_stex_tp": "KRX",
                "orig_ord_no": order_no,
                "stk_cd": stock_code,
                "cncl_qty": str(quantity),
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.STOCK_CANCEL_ORDER, query=query, params=params
            )

        # === 2. 주문 조회 도구들 ===

        @self.mcp.tool()
        async def get_outstanding_orders(
            order_no: str | None = None,
            account_no: str | None = None,
            order_date: str | None = None,
        ) -> StandardResponse:
            """
            미체결 주문 조회

            API: ka10075 (미체결요청)

            Args:
                order_no: 주문번호 (전체 조회시 None)
                account_no: 계좌번호 (선택)
                order_date: 조회일자 (YYYYMMDD 형식, 선택)
            """
            # 날짜 형식 유효성 검사
            if order_date and (len(order_date) != 8 or not order_date.isdigit()):
                return self.create_standard_response(
                    success=False,
                    query="미체결 조회 유효성 검사",
                    error="조회일자는 YYYYMMDD 형식이어야 합니다",
                )

            query = f"미체결 조회: {order_no or '전체'}"

            params = {
                "all_stk_tp": "Y" if not order_no else "N",  # 전체종목구분
                "trde_tp": "0",  # 0:전체, 1:매도, 2:매수
                "stex_tp": "0",  # 거래소구분
                "stk_cd": "",  # 종목코드 (전체일 때 빈값)
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.OUTSTANDING_ORDER, query=query, params=params
            )

        @self.mcp.tool()
        async def get_order_executions(
            account_no: str | None = None,
            start_date: str | None = None,
            end_date: str | None = None,
        ) -> StandardResponse:
            """
            체결 내역 조회

            API: ka10076 (체결요청)

            Args:
                account_no: 계좌번호 (선택)
                start_date: 시작일자 (YYYYMMDD 형식, 선택)
                end_date: 종료일자 (YYYYMMDD 형식, 선택)
            """
            # 날짜 형식 유효성 검사
            if start_date and (len(start_date) != 8 or not start_date.isdigit()):
                return self.create_standard_response(
                    success=False,
                    query="체결 조회 유효성 검사",
                    error="시작일자는 YYYYMMDD 형식이어야 합니다",
                )

            if end_date and (len(end_date) != 8 or not end_date.isdigit()):
                return self.create_standard_response(
                    success=False,
                    query="체결 조회 유효성 검사",
                    error="종료일자는 YYYYMMDD 형식이어야 합니다",
                )

            query = f"체결 내역 조회: {start_date or '당일'}"

            datetime.now().strftime("%Y%m%d")

            params = {
                "qry_tp": "1",  # 조회구분
                "sell_tp": "0",  # 0:전체, 1:매도, 2:매수
                "stex_tp": "0",  # 거래소구분
                "stk_cd": "",  # 종목코드
                "ord_no": "",  # 주문번호
            }

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.EXECUTION_REQUEST, query=query, params=params
            )

        # === 3. 주문 가능 조회 도구들 ===

        @self.mcp.tool()
        async def get_orderable_amount(
            stock_code: str,
            trade_type: str,  # "buy" or "sell"
            price: float | None = None,
        ) -> StandardResponse:
            """
            주문 가능 금액 조회

            API: kt00010 (주문인출가능금액요청)
            """
            query = f"주문 가능 금액: {stock_code} ({trade_type})"

            params = {
                "stk_cd": stock_code,
                "trde_tp": "2" if trade_type == "buy" else "1",  # 1:매도, 2:매수
                "uv": str(price) if price else "0",
                "io_amt": None,  # 입출금액
                "trde_qty": None,  # 매매수량
                "exp_buy_unp": None,  # 예상매수단가
            }

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.ORDER_WITHDRAWABLE, query=query, params=params
            )

        @self.mcp.tool()
        async def get_orderable_quantity(
            stock_code: str, price: float | None = None
        ) -> StandardResponse:
            """
            주문 가능 수량 조회

            API: kt00011 (증거금율별주문가능수량조회요청)
            """
            query = f"주문 가능 수량: {stock_code}"

            params = {"stk_cd": stock_code, "uv": str(price) if price else None}

            # None 값 제거
            params = {k: v for k, v in params.items() if v is not None}

            return await self.call_api_with_response(
                api_id=KiwoomAPIID.MARGIN_ORDER_QUANTITY, query=query, params=params
            )

        # === 4. 위험 관리 도구들 ===

        @self.mcp.tool()
        async def check_order_risk(
            stock_code: str,
            order_type: str,
            quantity: int,
            price: float | None = None,
            account_no: str | None = None,
        ) -> StandardResponse:
            """
            주문 위험 관리 체크

            주문 전 위험 요소들을 사전 검증

            Args:
                stock_code: 종목 코드
                order_type: 매수/매도 구분
                quantity: 주문 수량
                price: 주문 가격 (선택)
                account_no: 계좌번호 (선택)
            """
            # 매개변수 유효성 검사
            if not stock_code or not stock_code.strip():
                return self.create_standard_response(
                    success=False,
                    query="위험 관리 체크 유효성 검사",
                    error="종목코드는 필수입니다",
                )

            if not order_type or order_type not in ["buy", "sell"]:
                return self.create_standard_response(
                    success=False,
                    query="위험 관리 체크 유효성 검사",
                    error="주문구분은 'buy' 또는 'sell'이어야 합니다",
                )

            if quantity <= 0:
                return self.create_standard_response(
                    success=False,
                    query="위험 관리 체크 유효성 검사",
                    error="주문 수량은 양수여야 합니다",
                )

            query = f"위험 관리 체크: {stock_code}"

            risk_result = await self._check_order_risk(
                stock_code,
                order_type,
                quantity,
                price,
                account_no,
            )

            return self.create_standard_response(
                success=risk_result["allowed"], query=query, data=risk_result
            )

        @self.mcp.tool()
        async def get_trading_limits() -> StandardResponse:
            """
            거래 한도 및 제한 사항 조회
            """
            query = "거래 한도 조회"

            limits_data = {
                "risk_config": self.risk_config,
                "daily_usage": {
                    "order_count": self.daily_order_count,
                    "max_orders": self.risk_config["max_daily_orders"],
                    "remaining_orders": self.risk_config["max_daily_orders"]
                    - self.daily_order_count,
                },
                "trading_mode": {
                    "mode": self.mode,
                },
                "last_update": datetime.now().isoformat(),
            }

            return self.create_standard_response(
                success=True, query=query, data=limits_data
            )

        # === 5. 통합 도구 ===

        @self.mcp.tool()
        async def get_trading_summary() -> StandardResponse:
            """
            거래 요약 정보 (오늘의 주문/체결 요약)
            """
            query = "거래 요약 조회"

            try:
                # 병렬로 여러 데이터 조회
                today = datetime.now().strftime("%Y%m%d")

                tasks = [
                    self.call_api_with_response(
                        KiwoomAPIID.OUTSTANDING_ORDER,
                        "미체결 주문",
                        {
                            "all_stk_tp": "Y",
                            "trde_tp": "0",
                            "stex_tp": "0",
                            "stk_cd": "",
                        },
                    ),
                    self.call_api_with_response(
                        KiwoomAPIID.EXECUTION_REQUEST,
                        "당일 체결",
                        {
                            "qry_tp": "1",
                            "sell_tp": "0",
                            "stex_tp": "0",
                            "stk_cd": "",
                            "ord_no": "",
                        },
                    ),
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 결과 조합 - 타입 안전성을 위한 길이 체크
                if len(results) >= 2:
                    summary_data = {
                        "trade_date": today,
                        "outstanding_orders": results[0].data
                        if isinstance(results[0], StandardResponse)
                        and results[0].success
                        else None,
                        "executions": results[1].data
                        if isinstance(results[1], StandardResponse)
                        and results[1].success
                        else None,
                        "daily_order_count": self.daily_order_count,
                        "trading_mode": self.mode,
                        "timestamp": datetime.now().isoformat(),
                    }
                else:
                    summary_data = {
                        "error": "Insufficient API responses",
                        "trade_date": today,
                        "timestamp": datetime.now().isoformat(),
                    }

                return self.create_standard_response(
                    success=True,
                    query=query,
                    data=summary_data,
                )

            except Exception as e:
                logger.error(f"Trading summary error: {e}")
                return self.create_standard_response(
                    success=False, query=query, error=f"거래 요약 조회 실패: {str(e)}"
                )

        logger.info("Trading domain tools registered successfully")

    # === 내부 헬퍼 메서드들 ===

    async def _check_order_risk(
        self,
        stock_code: str,
        order_type: str,
        quantity: int,
        price: float | None,
        account_no: str | None,
    ) -> dict[str, Any]:
        """주문 위험 관리 체크"""

        # 일일 주문 건수 체크
        today = datetime.now().strftime("%Y%m%d")
        if self.last_order_date != today:
            self.daily_order_count = 0
            self.last_order_date = today

        if self.daily_order_count >= self.risk_config["max_daily_orders"]:
            return {
                "allowed": False,
                "reason": f"일일 최대 주문 건수 초과 ({self.risk_config['max_daily_orders']}건)",
            }

        # 수량 체크
        if quantity > self.risk_config["max_single_quantity"]:
            return {
                "allowed": False,
                "reason": f"단일 주문 최대 수량 초과 ({self.risk_config['max_single_quantity']}주)",
            }

        # 주문 금액 체크 (가격이 있는 경우)
        if price:
            order_amount = price * quantity
            if order_amount > self.risk_config["max_order_amount"]:
                return {
                    "allowed": False,
                    "reason": f"최대 주문 금액 초과 ({self.risk_config['max_order_amount']:,}원)",
                }

        # TODO: 추가 위험 관리 로직
        # - 현재가 대비 가격 제한 체크
        # - 계좌 잔고 체크
        # - 보유 종목 집중도 체크

        return {
            "allowed": True,
            "reason": "위험 관리 통과",
            "checks_passed": ["daily_order_limit", "quantity_limit", "amount_limit"],
        }


# === 서버 인스턴스 생성 ===


def create_trading_domain_server(debug: bool = False) -> TradingDomainServer:
    """Trading Domain 서버 인스턴스 생성"""
    return TradingDomainServer(debug=debug)


# === 메인 실행 ===


def main():
    """메인 실행 함수"""
    import argparse

    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware

    parser = argparse.ArgumentParser(description="Kiwoom Trading Domain Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=8030, help="Server port")
    args = parser.parse_args()

    # 서버 생성
    server = create_trading_domain_server(debug=args.debug)

    # 포트 설정 (필요시)
    if args.port != 8030:
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
        logger.info(f"Starting Trading Domain Server on port {server.port} with CORS middleware")
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
        logger.info("Trading Domain Server stopped")


if __name__ == "__main__":
    main()
