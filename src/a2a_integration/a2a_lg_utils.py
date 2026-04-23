"""
공통 A2A 서버 유틸리티.

어떤 AgentExecutor 구현체든 최소한의 코드로 A2A 서버를 구성할 수 있도록
헬퍼 함수들을 제공합니다.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
import structlog
from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AFastAPIApplication, A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

wrapper_logger = structlog.get_logger(__name__)

SUPPORTED_CONTENT_MIME_TYPES = ["text/plain", "text/markdown", "application/json"]


def build_request_handler(executor: AgentExecutor) -> DefaultRequestHandler:
    """A2A HTTP 요청 핸들러를 생성합니다.

    MCP/에이전트 호출의 긴 레이턴시를 고려해 타임아웃을 넉넉하게 설정합니다.

    Args:
        executor: AgentExecutor 구현체

    Returns:
        DefaultRequestHandler: 마운트 가능한 핸들러
    """
    httpx_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=60.0, read=600.0, write=60.0, pool=600.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=50,
            keepalive_expiry=60.0,
        ),
        follow_redirects=True,
        headers={"Connection": "keep-alive"},
    )
    push_config_store = InMemoryPushNotificationConfigStore()
    push_sender = BasePushNotificationSender(
        httpx_client=httpx_client,
        config_store=push_config_store,
    )
    return DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        push_config_store=push_config_store,
        push_sender=push_sender,
    )


def build_a2a_starlette_application(
    agent_card: AgentCard, handler: DefaultRequestHandler
) -> A2AStarletteApplication:
    """Starlette 기반 A2A 애플리케이션을 생성합니다."""
    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)


def build_a2a_fastapi_application(
    agent_card: AgentCard, handler: DefaultRequestHandler
) -> A2AFastAPIApplication:
    """FastAPI 기반 A2A 애플리케이션을 생성합니다.

    Note:
        ``uv add "a2a-sdk[http-server]"`` 가 설치되어 있어야 합니다.
    """
    return A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)


def create_agent_skill(
    skill_id: str,
    description: str,
    tags: list[str],
    name: str | None = None,
    input_modes: list[str] | None = None,
    output_modes: list[str] | None = None,
    examples: list[str] | None = None,
) -> AgentSkill:
    """A2A 표준 AgentSkill 객체를 생성합니다."""
    return AgentSkill(
        id=skill_id,
        name=name or skill_id,
        description=description,
        input_modes=input_modes or SUPPORTED_CONTENT_MIME_TYPES,
        output_modes=output_modes or SUPPORTED_CONTENT_MIME_TYPES,
        tags=tags,
        examples=examples,
    )


def create_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    skills: Iterable[AgentSkill],
    version: str = "1.0.0",
    default_input_modes: list[str] | None = None,
    default_output_modes: list[str] | None = None,
    streaming: bool = True,
    push_notifications: bool = True,
) -> AgentCard:
    """A2A 표준 AgentCard 메타데이터를 생성합니다."""
    capabilities = AgentCapabilities(
        streaming=streaming,
        push_notifications=push_notifications,
    )
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version=version,
        default_input_modes=default_input_modes or SUPPORTED_CONTENT_MIME_TYPES,
        default_output_modes=default_output_modes or SUPPORTED_CONTENT_MIME_TYPES,
        capabilities=capabilities,
        skills=list(skills),
    )
