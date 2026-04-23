"""
키움증권 MCP 서버 공통 기본 클라이언트

모든 키움 MCP 서버가 공유하는 기본 HTTP 클라이언트와 인증 로직을 제공합니다.
BaseHTTPClient를 확장하여 키움 API 특화 기능을 구현합니다.

Beginner notes:
    - Access token lifecycle: ``_get_access_token`` caches and refreshes tokens
      5 minutes before expiry to avoid mid-call failures.
    - Verification cache: ``check_api_verification`` reads a local cache file
      when available to warn about unverified APIs; it does not block execution.
    - Safety defaults: In connectivity/auth failures, ``_make_request`` returns
      a mock-style response for resilience in development.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

from src.mcp_servers.common.clients.base_client import (
    BaseHTTPClient,
    CircuitBreakerError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class KiwoomAPIResponse(BaseModel):
    """키움 API 표준 응답 모델"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    api_verified: bool = False  # API 검증 상태
    is_mock: bool = False  # Mock 데이터 여부

    @property
    def has_more_data(self) -> bool:
        """연속 조회 가능 여부 확인"""
        return self.headers and self.headers.get("cont-yn") == "Y"

    @property
    def next_key(self) -> Optional[str]:
        """다음 조회를 위한 키 값"""
        return self.headers.get("next-key") if self.headers else None

    def is_success(self) -> bool:
        """성공 여부 확인"""
        return self.success and self.error_code is None


