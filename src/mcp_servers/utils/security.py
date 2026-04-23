"""
보안 유틸리티 모듈

민감한 정보 감지 및 마스킹 기능을 제공하는 보안 시스템입니다.
로그 출력 시 자동으로 민감한 데이터를 필터링하여 보안을 강화합니다.

Beginner notes:
    - Masking levels: FULL (always mask), PARTIAL (first N chars), NONE.
    - Environment-driven: ``ENVIRONMENT`` and ``LOG_MASKING_LEVEL`` control
      defaults; you can override via env vars without code changes.
    - Use ``configure_secure_logging`` at server startup to install processors.
"""

import os
import re
from enum import Enum
from re import Pattern
from typing import Any

from pydantic import BaseModel


class MaskingLevel(str, Enum):
    """마스킹 수준 정의."""

    FULL = "full"  # 완전 마스킹
    PARTIAL = "partial"  # 부분 마스킹
    NONE = "none"  # 마스킹 없음


class SensitivePattern(BaseModel):
    """민감한 데이터 패턴 정의."""

    name: str
    patterns: list[Pattern[str]]
    masking_level: MaskingLevel
    show_chars: int = 3
    mask_char: str = "*"


class SensitiveDataFilter(BaseModel):
    """민감한 데이터 필터링 클래스."""

    mask_char: str = "*"
    show_chars: int = 3

    def __init__(self, mask_char: str = "*", show_chars: int = 3):
        """
        Args:
            mask_char: 마스킹에 사용할 문자
            show_chars: 부분 마스킹 시 보여줄 문자 수

        """
        super().__init__(mask_char=mask_char, show_chars=show_chars)
        self._masking_level = self._get_masking_level()
        self._sensitive_patterns = self._build_sensitive_patterns()

    def _get_masking_level(self) -> MaskingLevel:
        """환경변수에서 마스킹 수준 결정."""
        env = os.getenv("ENVIRONMENT", "development").lower()
        level = os.getenv("LOG_MASKING_LEVEL", "").lower()

        if level in [e.value for e in MaskingLevel]:
            return MaskingLevel(level)

        # 환경별 기본 설정
        if env == "production":
            return MaskingLevel.FULL
        elif env == "development":
            return MaskingLevel.PARTIAL
        else:
            return MaskingLevel.PARTIAL

    def _build_sensitive_patterns(self) -> list[SensitivePattern]:
        """민감한 데이터 패턴 구성."""
        patterns = [
            # 키움증권 API 관련
            SensitivePattern(
                name="app_key",
                patterns=[
                    re.compile(r"app[_\-]?key", re.IGNORECASE),
                    re.compile(r"application[_\-]?key", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.FULL,
                mask_char="*",
            ),
            SensitivePattern(
                name="app_secret",
                patterns=[
                    re.compile(r"app[_\-]?secret", re.IGNORECASE),
                    re.compile(r"application[_\-]?secret", re.IGNORECASE),
                    re.compile(r"client[_\-]?secret", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.FULL,
                mask_char="*",
            ),
            # 토큰 관련
            SensitivePattern(
                name="token",
                patterns=[
                    re.compile(r"access[_\-]?token", re.IGNORECASE),
                    re.compile(r"refresh[_\-]?token", re.IGNORECASE),
                    re.compile(r"bearer[_\-]?token", re.IGNORECASE),
                    re.compile(r"\btoken\b", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.PARTIAL,
                show_chars=8,
                mask_char=".",
            ),
            # 비밀번호 관련
            SensitivePattern(
                name="password",
                patterns=[
                    re.compile(r"password", re.IGNORECASE),
                    re.compile(r"passwd", re.IGNORECASE),
                    re.compile(r"\bpwd\b", re.IGNORECASE),
                    re.compile(r"secret", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.FULL,
                mask_char="*",
            ),
            # 계좌 관련
            SensitivePattern(
                name="account_number",
                patterns=[
                    re.compile(r"account[_\-]?number", re.IGNORECASE),
                    re.compile(r"account[_\-]?no", re.IGNORECASE),
                    re.compile(r"acct[_\-]?no", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.PARTIAL,
                show_chars=4,
                mask_char="*",
            ),
            # 카드 번호
            SensitivePattern(
                name="card_number",
                patterns=[
                    re.compile(r"card[_\-]?number", re.IGNORECASE),
                    re.compile(r"card[_\-]?no", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.PARTIAL,
                show_chars=4,
                mask_char="*",
            ),
            # 주민번호/사업자번호
            SensitivePattern(
                name="identification",
                patterns=[
                    re.compile(r"ssn", re.IGNORECASE),
                    re.compile(r"social[_\-]?security", re.IGNORECASE),
                    re.compile(r"business[_\-]?registration", re.IGNORECASE),
                    re.compile(r"registration[_\-]?number", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.FULL,
                mask_char="*",
            ),
            # API 키 일반
            SensitivePattern(
                name="api_key",
                patterns=[
                    re.compile(r"api[_\-]?key", re.IGNORECASE),
                    re.compile(r"apikey", re.IGNORECASE),
                ],
                masking_level=MaskingLevel.PARTIAL,
                show_chars=6,
                mask_char="*",
            ),
        ]

        return patterns

    def is_sensitive_key(self, key: str) -> SensitivePattern | None:
        """키가 민감한 정보인지 확인하고 해당 패턴 반환."""
        for pattern_def in self._sensitive_patterns:
            for pattern in pattern_def.patterns:
                if pattern.search(key):
                    return pattern_def
        return None

    def mask_value(self, value: str, pattern: SensitivePattern) -> str:
        """값을 패턴에 따라 마스킹."""
        if not value or not isinstance(value, str):
            return str(value)

        # 마스킹 레벨이 NONE이면 원본 반환
        if self._masking_level == MaskingLevel.NONE:
            return value

        # 완전 마스킹
        if (
            self._masking_level == MaskingLevel.FULL
            or pattern.masking_level == MaskingLevel.FULL
        ):
            return "***"

        # 부분 마스킹
        value_len = len(value)
        show_chars = min(pattern.show_chars, value_len // 2)

        # 값이 너무 짧으면 완전 마스킹
        if value_len <= 4:
            return pattern.mask_char * 3

        if show_chars > 0:
            masked_part = pattern.mask_char * 3
            return f"{value[:show_chars]}{masked_part}"
        else:
            return pattern.mask_char * 3

    def filter_sensitive_data(self, data: Any) -> Any:
        """재귀적으로 민감한 정보를 마스킹."""
        if isinstance(data, dict):
            return self._filter_dict(data)
        elif isinstance(data, list):
            return self._filter_list(data)
        elif isinstance(data, tuple):
            return tuple(self._filter_list(list(data)))
        elif isinstance(data, str):
            return self._filter_string_content(data)
        else:
            return data

    def _filter_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """딕셔너리의 민감한 정보 필터링."""
        filtered = {}

        for key, value in data.items():
            sensitive_pattern = self.is_sensitive_key(key)

            if sensitive_pattern:
                # 키가 민감한 경우 값을 마스킹
                if isinstance(value, str):
                    filtered[key] = self.mask_value(value, sensitive_pattern)
                else:
                    # 문자열이 아닌 경우 타입에 따라 처리
                    filtered[key] = (
                        "***"
                        if sensitive_pattern.masking_level == MaskingLevel.FULL
                        else str(value)
                    )
            else:
                # 재귀적으로 중첩된 구조 처리
                filtered[key] = self.filter_sensitive_data(value)

        return filtered

    def _filter_list(self, data: list[Any]) -> list[Any]:
        """리스트의 민감한 정보 필터링."""
        return [self.filter_sensitive_data(item) for item in data]

    def _filter_string_content(self, data: str) -> str:
        """문자열 내용에서 민감한 패턴 검색 및 마스킹."""
        # JSON 문자열이나 URL 파라미터 등에서 민감 정보 검출
        result = data

        # JWT 토큰 패턴 (Bearer 토큰)
        jwt_pattern = re.compile(
            r"Bearer\s+([A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)",
            re.IGNORECASE,
        )
        result = jwt_pattern.sub(r"Bearer ****", result)

        # API 키 형태의 긴 문자열 (32자 이상의 랜덤 문자열)
        api_key_pattern = re.compile(r"\b[A-Za-z0-9]{32,}\b")
        if self._masking_level != MaskingLevel.NONE:
            result = api_key_pattern.sub("****", result)

        return result


def sensitive_data_processor(logger, method_name, event_dict):
    """
    Structlog processor 함수.

    모든 로그 이벤트에서 민감한 정보를 자동으로 필터링합니다.
    """
    # 환경변수에서 필터링 활성화 여부 확인
    filtering_enabled = os.getenv("ENABLE_LOG_FILTERING", "true").lower() == "true"

    if not filtering_enabled:
        return event_dict

    # 글로벌 필터가 없거나 환경변수가 변경된 경우 새로 생성
    current_masking_level = os.getenv("LOG_MASKING_LEVEL", "partial")

    if (
        not hasattr(sensitive_data_processor, "_filter")
        or sensitive_data_processor._last_masking_level != current_masking_level
    ):
        sensitive_data_processor._filter = SensitiveDataFilter()
        sensitive_data_processor._last_masking_level = current_masking_level

    filter_instance = sensitive_data_processor._filter

    # 이벤트 딕셔너리의 모든 항목 필터링
    filtered_event = {}

    for key, value in event_dict.items():
        # 특별한 structlog 키들은 그대로 유지
        if key in ["event", "level", "timestamp", "logger"]:
            filtered_event[key] = value
        else:
            filtered_event[key] = filter_instance.filter_sensitive_data(value)

    return filtered_event


def configure_secure_logging():
    """보안 로깅 설정 함수."""
    import structlog

    # 기존 processors 가져오기
    processors = [
        sensitive_data_processor,  # 민감 정보 필터링을 먼저 수행
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # 개발 환경에서는 이쁜 출력
    if os.getenv("ENVIRONMENT", "development").lower() == "development":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class SecurityConfig(BaseModel):
    """보안 설정 클래스."""

    @classmethod
    def get_masking_level(cls) -> MaskingLevel:
        """현재 마스킹 수준 반환."""
        env = os.getenv("ENVIRONMENT", "development").lower()
        level = os.getenv("LOG_MASKING_LEVEL", "").lower()

        if level in [e.value for e in MaskingLevel]:
            return MaskingLevel(level)

        return MaskingLevel.FULL if env == "production" else MaskingLevel.PARTIAL

    @classmethod
    def is_filtering_enabled(cls) -> bool:
        """로그 필터링 활성화 여부 반환."""
        return os.getenv("ENABLE_LOG_FILTERING", "true").lower() == "true"

    @classmethod
    def get_performance_mode(cls) -> bool:
        """성능 모드 활성화 여부 반환."""
        return os.getenv("LOG_FILTERING_PERFORMANCE_MODE", "false").lower() == "true"


# 모듈 수준에서 사용할 수 있는 기본 필터 인스턴스
default_filter = SensitiveDataFilter()


# 편의 함수들
def filter_dict(data: dict[str, Any]) -> dict[str, Any]:
    """딕셔너리 필터링 편의 함수."""
    return default_filter.filter_sensitive_data(data)


def filter_string(data: str) -> str:
    """문자열 필터링 편의 함수."""
    return default_filter.filter_sensitive_data(data)


def is_sensitive(key: str) -> bool:
    """키가 민감한지 확인하는 편의 함수."""
    return default_filter.is_sensitive_key(key) is not None
