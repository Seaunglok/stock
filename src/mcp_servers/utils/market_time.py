"""
한국 주식시장 시간 관리 유틸리티

한국 주식시장의 거래시간, 공휴일, 시간대별 특성을 반영하는 시간 관련 함수들을 제공합니다.

Beginner notes:
    - All times are normalized to KST (Asia/Seoul). Pass timezone-naive inputs
      and they will be localized. Pass aware inputs and they will be converted.
    - Holiday sets are static examples. For production, wire an official KRX
      calendar provider or update yearly.
"""

import random
from datetime import date, datetime, time, timedelta
from enum import Enum

import pytz
import structlog

logger = structlog.get_logger(__name__)

# 한국 표준시 (KST)
KST = pytz.timezone("Asia/Seoul")

# 거래 시간 상수
MARKET_OPEN_TIME = time(9, 0, 0)  # 09:00:00
MARKET_CLOSE_TIME = time(15, 30, 0)  # 15:30:00
PRE_MARKET_START = time(8, 30, 0)  # 08:30:00 (시간외 거래 시작)
POST_MARKET_END = time(16, 0, 0)  # 16:00:00 (시간외 거래 종료)


class TradingSession(Enum):
    """거래 세션 구분."""

    PRE_MARKET = "장전"  # 8:30-9:00
    REGULAR = "정규장"  # 9:00-15:30
    POST_MARKET = "시간외"  # 15:30-16:00
    CLOSED = "휴장"  # 그 외 시간


# 한국 주요 공휴일 데이터 (KRX 휴장일 기준)
KOREAN_HOLIDAYS: dict[int, list[str]] = {
    2024: [
        "2024-01-01",  # 신정
        "2024-02-09",
        "2024-02-10",
        "2024-02-11",
        "2024-02-12",  # 설날 연휴
        "2024-03-01",  # 삼일절
        "2024-04-10",  # 국회의원선거일
        "2024-05-01",  # 근로자의날
        "2024-05-05",  # 어린이날 (일요일이라 대체공휴일 없음)
        "2024-05-06",  # 어린이날 대체공휴일
        "2024-05-15",  # 부처님오신날
        "2024-06-06",  # 현충일
        "2024-08-15",  # 광복절
        "2024-09-16",
        "2024-09-17",
        "2024-09-18",  # 추석 연휴
        "2024-10-03",  # 개천절
        "2024-10-09",  # 한글날
        "2024-12-25",  # 성탄절
        "2024-12-31",  # 연말휴장
    ],
    2025: [
        "2025-01-01",  # 신정
        "2025-01-28",
        "2025-01-29",
        "2025-01-30",  # 설날 연휴
        "2025-03-01",  # 삼일절 (토요일이라 대체공휴일 없음)
        "2025-05-01",  # 근로자의날
        "2025-05-05",  # 어린이날
        "2025-05-06",  # 부처님오신날
        "2025-06-06",  # 현충일
        "2025-08-15",  # 광복절
        "2025-10-05",
        "2025-10-06",
        "2025-10-07",  # 추석 연휴
        "2025-10-03",  # 개천절
        "2025-10-09",  # 한글날
        "2025-12-25",  # 성탄절
        "2025-12-31",  # 연말휴장
    ],
    2026: [
        "2026-01-01",  # 신정
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",  # 설날 연휴 (예상)
        "2026-03-01",  # 삼일절
        "2026-05-01",  # 근로자의날
        "2026-05-05",  # 어린이날
        "2026-05-24",  # 부처님오신날 (예상)
        "2026-06-06",  # 현충일
        "2026-08-15",  # 광복절
        "2026-09-24",
        "2026-09-25",
        "2026-09-26",  # 추석 연휴 (예상)
        "2026-10-03",  # 개천절
        "2026-10-09",  # 한글날
        "2026-12-25",  # 성탄절
        "2026-12-31",  # 연말휴장
    ],
}


