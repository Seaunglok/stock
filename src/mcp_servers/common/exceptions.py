"""
MCP 서버 공통 예외 처리 체계

모든 MCP 서버에서 사용할 수 있는 일관된 예외 클래스와 에러 핸들링 데코레이터를 제공합니다.

Usage:
    from mcp_servers.common.exceptions import MCPError, handle_mcp_errors

    @handle_mcp_errors
    async def my_tool_function():
        raise ValidationError("Invalid input data", details={"field": "symbol"})
"""

import contextvars
import functools
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional, TypeVar

import structlog

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# 추적 ID 및 컨텍스트 전파 시스템 (Tracing & Context Propagation)
# =============================================================================

# 컨텍스트 변수 정의 - 비동기 안전 추적 ID 전파
trace_context = contextvars.ContextVar("trace_context", default=None)
request_context = contextvars.ContextVar("request_context", default=None)


class TraceContext:
    """
    추적 컨텍스트 클래스

    요청별 고유 추적 ID와 관련 메타데이터를 관리합니다.
    비동기 환경에서 안전하게 컨텍스트를 전파합니다.
    """

    def __init__(
        self,
        trace_id: str | None = None,
        parent_id: str | None = None,
        span_id: str | None = None,
        operation_name: str | None = None,
    ):
        self.trace_id = trace_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.span_id = span_id or str(uuid.uuid4())[:8]  # 8자리 span ID
        self.operation_name = operation_name
        self.start_time = time.perf_counter()
        self.metadata: dict[str, any] = {}
        self.tags: dict[str, str] = {}

    def add_tag(self, key: str, value: str) -> "TraceContext":
        """태그 추가"""
        self.tags[key] = value
        return self

    def add_metadata(self, key: str, value: any) -> "TraceContext":
        """메타데이터 추가"""
        self.metadata[key] = value
        return self

    def get_duration(self) -> float:
        """현재까지의 실행 시간 반환 (초)"""
        return time.perf_counter() - self.start_time

    def to_dict(self) -> dict[str, any]:
        """딕셔너리 형태로 변환"""
        return {
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "span_id": self.span_id,
            "operation_name": self.operation_name,
            "duration_ms": round(self.get_duration() * 1000, 2),
            "metadata": self.metadata,
            "tags": self.tags,
        }


class RequestContext:
    """
    요청 컨텍스트 클래스

    요청별 추가 정보 (사용자 ID, 세션 정보 등)를 관리합니다.
    """

    def __init__(
        self,
        request_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        client_info: dict[str, any] | None = None,
    ):
        self.request_id = request_id or str(uuid.uuid4())
        self.user_id = user_id
        self.session_id = session_id
        self.client_info = client_info or {}
        self.timestamp = datetime.now(UTC)

    def to_dict(self) -> dict[str, any]:
        """딕셔너리 형태로 변환"""
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "client_info": self.client_info,
            "timestamp": self.timestamp.isoformat(),
        }


# 컨텍스트 접근 및 설정 함수들
def get_trace_context() -> TraceContext | None:
    """현재 추적 컨텍스트 반환"""
    return trace_context.get()


def set_trace_context(context: TraceContext) -> None:
    """추적 컨텍스트 설정"""
    trace_context.set(context)


def get_request_context() -> RequestContext | None:
    """현재 요청 컨텍스트 반환"""
    return request_context.get()


def set_request_context(context: RequestContext) -> None:
    """요청 컨텍스트 설정"""
    request_context.set(context)


def get_trace_id() -> str:
    """현재 추적 ID 반환 (없으면 새로 생성)"""
    context = trace_context.get()
    return context.trace_id if context else str(uuid.uuid4())


def get_span_id() -> str:
    """현재 스팬 ID 반환 (없으면 새로 생성)"""
    context = trace_context.get()
    return context.span_id if context else str(uuid.uuid4())[:8]


def create_child_trace_context(operation_name: str) -> TraceContext:
    """자식 추적 컨텍스트 생성"""
    parent = trace_context.get()
    if parent:
        return TraceContext(
            trace_id=parent.trace_id,
            parent_id=parent.span_id,
            operation_name=operation_name,
        )
    else:
        return TraceContext(operation_name=operation_name)


