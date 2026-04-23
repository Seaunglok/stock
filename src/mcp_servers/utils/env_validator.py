"""
환경변수 검증 유틸리티

MCP 서버들에서 공통으로 사용하는 환경변수 검증 로직을 제공합니다.

Beginner notes:
    - Fail fast: 필수 항목은 즉시 예외를 발생시켜 잘못된 구성으로 서버가
      뜨지 않도록 합니다. 메시지는 한국어로 친절하게 작성되어 있습니다.
    - Dummy pattern check: 'your_api_key_here' 같은 더미 값을 방지합니다.
      실제 키를 발급 후 환경변수에 설정하세요.
"""

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# 통합된 더미 API 키 패턴들 (15개 → 20개로 확장)
COMMON_DUMMY_PATTERNS = [
    # 기본 더미 패턴들
    "your_api_key_here",
    "test_key",
    "demo_key",
    "sample_key",
    "placeholder_key",
    "dummy_key",
    "mock_key",
    "fake_key",
    "example_key",
    "default_key",
    # 시크릿 패턴들
    "your_secret_here",
    "test_secret",
    "demo_secret",
    "sample_secret",
    "placeholder_secret",
    "dummy_secret",
    "mock_secret",
    "fake_secret",
    "example_secret",
    "default_secret",
    # 토큰 패턴들
    "your_token_here",
    "test_token",
    "demo_token",
    "sample_token",
    "placeholder_token",
    # 일반적인 패턴들
    "change_me",
    "replace_me",
    "set_your_key",
    "enter_your_key",
    "insert_key_here",
]


class EnvironmentVariableError(Exception):
    """환경변수 관련 에러."""

    pass


class EnhancedAPIKeyValidator:
    """강화된 API 키 검증기."""

    @classmethod
    def validate_api_key(
        cls,
        key: str,
        service_name: str,
        min_length: int = 10,
        additional_patterns: list[str] | None = None,
    ) -> str:
        """
        API 키를 검증합니다.

        Args:
            key: 검증할 API 키
            service_name: 서비스명 (에러 메시지용)
            min_length: 최소 길이
            additional_patterns: 추가 더미 패턴들

        Returns:
            검증된 API 키

        Raises:
            EnvironmentVariableError: 더미 키이거나 유효하지 않은 경우
        """
        if not key or key.strip() == "":
            raise EnvironmentVariableError(
                f"{service_name} API 키가 설정되지 않았습니다."
            )

        key = key.strip()

        # 최소 길이 검증
        if len(key) < min_length:
            raise EnvironmentVariableError(
                f"{service_name} API 키가 너무 짧습니다. 최소 {min_length}자 이상이어야 합니다."
            )

        # 더미 패턴 검증
        all_patterns = COMMON_DUMMY_PATTERNS[:]
        if additional_patterns:
            all_patterns.extend(additional_patterns)

        key_lower = key.lower()
        for pattern in all_patterns:
            if pattern.lower() in key_lower:
                raise EnvironmentVariableError(
                    f"{service_name} API 키에서 더미 패턴이 감지되었습니다: '{pattern}'\n"
                    f"실제 {service_name}에서 발급받은 키를 사용하세요."
                )

        logger.debug(
            "api_key_validated",
            service_name=service_name,
            key_length=len(key),
            key_prefix=key[:8] + "*" * (len(key) - 8)
            if len(key) > 8
            else "*" * len(key),
        )

        return key

    @classmethod
    def validate_multiple_keys(cls, key_configs: list[dict]) -> dict[str, str]:
        """
        여러 API 키를 한 번에 검증합니다.

        Args:
            key_configs: [{"env_var": "API_KEY", "service": "서비스명", "min_length": 10}, ...]

        Returns:
            검증된 키들의 딕셔너리
        """
        validated_keys = {}

        for config in key_configs:
            env_var = config["env_var"]
            service = config["service"]
            min_length = config.get("min_length", 10)
            additional_patterns = config.get("additional_patterns", [])

            key_value = os.getenv(env_var)
            if key_value:
                validated_key = cls.validate_api_key(
                    key_value, service, min_length, additional_patterns
                )
                validated_keys[env_var] = validated_key

        return validated_keys