def get_market_time(target_datetime: datetime | None = None) -> datetime:
    """
    현재 시간을 실제 거래시간 범위로 조정하여 반환합니다.

    장 시간 외에는 가장 가까운 거래시간으로 조정됩니다:
    - 장전 시간(8:30 이전): 9:00으로 조정
    - 장후 시간(15:30 이후): 15:30으로 조정
    - 주말/공휴일: 가장 가까운 거래일의 거래시간으로 조정

    Args:
        target_datetime: 조정할 기준 시간 (None이면 현재 시간)

    Returns:
        조정된 거래시간 (KST)

    """
    if target_datetime is None:
        now = datetime.now(KST)
    else:
        # timezone-naive인 경우 KST로 설정
        if target_datetime.tzinfo is None:
            now = KST.localize(target_datetime)
        else:
            now = target_datetime.astimezone(KST)

    current_date = now.date()

    # 거래일인지 확인
    if not is_trading_day(current_date):
        # 가장 가까운 거래일 찾기
        trading_date = _get_next_trading_day(current_date)
        # 해당 거래일의 장 시작 시간 + 랜덤 조정
        market_time = datetime.combine(trading_date, MARKET_OPEN_TIME)
        market_time = KST.localize(market_time)

        # 장 시작 후 0-6시간 30분 사이의 랜덤 시간 추가
        random_minutes = random.randint(0, 390)  # 6시간 30분 = 390분
        market_time += timedelta(minutes=random_minutes)

        # 15:30을 넘지 않도록 제한
        close_time = datetime.combine(trading_date, MARKET_CLOSE_TIME)
        close_time = KST.localize(close_time)
        if market_time > close_time:
            market_time = close_time

        return market_time

    # 거래일인 경우 현재 시간을 거래시간으로 조정
    current_time = now.time()

    if current_time < PRE_MARKET_START:
        # 8:30 이전 → 9:00으로 조정
        target_time = MARKET_OPEN_TIME
    elif current_time > MARKET_CLOSE_TIME:
        # 15:30 이후 → 15:30으로 조정
        target_time = MARKET_CLOSE_TIME
    else:
        # 거래시간 내 → 현재 시간 유지
        target_time = current_time

    adjusted_time = datetime.combine(current_date, target_time)
    return KST.localize(adjusted_time)


def is_trading_day(target_date: date | datetime) -> bool:
    """
    해당 날짜가 거래일인지 확인합니다.

    주말(토, 일)과 한국 주요 공휴일을 거래 휴장일로 처리합니다.

    Args:
        target_date: 확인할 날짜

    Returns:
        거래일이면 True, 휴장일이면 False

    """
    check_date = (
        target_date.date() if isinstance(target_date, datetime) else target_date
    )

    # 주말 체크 (토: 5, 일: 6)
    if check_date.weekday() >= 5:
        return False

    # 공휴일 체크
    year = check_date.year
    if year in KOREAN_HOLIDAYS:
        date_str = check_date.strftime("%Y-%m-%d")
        if date_str in KOREAN_HOLIDAYS[year]:
            return False

    return True


def get_trading_session(target_datetime: datetime | None = None) -> TradingSession:
    """
    현재 시간의 거래 세션을 반환합니다.

    Args:
        target_datetime: 확인할 시간 (None이면 현재 시간)

    Returns:
        거래 세션 구분

    """
    if target_datetime is None:
        now = datetime.now(KST)
    else:
        if target_datetime.tzinfo is None:
            now = KST.localize(target_datetime)
        else:
            now = target_datetime.astimezone(KST)

    # 거래일이 아니면 휴장
    if not is_trading_day(now.date()):
        return TradingSession.CLOSED

    current_time = now.time()

    if PRE_MARKET_START <= current_time < MARKET_OPEN_TIME:
        return TradingSession.PRE_MARKET
    elif MARKET_OPEN_TIME <= current_time < MARKET_CLOSE_TIME:
        return TradingSession.REGULAR
    elif MARKET_CLOSE_TIME <= current_time < POST_MARKET_END:
        return TradingSession.POST_MARKET
    else:
        return TradingSession.CLOSED


def get_trading_volume_multiplier(target_datetime: datetime | None = None) -> float:
    """
    시간대별 거래량 특성을 반영한 승수를 반환합니다.

    한국 주식시장의 거래량 패턴을 반영:
    - 장 초반(9:00-10:00): 높은 거래량 (1.5-2.0배)
    - 장 중반(10:00-14:00): 안정적 거래량 (0.8-1.2배)
    - 장 종반(14:00-15:30): 높은 거래량 (1.3-1.8배)
    - 시간외: 낮은 거래량 (0.3-0.6배)
    - 휴장: 거래량 없음 (0.0배)

    Args:
        target_datetime: 확인할 시간 (None이면 현재 시간)

    Returns:
        거래량 승수 (0.0-2.0 범위)

    """
    if target_datetime is None:
        now = datetime.now(KST)
    else:
        if target_datetime.tzinfo is None:
            now = KST.localize(target_datetime)
        else:
            now = target_datetime.astimezone(KST)

    session = get_trading_session(now)
    current_time = now.time()

    if session == TradingSession.CLOSED:
        return 0.0
    elif session == TradingSession.PRE_MARKET or session == TradingSession.POST_MARKET:
        return random.uniform(0.3, 0.6)
    elif session == TradingSession.REGULAR:
        # 정규장 시간대별 패턴
        if time(9, 0) <= current_time < time(10, 0):
            # 장 초반: 높은 거래량
            return random.uniform(1.5, 2.0)
        elif time(10, 0) <= current_time < time(14, 0):
            # 장 중반: 안정적 거래량
            return random.uniform(0.8, 1.2)
        elif time(14, 0) <= current_time < time(15, 30):
            # 장 종반: 높은 거래량
            return random.uniform(1.3, 1.8)
        else:
            return 1.0
    else:
        return 1.0


