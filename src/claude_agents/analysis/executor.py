"""Analysis 에이전트 Claude SDK 실행기."""

from src.claude_agents.base.claude_executor import BaseClaudeAgentExecutor
from src.claude_agents.base.mcp_config import get_mcp_urls
from src.claude_agents.base.prompts import ANALYSIS_AGENT_SYSTEM_PROMPT


class AnalysisClaudeExecutor(BaseClaudeAgentExecutor):
    """4차원 주식 분석 전용 Claude 에이전트 실행기.

    연결 MCP 서버:
        - stock-analysis-mcp (기술적 분석)
        - financial-analysis-mcp (기본적 분석)
        - macroeconomic-analysis-mcp (거시경제 분석)
        - naver-news-mcp (감성 분석)
        - tavily-search-mcp (시장 트렌드)
    """

    mcp_server_urls = get_mcp_urls("analysis")
    system_prompt = ANALYSIS_AGENT_SYSTEM_PROMPT