# JSON 포맷 로깅 지원 함수들
def create_log_context() -> dict[str, any]:
    """로그용 컨텍스트 정보 생성"""
    trace_ctx = trace_context.get()
    request_ctx = request_context.get()

    log_context = {"timestamp": datetime.now(UTC).isoformat(), "service": "mcp_server"}

    if trace_ctx:
        log_context.update(
            {
                "trace_id": trace_ctx.trace_id,
                "span_id": trace_ctx.span_id,
                "parent_id": trace_ctx.parent_id,
                "operation": trace_ctx.operation_name,
                "duration_ms": round(trace_ctx.get_duration() * 1000, 2),
            }
        )

    if request_ctx:
        log_context.update(
            {
                "request_id": request_ctx.request_id,
                "user_id": request_ctx.user_id,
                "session_id": request_ctx.session_id,
            }
        )

    return log_context


def log_with_context(level: str, message: str, **kwargs) -> None:
    """컨텍스트 정보를 포함한 로깅"""
    log_data = create_log_context()
    log_data.update(kwargs)

    # structlog을 사용한 구조화 로깅
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message, **log_data)


def trace_operation(operation_name: str):
    """오퍼레이션 추적 컨텍스트 매니저"""

    class TraceContextManager:
        def __init__(self, op_name: str):
            self.operation_name = op_name
            self.trace_ctx = None
            self.original_ctx = None

        def __enter__(self):
            self.original_ctx = trace_context.get()
            self.trace_ctx = create_child_trace_context(self.operation_name)
            set_trace_context(self.trace_ctx)
            return self.trace_ctx

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.original_ctx:
                set_trace_context(self.original_ctx)
            else:
                # 컨텍스트를 완전히 제거
                trace_context.set(None)

        async def __aenter__(self):
            return self.__enter__()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return self.__exit__(exc_type, exc_val, exc_tb)

    return TraceContextManager(operation_name)


class ErrorSeverity(Enum):
    """에러 심각도 레벨"""

    LOW = "low"  # 사용자 입력 오류 등 예상 가능한 에러
    MEDIUM = "medium"  # API 연결 실패 등 시스템 수준 에러
    HIGH = "high"  # 데이터 손실 가능성 있는 에러
    CRITICAL = "critical"  # 서비스 중단을 야기하는 에러


