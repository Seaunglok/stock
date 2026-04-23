"""
Financial Analysis MCP Server

재무 분석에 특화된 MCP 서버로, 다음 기능을 제공합니다:
- DCF 밸류에이션
- 재무비율 분석
- 재무제표 분석
- 기업 가치 평가
- 투자 수익률 분석

주의: 일부 데이터 소스가 미설정일 경우 Mock 또는 대체 계산으로 폴백될 수 있습니다.
"""

from src.mcp_servers.financial_analysis_mcp.server import FinancialAnalysisMCPServer

__all__ = ["FinancialAnalysisMCPServer"]
