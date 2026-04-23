"""
MCP 서버 공통 에러 처리 유틸리티

모든 MCP 서버에서 사용할 수 있는 일관된 에러 처리 데코레이터와 헬퍼 함수들을 제공합니다.

Beginner notes:
    - This module is lightweight and separate from the richer common/exceptions.py.
      Use this when you need a simple decorator without tracing/metrics.
    - Prefer returning dicts for MCP tools so clients always receive JSON.
"""

import functools
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

import structlog

from src.mcp_servers.utils.constants import ErrorMessages

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def create_api_response(
    success: bool = True,
    message: str = "",
    data: Any | None = None,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    표준화된 API 응답 생성

    Args:
        success: 성공 여부
        message: 응답 메시지
        data: 응답 데이터
        error_code: 에러 코드 (실패 시)
        metadata: 추가 메타데이터

    Returns:
        표준화된 응답 딕셔너리

    """
    response = {
        "success": success,
        "message": message,
        "timestamp": None,  # 실제 구현에서는 datetime.now().isoformat() 사용
    }

    if success:
        response["data"] = data or {}
    else:
        response["error"] = {"code": error_code or "UNKNOWN_ERROR", "message": message}

    if metadata:
        response["metadata"] = metadata

    return response


def handle_api_errors(
    default_message: str = "작업 실행 중 오류가 발생했습니다",
    log_traceback: bool = True,
    return_dict: bool = True,
) -> Callable[[F], F]:
    """
    API 에러 처리 데코레이터

    Args:
        default_message: 기본 에러 메시지
        log_traceback: 트레이스백 로깅 여부
        return_dict: dict 형태로 반환할지 여부

    Returns:
        데코레이터 함수

    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                return _handle_exception(
                    e, func.__name__, default_message, log_traceback, return_dict
                )

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return _handle_exception(
                    e, func.__name__, default_message, log_traceback, return_dict
                )

        # 비동기 함수인지 확인
        if hasattr(func, "__await__"):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


def _handle_exception(
    error: Exception,
    function_name: str,
    default_message: str,
    log_traceback: bool,
    return_dict: bool,
) -> dict[str, Any] | Exception:
    """예외 처리 공통 로직"""
    error_message = str(error) or default_message

    # 로깅
    log_data = {
        "function": function_name,
        "error_type": type(error).__name__,
        "error_message": error_message,
    }

    if log_traceback:
        log_data["traceback"] = traceback.format_exc()

    logger.error("api_error", **log_data)

    # 응답 형태 결정
    if return_dict:
        return create_api_response(
            success=False,
            message=error_message,
            error_code=type(error).__name__.upper(),
        )
    else:
        raise error


def handle_validation_error(func: F) -> F:
    """입력 검증 에러 전용 데코레이터"""
    return handle_api_errors(
        default_message=ErrorMessages.INVALID_SYMBOL, log_traceback=False
    )(func)


def handle_api_connection_error(func: F) -> F:
    """API 연결 에러 전용 데코레이터"""
    return handle_api_errors(
        default_message=ErrorMessages.API_CONNECTION_ERROR, log_traceback=True
    )(func)


def handle_rate_limit_error(func: F) -> F:
    """Rate Limit 에러 전용 데코레이터"""
    return handle_api_errors(
        default_message=ErrorMessages.RATE_LIMIT_EXCEEDED, log_traceback=False
    )(func)


class MCPErrorHandler:
    """MCP 서버 전용 에러 처리 헬퍼 클래스"""

    @staticmethod
    def create_tool_error_response(
        tool_name: str, error: Exception, context: str | None = None
    ) -> dict[str, Any]:
        """MCP 도구 에러 응답 생성"""
        message = f"{tool_name} 실행 실패"
        if context:
            message += f" ({context})"
        message += f": {error!s}"

        return create_api_response(
            success=False, message=message, error_code=f"{tool_name.upper()}_ERROR"
        )

    @staticmethod
    def create_resource_error_response(
        resource_uri: str, error: Exception
    ) -> dict[str, Any]:
        """MCP 리소스 에러 응답 생성"""
        return create_api_response(
            success=False,
            message=f"리소스 {resource_uri} 접근 실패: {error!s}",
            error_code="RESOURCE_ACCESS_ERROR",
        )

    @staticmethod
    def is_retryable_error(error: Exception) -> bool:
        """재시도 가능한 에러인지 판단"""
        retryable_errors = (
            ConnectionError,
            TimeoutError,
            # aiohttp.ClientTimeout,  # 실제 사용 시 주석 해제
            # aiohttp.ClientConnectionError,
        )
        return isinstance(error, retryable_errors)


# 편의 함수들
def safe_dict_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """안전한 딕셔너리 접근"""
    try:
        return data.get(key, default)
    except (AttributeError, TypeError):
        return default


def safe_int_convert(value: Any, default: int = 0) -> int:
    """안전한 정수 변환"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float_convert(value: Any, default: float = 0.0) -> float:
    """안전한 실수 변환"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
