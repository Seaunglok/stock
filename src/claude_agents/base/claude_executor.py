"""
Claude SDK 기반 A2A AgentExecutor 베이스 클래스.

LangGraphAgentExecutorV2를 대체하며, Anthropic Claude API의 tool use 루프를
직접 구현합니다. MCP 도구 연결은 MCPManager를 통해 처리합니다.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
import structlog
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart
from a2a.utils import new_agent_parts_message, new_agent_text_message

from src.claude_agents.base.mcp_client import MCPManager

logger = structlog.get_logger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 25


class BaseClaudeAgentExecutor(AgentExecutor):
    """Claude SDK + MCP 도구를 사용하는 A2A 에이전트 실행기 베이스 클래스.

    서브클래스에서 반드시 구현해야 하는 것:
        - mcp_server_urls: 연결할 MCP 서버 {이름: URL} 딕셔너리
        - system_prompt: Claude에 전달할 시스템 프롬프트 문자열
    """

    mcp_server_urls: dict[str, str] = {}
    system_prompt: str = ""

    def __init__(self, model: str = DEFAULT_MODEL):
        self._client = anthropic.AsyncAnthropic()
        self._model = model

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = cast(str, context.task_id)
        context_id = str(getattr(context, "context_id", task_id))
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task_id, context_id=context_id
        )

        try:
            await updater.update_status(TaskState.working)
            user_message = self._extract_user_message(context)

            async with MCPManager(self.mcp_server_urls) as mcp:
                final_text = await self._run_tool_loop(
                    user_message=user_message,
                    mcp=mcp,
                    updater=updater,
                )

            parts = [Part(root=TextPart(text=final_text))]
            final_msg = new_agent_parts_message(parts)
            await updater.update_status(TaskState.completed, final_msg, final=True)

        except Exception as e:
            logger.error("에이전트 실행 오류", error=str(e), exc_info=True)
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
    # Tool use loop
    # -------------------------------------------------------------------------

    async def _run_tool_loop(
        self,
        user_message: str,
        mcp: MCPManager,
        updater: TaskUpdater,
    ) -> str:
        """Claude tool use 루프를 실행하고 최종 응답 텍스트를 반환합니다."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message}
        ]
        tools = mcp.tools

        for iteration in range(MAX_ITERATIONS):
            streamed_text, response = await self._stream_response(
                messages=messages,
                tools=tools,
                updater=updater,
            )

            if response.stop_reason == "end_turn":
                # 스트리밍 중 이미 텍스트를 전송했으므로 최종 텍스트만 반환
                return streamed_text or self._extract_text(response.content)

            if response.stop_reason == "tool_use":
                tool_results = await self._execute_tool_calls(
                    response.content, mcp, updater
                )
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            # 예상치 못한 stop_reason
            logger.warning("예상치 못한 stop_reason", reason=response.stop_reason)
            return self._extract_text(response.content)

        logger.warning("최대 반복 횟수 도달", max_iter=MAX_ITERATIONS)
        return "최대 반복 횟수에 도달했습니다."

    async def _stream_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        updater: TaskUpdater,
    ) -> tuple[str, Any]:
        """Claude 응답을 스트리밍하고 (누적 텍스트, 최종 응답)을 반환합니다."""
        accumulated_text = ""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 8192,
            "messages": messages,
        }
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for text_chunk in stream.text_stream:
                accumulated_text += text_chunk
                # 스트리밍 텍스트를 A2A 이벤트로 전송
                chunk_msg = new_agent_text_message(text_chunk)
                await updater.update_status(TaskState.working, chunk_msg)

            response = await stream.get_final_message()

        return accumulated_text, response

    async def _execute_tool_calls(
        self,
        content: list[Any],
        mcp: MCPManager,
        updater: TaskUpdater,
    ) -> list[dict[str, Any]]:
        """응답 content의 tool_use 블록을 실행하고 tool_result 리스트를 반환합니다."""
        results: list[dict[str, Any]] = []

        for block in content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input

            # 도구 실행 알림
            notice = new_agent_text_message(f"도구 실행 중: {tool_name}")
            await updater.update_status(TaskState.working, notice)

            try:
                result_text = await mcp.call_tool(tool_name, tool_input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
                logger.debug("도구 실행 완료", tool=tool_name)
            except Exception as e:
                logger.error("도구 실행 실패", tool=tool_name, error=str(e))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"도구 실행 오류: {e}",
                    "is_error": True,
                })

        return results

    # -------------------------------------------------------------------------
    # Input extraction
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_user_message(context: RequestContext) -> str:
        """RequestContext에서 사용자 메시지 텍스트를 추출합니다."""
        # context.get_user_input() 시도
        try:
            text = context.get_user_input()
            if text:
                return text
        except Exception:
            pass

        # message.parts 순회
        message = getattr(context, "message", None)
        if message and hasattr(message, "parts"):
            for part in message.parts:
                root = getattr(part, "root", part)
                if hasattr(root, "text") and root.text:
                    return root.text

        return ""

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        """응답 content 블록에서 텍스트를 추출합니다."""
        return "".join(
            block.text for block in content if hasattr(block, "text")
        )