def get_next_trading_day(
    target_date: date | datetime | None = None, days_ahead: int = 1
) -> date:
    """
    지정된 날짜 이후의 거래일을 찾아 반환합니다.

    Args:
        target_date: 기준 날짜 (None이면 현재 날짜)
        days_ahead: 찾을 거래일 수 (기본 1일)

    Returns:
        다음 거래일

    """
    if target_date is None:
        start_date = datetime.now(KST).date()
    elif isinstance(target_date, datetime):
        start_date = target_date.date()
    else:
        start_date = target_date

    return _get_next_trading_day(start_date, days_ahead)


def get_previous_trading_day(
    target_date: date | datetime | None = None, days_back: int = 1
) -> date:
    """
    지정된 날짜 이전의 거래일을 찾아 반환합니다.

    Args:
        target_date: 기준 날짜 (None이면 현재 날짜)
        days_back: 찾을 거래일 수 (기본 1일)

    Returns:
        이전 거래일

    """
    if target_date is None:
        start_date = datetime.now(KST).date()
    elif isinstance(target_date, datetime):
        start_date = target_date.date()
    else:
        start_date = target_date

    return _get_previous_trading_day(start_date, days_back)


def _get_next_trading_day(start_date: date, days_ahead: int = 1) -> date:
    """다음 거래일을 찾는 내부 함수."""
    current_date = start_date + timedelta(days=1)
    found_days = 0

    while found_days < days_ahead:
        if is_trading_day(current_date):
            found_days += 1
            if found_days == days_ahead:
                return current_date
        current_date += timedelta(days=1)

        # 무한 루프 방지 (최대 30일)
        if (current_date - start_date).days > 30:
            logger.warning(
                "next_trading_day_search_limit_exceeded",
                start_date=start_date,
                days_ahead=days_ahead,
            )
            break

    return current_date


def _get_previous_trading_day(start_date: date, days_back: int = 1) -> date:
    """이전 거래일을 찾는 내부 함수."""
    current_date = start_date - timedelta(days=1)
    found_days = 0

    while found_days < days_back:
        if is_trading_day(current_date):
            found_days += 1
            if found_days == days_back:
                return current_date
        current_date -= timedelta(days=1)

        # 무한 루프 방지 (최대 30일)
        if (start_date - current_date).days > 30:
            logger.warning(
                "previous_trading_day_search_limit_exceeded",
                start_date=start_date,
                days_back=days_back,
            )
            break

    return current_date


def get_market_hours_info() -> dict[str, str | time]:
    """
    한국 주식시장의 거래시간 정보를 반환합니다.

    Returns:
        거래시간 정보 딕셔너리

    """
    return {
        "timezone": "Asia/Seoul",
        "pre_market_start": PRE_MARKET_START,
        "market_open": MARKET_OPEN_TIME,
        "market_close": MARKET_CLOSE_TIME,
        "post_market_end": POST_MARKET_END,
        "description": "한국거래소(KRX) 주식시장 거래시간",
    }


def format_market_time(dt: datetime, include_session: bool = True) -> str:
    """
    거래시간을 한국 형식으로 포맷팅합니다.

    Args:
        dt: 포맷팅할 시간
        include_session: 거래 세션 정보 포함 여부

    Returns:
        포맷팅된 시간 문자열

    """
    dt = KST.localize(dt) if dt.tzinfo is None else dt.astimezone(KST)

    formatted = dt.strftime("%Y-%m-%d %H:%M:%S KST")

    if include_session:
        session = get_trading_session(dt)
        formatted += f" ({session.value})"

    return formatted
