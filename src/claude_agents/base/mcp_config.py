"""
MCP 서버 URL 설정 (Docker 없이 로컬 실행 전용).

langchain-mcp-adapters 없이 순수 URL 딕셔너리만 제공합니다.
"""

# 로컬 MCP 서버 URL 맵
STANDARD_MCP_SERVERS: dict[str, str] = {
    # 키움 도메인
    "kiwoom-market-mcp":        "http://localhost:8031/mcp/",
    "kiwoom-info-mcp":          "http://localhost:8032/mcp/",
    "trading-domain":           "http://localhost:8030/mcp/",
    "investor-domain":          "http://localhost:8033/mcp/",
    "portfolio-domain":         "http://localhost:8034/mcp/",
    # 분석 도메인
    "stock-analysis-mcp":       "http://localhost:8042/mcp",
    "financial-analysis-mcp":   "http://localhost:8040/mcp",
    "macroeconomic-analysis-mcp": "http://localhost:8041/mcp",
    # 외부 서비스
    "naver-news-mcp":           "http://localhost:8050/mcp",
    "tavily-search-mcp":        "http://localhost:3020/mcp",
    # 종가배팅 (계산기)
    "closing-bet-mcp":          "http://localhost:8060/mcp",
}

# 에이전트별 MCP 서버 그룹
AGENT_MCP_SERVERS: dict[str, list[str]] = {
    "data_collector": [
        "kiwoom-market-mcp",
        "kiwoom-info-mcp",
        "investor-domain",
        "financial-analysis-mcp",
        "naver-news-mcp",
        "tavily-search-mcp",
        "closing-bet-mcp",
    ],
    "analysis": [
        "stock-analysis-mcp",
        "financial-analysis-mcp",
        "macroeconomic-analysis-mcp",
        "naver-news-mcp",
        "tavily-search-mcp",
        "closing-bet-mcp",
    ],
    "trading": [
        "trading-domain",
        "portfolio-domain",
    ],
}


def get_mcp_urls(agent_type: str) -> dict[str, str]:
    """에이전트 타입에 맞는 MCP 서버 URL 딕셔너리를 반환합니다.

    Args:
        agent_type: "data_collector" | "analysis" | "trading"

    Returns:
        {서버이름: URL} 딕셔너리
    """
    server_names = AGENT_MCP_SERVERS.get(agent_type, [])
    return {
        name: STANDARD_MCP_SERVERS[name]
        for name in server_names
        if name in STANDARD_MCP_SERVERS
    }