class MCPError(Exception):
    """
    MCP 서버 기본 예외 클래스

    모든 MCP 관련 예외의 기본 클래스로, 표준화된 에러 응답 생성 기능을 제공합니다.

    Attributes:
        message: 에러 메시지
        error_code: 에러 코드 (기본값: 클래스명의 대문자)
        details: 추가 에러 상세 정보
        severity: 에러 심각도
        retryable: 재시도 가능 여부

    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        self.details = details or {}
        self.severity = severity
        self.retryable = retryable
        self.timestamp = datetime.now(UTC).isoformat()

    def to_response(self) -> dict[str, any]:
        """
        표준 에러 응답 포맷 생성 (추적 컨텍스트 포함)

        Returns:
            MCP 표준 에러 응답 딕셔너리

        """
        error_response = {
            "success": False,
            "error": {
                "code": self.error_code,
                "message": self.message,
                "details": self.details,
                "severity": self.severity.value,
                "retryable": self.retryable,
                "timestamp": self.timestamp,
            },
        }

        # 추적 컨텍스트 정보 추가
        trace_ctx = get_trace_context()
        request_ctx = get_request_context()

        if trace_ctx or request_ctx:
            tracing_info = {}

            if trace_ctx:
                tracing_info.update(
                    {
                        "trace_id": trace_ctx.trace_id,
                        "span_id": trace_ctx.span_id,
                        "parent_id": trace_ctx.parent_id,
                        "operation": trace_ctx.operation_name,
                    }
                )

            if request_ctx:
                tracing_info.update(
                    {
                        "request_id": request_ctx.request_id,
                        "user_id": request_ctx.user_id,
                        "session_id": request_ctx.session_id,
                    }
                )

            error_response["tracing"] = tracing_info

        return error_response

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"error_code='{self.error_code}', "
            f"severity={self.severity.value})"
        )


class APIError(MCPError):
    """
    외부 API 호출 실패 예외

    키움증권 API, FinanceDataReader 등 외부 API 호출 시 발생하는 에러를 처리합니다.
    """

    def __init__(
        self,
        message: str,
        api_name: str | None = None,
        status_code: int | None = None,
        response_data: dict[str, any] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if api_name:
            details["api_name"] = api_name
        if status_code:
            details["status_code"] = status_code
        if response_data:
            details["response_data"] = response_data

        super().__init__(
            message=message,
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", True),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "severity", "retryable"]
            },
        )


class ValidationError(MCPError):
    """
    데이터 검증 실패 예외

    입력 데이터 검증, 파라미터 유효성 검사 등에서 발생하는 에러를 처리합니다.
    """

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        expected_format: Optional[str] = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if field_name:
            details["field_name"] = field_name
        if field_value is not None:
            details["field_value"] = str(field_value)
        if expected_format:
            details["expected_format"] = expected_format

        super().__init__(
            message=message,
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.LOW),
            retryable=False,
            **{k: v for k, v in kwargs.items() if k not in ["details", "severity"]},
        )


class AuthError(MCPError):
    """
    인증/인가 실패 예외

    API 키 인증 실패, 권한 부족 등 인증 관련 에러를 처리합니다.
    """

    def __init__(
        self,
        message: str,
        auth_type: str | None = None,
        required_permissions: list[str] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if auth_type:
            details["auth_type"] = auth_type
        if required_permissions:
            details["required_permissions"] = required_permissions

        super().__init__(
            message=message,
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.HIGH),
            retryable=False,
            **{k: v for k, v in kwargs.items() if k not in ["details", "severity"]},
        )


class ResourceError(MCPError):
    """
    리소스 접근 실패 예외

    파일 읽기/쓰기 실패, 데이터베이스 연결 실패 등 리소스 관련 에러를 처리합니다.
    """

    def __init__(
        self,
        message: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        operation: str | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if resource_type:
            details["resource_type"] = resource_type
        if resource_id:
            details["resource_id"] = resource_id
        if operation:
            details["operation"] = operation

        super().__init__(
            message=message,
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", True),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "severity", "retryable"]
            },
        )


class RateLimitError(MCPError):
    """
    Rate Limit 초과 예외

    API 호출 빈도 제한 초과 시 발생하는 에러를 처리합니다.
    """

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        current_rate: int | None = None,
        rate_limit: int | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if retry_after:
            details["retry_after_seconds"] = retry_after
        if current_rate:
            details["current_rate"] = current_rate
        if rate_limit:
            details["rate_limit"] = rate_limit

        super().__init__(
            message=message,
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.LOW),
            retryable=True,
            **{k: v for k, v in kwargs.items() if k not in ["details", "severity"]},
        )


def handle_mcp_errors(
    default_message: str | None = None,
    log_traceback: bool = True,
    reraise_on_critical: bool = True,
) -> Callable[[F], F]:
    """
    MCP 에러 처리 데코레이터

    모든 MCP 도구 함수에 적용하여 일관된 에러 처리와 로깅을 제공합니다.

    Args:
        default_message: 예상치 못한 에러 발생 시 기본 메시지
        log_traceback: 상세 트레이스백 로깅 여부
        reraise_on_critical: 심각한 에러 시 재발생 여부

    Returns:
        데코레이터 함수

    Example:
        @handle_mcp_errors(default_message="도구 실행 실패")
        async def my_mcp_tool(symbol: str) -> Dict[str, any]:
            if not symbol:
                raise ValidationError("종목 코드가 필요합니다", field_name="symbol")
            return {"data": "success"}

    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return _ensure_success_response(result)
            except MCPError as e:
                return _handle_mcp_error(
                    e, func.__name__, log_traceback, reraise_on_critical
                )
            except Exception as e:
                return _handle_unexpected_error(
                    e,
                    func.__name__,
                    default_message,
                    log_traceback,
                    reraise_on_critical,
                )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                return _ensure_success_response(result)
            except MCPError as e:
                return _handle_mcp_error(
                    e, func.__name__, log_traceback, reraise_on_critical
                )
            except Exception as e:
                return _handle_unexpected_error(
                    e,
                    func.__name__,
                    default_message,
                    log_traceback,
                    reraise_on_critical,
                )

        # 비동기 함수 여부 확인
        if hasattr(func, "__code__") and func.__code__.co_flags & 0x80:  # CO_COROUTINE
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


