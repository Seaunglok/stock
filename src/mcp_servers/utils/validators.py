"""MCP 서버 공통 검증 유틸리티.

Beginner notes:
    - All validators return ``ValidationResult`` with ``is_valid`` and either
      ``validated_data`` or a Korean ``error_message`` for UI display.
    - Price tick size is simplified for KRX; adjust units as needed.
"""

from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger(__name__)


class ValidationResult(BaseModel):
    """검증 결과."""

    is_valid: bool
    error_message: str | None = None
    validated_data: Any | None = None


def validate_symbol(symbol: str) -> ValidationResult:
    """
    종목 코드 검증.

    Args:
        symbol: 종목 코드

    Returns:
        ValidationResult: 검증 결과

    """
    # 한국 주식 코드 패턴 (6자리 숫자)
    if not symbol:
        return ValidationResult(
            is_valid=False, error_message="종목 코드가 비어있습니다."
        )

    if not symbol.isdigit():
        return ValidationResult(
            is_valid=False, error_message="종목 코드는 숫자로만 구성되어야 합니다."
        )

    if len(symbol) != 6:
        return ValidationResult(
            is_valid=False, error_message="종목 코드는 6자리여야 합니다."
        )

    return ValidationResult(is_valid=True, validated_data=symbol)


def validate_date_range(start_date: str, end_date: str) -> ValidationResult:
    """
    날짜 범위 검증.

    Args:
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)

    Returns:
        ValidationResult: 검증 결과

    """
    from datetime import datetime

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        if start > end:
            return ValidationResult(
                is_valid=False, error_message="시작일이 종료일보다 늦습니다."
            )

        # 최대 5년 제한
        max_days = 365 * 5
        if (end - start).days > max_days:
            return ValidationResult(
                is_valid=False,
                error_message=f"조회 기간은 최대 {max_days}일까지 가능합니다.",
            )

        return ValidationResult(
            is_valid=True,
            validated_data={
                "start_date": start_date,
                "end_date": end_date,
                "days": (end - start).days,
            },
        )

    except ValueError as e:
        return ValidationResult(
            is_valid=False,
            error_message=f"날짜 형식이 올바르지 않습니다 (YYYY-MM-DD): {e!s}",
        )


def validate_price(price: float, min_price: float = 0) -> ValidationResult:
    """
    가격 검증.

    Args:
        price: 가격
        min_price: 최소 가격

    Returns:
        ValidationResult: 검증 결과

    """
    if price < min_price:
        return ValidationResult(
            is_valid=False, error_message=f"가격은 {min_price} 이상이어야 합니다."
        )

    # 한국 주식 호가 단위 체크 (간단한 버전)
    if price < 1000:
        unit = 1
    elif price < 5000:
        unit = 5
    elif price < 10000:
        unit = 10
    elif price < 50000:
        unit = 50
    elif price < 100000:
        unit = 100
    elif price < 500000:
        unit = 500
    else:
        unit = 1000

    if int(price) % unit != 0:
        return ValidationResult(
            is_valid=False,
            error_message=f"가격 {price}은(는) 호가 단위 {unit}원에 맞지 않습니다.",
        )

    return ValidationResult(is_valid=True, validated_data=int(price))


def validate_quantity(quantity: int, min_qty: int = 1) -> ValidationResult:
    """
    수량 검증.

    Args:
        quantity: 수량
        min_qty: 최소 수량

    Returns:
        ValidationResult: 검증 결과

    """
    if quantity < min_qty:
        return ValidationResult(
            is_valid=False, error_message=f"수량은 {min_qty} 이상이어야 합니다."
        )

    if quantity > 1000000:  # 임의의 최대값
        return ValidationResult(
            is_valid=False, error_message="수량이 너무 큽니다 (최대 1,000,000)."
        )

    return ValidationResult(is_valid=True, validated_data=quantity)


def validate_model(data: dict, model_class: type[BaseModel]) -> ValidationResult:
    """
    Pydantic 모델 검증.

    Args:
        data: 검증할 데이터
        model_class: Pydantic 모델 클래스

    Returns:
        ValidationResult: 검증 결과

    """
    try:
        validated = model_class(**data)
        return ValidationResult(is_valid=True, validated_data=validated)
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            error_messages.append(f"{field}: {msg}")

        return ValidationResult(is_valid=False, error_message="; ".join(error_messages))


