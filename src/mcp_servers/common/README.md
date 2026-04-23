# MCP 서버 공통 예외 처리 체계

이 모듈은 모든 MCP 서버에서 사용할 수 있는 일관된 예외 처리 클래스와 데코레이터를 제공합니다.

## 주요 특징

- 🎯 **일관된 에러 응답**: 모든 MCP 서버에서 동일한 에러 응답 포맷 제공
- 🚦 **심각도 기반 로깅**: 에러 심각도에 따른 차별화된 로깅 레벨
- 🔄 **재시도 지원**: 재시도 가능한 에러와 불가능한 에러 자동 분류
- 📊 **상세 에러 정보**: 디버깅에 유용한 상세 에러 컨텍스트 제공
- 🛡️ **타입 안전성**: 완전한 타입 힌트 지원

## 설치 및 설정

```python
from mcp_servers.common.exceptions import (
    MCPError,
    APIError,
    ValidationError,
    AuthError,
    ResourceError,
    RateLimitError,
    handle_mcp_errors
)
```

## 핵심 예외 클래스

### MCPError (기본 클래스)

모든 MCP 관련 예외의 기본 클래스입니다.

```python
class MCPError(Exception):
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False
    ):
        # ...
```

**속성:**
- `message`: 에러 메시지
- `error_code`: 에러 코드 (기본값: 클래스명 대문자)
- `details`: 추가 에러 상세 정보
- `severity`: 에러 심각도 (LOW, MEDIUM, HIGH, CRITICAL)
- `retryable`: 재시도 가능 여부

### 도메인별 예외 클래스

#### APIError
외부 API 호출 실패 시 사용:

```python
raise APIError(
    message="키움증권 API 호출 실패",
    api_name="kiwoom_api",
    status_code=500,
    response_data={"error": "server_error"}
)
```

#### ValidationError
입력 데이터 검증 실패 시 사용:

```python
raise ValidationError(
    message="종목 코드 형식이 올바르지 않습니다",
    field_name="symbol",
    field_value="ABC123",
    expected_format="6자리 숫자 (예: 005930)"
)
```

#### AuthError
인증/인가 실패 시 사용:

```python
raise AuthError(
    message="API 키가 유효하지 않습니다",
    auth_type="api_key",
    required_permissions=["stock_data_read"]
)
```

#### ResourceError
파일/데이터베이스 등 리소스 접근 실패 시 사용:

```python
raise ResourceError(
    message="캐시 파일 저장 실패",
    resource_type="file",
    resource_id="/tmp/cache.json",
    operation="write"
)
```

#### RateLimitError
API 호출 한도 초과 시 사용:

```python
raise RateLimitError(
    message="API 호출 한도를 초과했습니다",
    retry_after=60,
    current_rate=100,
    rate_limit=50
)
```

## @handle_mcp_errors 데코레이터

모든 MCP 도구 함수에 적용하여 일관된 에러 처리를 제공합니다.

### 기본 사용법

```python
@handle_mcp_errors(default_message="주식 정보 조회 실패")
async def get_stock_info(symbol: str) -> Dict[str, Any]:
    if not symbol:
        raise ValidationError("종목 코드가 필요합니다", field_name="symbol")
    
    # API 호출 로직
    return {"symbol": symbol, "price": 50000}
```

### 데코레이터 옵션

```python
@handle_mcp_errors(
    default_message="기본 에러 메시지",
    log_traceback=True,           # 트레이스백 로깅 여부
    reraise_on_critical=True      # CRITICAL 에러 시 재발생 여부
)
def my_tool_function():
    # ...
```

## 응답 포맷

### 성공 응답
```json
{
    "success": true,
    "data": {
        "symbol": "005930",
        "price": 50000
    },
    "timestamp": "2025-08-06T08:35:21.206974"
}
```

### 에러 응답
```json
{
    "success": false,
    "error": {
        "code": "VALIDATIONERROR",
        "message": "종목 코드가 필요합니다",
        "details": {
            "field_name": "symbol",
            "field_value": "",
            "expected_format": "6자리 숫자 (예: 005930)"
        },
        "severity": "low",
        "retryable": false,
        "timestamp": "2025-08-06T08:35:21.207043"
    }
}
```

## 실제 사용 예시

### MCP 도구 함수 구현

```python
from mcp_servers.common.exceptions import handle_mcp_errors, ValidationError, APIError

class StockMCPServer:
    @handle_mcp_errors(default_message="주식 정보 조회 실패")
    async def get_stock_price(self, symbol: str, api_key: str) -> Dict[str, Any]:
        # 1. 입력 검증
        if not symbol or len(symbol) != 6 or not symbol.isdigit():
            raise ValidationError(
                message="올바른 종목 코드를 입력해주세요",
                field_name="symbol",
                field_value=symbol,
                expected_format="6자리 숫자"
            )
        
        if not api_key:
            raise AuthError(
                message="API 키가 필요합니다",
                auth_type="api_key"
            )
        
        try:
            # 2. 외부 API 호출
            response = await self.external_api.get_stock_price(symbol)
            return {"symbol": symbol, "price": response.price}
            
        except ConnectionError as e:
            # 3. 네트워크 에러 처리
            raise APIError(
                message="주식 정보 서버 연결 실패",
                api_name="stock_api",
                retryable=True,
                details={"connection_error": str(e)}
            )
```