def _ensure_success_response(result: any) -> dict[str, any]:
    """
    응답 형태를 표준 포맷으로 보장 (추적 컨텍스트 포함)

    Args:
        result: 함수 실행 결과

    Returns:
        표준 성공 응답 포맷

    """
    if isinstance(result, dict) and "success" in result:
        # 기존에 성공 응답이 있다면 추적 정보만 추가
        trace_ctx = get_trace_context()
        request_ctx = get_request_context()

        if (trace_ctx or request_ctx) and "tracing" not in result:
            tracing_info = {}

            if trace_ctx:
                tracing_info.update(
                    {
                        "trace_id": trace_ctx.trace_id,
                        "span_id": trace_ctx.span_id,
                        "operation": trace_ctx.operation_name,
                    }
                )

            if request_ctx:
                tracing_info.update({"request_id": request_ctx.request_id})

            result["tracing"] = tracing_info

        return result

    # 새로운 성공 응답 생성
    success_response = {
        "success": True,
        "data": result,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # 추적 컨텍스트 정보 추가
    trace_ctx = get_trace_context()
    request_ctx = get_request_context()

    if trace_ctx or request_ctx:
        tracing_info = {}

        if trace_ctx:
            tracing_info.update(
                {
                    "trace_id": trace_ctx.trace_id,
                    "span_id": trace_ctx.span_id,
                    "operation": trace_ctx.operation_name,
                    "duration_ms": round(trace_ctx.get_duration() * 1000, 2),
                }
            )

        if request_ctx:
            tracing_info.update({"request_id": request_ctx.request_id})

        success_response["tracing"] = tracing_info

    return success_response


def _handle_mcp_error(
    error: MCPError, function_name: str, log_traceback: bool, reraise_on_critical: bool
) -> dict[str, any] | None:
    """
    MCPError 처리

    Args:
        error: MCPError 인스턴스
        function_name: 함수명
        log_traceback: 트레이스백 로깅 여부
        reraise_on_critical: 심각한 에러 시 재발생 여부

    Returns:
        에러 응답 또는 None (재발생 시)

    """
    # 로깅 (추적 컨텍스트 포함)
    log_data = create_log_context()  # 추적 컨텍스트 정보 포함
    log_data.update(
        {
            "function": function_name,
            "error_code": error.error_code,
            "error_message": error.message,
            "severity": error.severity.value,
            "retryable": error.retryable,
            "details": error.details,
            "error_type": "mcp_error",
        }
    )

    if log_traceback and error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
        log_data["traceback"] = traceback.format_exc()

    # 심각도에 따른 로그 레벨 선택
    if error.severity == ErrorSeverity.CRITICAL:
        logger.critical("mcp_error", **log_data)
        if reraise_on_critical:
            raise error
    elif error.severity == ErrorSeverity.HIGH:
        logger.error("mcp_error", **log_data)
    elif error.severity == ErrorSeverity.MEDIUM:
        logger.warning("mcp_error", **log_data)
    else:
        logger.info("mcp_error", **log_data)

    return error.to_response()


def _handle_unexpected_error(
    error: Exception,
    function_name: str,
    default_message: str | None,
    log_traceback: bool,
    reraise_on_critical: bool,
) -> dict[str, any]:
    """
    예상치 못한 에러 처리

    Args:
        error: 예외 인스턴스
        function_name: 함수명
        default_message: 기본 메시지
        log_traceback: 트레이스백 로깅 여부
        reraise_on_critical: 심각한 에러 시 재발생 여부

    Returns:
        에러 응답

    """
    error_message = str(error) or default_message or "예상치 못한 오류가 발생했습니다"

    # 로깅 (추적 컨텍스트 포함)
    log_data = create_log_context()  # 추적 컨텍스트 정보 포함
    log_data.update(
        {
            "function": function_name,
            "error_type": type(error).__name__,
            "error_message": error_message,
            "severity": "high",  # 예상치 못한 에러는 높은 심각도로 처리
            "original_error_type": type(error).__name__,
        }
    )

    if log_traceback:
        log_data["traceback"] = traceback.format_exc()

    logger.error("unexpected_error", **log_data)

    # MCPError로 래핑하여 일관성 유지
    mcp_error = MCPError(
        message=error_message,
        error_code="UNEXPECTED_ERROR",
        details={"original_error_type": type(error).__name__},
        severity=ErrorSeverity.HIGH,
        retryable=_is_retryable_error(error),
    )

    return mcp_error.to_response()


def _is_retryable_error(error: Exception) -> bool:
    """
    재시도 가능한 에러인지 판단

    Args:
        error: 예외 인스턴스

    Returns:
        재시도 가능 여부

    """
    retryable_error_types = (
        ConnectionError,
        TimeoutError,
        OSError,  # 네트워크 관련 OS 에러
    )

    return isinstance(error, retryable_error_types)


# 편의 함수들 - 기존 utils/error_handler.py와의 호환성 유지
def create_tool_error_response(
    tool_name: str, error: Exception, context: str | None = None
) -> dict[str, any]:
    """
    MCP 도구 에러 응답 생성 (호환성 함수)

    Args:
        tool_name: 도구명
        error: 예외 인스턴스
        context: 추가 컨텍스트

    Returns:
        에러 응답 딕셔너리

    """
    if isinstance(error, MCPError):
        response = error.to_response()
        if context:
            response["error"]["details"]["context"] = context
        return response

    message = f"{tool_name} 실행 실패"
    if context:
        message += f" ({context})"
    message += f": {error!s}"

    mcp_error = MCPError(
        message=message,
        error_code=f"{tool_name.upper()}_ERROR",
        details={"context": context} if context else {},
        severity=ErrorSeverity.MEDIUM,
    )

    return mcp_error.to_response()


def create_resource_error_response(
    resource_uri: str, error: Exception
) -> dict[str, any]:
    """
    MCP 리소스 에러 응답 생성 (호환성 함수)

    Args:
        resource_uri: 리소스 URI
        error: 예외 인스턴스

    Returns:
        에러 응답 딕셔너리

    """
    if isinstance(error, MCPError):
        return error.to_response()

    resource_error = ResourceError(
        message=f"리소스 {resource_uri} 접근 실패: {error!s}",
        error_code="RESOURCE_ACCESS_ERROR",
        resource_type="MCP_RESOURCE",
        resource_id=resource_uri,
        operation="access",
    )

    return resource_error.to_response()


# =============================================================================
# 도메인별 예외 클래스 (Domain-Specific Exceptions)
# =============================================================================


class TradingError(MCPError):
    """
    거래 관련 예외

    주문 실행 실패, 포지션 관리 오류, 잔고 부족 등 거래 관련 에러를 처리합니다.
    """

    def __init__(
        self, message: str, trading_context: dict[str, any] | None = None, **kwargs
    ):
        details = kwargs.get("details", {})
        if trading_context:
            details.update(
                {"trading_context": trading_context, "error_domain": "trading"}
            )

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "TRADING_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.HIGH),
            retryable=kwargs.get("retryable", False),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


class DataError(MCPError):
    """
    데이터 관련 예외

    API 호출 실패, 데이터 파싱 오류, 데이터 품질 문제 등을 처리합니다.
    """

    def __init__(
        self,
        message: str,
        data_source: str | None = None,
        data_context: dict[str, any] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        details.update({"error_domain": "data"})

        if data_source:
            details["data_source"] = data_source
        if data_context:
            details["data_context"] = data_context

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "DATA_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", True),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


class DataSourceError(DataError):
    """
    데이터 소스 관련 예외

    데이터 소스 연결 실패, 데이터 불일치, 소스 접근 권한 문제 등을 처리합니다.
    """

    def __init__(
        self,
        message: str,
        source_type: str | None = None,
        source_config: dict[str, any] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        details.update({"error_domain": "data_source"})

        if source_type:
            details["source_type"] = source_type
        if source_config:
            details["source_config"] = source_config

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "DATA_SOURCE_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", True),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


class AnalysisError(MCPError):
    """
    분석 관련 예외

    기술적 분석 실패, 펀더멘털 분석 오류, 계산 실패 등을 처리합니다.
    """

    def __init__(
        self,
        message: str,
        analysis_type: str | None = None,
        analysis_context: dict[str, any] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        details.update({"error_domain": "analysis"})

        if analysis_type:
            details["analysis_type"] = analysis_type
        if analysis_context:
            details["analysis_context"] = analysis_context

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "ANALYSIS_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", True),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


class PortfolioError(MCPError):
    """
    포트폴리오 관리 관련 예외

    포트폴리오 구성 오류, 자산 배분 실패, 리밸런싱 오류 등을 처리합니다.
    """

    def __init__(
        self, message: str, portfolio_context: dict[str, any] | None = None, **kwargs
    ):
        details = kwargs.get("details", {})
        details.update({"error_domain": "portfolio"})

        if portfolio_context:
            details["portfolio_context"] = portfolio_context

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "PORTFOLIO_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.MEDIUM),
            retryable=kwargs.get("retryable", False),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


class RiskError(MCPError):
    """
    리스크 관리 관련 예외

    리스크 한도 초과, VaR 계산 실패, 리스크 모니터링 오류 등을 처리합니다.
    """

    def __init__(
        self,
        message: str,
        risk_type: str | None = None,
        risk_context: dict[str, any] | None = None,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        details.update({"error_domain": "risk"})

        if risk_type:
            details["risk_type"] = risk_type
        if risk_context:
            details["risk_context"] = risk_context

        super().__init__(
            message=message,
            error_code=kwargs.get("error_code", "RISK_ERROR"),
            details=details,
            severity=kwargs.get("severity", ErrorSeverity.HIGH),
            retryable=kwargs.get("retryable", False),
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["details", "error_code", "severity", "retryable"]
            },
        )


# =============================================================================
# HTTP 상태 코드 매핑 (HTTP Status Code Mapping)
# =============================================================================

HTTP_STATUS_MAPPING: dict[str, int] = {
    # 기본 MCP 에러들
    "MCPERROR": 500,
    "APIERROR": 502,
    "VALIDATIONERROR": 400,
    "AUTHERROR": 401,
    "RESOURCEERROR": 503,
    "RATELIMITERROR": 429,
    # 도메인별 에러들
    "TRADING_ERROR": 422,  # Unprocessable Entity - 거래 실행 불가
    "DATA_ERROR": 503,  # Service Unavailable - 데이터 서비스 이용 불가
    "ANALYSIS_ERROR": 422,  # Unprocessable Entity - 분석 처리 불가
    "PORTFOLIO_ERROR": 409,  # Conflict - 포트폴리오 상태 충돌
    "RISK_ERROR": 403,  # Forbidden - 리스크 정책 위반
    # 세부 에러 코드들
    "INSUFFICIENT_DATA": 422,
    "CALCULATION_ERROR": 422,
    "MARKET_CLOSED": 503,
    "INVALID_SYMBOL": 400,
    "POSITION_LIMIT_EXCEEDED": 403,
    "BALANCE_INSUFFICIENT": 402,  # Payment Required
    "ORDER_REJECTED": 422,
    "RISK_LIMIT_EXCEEDED": 403,
    "UNEXPECTED_ERROR": 500,
}


def get_http_status_code(error_code: str) -> int:
    """
    에러 코드에 해당하는 HTTP 상태 코드를 반환

    Args:
        error_code: MCP 에러 코드

    Returns:
        HTTP 상태 코드 (기본값: 500)

    """
    return HTTP_STATUS_MAPPING.get(error_code.upper(), 500)


def is_retryable_by_error_code(error_code: str) -> bool:
    """
    에러 코드에 따른 재시도 가능 여부 판단

    Args:
        error_code: MCP 에러 코드

    Returns:
        재시도 가능 여부

    """
    retryable_codes = {
        "DATA_ERROR",
        "APIERROR",
        "RESOURCEERROR",
        "MARKET_CLOSED",
        "UNEXPECTED_ERROR",
    }

    non_retryable_codes = {
        "VALIDATIONERROR",
        "AUTHERROR",
        "TRADING_ERROR",
        "PORTFOLIO_ERROR",
        "RISK_ERROR",
        "INVALID_SYMBOL",
        "BALANCE_INSUFFICIENT",
        "ORDER_REJECTED",
        "POSITION_LIMIT_EXCEEDED",
        "RISK_LIMIT_EXCEEDED",
    }

    error_code_upper = error_code.upper()

    if error_code_upper in non_retryable_codes:
        return False
    elif error_code_upper in retryable_codes:
        return True
    else:
        # 기본적으로 서버 에러는 재시도 가능, 클라이언트 에러는 재시도 불가
        http_status = get_http_status_code(error_code)
        return 500 <= http_status < 600


# =============================================================================
# 강화된 예외 핸들러 데코레이터 (Enhanced Exception Handler)
# =============================================================================


def exception_handler(
    collect_metrics: bool = True,
    include_trace: bool = True,
    auto_retry: bool = False,
    max_retries: int = 3,
    retry_delays: list[float] | None = None,
    default_message: str | None = None,
    log_traceback: bool = True,
    reraise_on_critical: bool = True,
    operation_name: str | None = None,
) -> Callable[[F], F]:
    """
    강화된 MCP 예외 처리 데코레이터

    기존 @handle_mcp_errors를 확장하여 고급 기능을 제공합니다:
    - 자동 추적 컨텍스트 생성 및 전파
    - 메트릭 수집 통합
    - 자동 재시도 로직
    - HTTP 상태 코드 자동 매핑
    - 구조화된 로깅

    Args:
        collect_metrics: 메트릭 수집 여부
        include_trace: 추적 컨텍스트 포함 여부
        auto_retry: 자동 재시도 활성화 여부
        max_retries: 최대 재시도 횟수
        retry_delays: 재시도 지연 시간 리스트 (초)
        default_message: 기본 에러 메시지
        log_traceback: 트레이스백 로깅 여부
        reraise_on_critical: 심각한 에러 시 재발생 여부
        operation_name: 오퍼레이션 명 (추적용)

    Returns:
        강화된 예외 처리 데코레이터

    Example:
        @exception_handler(
            collect_metrics=True,
            include_trace=True,
            auto_retry=True,
            max_retries=3
        )
        async def my_mcp_tool(symbol: str) -> Dict[str, any]:
            # 도구 구현
            return {"result": "success"}

    """
    if retry_delays is None:
        retry_delays = [0.1, 0.5, 1.0, 2.0, 5.0]

    def decorator(func: F) -> F:
        func_operation_name = operation_name or f"{func.__module__}.{func.__name__}"

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 추적 컨텍스트 설정
            original_trace_ctx = None
            if include_trace:
                original_trace_ctx = get_trace_context()
                if not original_trace_ctx:
                    trace_ctx = TraceContext(operation_name=func_operation_name)
                    set_trace_context(trace_ctx)
                else:
                    # 자식 컨텍스트 생성
                    child_ctx = create_child_trace_context(func_operation_name)
                    set_trace_context(child_ctx)

            start_time = time.perf_counter()
            method_name = func.__name__
            attempt = 0
            last_error = None

            while attempt <= max_retries:
                try:
                    # 현재 시도에 대한 추적 정보 업데이트
                    if include_trace and attempt > 0:
                        trace_ctx = get_trace_context()
                        if trace_ctx:
                            trace_ctx.add_tag("retry_attempt", str(attempt))
                            trace_ctx.add_metadata("is_retry", True)

                    # 함수 실행
                    result = await func(*args, **kwargs)

                    # 성공 메트릭 수집
                    if collect_metrics:
                        duration = time.perf_counter() - start_time
                        await _record_success_metrics(method_name, duration, attempt)

                    # 성공 로깅 (재시도 후 성공시)
                    if attempt > 0:
                        log_with_context(
                            "info",
                            f"Function {method_name} succeeded after {attempt} retries",
                            function=method_name,
                            retry_attempts=attempt,
                            final_duration_ms=round(
                                (time.perf_counter() - start_time) * 1000, 2
                            ),
                        )

                    return _ensure_success_response_with_trace(result)

                except MCPError as e:
                    last_error = e
                    return await _handle_mcp_error_enhanced(
                        e, method_name, collect_metrics, start_time, attempt
                    )

                except Exception as e:
                    last_error = e

                    # 재시도 가능한지 확인
                    if auto_retry and attempt < max_retries and _is_retryable_error(e):
                        attempt += 1
                        delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]

                        # 재시도 로깅
                        log_with_context(
                            "warning",
                            f"Function {method_name} failed, retrying in {delay}s (attempt {attempt}/{max_retries})",
                            function=method_name,
                            error_type=type(e).__name__,
                            error_message=str(e),
                            retry_attempt=attempt,
                            retry_delay_seconds=delay,
                        )

                        await asyncio.sleep(delay)
                        continue
                    else:
                        # 재시도 불가능하거나 최대 재시도 횟수 도달
                        return await _handle_unexpected_error_enhanced(
                            e,
                            method_name,
                            collect_metrics,
                            start_time,
                            attempt,
                            default_message,
                        )

            # 여기에 도달하면 모든 재시도가 실패
            return await _handle_retry_exhausted(
                last_error, method_name, max_retries, collect_metrics, start_time
            )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 동기 함수에 대한 간단한 처리 (재시도 없음)
            if include_trace:
                original_trace_ctx = get_trace_context()
                if not original_trace_ctx:
                    trace_ctx = TraceContext(operation_name=func_operation_name)
                    set_trace_context(trace_ctx)
                else:
                    child_ctx = create_child_trace_context(func_operation_name)
                    set_trace_context(child_ctx)

            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)

                # 성공 메트릭 수집 (동기)
                if collect_metrics:
                    time.perf_counter() - start_time
                    # 동기 메트릭 기록은 구현하지 않음 (비동기 시스템 전용)

                return _ensure_success_response(result)

            except MCPError as e:
                return _handle_mcp_error(
                    e, func.__name__, log_traceback, reraise_on_critical
                )
            except Exception as e:
                return _handle_unexpected_error(
                    e,
                    func.__name__,
                    default_message,
                    log_traceback,
                    reraise_on_critical,
                )

        # 함수 타입 확인 (비동기 vs 동기)
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


