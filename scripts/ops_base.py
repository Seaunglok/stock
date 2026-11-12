"""운용 공용 기반 — I3·리그·일지·점검 코드가 부르는 이름 (2026-11-12, 리팩터링 3번).

공용 기반(.env 로드·MCP URL·계좌·텔레그램 알림)이 종료한 트랙 이름(`trend_config`·`trend_runtime`)을 달고 있어서,
I3 쪽 코드가 '추세추종'을 import 하는 것처럼 읽혔다. 이제 I3 쪽은 이 모듈 이름으로 부른다.

구현은 **옮기지 않고 그대로 다시 내보낸다** — `trend_config` 는 import 때 `.env` 를 읽고(LIVE-GUARD `ENV_LOADED`) 그 값으로
상수를 만든다. 구현을 옮기면 `.env` 를 읽는 순서와 `tests/test_trend_config.py` 의 reload 시험(설정 파일 없음 재현)이
흔들린다. 그래서 이름만 한 곳으로 모으고, 나중에 구현을 옮길 때도 바꿀 곳은 여기 하나다.
"""
from __future__ import annotations

from trend_config import (  # noqa: F401 — 다시 내보내기
    ACCOUNT_NO, INFO_URL, INVESTOR_URL, MARKET_URL, PORTFOLIO_URL, PRODUCTION_MODE, TRADING_URL,
)
from trend_runtime import notify  # noqa: F401 — 텔레그램(critical 이면 TELEGRAM_CRITICAL_CHAT_ID)

__all__ = ["ACCOUNT_NO", "INFO_URL", "INVESTOR_URL", "MARKET_URL", "PORTFOLIO_URL", "PRODUCTION_MODE", "TRADING_URL",
           "notify"]