class KiwoomAPIError(Exception):
    """키움 API 관련 오류"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        api_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.api_id = api_id


class KiwoomBaseClient(BaseHTTPClient):
    """키움증권 API 기본 클라이언트"""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        is_paper_mode: bool = True,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        키움 기본 클라이언트 초기화

        Args:
            app_key: 키움 앱 키
            app_secret: 키움 앱 시크릿
            account_no: 계좌번호
            is_paper_mode: 모의투자 모드 (기본: True)
            timeout: 요청 타임아웃 (초)
            max_retries: 재시도 횟수
        """
        super().__init__()

        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_paper_mode = is_paper_mode

        # API 도메인 설정
        self.api_domain = "mockapi.kiwoom.com" if is_paper_mode else "api.kiwoom.com"
        self.base_url = f"https://{self.api_domain}"

        # HTTP 클라이언트 설정
        self.timeout = timeout
        self.max_retries = max_retries

        # 인증 관련
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        # 클라이언트 인스턴스
        self._client: Optional[httpx.AsyncClient] = None

        # API 검증 상태 캐시
        self._api_verification_cache: Dict[str, Dict[str, Any]] = {}
        self._verification_cache_loaded = False

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        await self._ensure_client()
        # await self._load_api_verification_status()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        await self._close_client()

    async def _ensure_client(self) -> None:
        """HTTP 클라이언트 생성 보장"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            logger.info(f"키움 HTTP 클라이언트 생성 완료 (도메인: {self.api_domain})")

    async def _close_client(self) -> None:
        """HTTP 클라이언트 종료"""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("키움 HTTP 클라이언트 종료 완료")

    async def _load_api_verification_status(self) -> None:
        """API 검증 상태 로드"""
        if self._verification_cache_loaded:
            return

        verification_file = Path("docs/kiwoom_api_verification_status.json")

        try:
            if verification_file.exists():
                with open(verification_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._api_verification_cache = data.get("apis", {})
                logger.info(
                    f"API 검증 상태 로드 완료: {len(self._api_verification_cache)}개 API"
                )
            else:
                logger.warning(f"API 검증 상태 파일이 없습니다: {verification_file}")
        except Exception as e:
            logger.error(f"API 검증 상태 로드 실패: {e}")

        self._verification_cache_loaded = True

    def check_api_verification(self, api_id: str) -> Dict[str, Any]:
        """API 검증 상태 확인"""
        api_info = self._api_verification_cache.get(api_id, {})

        return {
            "api_id": api_id,
            "verification_status": api_info.get("verification_status", "UNVERIFIED"),
            "api_name": api_info.get("api_name", "Unknown"),
            "category": api_info.get("category", "unknown"),
            "test_date": api_info.get("test_date"),
            "error_message": api_info.get("error_message"),
            "is_verified": api_info.get("verification_status") == "VERIFIED",
        }

    async def _get_access_token(self) -> str:
        """OAuth 액세스 토큰 획득"""
        # 토큰이 유효한지 확인
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._access_token

        logger.info("키움 액세스 토큰 갱신 중...")

        await self._ensure_client()

        # OAuth 토큰 요청
        token_url = f"{self.base_url}/oauth2/token"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }

        try:
            response = await self._client.post(
                token_url,
                headers=headers,
                data=data,
            )
            response.raise_for_status()

            token_data = response.json()

            self._access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            logger.info(f"키움 액세스 토큰 획득 성공 (만료: {self._token_expires_at})")
            return self._access_token

        except httpx.HTTPStatusError as e:
            error_msg = f"키움 토큰 획득 실패 (HTTP {e.response.status_code})"
            logger.error(error_msg)
            raise KiwoomAPIError(error_msg, error_code="AUTH_FAILED") from e
        except Exception as e:
            error_msg = f"키움 토큰 획득 중 오류: {e}"
            logger.error(error_msg)
            raise KiwoomAPIError(error_msg, error_code="AUTH_ERROR") from e

    def _get_headers(
        self,
        api_id: str,
        cont_yn: Optional[str] = None,
        next_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """API 요청 헤더 생성"""
        headers = {
            "api-id": api_id,
            "authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "KiwoomMCPClient/1.0",
        }

        if cont_yn:
            headers["cont-yn"] = cont_yn
        if next_key:
            headers["next-key"] = next_key

        return headers

    async def _make_request(
        self,
        api_id: str,
        endpoint: str,
        data: Dict[str, Any],
        cont_yn: Optional[str] = None,
        next_key: Optional[str] = None,
    ) -> KiwoomAPIResponse:
        """키움 API 요청 실행"""

        # API 검증 상태 확인
        verification_info = self.check_api_verification(api_id)

        # 실거래 차단 체크
        if not self.is_paper_mode and self.production_disabled:
            return KiwoomAPIResponse(
                success=False,
                error_code="PRODUCTION_DISABLED",
                error_message="보안상 실거래는 차단되어 있습니다. 모의투자만 가능합니다.",
                api_verified=verification_info["is_verified"],
            )

        # 미검증 API 경고
        if verification_info["verification_status"] not in ["VERIFIED"]:
            logger.warning(
                f"️  API {api_id}는 검증되지 않은 상태입니다: {verification_info['verification_status']}"
            )

        await self._ensure_client()

        # 액세스 토큰 획득
        try:
            await self._get_access_token()
        except KiwoomAPIError:
            # 인증 실패시 Mock 응답 반환
            return self._create_mock_response(api_id, data, verification_info)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers(api_id, cont_yn, next_key)

        # 회로 차단기와 속도 제한 확인
        try:
            await self.circuit_breaker.call(lambda: None)  # 회로 상태 확인
            await self.rate_limiter.acquire()  # 속도 제한 확인
        except (CircuitBreakerError, RateLimitError) as e:
            return KiwoomAPIResponse(
                success=False,
                error_code="RATE_LIMITED",
                error_message=str(e),
                api_verified=verification_info["is_verified"],
            )

        # API 요청 실행
        try:
            logger.debug(f"키움 API 요청: {api_id} -> {url}")

            response = await self._client.post(url, headers=headers, json=data)
            response.raise_for_status()

            response_data = response.json()

            # 에러 응답 처리
            if "error" in response_data:
                error_info = response_data["error"]
                return KiwoomAPIResponse(
                    success=False,
                    error_code=error_info.get("code"),
                    error_message=error_info.get("message"),
                    api_verified=verification_info["is_verified"],
                )

            # 성공 응답
            self.circuit_breaker.record_success()

            return KiwoomAPIResponse(
                success=True,
                data=response_data,
                headers=dict(response.headers),
                api_verified=verification_info["is_verified"],
                is_mock=False,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"키움 API 오류 (HTTP {e.response.status_code})"
            logger.error(f"{api_id}: {error_msg}")

            self.circuit_breaker.record_failure()

            return KiwoomAPIResponse(
                success=False,
                error_code=f"HTTP_{e.response.status_code}",
                error_message=error_msg,
                api_verified=verification_info["is_verified"],
            )

        except Exception as e:
            error_msg = f"키움 API 요청 중 오류: {e}"
            logger.error(f"{api_id}: {error_msg}")

            self.circuit_breaker.record_failure()

            # 연결 실패시 Mock 응답 반환
            return self._create_mock_response(api_id, data, verification_info)

    async def close(self) -> None:
        """클라이언트 종료"""
        await self._close_client()
        logger.info("KiwoomBaseClient 종료 완료")