### 사용자 정의 예외 클래스

특정 도메인에 맞는 예외 클래스를 생성할 수 있습니다:

```python
class KiwoomAPIError(APIError):
    """키움증권 API 전용 예외"""
    
    def __init__(self, message: str, kiwoom_error_code: str, **kwargs):
        details = kwargs.get("details", {})
        details["kiwoom_error_code"] = kiwoom_error_code
        
        super().__init__(
            message=message,
            api_name="kiwoom_api",
            details=details,
            **kwargs
        )

# 사용법
raise KiwoomAPIError(
    message="주문 실행 실패",
    kiwoom_error_code="KOA_NORMAL_INVESTING_BANK_ERROR",
    status_code=400
)
```

## 로깅 통합

예외 처리 체계는 `structlog`와 완전히 통합되어 있습니다:

```python
# 심각도별 로그 레벨
- ErrorSeverity.LOW      -> logger.info()
- ErrorSeverity.MEDIUM   -> logger.warning()
- ErrorSeverity.HIGH     -> logger.error()
- ErrorSeverity.CRITICAL -> logger.critical()
```

로그에는 다음 정보가 포함됩니다:
- 함수명
- 에러 코드
- 에러 메시지
- 심각도
- 재시도 가능 여부
- 상세 정보
- 트레이스백 (HIGH/CRITICAL 에러 시)

## 기존 코드 마이그레이션

### Before (기존 방식)
```python
def get_stock_info(symbol: str) -> Dict[str, Any]:
    try:
        if not symbol:
            return {
                "success": False,
                "error": {"code": "INVALID_INPUT", "message": "종목 코드 필요"}
            }
        
        result = api_call(symbol)
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "success": False,
            "error": {"code": "UNKNOWN_ERROR", "message": str(e)}
        }
```

### After (새로운 방식)
```python
@handle_mcp_errors(default_message="주식 정보 조회 실패")
def get_stock_info(symbol: str) -> Dict[str, Any]:
    if not symbol:
        raise ValidationError("종목 코드가 필요합니다", field_name="symbol")
    
    try:
        result = api_call(symbol)
        return {"data": result}  # 성공 응답은 데코레이터가 자동 처리
        
    except ConnectionError as e:
        raise APIError(
            message="API 서버 연결 실패",
            api_name="external_api",
            retryable=True
        )
```

## 재시도 가능한 에러 감지

다음 에러들은 자동으로 재시도 가능(`retryable=True`)으로 분류됩니다:

- `ConnectionError`
- `TimeoutError`
- `OSError` (네트워크 관련)
- `aiohttp.ClientTimeout` (설치된 경우)
- `aiohttp.ClientConnectionError` (설치된 경우)
- `aiohttp.ServerTimeoutError` (설치된 경우)

## 호환성

기존 `utils/error_handler.py`와의 호환성을 위해 다음 함수들을 제공합니다:

```python
from mcp_servers.common.exceptions import (
    create_tool_error_response,
    create_resource_error_response
)

# 기존 코드와 동일하게 사용 가능
response = create_tool_error_response("get_stock_info", error, "context")
```

## 테스트

테스트 파일 위치: `tests/mcp_servers/test_common_exceptions.py`

```bash
# 전체 테스트 실행
python -m pytest tests/mcp_servers/test_common_exceptions.py -v

# 특정 테스트 클래스 실행
python -m pytest tests/mcp_servers/test_common_exceptions.py::TestMCPError -v

# 통합 테스트 실행
python -m pytest tests/mcp_servers/test_common_exceptions.py::TestIntegrationScenarios -v
```

## 베스트 프랙티스

1. **적절한 예외 클래스 선택**: 상황에 맞는 도메인별 예외 클래스 사용
2. **상세 정보 제공**: `details` 매개변수에 디버깅에 유용한 정보 포함
3. **재시도 가능성 고려**: API 에러 시 `retryable=True` 명시적 설정
4. **심각도 설정**: 적절한 `ErrorSeverity` 레벨 선택
5. **일관된 데코레이터 사용**: 모든 MCP 도구 함수에 `@handle_mcp_errors` 적용

## 예제 코드

완전한 예제 코드는 `src/mcp_servers/common/examples.py`에서 확인할 수 있습니다.

```bash
# 예제 실행
python -c "
import asyncio
from src.mcp_servers.common.examples import example_scenarios
asyncio.run(example_scenarios())
"
```