def validate_technical_indicator_params(
    indicator: str, params: dict
) -> ValidationResult:
    """
    기술적 지표 파라미터 검증.

    Args:
        indicator: 지표 이름
        params: 지표 파라미터

    Returns:
        ValidationResult: 검증 결과

    """
    # 공통 파라미터 검증
    period = params.get("period", 20)
    if not isinstance(period, int) or period < 1 or period > 200:
        return ValidationResult(
            is_valid=False, error_message="Period는 1-200 사이의 정수여야 합니다."
        )

    # 지표별 특수 검증
    if indicator.upper() == "MACD":
        fast_period = params.get("fast_period", 12)
        slow_period = params.get("slow_period", 26)
        signal_period = params.get("signal_period", 9)

        if fast_period >= slow_period:
            return ValidationResult(
                is_valid=False,
                error_message="MACD fast_period는 slow_period보다 작아야 합니다.",
            )

        if not all(
            isinstance(p, int) and p > 0
            for p in [fast_period, slow_period, signal_period]
        ):
            return ValidationResult(
                is_valid=False,
                error_message="MACD 파라미터는 모두 양의 정수여야 합니다.",
            )

    elif indicator.upper() == "BOLLINGER":
        period = params.get("period", 20)
        std_dev = params.get("std_dev", 2.0)

        if not isinstance(std_dev, int | float) or std_dev <= 0:
            return ValidationResult(
                is_valid=False,
                error_message="Bollinger Bands std_dev는 양수여야 합니다.",
            )

    elif indicator.upper() == "RSI":
        period = params.get("period", 14)

        if period < 2 or period > 100:
            return ValidationResult(
                is_valid=False, error_message="RSI period는 2-100 사이여야 합니다."
            )

    return ValidationResult(is_valid=True, validated_data=params)


def validate_timeframe(timeframe: str) -> ValidationResult:
    """
    시간프레임 검증.

    Args:
        timeframe: 시간프레임 (예: '1m', '5m', '1h', '1d')

    Returns:
        ValidationResult: 검증 결과

    """
    import re

    # 시간프레임 패턴 검증
    pattern = r"^(\d+)([mhd])$"
    match = re.match(pattern, timeframe.lower())

    if not match:
        return ValidationResult(
            is_valid=False,
            error_message="시간프레임 형식이 올바르지 않습니다 (예: 1m, 5m, 1h, 1d).",
        )

    value, unit = match.groups()
    value = int(value)

    # 단위별 범위 검증
    if unit == "m":  # 분
        if value not in [1, 3, 5, 10, 15, 30]:
            return ValidationResult(
                is_valid=False,
                error_message="분봉은 1, 3, 5, 10, 15, 30분만 지원됩니다.",
            )
    elif unit == "h":  # 시간
        if value not in [1, 4]:
            return ValidationResult(
                is_valid=False, error_message="시간봉은 1, 4시간만 지원됩니다."
            )
    elif unit == "d":  # 일
        if value != 1:
            return ValidationResult(
                is_valid=False, error_message="일봉은 1일만 지원됩니다."
            )

    return ValidationResult(is_valid=True, validated_data=timeframe)


def validate_market_session(session: str) -> ValidationResult:
    """
    시장 세션 검증.

    Args:
        session: 시장 세션 ('regular', 'pre', 'after', 'extended')

    Returns:
        ValidationResult: 검증 결과

    """
    valid_sessions = ["regular", "pre", "after", "extended"]

    if session not in valid_sessions:
        return ValidationResult(
            is_valid=False,
            error_message=f"시장 세션은 {valid_sessions} 중 하나여야 합니다.",
        )

    return ValidationResult(is_valid=True, validated_data=session)


