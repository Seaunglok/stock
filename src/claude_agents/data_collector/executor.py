"""DataCollector 에이전트 Claude SDK 실행기."""

from src.claude_agents.base.claude_executor import BaseClaudeAgentExecutor
from src.claude_agents.base.mcp_config import get_mcp_urls
from src.claude_agents.base.prompts import DATA_COLLECTOR_SYSTEM_PROMPT


class DataCollectorClaudeExecutor(BaseClaudeAgentExecutor):
    """주식 데이터 수집 전용 Claude 에이전트 실행기.

    연결 MCP 서버:
        - kiwoom-market-mcp (실시간 시세, 차트, 거래량)
        - kiwoom-info-mcp (종목 정보, ETF, 테마)
        - naver-news-mcp (뉴스 수집)
        - tavily-search-mcp (웹 검색)
    """

    mcp_server_urls = get_mcp_urls("data_collector")
    system_prompt = DATA_COLLECTOR_SYSTEM_PROMPT
