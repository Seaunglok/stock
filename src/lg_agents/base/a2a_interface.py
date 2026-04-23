"""
LangGraph 에이전트를 위한 A2A(Agent-to-Agent) 통합 인터페이스.

이 모듈은 LangGraph 기반 에이전트를 A2A 프로토콜과 일관되게 연동하기 위한
표준화된 인터페이스와 유틸리티를 제공합니다. 스트리밍과 폴링 방식 모두에서
동일한 데이터 형식을 유지하도록 설계되었습니다.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Literal, Optional, TypedDict

import structlog

logger = structlog.get_logger(__name__)


class A2AOutput(TypedDict):
    """
    A2A 통합을 위한 표준 출력 포맷.

    이 포맷은 스트리밍 중간 이벤트와 최종 결과를 하나의 스키마로 통합하여,
    A2A 실행기에서 일관되게 처리할 수 있도록 합니다.

    필수 키:
        - agent_type: 에이전트 식별자 (예: "DataCollector", "Analysis")
        - status: 다음 중 하나 {"working", "completed", "failed", "input_required"}
        - stream_event: 스트리밍 이벤트 여부 (중간 이벤트면 True, 최종 스냅샷이면 False/생략)
        - final: 해당 요청에 대한 최종 결과인지 여부

    선택 키:
        - text_content: 렌더링 가능한 텍스트 (클라이언트의 TextPart 로 사용)
        - data_content: 구조화된 페이로드 (클라이언트의 DataPart 로 사용)
        - metadata: 임의의 처리 메타데이터
        - error_message: status=="failed" 일 때의 에러 상세
        - requires_approval: 거래 등 HITL 승인이 필요한 경우 표시
    """

    # 에이전트 식별 정보
    agent_type: str  # 예: "DataCollector", "Analysis", "Trading", "Supervisor"

    # 상태 표시
    status: Literal["working", "completed", "failed", "input_required"]

    # 메시지 콘텐츠 (A2A 파트에 매핑)
    text_content: Optional[str]
    data_content: Optional[Dict[str, Any]]

    # 처리 메타데이터
    metadata: Dict[str, Any]

    # 이벤트 유형 플래그
    stream_event: bool
    final: bool

    # 특정 사용 사례를 위한 선택 필드
    error_message: Optional[str]
    requires_approval: Optional[bool]


class BaseA2AAgent(ABC):
    """
    A2A 통합을 지원하는 LangGraph 에이전트의 추상 기반 클래스.

    각 구현 클래스는 다음 3가지를 반드시 제공해야 합니다.
    - execute_for_a2a: 워크플로우를 실행하고 ``A2AOutput`` 반환
    - format_stream_event: 스트리밍 이벤트를 ``A2AOutput`` 으로 변환
    - extract_final_output: 최종 그래프 상태를 ``A2AOutput`` 으로 변환

    출력은 직렬화 가능하고 가볍게 유지하는 것을 권장합니다.
    """

    def __init__(self):
        """기본 A2A 에이전트 초기화.

        사용자에게 보여줄 라벨을 간결하게 유지하기 위해 클래스명에서
        접미사 "Agent" 를 제거하여 ``agent_type`` 을 유도합니다.
        """
        self.agent_type = self.__class__.__name__.replace("Agent", "")
        logger.info(f"Initializing A2A agent: {self.agent_type}")

    @abstractmethod
    async def execute_for_a2a(
        self,
        input_dict: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None
    ) -> A2AOutput:
        """
        A2A 호환 입력/출력으로 에이전트를 실행합니다.

        이 메서드는 직접적인 graph.ainvoke() 호출을 대체하며,
        A2A 실행기를 위한 표준화된 인터페이스를 제공합니다.

        Args:
            input_dict: 표준 입력 딕셔너리 (예: {"messages": [...]})
            config: 선택적 설정. 제공 시에는 thread_id 를
                config["configurable"]["thread_id"] 에 포함해야 합니다.

        Returns:
            A2AOutput: A2A 처리를 위한 표준 출력
        """
        raise NotImplementedError

    @abstractmethod
    def format_stream_event(
        self,
        event: Dict[str, Any]
    ) -> Optional[A2AOutput]:
        """
        스트리밍 이벤트를 표준 A2A 출력으로 변환합니다.

        다음과 같은 이벤트 유형을 처리합니다.
        - on_llm_stream: LLM 토큰 스트리밍
        - on_chain_start/end: 노드 실행 이벤트
        - on_tool_start/end: 도구 실행 이벤트

        Args:
            event: LangGraph 로부터 전달된 원시 스트리밍 이벤트

        Returns:
            전달할 가치가 있는 이벤트면 ``A2AOutput`` 을, 아니면 ``None`` 을 반환
        """
        raise NotImplementedError

    @abstractmethod
    def extract_final_output(
        self,
        state: Dict[str, Any]
    ) -> A2AOutput:
        """
        에이전트 상태에서 최종 출력을 추출합니다.

        스트리밍이 종료되면 현재 요청에 대해 하나의 최종 통합 출력을
        생성하기 위해 호출됩니다.

        Args:
            state: LangGraph 실행으로부터의 최종 상태

        Returns:
            A2AOutput: 최종 표준 출력
        """
        raise NotImplementedError

    # Common utility methods

    def create_a2a_output(
        self,
        status: Literal["working", "completed", "failed", "input_required"],
        text_content: Optional[str] = None,
        data_content: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        stream_event: bool = False,
        final: bool = False,
        **kwargs
    ) -> A2AOutput:
        """
        표준 A2A 출력을 생성하는 헬퍼 메서드.

        Args:
            status: 에이전트의 현재 상태
            text_content: 텍스트 파트에 해당하는 문자열
            data_content: 데이터 파트에 해당하는 구조화된 데이터
            metadata: 추가 메타데이터
            stream_event: 스트리밍 이벤트 여부
            final: 최종 출력 여부
            **kwargs: 추가 선택 필드 (예: error_message)

        Returns:
            A2AOutput: 표준 출력 딕셔너리
        """
        output: A2AOutput = {
            "agent_type": self.agent_type,
            "status": status,
            "text_content": text_content,
            "data_content": data_content,
            "metadata": metadata or {},
            "stream_event": stream_event,
            "final": final,
            "error_message": kwargs.get("error_message"),
            "requires_approval": kwargs.get("requires_approval")
        }

        return output

    def format_error(
        self,
        error: Exception,
        context: Optional[str] = None
    ) -> A2AOutput:
        """
        발생한 예외를 표준 A2A 출력 형식으로 변환합니다.

        Args:
            error: 발생한 예외 객체
            context: 에러가 발생한 위치/맥락 (선택)

        Returns:
            A2AOutput: 에러 정보를 담은 A2A 출력
        """
        error_message = f"{type(error).__name__}: {str(error)}"
        if context:
            error_message = f"{context}: {error_message}"

        logger.error(f"A2A Agent Error: {error_message}")

        return self.create_a2a_output(
            status="failed",
            text_content=f"에러가 발생했습니다: {str(error)}",
            metadata={"error_type": type(error).__name__, "context": context},
            final=True,
            error_message=error_message
        )

    def is_completion_event(self, event: Dict[str, Any]) -> bool:
        """
        스트리밍 이벤트가 완료를 나타내는지 확인합니다.

        Args:
            event: 확인할 스트리밍 이벤트

        Returns:
            bool: 완료 이벤트이면 True
        """
        event_type = event.get("event", "")

        # Check for explicit end events
        if event_type == "on_chain_end":
            node_name = event.get("name", "")
            # Common completion node names
            if node_name in ["__end__", "final", "complete"]:
                return True

        # Check for completion in metadata
        metadata = event.get("metadata", {})
        if metadata.get("is_final", False):
            return True

        return False

    def extract_llm_content(self, event: Dict[str, Any]) -> Optional[str]:
        """
        스트리밍 이벤트에서 LLM의 텍스트 내용을 추출합니다.

        Args:
            event: LLM 출력이 포함된 스트리밍 이벤트

        Returns:
            str | None: 추출된 텍스트. LLM 이벤트가 아니면 None
        """
        if event.get("event") != "on_llm_stream":
            return None

        data = event.get("data", {})
        chunk = data.get("chunk", {})

        # Handle AIMessageChunk
        if hasattr(chunk, "content"):
            return chunk.content
        # Handle dict-like chunk
        elif isinstance(chunk, dict):
            return chunk.get("content", "")

        return None


class A2AStreamBuffer:
    """
    스트리밍 콘텐츠 관리를 위한 버퍼.

    토큰 스트림을 일정 간격으로 모았다가 적절한 시점에 내보내어
    사용자 경험을 개선합니다.
    """

    def __init__(self, max_size: int = 100):
        """
        스트림 버퍼 초기화.

        Args:
            max_size: 자동 플러시가 일어나는 최대 버퍼 크기
        """
        self.buffer: list[str] = []
        self.size: int = 0
        self.max_size = max_size

    def add(self, content: str) -> bool:
        """
        버퍼에 내용을 추가합니다.

        Args:
            content: 추가할 내용

        Returns:
            bool: 플러시가 필요하면 True
        """
        if not content:
            return False

        self.buffer.append(content)
        self.size += len(content)

        return self.size >= self.max_size

    def flush(self) -> str:
        """
        버퍼를 비우고 누적된 내용을 반환합니다.

        Returns:
            str: 누적된 내용
        """
        if not self.buffer:
            return ""

        content = "".join(self.buffer)
        self.buffer.clear()
        self.size = 0

        return content

    def has_content(self) -> bool:
        """버퍼에 내용이 있는지 확인합니다."""
        return len(self.buffer) > 0