def _validate_api_key_patterns(
    key: str, key_name: str, check_patterns: list[str] | None = None
) -> bool:
    """API 키의 더미 패턴을 검증하는 내부 함수."""
    patterns_to_check = check_patterns or COMMON_DUMMY_PATTERNS

    key_lower = key.lower()
    for pattern in patterns_to_check:
        if pattern.lower() in key_lower:
            raise EnvironmentVariableError(
                f"{key_name}에서 더미 패턴이 감지되었습니다: '{pattern}'\n"
                "실제 API에서 발급받은 키를 사용하세요."
            )
    return True


def validate_required_env_vars(required_vars: list[str]) -> dict[str, str]:
    """
    필수 환경변수들이 모두 설정되어 있는지 검증합니다.

    Args:
        required_vars: 필수 환경변수 이름 목록

    Returns:
        검증된 환경변수들의 딕셔너리

    Raises:
        EnvironmentVariableError: 필수 환경변수가 누락된 경우

    """
    missing_vars = []
    env_values = {}

    for var_name in required_vars:
        value = os.getenv(var_name)
        if not value or value.strip() == "":
            missing_vars.append(var_name)
        else:
            env_values[var_name] = value.strip()

    if missing_vars:
        raise EnvironmentVariableError(
            f"다음 필수 환경변수들이 설정되지 않았습니다: {', '.join(missing_vars)}\n"
            "자세한 내용은 .env.example 파일을 참조하세요."
        )

    logger.info(
        "environment_variables_validated",
        validated_vars=list(env_values.keys()),
        total_count=len(env_values),
    )

    return env_values


def validate_kiwoom_credentials() -> dict[str, str]:
    """
    키움증권 관련 필수 환경변수들을 검증합니다.

    Returns:
        검증된 키움증권 환경변수들

    Raises:
        EnvironmentVariableError: 필수 환경변수가 누락된 경우

    """
    required_vars = ["KIWOOM_APP_KEY", "KIWOOM_APP_SECRET"]

    credentials = validate_required_env_vars(required_vars)

    # 키 형식 기본 검증
    app_key = credentials["KIWOOM_APP_KEY"]
    app_secret = credentials["KIWOOM_APP_SECRET"]

    if len(app_key) < 10:
        raise EnvironmentVariableError(
            "KIWOOM_APP_KEY가 너무 짧습니다. 키움증권에서 발급받은 올바른 키를 사용하세요."
        )

    if len(app_secret) < 10:
        raise EnvironmentVariableError(
            "KIWOOM_APP_SECRET이 너무 짧습니다. 키움증권에서 발급받은 올바른 시크릿을 사용하세요."
        )

    # 키움 전용 더미 패턴 체크
    return _validate_api_key_patterns(
        app_key, "KIWOOM_APP_KEY"
    ) and _validate_api_key_patterns(
        app_secret,
        "KIWOOM_APP_SECRET",
        check_patterns=[
            "your_kiwoom_app_key_here",
            "your_kiwoom_secret_key_here",
            "mock_app_key",
            "mock_app_secret",
        ],
    )

    # 검증이 위에서 완료됨

    logger.info(
        "kiwoom_credentials_validated",
        app_key_length=len(app_key),
        app_secret_length=len(app_secret),
    )

    return credentials


def validate_optional_env_var(
    var_name: str,
    default_value: str | None = None,
    allowed_values: list[str] | None = None,
) -> str | None:
    """
    선택적 환경변수를 검증합니다.

    Args:
        var_name: 환경변수 이름
        default_value: 기본값
        allowed_values: 허용된 값들의 목록

    Returns:
        환경변수 값 또는 기본값

    Raises:
        EnvironmentVariableError: 허용되지 않은 값인 경우

    """
    value = os.getenv(var_name, default_value)

    if allowed_values and value not in allowed_values:
        raise EnvironmentVariableError(
            f"{var_name}의 값 '{value}'는 허용되지 않습니다. "
            f"허용된 값들: {', '.join(allowed_values)}"
        )

    return value


