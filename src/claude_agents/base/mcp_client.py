"""
MCP 서버 연결 및 Anthropic SDK 도구 변환 모듈.

langchain-mcp-adapters를 대체하며, Anthropic SDK가 직접 사용할 수 있는
형태로 MCP 도구를 로딩하고 실행합니다.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any

import httpx
import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = structlog.get_logger(__name__)


class MCPManager:
    """여러 MCP 서버에 연결하고 Anthropic 형식 도구를 제공합니다.

    사용 방법 (async context manager):
        async with MCPManager(server_urls) as mcp:
            tools = mcp.tools
            result = await mcp.call_tool("tool_name", {"arg": "value"})
    """

    def __init__(self, server_urls: dict[str, str]):
        """
        Args:
            server_urls: {서버이름: URL} 딕셔너리
                예: {"kiwoom-market-mcp": "http://localhost:8031/mcp/"}
        """
        self._server_urls = server_urls
        self._tool_server_map: dict[str, str] = {}  # tool_name → server_name
        self._anthropic_tools: list[dict[str, Any]] = []
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}

    _HEALTH_TIMEOUT = 3.0  # 서버 생존 확인 HTTP 타임아웃 (초)

    async def __aenter__(self) -> MCPManager:
        for server_name, url in self._server_urls.items():
            if not await self._is_server_reachable(url):
                logger.warning("MCP 서버 접근 불가 - 건너뜀", server=server_name, url=url)
                continue
            try:
                await self._connect_server(server_name, url)
            except Exception as e:
                logger.warning("MCP 서버 연결 실패 - 건너뜀", server=server_name, error=str(e))

        logger.info("MCPManager 초기화 완료", total_tools=len(self._anthropic_tools))
        return self

    async def _is_server_reachable(self, url: str) -> bool:
        """MCP 서버에 HTTP로 빠르게 접근 가능한지 확인합니다."""
        try:
            async with httpx.AsyncClient(timeout=self._HEALTH_TIMEOUT) as client:
                resp = await client.get(url)
                return resp.status_code < 500
        except Exception:
            return False

    async def _connect_server(self, server_name: str, url: str) -> None:
        """단일 MCP 서버에 연결하고 도구 목록을 로드합니다."""
        read, write, _ = await self._exit_stack.enter_async_context(
            streamablehttp_client(url)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        self._sessions[server_name] = session

        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            self._anthropic_tools.append(self._to_anthropic_tool(tool))
            self._tool_server_map[tool.name] = server_name

        logger.info(
            "MCP 서버 연결 완료",
            server=server_name,
            tool_count=len(tools_result.tools),
        )

    async def __aexit__(self, *args: Any) -> None:
        await self._exit_stack.aclose()

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Anthropic messages.create()에 전달할 tools 리스트."""
        return self._anthropic_tools

    async def call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """MCP 도구를 실행하고 결과를 문자열로 반환합니다.

        Args:
            tool_name: 실행할 도구 이름
            tool_input: 도구 입력 파라미터

        Returns:
            도구 실행 결과 문자열

        Raises:
            KeyError: 알 수 없는 도구 이름
            Exception: 도구 실행 실패
        """
        if tool_name not in self._tool_server_map:
            raise KeyError(f"알 수 없는 도구: {tool_name}")

        server_name = self._tool_server_map[tool_name]
        session = self._sessions[server_name]

        logger.debug("도구 실행", tool=tool_name, server=server_name)
        result = await session.call_tool(tool_name, tool_input)

        return self._format_tool_result(result)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _to_anthropic_tool(mcp_tool: Any) -> dict[str, Any]:
        """MCP Tool 객체를 Anthropic tool 형식으로 변환합니다."""
        input_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}
        return {
            "name": mcp_tool.name,
            "description": mcp_tool.description or "",
            "input_schema": input_schema,
        }

    @staticmethod
    def _format_tool_result(result: Any) -> str:
        """MCP 도구 실행 결과를 문자열로 변환합니다."""
        if not result.content:
            return ""

        parts: list[str] = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            elif hasattr(content, "data"):
                parts.append(json.dumps(content.data, ensure_ascii=False))
            else:
                parts.append(str(content))

        return "\n".join(parts)
