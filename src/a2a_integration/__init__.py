"""
A2A Integration Module.

A2A 프로토콜 서버/클라이언트 유틸리티 모음입니다. Claude SDK 기반 에이전트는
``src.claude_agents`` 에 구현되어 있으며, 여기의 헬퍼로 A2A 서버를 구성합니다.
"""

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2
from src.a2a_integration.a2a_lg_utils import (
    build_a2a_starlette_application,
    build_request_handler,
    create_agent_card,
    create_agent_skill,
)

__all__ = [
    "A2AClientManagerV2",
    "build_a2a_starlette_application",
    "build_request_handler",
    "create_agent_card",
    "create_agent_skill",
]