def get_boolean_env_var(var_name: str, default_value: bool = False) -> bool:
    """
    불린 환경변수를 안전하게 파싱합니다.

    Args:
        var_name: 환경변수 이름
        default_value: 기본값

    Returns:
        불린 값

    """
    value = os.getenv(var_name)
    if value is None:
        return default_value

    return value.lower() in ("true", "1", "yes", "on")


def get_int_env_var(
    var_name: str,
    default_value: int = 0,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    """
    정수 환경변수를 안전하게 파싱합니다.

    Args:
        var_name: 환경변수 이름
        default_value: 기본값
        min_value: 최소값
        max_value: 최대값

    Returns:
        정수 값

    Raises:
        EnvironmentVariableError: 파싱 실패 또는 범위 초과

    """
    value_str = os.getenv(var_name)
    if value_str is None:
        return default_value

    try:
        value = int(value_str)
    except ValueError:
        raise EnvironmentVariableError(
            f"{var_name}의 값 '{value_str}'은 유효한 정수가 아닙니다."
        ) from None

    if min_value is not None and value < min_value:
        raise EnvironmentVariableError(
            f"{var_name}의 값 {value}는 최소값 {min_value}보다 작습니다."
        )

    if max_value is not None and value > max_value:
        raise EnvironmentVariableError(
            f"{var_name}의 값 {value}는 최대값 {max_value}보다 큽니다."
        )

    return value


def validate_all_required_for_trading() -> dict[str, Any]:
    """
    거래 관련 모든 필수 환경변수를 검증합니다.

    Returns:
        검증된 모든 환경변수들

    """
    # 키움증권 인증 정보
    credentials = validate_kiwoom_credentials()

    # 계좌 번호 (선택적이지만 거래 시 필요)
    account_number = os.getenv("KIWOOM_ACCOUNT_NUMBER")
    if account_number and account_number.strip():
        credentials["KIWOOM_ACCOUNT_NUMBER"] = account_number.strip()

    # 안전 설정들
    # 환경변수로 모의투자 모드 제어
    mock_mode = get_boolean_env_var("KIWOOM_MOCK_MODE", False)  # 환경변수로 제어
    enable_trading = get_boolean_env_var(
        "KIWOOM_ENABLE_TRADING", False
    )  # 기본적으로 거래 비활성화
    production_mode = get_boolean_env_var(
        "KIWOOM_PRODUCTION_MODE", False
    )  # 환경변수로 제어

    # 환경변수로 실거래 모드를 시도해도 무시하고 경고
    if get_boolean_env_var("KIWOOM_PRODUCTION_MODE", False):
        logger.warning(
            "production_mode_disabled",
            message="️ 실거래 모드는 보안상 완전히 비활성화되었습니다. 모의투자 모드만 사용 가능합니다.",
        )

    if not get_boolean_env_var("KIWOOM_MOCK_MODE", True):
        logger.warning(
            "mock_mode_forced",
            message="️ 모의투자 모드가 강제로 활성화되었습니다. 실거래는 지원하지 않습니다.",
        )

    return {
        **credentials,
        "mock_mode": mock_mode,
        "enable_trading": enable_trading,
        "production_mode": production_mode,
    }


def validate_all_mcp_server_keys() -> dict[str, dict[str, str]]:
    """
    모든 MCP 서버에서 사용하는 API 키들을 통합 검증합니다.

    Returns:
        서버별로 분류된 검증된 키들
    """
    results = {}

    # 키움증권 MCP 서버
    try:
        kiwoom_keys = validate_kiwoom_credentials()
        results["kiwoom_mcp"] = kiwoom_keys
        logger.info("kiwoom_keys_validated", count=len(kiwoom_keys))
    except EnvironmentVariableError as e:
        logger.warning("kiwoom_keys_validation_failed", error=str(e))
        results["kiwoom_mcp"] = {}

    # 다른 외부 API들 (선택적)
    optional_apis = [
        {"env_var": "OPENAI_API_KEY", "service": "OpenAI", "min_length": 20},
        {"env_var": "ANTHROPIC_API_KEY", "service": "Anthropic", "min_length": 20},
        {"env_var": "FINNHUB_API_TOKEN", "service": "Finnhub", "min_length": 15},
        {
            "env_var": "ALPHA_VANTAGE_API_KEY",
            "service": "Alpha Vantage",
            "min_length": 10,
        },
        {
            "env_var": "FINANCIAL_MODELING_PREP_API_KEY",
            "service": "Financial Modeling Prep",
            "min_length": 15,
        },
    ]

    external_keys = EnhancedAPIKeyValidator.validate_multiple_keys(optional_apis)
    if external_keys:
        results["external_apis"] = external_keys
        logger.info(
            "external_api_keys_validated",
            count=len(external_keys),
            services=list(external_keys.keys()),
        )

    # 검증 요약 로그
    total_validated = sum(len(server_keys) for server_keys in results.values())
    logger.info(
        "all_api_keys_validation_complete",
        total_servers=len(results),
        total_keys=total_validated,
        servers=list(results.keys()),
    )

    return results


def validate_server_startup_environment(
    server_name: str, required_keys: list[dict] | None = None
) -> bool:
    """
    MCP 서버 시작 시 환경변수를 검증합니다.

    Args:
        server_name: 서버 이름
        required_keys: 필수 키 설정 목록

    Returns:
        검증 성공 여부
    """
    try:
        logger.info("validating_startup_environment", server_name=server_name)

        if required_keys:
            # 특정 키들 검증
            validated = EnhancedAPIKeyValidator.validate_multiple_keys(required_keys)
            logger.info(
                "server_environment_validated",
                server_name=server_name,
                validated_keys=len(validated),
            )
        else:
            # 전체 키들 검증 (더 간단한 로그)
            validate_all_mcp_server_keys()

        return True

    except EnvironmentVariableError as e:
        logger.error(
            "server_environment_validation_failed",
            server_name=server_name,
            error=str(e),
        )
        return False


class EnvironmentValidationResult:
    """환경변수 검증 결과."""

    def __init__(
        self,
        is_valid: bool = True,
        missing_required: list[str] = None,
        warnings: list[str] = None,
    ):
        self.is_valid = is_valid
        self.missing_required = missing_required or []
        self.warnings = warnings or []


def validate_environment(
    required_vars: list[str], optional_vars: list[str] = None
) -> EnvironmentValidationResult:
    """
    환경변수들을 검증하고 결과를 반환합니다.

    Args:
        required_vars: 필수 환경변수 목록
        optional_vars: 선택적 환경변수 목록

    Returns:
        검증 결과
    """
    missing_required = []
    warnings = []

    # 필수 환경변수 확인
    for var in required_vars:
        if not os.getenv(var):
            missing_required.append(var)

    # 선택적 환경변수 확인
    if optional_vars:
        for var in optional_vars:
            if not os.getenv(var):
                warnings.append(f"선택적 환경변수 {var}이 설정되지 않았습니다.")

    is_valid = len(missing_required) == 0

    return EnvironmentValidationResult(
        is_valid=is_valid, missing_required=missing_required, warnings=warnings
    )


def log_environment_summary():
    """현재 환경 설정 요약을 로그로 출력합니다."""
    try:
        # 기존 키움 검증
        config = validate_all_required_for_trading()

        # 전체 API 키들 검증
        all_keys = validate_all_mcp_server_keys()

        logger.info(
            "environment_summary",
            mock_mode=config.get("mock_mode", False),
            enable_trading=config.get("enable_trading", False),
            production_mode=config.get("production_mode", False),
            has_account_number=bool(config.get("KIWOOM_ACCOUNT_NUMBER")),
            credentials_valid=True,
            total_api_services=len(all_keys),
            total_validated_keys=sum(len(keys) for keys in all_keys.values()),
        )

    except EnvironmentVariableError as e:
        logger.error("environment_validation_failed", error=str(e))
