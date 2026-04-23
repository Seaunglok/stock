"""
Supervisor 에이전트 Claude SDK 실행기.

하위 에이전트(DataCollector, Analysis, Trading)를 Claude의 tool use 기능을 통해
호출하며, LangGraph StateGraph를 완전히 대체합니다.
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

import anthropic
import structlog
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart
from a2a.utils import new_agent_parts_message, new_agent_text_message

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2
from src.claude_agents.base.prompts import SUPERVISOR_SYSTEM_PROMPT

logger = structlog.get_logger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10

# 하위 에이전트를 Claude tool로 등록
_SUB_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "call_data_collector",
        "description": (
            "주식 시세, 기업 정보, 뉴스, 투자자 동향 등 데이터를 수집합니다. "
            "분석이나 거래 전에 반드시 먼저 호출하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "수집할 데이터에 대한 요청 (예: '삼성전자 현재가와 최근 뉴스 수집')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "call_analysis_agent",
        "description": (
            "기술적/기본적/거시경제/감성 4차원 통합 분석을 수행합니다. "
            "데이터 수집 후 분석이 필요한 경우에만 호출하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "분석 요청 및 이전 수집된 데이터 컨텍스트",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "call_trading_agent",
        "description": (
            "리스크 평가 후 실제 주문을 실행합니다. "
            "사용자가 명시적으로 거래 실행을 요청한 경우에만 호출하세요."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "거래 요청 및 분석 결과 컨텍스트",
                }
            },
            "required": ["query"],
        },
    },
]


class SupervisorClaudeExecutor(AgentExecutor):
    """하위 에이전트를 Claude tool로 오케스트레이션하는 Supervisor 실행기.

    흐름:
        1. 사용자 요청을 Claude에 전달
        2. Claude가 tool use로 하위 에이전트 호출 결정
        3. 해당 하위 에이전트를 A2A 프로토콜로 호출
        4. 결과를 Claude에 반환 → 최종 응답 생성
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        self._client = anthropic.AsyncAnthropic()
        self._model = model
        self._agent_urls: dict[str, str] = {}

    def _get_agent_urls(self) -> dict[str, str]:
        """환경변수에서 하위 에이전트 URL을 읽어 반환합니다."""
        if not self._agent_urls:
            self._agent_urls = {
                "data_collector": os.getenv(
                    "DATA_COLLECTOR_URL", "http://localhost:8001"
                ),
                "analysis": os.getenv("ANALYSIS_URL", "http://localhost:8002"),
                "trading": os.getenv("TRADING_URL", "http://localhost:8003"),
            }
        return self._agent_urls

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = cast(str, context.task_id)
        context_id = str(getattr(context, "context_id", task_id))
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task_id, context_id=context_id
        )

        try:
            await updater.update_status(TaskState.working)
            user_message = self._extract_user_message(context)

            final_text = await self._run_supervisor_loop(
                user_message=user_message,
                updater=updater,
            )

            parts = [Part(root=TextPart(text=final_text))]
            final_msg = new_agent_parts_message(parts)
            await updater.update_status(TaskState.completed, final_msg, final=True)

        except Exception as e:
            logger.error("Supervisor 실행 오류", error=str(e), exc_info=True)
            err_msg = new_agent_text_message(f"오류가 발생했습니다: {e}")
            try:
                await updater.update_status(TaskState.failed, err_msg, final=True)
            except Exception:
                pass

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = cast(str, context.task_id)
        context_id = str(getattr(context, "context_id", task_id))
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task_id, context_id=context_id
        )
        await updater.cancel()

    # -------------------------------------------------------------------------
    # Supervisor tool use loop
    # -------------------------------------------------------------------------

    async def _run_supervisor_loop(
        self,
        user_message: str,
        updater: TaskUpdater,
    ) -> str:
        """Claude가 하위 에이전트를 tool로 호출하는 루프를 실행합니다."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message}
        ]

        for _ in range(MAX_ITERATIONS):
            streamed_text, response = await self._stream_response(
                messages=messages,
                updater=updater,
            )

            if response.stop_reason == "end_turn":
                return streamed_text or self._extract_text(response.content)

            if response.stop_reason == "tool_use":
                tool_results = await self._dispatch_agent_calls(
                    response.content, updater
                )
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            logger.warning("예상치 못한 stop_reason", reason=response.stop_reason)
            return self._extract_text(response.content)

        return "최대 반복 횟수에 도달했습니다."

    async def _stream_response(
        self,
        messages: list[dict[str, Any]],
        updater: TaskUpdater,
    ) -> tuple[str, Any]:
        """Claude 응답을 스트리밍합니다."""
        accumulated_text = ""

        async with self._client.messages.stream(
            model=self._model,
            system=SUPERVISOR_SYSTEM_PROMPT,
            tools=_SUB_AGENT_TOOLS,
            messages=messages,
            max_tokens=8192,
        ) as stream:
            async for text_chunk in stream.text_stream:
                accumulated_text += text_chunk
                chunk_msg = new_agent_text_message(text_chunk)
                await updater.update_status(TaskState.working, chunk_msg)

            response = await stream.get_final_message()

        return accumulated_text, response

    async def _dispatch_agent_calls(
        self,
        content: list[Any],
        updater: TaskUpdater,
    ) -> list[dict[str, Any]]:
        """tool_use 블록을 해석하여 해당 하위 에이전트를 A2A로 호출합니다."""
        results: list[dict[str, Any]] = []
        agent_urls = self._get_agent_urls()

        for block in content:
            if block.type != "tool_use":
                continue

            tool_name: str = block.name
            query: str = block.input.get("query", "")

            agent_key = self._tool_to_agent_key(tool_name)
            if not agent_key:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"알 수 없는 도구: {tool_name}",
                    "is_error": True,
                })
                continue

            agent_url = agent_urls.get(agent_key, "")
            notice = new_agent_text_message(
                f"{tool_name} 호출 중... ({agent_url})"
            )
            await updater.update_status(TaskState.working, notice)

            try:
                result_text = await self._call_sub_agent(agent_url, query)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
                logger.info("하위 에이전트 호출 완료", agent=agent_key)
            except Exception as e:
                logger.error("하위 에이전트 호출 실패", agent=agent_key, error=str(e))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"에이전트 오류: {e}",
                    "is_error": True,
                })

        return results

    async def _call_sub_agent(self, base_url: str, query: str) -> str:
        """A2AClientManagerV2를 통해 하위 에이전트를 호출합니다."""
        async with A2AClientManagerV2(base_url=base_url) as client:
            result = await client.send_query(query)
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            return str(result)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _tool_to_agent_key(tool_name: str) -> str | None:
        mapping = {
            "call_data_collector": "data_collector",
            "call_analysis_agent": "analysis",
            "call_trading_agent": "trading",
        }
        return mapping.get(tool_name)

    @staticmethod
    def _extract_user_message(context: RequestContext) -> str:
        try:
            text = context.get_user_input()
            if text:
                return text
        except Exception:
            pass

        message = getattr(context, "message", None)
        if message and hasattr(message, "parts"):
            for part in message.parts:
                root = getattr(part, "root", part)
                if hasattr(root, "text") and root.text:
                    return root.text

        return ""

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        return "".join(
            block.text for block in content if hasattr(block, "text")
        )