# 강화된 헬퍼 함수들
def _ensure_success_response_with_trace(result: any) -> dict[str, any]:
    """성공 응답에 추적 정보 포함"""
    return _ensure_success_response(result)  # 이미 추적 정보 포함됨


async def _record_success_metrics(
    method_name: str, duration: float, retry_count: int = 0
):
    """성공 메트릭 기록 (비동기)"""
    # MetricsCollector와 통합할 수 있는 인터페이스
    # 실제 구현은 MetricsCollector 통합 작업에서 처리
    pass


async def _handle_mcp_error_enhanced(
    error: MCPError,
    function_name: str,
    collect_metrics: bool,
    start_time: float,
    retry_count: int = 0,
) -> dict[str, any]:
    """강화된 MCPError 처리"""
    duration = time.perf_counter() - start_time

    # 메트릭 수집
    if collect_metrics:
        await _record_error_metrics(
            function_name, error.error_code, duration, retry_count
        )

    # 기존 처리 로직 재사용
    return _handle_mcp_error(error, function_name, True, True)


async def _handle_unexpected_error_enhanced(
    error: Exception,
    function_name: str,
    collect_metrics: bool,
    start_time: float,
    retry_count: int = 0,
    default_message: str | None = None,
) -> dict[str, any]:
    """강화된 예상치 못한 에러 처리"""
    duration = time.perf_counter() - start_time

    # 메트릭 수집
    if collect_metrics:
        await _record_error_metrics(
            function_name, "UNEXPECTED_ERROR", duration, retry_count
        )

    # 기존 처리 로직 재사용
    return _handle_unexpected_error(error, function_name, default_message, True, True)


