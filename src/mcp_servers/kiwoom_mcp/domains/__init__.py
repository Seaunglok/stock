"""
키움 도메인 서버 패키지 (5개 새로운 도메인)

아키텍처 개요:
    - MarketDomainServer (8031): 실시간 시세/호가/체결, 차트, 랭킹
    - InfoDomainServer (8032): 종목/업종/테마/ETF 정보
    - TradingDomainServer (8030): 주문/정정/취소, 체결/미체결, 리스크
    - InvestorDomainServer (8033): 기관/외국인/프로그램 매매 동향
    - PortfolioDomainServer (8034): 계좌/보유종목/손익/성과/리스크

Beginner notes:
    - 각 도메인은 ``KiwoomDomainServer``를 상속합니다. 공통 CORS 설정,
      표준 응답(``StandardResponse``), 에러 포맷을 재사용합니다.
    - 모든 도구는 ``@server.mcp.tool()`` 데코레이터로 등록되어 FastMCP의
      HTTP/Streaming 엔드포인트로 노출됩니다.
    - 로컬 개발에서는 포트 충돌을 주의하세요. 각 도메인은 고정 포트를
      사용하므로 병렬 실행 시 포트가 열려 있어야 합니다.
"""

from src.mcp_servers.kiwoom_mcp.domains.info_domain import (
    InfoDomainServer,
    create_info_domain_server,
)
from src.mcp_servers.kiwoom_mcp.domains.investor_domain import (
    InvestorDomainServer,
    create_investor_domain_server,
)
from src.mcp_servers.kiwoom_mcp.domains.market_domain import (
    MarketDomainServer,
    create_market_domain_server,
)
from src.mcp_servers.kiwoom_mcp.domains.portfolio_domain import (
    PortfolioDomainServer,
    create_portfolio_domain_server,
)
from src.mcp_servers.kiwoom_mcp.domains.trading_domain import (
    TradingDomainServer,
    create_trading_domain_server,
)

__all__ = [
    "MarketDomainServer",
    "create_market_domain_server",
    "TradingDomainServer",
    "create_trading_domain_server",
    "InvestorDomainServer",
    "create_investor_domain_server",
    "InfoDomainServer",
    "create_info_domain_server",
    "PortfolioDomainServer",
    "create_portfolio_domain_server",
]

# 도메인 서버 포트 매핑 (5개 새로운 도메인)
DOMAIN_PORTS = {
    "market": 8031,  # 시장 데이터 (market_data, chart 등)
    "info": 8032,  # 종목 정보 (stock_info, etf, theme 등)
    "trading": 8030,  # 거래 관리 (order, account 등)
    "investor": 8033,  # 투자자 정보 (institutional, foreign 등)
    "portfolio": 8034,  # 포트폴리오 관리 (portfolio, risk 등)
}

# 도메인 서버 팩토리
DOMAIN_FACTORIES = {
    "market": create_market_domain_server,
    "trading": create_trading_domain_server,
    "investor": create_investor_domain_server,
    "info": create_info_domain_server,
    "portfolio": create_portfolio_domain_server,
}


def create_domain_server(domain_name: str, debug: bool = False):
    """
    도메인 이름으로 서버 생성

    Args:
        domain_name: 도메인 이름 (market, trading, info, investor, portfolio)
        debug: 디버그 모드 활성화

    Returns:
        해당 도메인 서버 인스턴스

    Raises:
        ValueError: 지원하지 않는 도메인 이름
    """
    if domain_name not in DOMAIN_FACTORIES:
        available = ", ".join(DOMAIN_FACTORIES.keys())
        raise ValueError(f"Unknown domain '{domain_name}'. Available: {available}")

    factory = DOMAIN_FACTORIES[domain_name]
    return factory(debug=debug)


def get_domain_port(domain_name: str) -> int:
    """
    도메인 이름으로 포트 번호 조회

    Args:
        domain_name: 도메인 이름

    Returns:
        포트 번호

    Raises:
        ValueError: 지원하지 않는 도메인 이름
    """
    if domain_name not in DOMAIN_PORTS:
        available = ", ".join(DOMAIN_PORTS.keys())
        raise ValueError(f"Unknown domain '{domain_name}'. Available: {available}")

    return DOMAIN_PORTS[domain_name]


def list_available_domains() -> list[str]:
    """사용 가능한 도메인 목록 반환"""
    return list(DOMAIN_FACTORIES.keys())
