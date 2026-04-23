"""
Korean Market Common Configuration and Utilities
한국 시장 공통 설정 및 유틸리티 모듈

이 모듈은 risk_control_mcp, order_management_mcp 등에서 중복 사용되던
한국 시장 특화 설정과 유틸리티를 통합합니다.
"""

from datetime import datetime, time
from typing import Literal

import pytz
from pydantic import BaseModel, Field


class KoreanMarketConfig(BaseModel):
    """한국 시장 설정"""

    # 거래 시간 설정 (KST)
    market_open_time: time = Field(default=time(9, 0), description="시장 개장 시간")
    market_close_time: time = Field(default=time(15, 30), description="시장 마감 시간")
    lunch_break_start: time = Field(default=time(12, 0), description="점심 시간 시작")
    lunch_break_end: time = Field(default=time(13, 0), description="점심 시간 종료")

    # 집중 거래 시간대
    high_volume_periods: list[tuple[time, time]] = Field(
        default=[
            (time(9, 0), time(9, 30)),  # 개장 후 30분
            (time(15, 0), time(15, 30)),  # 마감 전 30분
        ],
        description="집중 거래 시간대",
    )

    # 리스크 조정 계수
    market_hours_risk_factor: float = Field(
        default=1.2, description="장중 리스크 조정 계수"
    )
    off_hours_risk_factor: float = Field(
        default=0.8, description="장외 리스크 조정 계수"
    )

    # KOSDAQ 리스크 프리미엄
    kosdaq_risk_premium: float = Field(
        default=0.2, description="KOSDAQ 종목 추가 리스크 프리미엄 (20%)"
    )


class KoreanMarketUtils:
    """한국 시장 유틸리티 함수"""

    def __init__(self, config: KoreanMarketConfig | None = None):
        self.config = config or KoreanMarketConfig()
        self.kst = pytz.timezone("Asia/Seoul")

    def get_current_time(self) -> datetime:
        """현재 한국 시간 반환"""
        return datetime.now(self.kst)

    def is_market_hours(self) -> bool:
        """현재 장중인지 확인"""
        now = self.get_current_time()

        # 주말 체크
        if now.weekday() >= 5:  # 토요일(5), 일요일(6)
            return False

        current_time = now.time()

        # 오전 세션
        morning_session = (
            self.config.market_open_time <= current_time < self.config.lunch_break_start
        )

        # 오후 세션
        afternoon_session = (
            self.config.lunch_break_end <= current_time <= self.config.market_close_time
        )

        return morning_session or afternoon_session

    def is_high_volume_period(self) -> bool:
        """현재 집중 거래 시간대인지 확인"""
        if not self.is_market_hours():
            return False

        current_time = self.get_current_time().time()

        for start, end in self.config.high_volume_periods:
            if start <= current_time <= end:
                return True

        return False

    def get_market_risk_factor(self) -> float:
        """현재 시간대별 리스크 팩터 반환"""
        if self.is_market_hours():
            return self.config.market_hours_risk_factor
        return self.config.off_hours_risk_factor

    def validate_stock_symbol(self, symbol: str) -> tuple[bool, str]:
        """
        한국 주식 종목 코드 검증

        Args:
            symbol: 종목 코드

        Returns:
            (유효 여부, 오류 메시지 또는 성공 메시지)
        """
        # 길이 검증
        if len(symbol) != 6:
            return False, "종목 코드는 6자리여야 합니다."

        # 숫자 검증
        if not symbol.isdigit():
            return False, "종목 코드는 숫자로만 구성되어야 합니다."

        # 범위 검증
        try:
            code = int(symbol)
            if code < 1 or code > 999999:
                return False, "올바르지 않은 종목 코드 범위입니다."
        except ValueError:
            return False, "종목 코드 변환 오류"

        # KOSPI/KOSDAQ 구분
        market_type = self.get_market_type(symbol)
        return True, f"유효한 {market_type} 종목입니다."

    def get_market_type(self, symbol: str) -> Literal["KOSPI", "KOSDAQ", "기타"]:
        """
        종목 코드로 시장 구분

        Args:
            symbol: 종목 코드

        Returns:
            시장 구분 (KOSPI, KOSDAQ, 기타)
        """
        if not symbol or len(symbol) != 6:
            return "기타"

        # KOSDAQ: 0 또는 3으로 시작
        if symbol.startswith(("0", "3")):
            return "KOSDAQ"

        # KOSPI: 그 외
        return "KOSPI"

    def is_kosdaq_symbol(self, symbol: str) -> bool:
        """KOSDAQ 종목 여부 확인"""
        return self.get_market_type(symbol) == "KOSDAQ"

    def apply_kosdaq_adjustment(
        self, base_value: float, portfolio_kosdaq_weight: float
    ) -> float:
        """
        KOSDAQ 비중에 따른 값 조정

        Args:
            base_value: 기본 값
            portfolio_kosdaq_weight: 포트폴리오 내 KOSDAQ 비중 (0.0 ~ 1.0)

        Returns:
            조정된 값
        """
        adjustment_factor = 1 + (
            portfolio_kosdaq_weight * self.config.kosdaq_risk_premium
        )
        return base_value * adjustment_factor

    def get_market_status_message(self) -> str:
        """현재 시장 상태 메시지 반환"""
        now = self.get_current_time()
        current_time = now.time()

        # 주말
        if now.weekday() >= 5:
            return " 주말 휴장"

        # 장중
        if self.is_market_hours():
            if self.is_high_volume_period():
                return " 집중 거래 시간"

            if current_time < self.config.lunch_break_start:
                return " 오전 장"
            else:
                return " 오후 장"

        # 점심 시간
        if self.config.lunch_break_start <= current_time < self.config.lunch_break_end:
            return "️ 점심 시간"

        # 장 시작 전
        if current_time < self.config.market_open_time:
            return "⏰ 장 시작 전"

        # 장 마감 후
        if current_time > self.config.market_close_time:
            return " 장 마감"

        return " 알 수 없음"

    def calculate_portfolio_kosdaq_weight(self, portfolio: dict) -> float:
        """
        포트폴리오의 KOSDAQ 비중 계산

        Args:
            portfolio: 포트폴리오 정보 (positions 포함)

        Returns:
            KOSDAQ 비중 (0.0 ~ 1.0)
        """
        if not portfolio or "positions" not in portfolio:
            return 0.0

        total_weight = 0.0
        kosdaq_weight = 0.0

        for position in portfolio.get("positions", []):
            symbol = position.get("symbol", "")
            weight = position.get("weight", 0.0)

            total_weight += weight

            if self.is_kosdaq_symbol(symbol):
                kosdaq_weight += weight

        if total_weight == 0:
            return 0.0

        return kosdaq_weight / total_weight


# 전역 인스턴스 (기본 설정)
default_korean_market = KoreanMarketUtils()
