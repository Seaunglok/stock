"""
Base HTTP client components for MCP servers.

Provides simple, reusable components for making HTTP requests with
rate limiting, circuit breaker pattern, and error handling.

Beginner notes:
    - Circuit breaker: Wrap async functions with ``SimpleCircuitBreaker.call``
      to automatically open the circuit after repeated failures. You can also
      manually mark outcomes via ``record_success()`` / ``record_failure()``.
    - Rate limiter: ``SimpleRateLimiter.acquire()`` implements a sliding window
      for per-second and per-hour limits. Always await it before requests.
    - Async only: The helpers here are designed for async HTTP clients
      (httpx.AsyncClient). For sync use, create a separate thin wrapper.
"""

import asyncio
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class CircuitBreakerError(Exception):
    """Circuit Breaker 활성화 시 발생하는 예외."""

    pass


class RateLimitError(Exception):
    """Rate Limit 초과 시 발생하는 예외."""

    pass


class SimpleCircuitBreaker:
    """
    간단한 Circuit Breaker 패턴 구현.

    kiwoom_mcp/client.py에서 추출한 간단하고 실용적인 버전입니다.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        Circuit Breaker 초기화.

        Args:
            failure_threshold: 실패 횟수 임계값
            recovery_timeout: 복구 대기 시간 (초)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func):
        """Wrap an async function call with circuit breaker semantics.

        The returned wrapper MUST be awaited. On success, resets the breaker;
        on exception, increments failure count and opens the circuit when the
        threshold is exceeded.
        """

        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if time.time() - self.last_failure_time < self.recovery_timeout:
                    raise CircuitBreakerError("Circuit breaker is OPEN")
                else:
                    self.state = "HALF_OPEN"

            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result
            except Exception:
                self._on_failure()
                raise

        return wrapper

    def _on_success(self):
        """Handle successful invocation: reset counters and close breaker."""
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        """Handle failed invocation: increment counters and open breaker."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                "circuit_breaker_opened",
                failure_count=self.failure_count,
                threshold=self.failure_threshold,
            )

    # Convenience methods used by some higher-level clients
    def record_success(self) -> None:
        """Manually record a successful call outcome."""
        self._on_success()

    def record_failure(self) -> None:
        """Manually record a failed call outcome."""
        self._on_failure()


class SimpleRateLimiter:
    """
    간단한 Rate Limiter 구현.

    kiwoom_mcp/client.py에서 추출한 슬라이딩 윈도우 방식입니다.
    """

    def __init__(self, requests_per_second: int = 10, requests_per_hour: int = 3600):
        """
        Rate Limiter 초기화.

        Args:
            requests_per_second: 초당 요청 제한
            requests_per_hour: 시간당 요청 제한
        """
        self.requests_per_second = requests_per_second
        self.requests_per_hour = requests_per_hour

        self.second_window = []
        self.hour_window = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Rate limit 체크 및 허용."""
        async with self._lock:
            current_time = time.time()

            # 1초 윈도우 정리
            self.second_window = [
                t for t in self.second_window if current_time - t < 1.0
            ]

            # 1시간 윈도우 정리
            self.hour_window = [
                t for t in self.hour_window if current_time - t < 3600.0
            ]

            # Rate limit 체크
            if len(self.second_window) >= self.requests_per_second:
                raise RateLimitError("초당 요청 제한 초과")

            if len(self.hour_window) >= self.requests_per_hour:
                raise RateLimitError("시간당 요청 제한 초과")

            # 요청 기록
            self.second_window.append(current_time)
            self.hour_window.append(current_time)


class BaseHTTPClient:
    """
    공용 HTTP 클라이언트 기본 클래스.

    재사용 가능한 HTTP 클라이언트 패턴을 제공합니다.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        requests_per_second: int = 10,
        requests_per_hour: int = 3600,
        enable_circuit_breaker: bool = True,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ):
        """
        HTTP 클라이언트 초기화.

        Args:
            base_url: 기본 URL
            timeout: 요청 타임아웃 (초)
            requests_per_second: 초당 요청 제한
            requests_per_hour: 시간당 요청 제한
            enable_circuit_breaker: Circuit Breaker 활성화 여부
            failure_threshold: 실패 횟수 임계값
            recovery_timeout: 복구 대기 시간 (초)
        """
        self.base_url = base_url

        # HTTP 클라이언트 설정
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        # Rate Limiter
        self.rate_limiter = SimpleRateLimiter(
            requests_per_second=requests_per_second, requests_per_hour=requests_per_hour
        )

        # Circuit Breaker
        self.circuit_breaker = (
            SimpleCircuitBreaker(
                failure_threshold=failure_threshold, recovery_timeout=recovery_timeout
            )
            if enable_circuit_breaker
            else None
        )

    async def __aenter__(self):
        """Context manager 진입."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager 종료."""
        await self.close()

    async def close(self):
        """리소스 정리."""
        await self.client.aclose()

    async def make_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        HTTP 요청 수행.

        Args:
            method: HTTP 메소드
            url: 요청 URL (상대 URL인 경우 base_url과 결합)
            params: Query 파라미터
            data: Request body 데이터
            headers: 추가 헤더
            **kwargs: 기타 httpx 파라미터

        Returns:
            API 응답 데이터
        """
        # Rate limiting
        await self.rate_limiter.acquire()

        # URL 구성
        if self.base_url and not url.startswith(("http://", "https://")):
            url = f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

        # 기본 헤더 설정
        request_headers = {
            "User-Agent": "MCP-Client/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)

        logger.debug(
            "http_request",
            method=method,
            url=url,
            has_data=data is not None,
            has_params=params is not None,
        )

        # Circuit Breaker 적용
        if self.circuit_breaker:
            request_func = self.circuit_breaker.call(self._execute_request)
        else:
            request_func = self._execute_request

        return await request_func(method, url, request_headers, params, data, **kwargs)

    async def _execute_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        **kwargs,
    ) -> dict[str, Any]:
        """실제 HTTP 요청 실행."""
        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                **kwargs,
            )
            response.raise_for_status()

            # JSON 응답 파싱
            if response.headers.get("content-type", "").startswith("application/json"):
                result = response.json()
            else:
                result = {"content": response.text, "status_code": response.status_code}

            logger.debug(
                "http_response",
                status_code=response.status_code,
                response_size=len(response.content),
            )

            return result

        except httpx.HTTPStatusError as e:
            logger.error(
                "http_request_failed",
                status_code=e.response.status_code,
                response=e.response.text,
                url=url,
            )
            raise
        except Exception as e:
            logger.error("http_request_error", error=str(e), url=url, exc_info=True)
            raise

    async def get(
        self, url: str, params: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        """GET 요청."""
        return await self.make_request("GET", url, params=params, **kwargs)

    async def post(
        self, url: str, data: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        """POST 요청."""
        return await self.make_request("POST", url, data=data, **kwargs)

    async def put(
        self, url: str, data: dict[str, Any] | None = None, **kwargs
    ) -> dict[str, Any]:
        """PUT 요청."""
        return await self.make_request("PUT", url, data=data, **kwargs)

    async def delete(self, url: str, **kwargs) -> dict[str, Any]:
        """DELETE 요청."""
        return await self.make_request("DELETE", url, **kwargs)
