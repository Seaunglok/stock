"""A2A 통합을 위한 표준 출력 TypedDict."""

from typing import Any, Dict, Literal, Optional, TypedDict


class A2AOutput(TypedDict):
    """
    A2A 통합을 위한 표준 출력 포맷.

    스트리밍 중간 이벤트와 최종 결과를 하나의 스키마로 통합하여,
    A2A 클라이언트/실행기에서 일관되게 처리할 수 있도록 합니다.

    필수 키:
        - agent_type: 에이전트 식별자 (예: "DataCollector", "Analysis")
        - status: {"working", "completed", "failed", "input_required"}
        - stream_event: 스트리밍 이벤트 여부 (중간 이벤트면 True)
        - final: 해당 요청에 대한 최종 결과 여부

    선택 키:
        - text_content: 렌더링 가능한 텍스트 (TextPart 로 사용)
        - data_content: 구조화된 페이로드 (DataPart 로 사용)
        - metadata: 임의의 처리 메타데이터
        - error_message: status=="failed" 일 때의 에러 상세
        - requires_approval: HITL 승인이 필요한 경우 표시
    """

    agent_type: str
    status: Literal["working", "completed", "failed", "input_required"]
    text_content: Optional[str]
    data_content: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]
    stream_event: bool
    final: bool
    error_message: Optional[str]
    requires_approval: Optional[bool]