class ResponseValidator:
    """
    KiwoomRESTAPIClient 응답 검증 클래스.

    모드별(Mock/Paper/Production)로 다른 검증 기준을 적용하여
    각 모드의 특성에 맞는 성공/실패 판정을 수행합니다.
    """

    def __init__(self, client_mode: str = "mock"):
        """
        ResponseValidator 초기화.

        Args:
            client_mode: 클라이언트 모드 (mock/paper/production)
        """
        self.client_mode = client_mode.lower()
        self.valid_modes = ["mock", "paper", "production"]

        if self.client_mode not in self.valid_modes:
            logger.warning(
                f"Invalid client mode: {client_mode}, defaulting to mock mode"
            )
            self.client_mode = "mock"

        logger.info(f"ResponseValidator initialized with mode: {self.client_mode}")

    def validate_response(
        self, response: dict, api_id: str, duration: float = 0.0
    ) -> ValidationResult:
        """
        응답 검증 메인 메서드.

        Args:
            response: API 응답 딕셔너리
            api_id: API ID
            duration: 응답 시간 (초)

        Returns:
            ValidationResult: 검증 결과
        """
        if not response or not isinstance(response, dict):
            return ValidationResult(
                is_valid=False,
                error_message="응답이 유효하지 않거나 딕셔너리가 아닙니다",
                validated_data={
                    "response_type": type(response).__name__,
                    "api_id": api_id,
                    "duration": duration,
                },
            )

        # 모드별 검증 로직 적용
        if self.client_mode == "mock":
            return self._validate_mock_response(response, api_id, duration)
        elif self.client_mode in ["paper", "production"]:
            return self._validate_real_response(response, api_id, duration)
        else:
            # Fallback to mock validation
            return self._validate_mock_response(response, api_id, duration)

    def _validate_mock_response(
        self, response: dict, api_id: str, duration: float
    ) -> ValidationResult:
        """
        Mock 모드 응답 검증.

        Mock 응답의 경우 _mock_meta 필드 존재와 기본 구조를 확인하여
        시뮬레이션 데이터의 품질을 검증합니다.
        """
        # Mock 메타데이터 확인
        mock_meta = response.get("_mock_meta", {})
        has_mock_meta = bool(mock_meta)

        # 기본 키움 API 구조 확인
        has_rt_cd = "rt_cd" in response
        has_msg_cd = "msg_cd" in response
        rt_cd_value = response.get("rt_cd", "")

        # 데이터 필드 확인 (output, output1, output2 등)
        data_fields = [key for key in response.keys() if key.startswith("output")]
        has_data = len(data_fields) > 0 or has_mock_meta

        # Mock 응답 품질 점수 계산
        quality_score = 0
        quality_factors = []

        if has_mock_meta:
            quality_score += 40
            quality_factors.append("mock_meta_present")

            # Mock 메타데이터 세부 검증
            expected_meta_fields = ["api_id", "timestamp", "mode", "simulated"]
            meta_completeness = sum(
                1 for field in expected_meta_fields if field in mock_meta
            )
            quality_score += (meta_completeness / len(expected_meta_fields)) * 20

            if mock_meta.get("mode") == "mock":
                quality_factors.append("correct_mode")
            if mock_meta.get("api_id") == api_id:
                quality_factors.append("correct_api_id")

        if has_rt_cd and rt_cd_value == "0":
            quality_score += 20
            quality_factors.append("success_rt_cd")
        elif has_rt_cd:
            quality_score += 10
            quality_factors.append("rt_cd_present")

        if has_msg_cd:
            quality_score += 10
            quality_factors.append("msg_cd_present")

        if has_data:
            quality_score += 10
            quality_factors.append("data_present")

        # Mock 응답은 관대한 기준으로 평가
        # 70점 이상 또는 mock_meta가 있으면 성공으로 판정
        is_success = quality_score >= 70 or has_mock_meta

        if is_success:
            validated_data = {
                "mode": "mock",
                "api_id": api_id,
                "duration": duration,
                "quality_score": quality_score,
                "quality_factors": quality_factors,
                "has_mock_meta": has_mock_meta,
                "has_rt_cd": has_rt_cd,
                "has_msg_cd": has_msg_cd,
                "has_data": has_data,
                "data_fields": data_fields,
                "rt_cd": rt_cd_value,
            }

            return ValidationResult(
                is_valid=True, error_message=None, validated_data=validated_data
            )
        else:
            error_msg = f"Mock 응답 품질이 낮습니다 (점수: {quality_score}/100)"
            validated_data = {
                "mode": "mock",
                "api_id": api_id,
                "duration": duration,
                "quality_score": quality_score,
                "quality_factors": quality_factors,
                "has_mock_meta": has_mock_meta,
                "error_reason": "low_quality",
            }

            return ValidationResult(
                is_valid=False, error_message=error_msg, validated_data=validated_data
            )

    def _validate_real_response(
        self, response: dict, api_id: str, duration: float
    ) -> ValidationResult:
        """
        실제 API (Paper/Production) 모드 응답 검증.

        실제 키움 API 응답의 경우 rt_cd와 데이터 완성도를
        종합적으로 판단하여 더 엄격한 검증을 적용합니다.
        """
        # 키움 API 표준 응답 구조 확인
        has_rt_cd = "rt_cd" in response
        has_msg_cd = "msg_cd" in response
        rt_cd_value = response.get("rt_cd", "")
        msg1 = response.get("msg1", "")

        # 데이터 필드 확인
        data_fields = [key for key in response.keys() if key.startswith("output")]
        has_data = len(data_fields) > 0

        # rt_cd 기반 성공 여부 판정 (기존 로직 유지)
        is_rt_cd_success = has_rt_cd and rt_cd_value == "0"

        # 유연한 성공 기준: rt_cd=0이거나 데이터가 충분히 있는 경우
        has_substantial_data = False
        if has_data:
            # 데이터 필드의 내용 확인
            for field in data_fields:
                field_data = response.get(field, {})
                if isinstance(field_data, dict) and len(field_data) > 0:
                    has_substantial_data = True
                    break
                elif isinstance(field_data, list) and len(field_data) > 0:
                    has_substantial_data = True
                    break

        # 성공 조건: rt_cd=0 또는 실질적인 데이터 존재
        is_success = is_rt_cd_success or (has_data and has_substantial_data)

        if is_success:
            status_message = "API Success" if is_rt_cd_success else "Partial Success"
            validated_data = {
                "mode": self.client_mode,
                "api_id": api_id,
                "duration": duration,
                "status": status_message,
                "has_rt_cd": has_rt_cd,
                "has_msg_cd": has_msg_cd,
                "has_data": has_data,
                "has_substantial_data": has_substantial_data,
                "data_fields": data_fields,
                "rt_cd": rt_cd_value,
                "msg1": msg1[:100] if msg1 else None,  # 메시지 일부만 저장
            }

            return ValidationResult(
                is_valid=True, error_message=None, validated_data=validated_data
            )
        else:
            # 실패 원인 분석
            error_reasons = []
            if not has_rt_cd:
                error_reasons.append("missing_rt_cd")
            elif rt_cd_value != "0":
                error_reasons.append(f"error_rt_cd_{rt_cd_value}")

            if not has_data:
                error_reasons.append("no_data_fields")
            elif not has_substantial_data:
                error_reasons.append("empty_data_fields")

            error_msg = f"API 응답 검증 실패: {', '.join(error_reasons)}"
            validated_data = {
                "mode": self.client_mode,
                "api_id": api_id,
                "duration": duration,
                "error_reasons": error_reasons,
                "has_rt_cd": has_rt_cd,
                "rt_cd": rt_cd_value,
                "msg1": msg1[:100] if msg1 else None,
            }

            return ValidationResult(
                is_valid=False, error_message=error_msg, validated_data=validated_data
            )

    def get_validation_summary(self, results: list[ValidationResult]) -> dict:
        """
        검증 결과들의 요약 정보를 생성합니다.

        Args:
            results: ValidationResult 리스트

        Returns:
            요약 정보 딕셔너리
        """
        if not results:
            return {"total": 0, "success": 0, "failure": 0, "success_rate": 0.0}

        total = len(results)
        success = sum(1 for r in results if r.is_valid)
        failure = total - success
        success_rate = (success / total) * 100 if total > 0 else 0.0

        # 모드별 분석
        mode_stats = {}
        quality_scores = []

        for result in results:
            if result.validated_data:
                mode = result.validated_data.get("mode", "unknown")
                if mode not in mode_stats:
                    mode_stats[mode] = {"total": 0, "success": 0}

                mode_stats[mode]["total"] += 1
                if result.is_valid:
                    mode_stats[mode]["success"] += 1

                # Mock 모드의 품질 점수 수집
                if mode == "mock" and "quality_score" in result.validated_data:
                    quality_scores.append(result.validated_data["quality_score"])

        summary = {
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": round(success_rate, 1),
            "mode": self.client_mode,
            "mode_stats": mode_stats,
        }

        # Mock 모드의 경우 품질 정보 추가
        if quality_scores:
            summary["mock_quality"] = {
                "avg_score": round(sum(quality_scores) / len(quality_scores), 1),
                "min_score": min(quality_scores),
                "max_score": max(quality_scores),
                "total_evaluated": len(quality_scores),
            }

        return summary
