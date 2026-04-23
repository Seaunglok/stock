"""
키움증권 통합 API 클라이언트

모든 MCP 서버에서 사용하는 통합 클라이언트입니다.
API Registry와 통합되어 178개 API를 자동으로 라우팅합니다.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Union

import httpx
from httpx import AsyncClient

from src.mcp_servers.kiwoom_mcp.common.constants import (
    KiwoomAPIID,
    KiwoomEndpoints,
    get_api,
    validate_params,
)

logger = logging.getLogger(__name__)


class KiwoomAPIError(Exception):
    """키움 API 에러"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, any] | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class KiwoomRESTAPIClient:
    """
    키움증권 통합 REST API 클라이언트

    특징:
    - 178개 전체 API 지원
    - API Registry 기반 자동 라우팅
    - Paper/Production 모드 지원
    - OAuth 2.0 인증 관리
    - 자동 재시도 및 에러 처리
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        account_no: Optional[str] = None,
        mode: str = "paper",  # paper, production only
    ):
        """
        통합 클라이언트 초기화

        Args:
            app_key: 키움 앱 키 (환경변수 대체 가능)
            app_secret: 키움 앱 시크릿 (환경변수 대체 가능)
            account_no: 계좌번호 (환경변수 대체 가능)
            mode: 실행 모드 (paper/production)
        """
        # 인증 정보 (필수)
        self.app_key = app_key or os.getenv("KIWOOM_APP_KEY")
        self.app_secret = app_secret or os.getenv("KIWOOM_APP_SECRET")
        self.account_no = account_no or os.getenv("KIWOOM_ACCOUNT_NO")

        # 인증 정보 필수 검증
        if not self.app_key or not self.app_secret or not self.account_no:
            missing = []
            if not self.app_key:
                missing.append("KIWOOM_APP_KEY")
            if not self.app_secret:
                missing.append("KIWOOM_APP_SECRET")
            if not self.account_no:
                missing.append("KIWOOM_ACCOUNT_NO")

            error_msg = f"필수 키움 API 환경변수가 없습니다: {', '.join(missing)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # 모드 설정 우선순위:
        # 1. 명시적 mode 파라미터 (최우선)
        # 2. KIWOOM_PRODUCTION_MODE 환경변수 (true면 production)
        # 3. 기본값: paper (모의투자)
        if mode and mode in [
            "paper",
            "production",
        ]:  # 명시적으로 mode가 지정되고 유효한 경우
            self.mode = mode
            logger.info(f" 명시적 모드 설정: {mode}")
        elif os.getenv("KIWOOM_PRODUCTION_MODE", "false").lower() == "true":
            self.mode = "production"
            logger.warning(" PRODUCTION MODE 활성화됨 - 실거래 주의!")
        else:
            self.mode = "paper"  # 기본값: 키움 공식 모의투자
            logger.info(" Paper Trading 모드 활성화됨 - 키움 모의투자")

        # API 엔드포인트 설정
        KiwoomEndpoints.set_mode(self.mode)
        self.base_url = KiwoomEndpoints.get_base_url()

        # HTTP 클라이언트 설정
        self.timeout = 60.0
        self.max_retries = 3
        self._client: Optional[AsyncClient] = None

        # 인증 토큰 관리
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        account_display = self.account_no[:4] + "****" if self.account_no else "None"
        logger.info(
            f" KiwoomRESTAPIClient 초기화 완료: "
            f"mode={self.mode}, base_url={self.base_url}, account={account_display}"
        )
        logger.info(
            f" 디버깅 정보 - 앱키: {'설정됨' if self.app_key else '없음'}, "
            f"시크릿: {'설정됨' if self.app_secret else '없음'}"
        )

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        await self.close()

    async def _ensure_client(self):
        """HTTP 클라이언트 확보"""
        if self._client is None:
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "FastCampusKiwoomClient",
            }

            self._client = AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )

    async def close(self):
        """클라이언트 리소스 정리"""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("UnifiedKiwoomClient closed")

    # === 인증 관리 ===

    async def _get_access_token(self) -> str:
        """액세스 토큰 획득 또는 갱신"""

        # 토큰이 유효하면 재사용
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._access_token

        # 새 토큰 요청
        await self._ensure_client()

        token_data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }

        try:
            response = await self._client.post("/oauth2/token", json=token_data)
            response.raise_for_status()

            token_info = response.json()
            self._access_token = token_info["token"]

            # 토큰 만료시간 설정
            expires_dt_str = token_info.get("expires_dt", "")
            if expires_dt_str:
                self._token_expires_at = datetime.strptime(
                    expires_dt_str, "%Y%m%d%H%M%S"
                )
            else:
                self._token_expires_at = datetime.now() + timedelta(hours=24)

            logger.info(f"Access token acquired, expires at: {self._token_expires_at}")
            return self._access_token

        except httpx.HTTPStatusError as e:
            error_msg = f"Token acquisition failed: {e.response.status_code}"
            logger.error(error_msg)
            raise KiwoomAPIError(error_msg, "AUTH_ERROR") from e
        except Exception as e:
            logger.error(f"Unexpected error during token acquisition: {e}")
            raise KiwoomAPIError(f"Token acquisition error: {e}", "AUTH_ERROR") from e

    # === 핵심 API 호출 메서드 ===

    async def call_api(
        self,
        api_id: Union[str, KiwoomAPIID],
        params: Optional[dict[str, any]] = None,
        **kwargs,
    ) -> dict[str, any]:
        """
        API Registry 기반 통합 API 호출

        Args:
            api_id: API ID (문자열 또는 KiwoomAPIID enum)
            params: API 파라미터
            **kwargs: 추가 파라미터 (params와 병합됨)

        Returns:
            API 응답 딕셔너리

        Raises:
            KiwoomAPIError: API 호출 실패
        """
        # API ID 정규화
        if isinstance(api_id, KiwoomAPIID):
            api_id = api_id.value

        # API 정보 조회
        api_info = get_api(api_id)
        if not api_info:
            raise KiwoomAPIError(f"Unknown API ID: {api_id}", "INVALID_API_ID")

        # 파라미터 병합
        all_params = {**(params or {}), **kwargs}

        # 파라미터 검증
        is_valid, missing = validate_params(api_id, all_params)
        if not is_valid:
            raise KiwoomAPIError(
                f"Missing required parameters for {api_id}: {missing}",
                "INVALID_PARAMS",
                {"missing": missing},
            )

        # API 호출
        method = api_info.get("method", "GET")
        endpoint = api_info.get("endpoint", "")

        return await self._make_request(
            method=method,
            endpoint=endpoint,
            api_id=api_id,
            params=all_params if method == "GET" else None,
            json_data=all_params if method in ["POST", "PUT", "PATCH"] else None,
        )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        api_id: str,
        params: Optional[dict[str, any]] = None,
        json_data: Optional[dict[str, any]] = None,
    ) -> dict[str, any]:
        """
        실제 HTTP 요청 수행

        Args:
            method: HTTP 메서드
            endpoint: API 엔드포인트
            api_id: API ID (헤더용)
            params: Query 파라미터
            json_data: Body 데이터

        Returns:
            API 응답
        """
        await self._ensure_client()

        # 인증 토큰 획득
        token = await self._get_access_token()

        # 키움 API 전용 헤더
        headers = KiwoomEndpoints.get_kiwoom_headers(
            api_id=api_id,
            access_token=token,
            app_key=self.app_key,
            app_secret=self.app_secret,
        )

        # 재시도 로직
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(
                    method=method,
                    url=endpoint,
                    params=params,
                    json=json_data,
                    headers=headers,
                )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 401:
                    # 토큰 만료시 재발급 후 재시도
                    logger.warning("Token expired, refreshing...")
                    self._access_token = None
                    token = await self._get_access_token()
                    headers["authorization"] = f"Bearer {token}"
                    continue
                elif e.response.status_code >= 500 and attempt < self.max_retries - 1:
                    # 서버 에러시 재시도
                    await asyncio.sleep(2**attempt)
                    continue
                else:
                    break
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                else:
                    break

        # 모든 재시도 실패
        error_msg = (
            f"API request failed after {self.max_retries} attempts: {last_error}"
        )
        logger.error(f"[{api_id}] {error_msg}")
        raise KiwoomAPIError(
            error_msg, "REQUEST_ERROR", {"api_id": api_id, "endpoint": endpoint}
        )

    # === 카테고리별 편의 메서드 ===

    async def auth_get_token(self) -> str:
        """OAuth 토큰 발급 (au10001)"""
        try:
            return await self._get_access_token()
        except Exception as e:
            raise KiwoomAPIError(f"Failed to get access token: {e}") from e

    async def auth_revoke_token(self) -> dict[str, any]:
        """OAuth 토큰 폐기 (au10002)"""
        result = await self.call_api(KiwoomAPIID.TOKEN_REVOKE)
        self._access_token = None
        self._token_expires_at = None
        return result

    async def get_stock_info(self, stock_code: str) -> dict[str, any]:
        """주식 기본정보 조회 (ka10001)"""
        return await self.call_api(KiwoomAPIID.STOCK_BASIC_INFO, stk_cd=stock_code)

    async def get_stock_price(
        self,
        stock_code: Optional[str] = None,
    ) -> dict[str, any]:
        """주식 현재가 조회 (ka10007 - 시세표성정보)"""
        return await self.call_api(
            "ka10007",  # 시세표성정보요청
            stk_cd=stock_code,
        )

    async def get_stock_orderbook(self, stock_code: str) -> dict[str, any]:
        """주식 호가 조회 (ka10004)"""
        return await self.call_api(KiwoomAPIID.STOCK_ORDERBOOK, stk_cd=stock_code)

    async def get_stock_chart(
        self,
        stock_code: str,
        chart_type: str = "daily",
        count: int = 100,
    ) -> dict[str, any]:
        """
        주식 차트 조회

        Args:
            stock_code: 종목코드
            chart_type: 차트 유형 (tick/minute/daily/weekly/monthly/yearly)
            count: 조회 개수
        """
        # 차트 유형별 API ID 매핑
        chart_api_map = {
            "tick": KiwoomAPIID.STOCK_TICK_CHART,
            "minute": KiwoomAPIID.STOCK_MINUTE_CHART,
            "daily": KiwoomAPIID.STOCK_DAILY_CHART,
            "weekly": KiwoomAPIID.STOCK_WEEKLY_CHART,
            "monthly": KiwoomAPIID.STOCK_MONTHLY_CHART,
            "yearly": KiwoomAPIID.STOCK_YEARLY_CHART,
        }

        api_id = chart_api_map.get(chart_type)
        if not api_id:
            raise KiwoomAPIError(
                f"Invalid chart type: {chart_type}", "INVALID_CHART_TYPE"
            )

        # 차트별 필수 파라미터 구성
        params = {"stk_cd": stock_code}

        if chart_type == "tick":
            params["tic_scope"] = "1"  # 틱 범위
            params["upd_stkpc_tp"] = "1"  # 수정주가 구분
        elif chart_type == "minute":
            params["intv"] = "1"  # 분 간격
            params["upd_stkpc_tp"] = "1"
        else:
            # daily, weekly, monthly, yearly
            params["prdt_cls"] = "A"  # 상품구분
            params["strt_dt"] = ""  # 시작일자 (빈값=최근부터)
            params["end_dt"] = ""  # 종료일자
            params["base_dt"] = datetime.now().strftime("%Y%m%d")  # 기준일자
            params["upd_stkpc_tp"] = "1"  # 수정주가 구분

        params["cnt"] = str(count)

        return await self.call_api(api_id, params)

    async def place_order(
        self,
        stock_code: str,
        order_type: str,  # buy/sell
        quantity: int,
        price: Optional[int] = None,
        order_method: str = "limit",  # limit/market
        account_no: Optional[str] = None,
    ) -> dict[str, any]:
        """
        주식 주문 (kt10000/kt10001)

        Args:
            stock_code: 종목코드
            order_type: 주문유형 (buy/sell)
            quantity: 주문수량
            price: 주문가격 (지정가일 때)
            order_method: 주문방법 (limit/market)
            account_no: 계좌번호
        """
        # API ID 결정
        if order_type.lower() == "buy":
            api_id = KiwoomAPIID.STOCK_BUY_ORDER
        elif order_type.lower() == "sell":
            api_id = KiwoomAPIID.STOCK_SELL_ORDER
        else:
            raise KiwoomAPIError(
                f"Invalid order type: {order_type}", "INVALID_ORDER_TYPE"
            )

        # 파라미터 구성
        params = {
            "dmst_stex_tp": "J",  # 국내증권거래소구분
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "trde_tp": "01" if order_method == "limit" else "02",  # 거래구분
        }

        if order_method == "limit" and price:
            params["ord_prc"] = str(price)

        # 계좌번호 (필요시)
        if account_no:
            params["acnt_no"] = account_no
        elif self.account_no:
            params["acnt_no"] = self.account_no

        return await self.call_api(api_id, params)

    async def get_account_balance(
        self, account_no: Optional[str] = None
    ) -> dict[str, any]:
        """
        계좌 잔고 조회 (kt00004 - 계좌평가현황)

        Args:
            account_no: 계좌번호
        """
        params = {
            "acnt_no": account_no or self.account_no,
            "inq_dt": datetime.now().strftime("%Y%m%d"),
            "qry_tp": "00",  # 조회구분
            "dmst_stex_tp": "J",  # 국내증권거래소구분
        }

        return await self.call_api("kt00004", params)

    async def get_sector_list(self) -> dict[str, any]:
        """업종 코드 리스트 조회 (ka10101)"""
        return await self.call_api(
            KiwoomAPIID.SECTOR_CODE_LIST,
            mrkt_tp="J",  # 시장구분 (J=전체)
        )

    async def get_theme_list(self) -> dict[str, any]:
        """테마 그룹 목록 조회 (ka90001)"""
        return await self.call_api(
            KiwoomAPIID.THEME_GROUP,
            qry_tp="00",  # 조회구분
            date_tp="D",  # 일자구분
            flu_pl_amt_tp="0",  # 변동금액구분
            stex_tp="J",  # 증권거래소구분
        )

    async def get_theme_stocks(self, theme_code: str) -> dict[str, any]:
        """테마 구성종목 조회 (ka90002)"""
        return await self.call_api(KiwoomAPIID.THEME_STOCKS, thema_grp_cd=theme_code)

    # === 배치 조회 메서드 ===

    async def get_multiple_stocks(
        self, stock_codes: list[str], api_id: Union[str, KiwoomAPIID]
    ) -> dict[str, any]:
        """
        여러 종목을 동시에 조회

        Args:
            stock_codes: 종목코드 리스트
            api_id: 사용할 API ID

        Returns:
            종목코드별 결과 딕셔너리
        """
        tasks = []
        for code in stock_codes:
            task = self.call_api(api_id, stk_cd=code)
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 매핑
        output = {}
        for code, result in zip(stock_codes, results, strict=True):
            if isinstance(result, Exception):
                output[code] = {"error": str(result)}
            else:
                output[code] = result

        return output

    # === 하위 호환성 메서드 (기존 kiwoom_client.py와 호환) ===

    async def get_market_data(
        self, symbols: list[str], fields: list[str]
    ) -> dict[str, any]:
        """다중 종목 시세 조회 (하위 호환용)"""
        result = {}

        for symbol in symbols:
            try:
                stock_data = await self.get_stock_price(symbol)

                # 요청된 필드만 추출
                filtered_data = {}
                for field in fields:
                    if field in stock_data:
                        filtered_data[field] = stock_data[field]

                result[symbol] = filtered_data

            except Exception as e:
                logger.warning(f"Failed to get data for {symbol}: {e}")
                result[symbol] = {"error": str(e)}

        return result

    async def get_order_book(self, symbol: str, depth: int = 10) -> dict[str, any]:
        """호가창 정보 조회 (하위 호환용)"""
        return await self.get_stock_orderbook(symbol)

    async def get_account_info(
        self, account_no: Optional[str] = None
    ) -> dict[str, any]:
        """계좌 정보 조회 (하위 호환용)"""
        return await self.get_account_balance(account_no)

    async def get_order_status(
        self, order_id: Optional[str] = None, account_no: Optional[str] = None
    ) -> dict[str, any]:
        """주문 상태 조회 (하위 호환용)"""
        # 미체결/체결 조회 (ka10075)
        params = {
            "acnt_no": account_no or self.account_no,
            "all_stk_tp": "0",  # 전체종목구분 (0=개별)
            "trde_tp": "00",  # 거래구분 (00=전체)
            "stex_tp": "J",  # 증권거래소구분
        }

        if order_id:
            params["ord_no"] = order_id

        return await self.call_api("ka10075", params)


# === 편의 함수 ===


async def create_client(mode: str = "paper") -> KiwoomRESTAPIClient:
    """
    클라이언트 생성 헬퍼

    Args:
        mode: 실행 모드 (paper/production)

    Returns:
        설정된 클라이언트 인스턴스
    """
    client = KiwoomRESTAPIClient(mode=mode)
    await client._ensure_client()
    return client
