"""Trading 에이전트 Claude SDK 실행기."""

from src.claude_agents.base.claude_executor import BaseClaudeAgentExecutor
from src.claude_agents.base.mcp_config import get_mcp_urls
from src.claude_agents.base.prompts import TRADING_AGENT_SYSTEM_PROMPT


class TradingClaudeExecutor(BaseClaudeAgentExecutor):
    """리스크 관리 및 주문 실행 전용 Claude 에이전트 실행기.

    연결 MCP 서버:
        - trading-domain (주문 관리, 모의 거래)
        - portfolio-domain (포트폴리오 최적화, VaR, Sharpe)
    """

    mcp_server_urls = get_mcp_urls("trading")
    system_prompt = TRADING_AGENT_SYSTEM_PROMPT