async def _handle_retry_exhausted(
    last_error: Exception,
    function_name: str,
    max_retries: int,
    collect_metrics: bool,
    start_time: float,
) -> dict[str, any]:
    """재시도 소진 처리"""
    duration = time.perf_counter() - start_time

    # 재시도 소진 로깅
    log_with_context(
        "error",
        f"Function {function_name} failed after {max_retries} retries",
        function=function_name,
        error_type=type(last_error).__name__,
        error_message=str(last_error),
        max_retries=max_retries,
        total_duration_ms=round(duration * 1000, 2),
        final_status="retry_exhausted",
    )

    # 메트릭 수집
    if collect_metrics:
        await _record_error_metrics(
            function_name, "RETRY_EXHAUSTED", duration, max_retries
        )

    # MCPError로 래핑
    retry_error = MCPError(
        message=f"함수 {function_name} 실행이 {max_retries}회 재시도 후에도 실패했습니다: {last_error!s}",
        error_code="RETRY_EXHAUSTED",
        details={
            "original_error": str(last_error),
            "original_error_type": type(last_error).__name__,
            "max_retries": max_retries,
            "total_duration_ms": round(duration * 1000, 2),
        },
        severity=ErrorSeverity.HIGH,
        retryable=False,
    )

    return retry_error.to_response()


async def _record_error_metrics(
    function_name: str, error_code: str, duration: float, retry_count: int = 0
):
    """에러 메트릭 기록 (비동기)"""
    # MetricsCollector와 통합할 수 있는 인터페이스
    # 실제 구현은 MetricsCollector 통합 작업에서 처리
    pass


# asyncio import 추가 (필요시)
try:
    import asyncio
except ImportError:
    # asyncio가 없는 환경에서는 동기 함수만 지원
    asyncio = None
