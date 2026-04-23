"""A2A Client Manager V2 - A2A 클라이언트 유틸리티

개요
    이 모듈은 A2A(Agent-to-Agent) 프로토콜과 상호작용하기 위한 고수준
    Python 클라이언트를 제공합니다. A2A 표준 스펙을 따르면서 실무에서
    사용하기 쉽고 안정적인 API를 목표로 설계되었습니다.

구성
    - Core Engine: :class:`A2AMessageEngine`
        HTTP 전송, 스트리밍 이벤트 처리, 재시도, 태스크 폴링, 결과 추출 등
        핵심 로직을 담당합니다.
    - Specialized Clients: :class:`A2ATextClient`, :class:`A2ADataClient`,
      :class:`A2AFileClient`
        텍스트/데이터/파일 전송을 간편화한 경량 래퍼입니다.
    - Unified Manager: :class:`A2AClientManagerV2`
        레거시 API와 호환되는 단일 진입점으로, 내부적으로 엔진과
        전문 클라이언트를 위임하여 제공합니다.
    - A2A Interface Utils
        LangGraph 기반 에이전트 표준 출력(`A2AOutput`)을 A2A 메시지/파트로
        변환하고, 스트리밍 결과를 합성하는 도우미를 포함합니다.

주요 특징
    - TextPart, DataPart, FilePart 모두 지원
    - 스트리밍/폴링 모두 지원하며, 안정적인 재시도(exponential backoff)
    - 태스크 완료 보장 위해 GetTask 폴링을 항상 수행하여 데이터 손실 방지
    - 로컬 개발 시 Docker 컨테이너 호스트명을 localhost로 자동 변환
    - 레거시 API 호환: 기존 호출부 변경 최소화

빠른 예시
    비동기 컨텍스트 매니저로 초기화하고 텍스트 전송:

    >>> async with A2AClientManagerV2(base_url="http://localhost:8080") as cm:
    ...     text = await cm.send_query("안녕?")
    ...     print(text)

오류 처리
    - 네트워크 및 클라이언트 오류는 `execute_with_retry`로 재시도됩니다.
    - 메시지 처리 단계별 예외는 로깅되며, 필요 시 상위로 전파됩니다.

콜백
    - 스트리밍 중간 결과를 수신하려면 `process_callback`(또는 각 클라이언트의
      `streaming_callback`)에 코루틴을 전달하세요. 콜백은 다음 형태의 딕셔너리를
      전달받습니다: `{ "type": "text"|"data"|"file", "content": Any }`.

주의 사항
    - 본 모듈은 asyncio 기반입니다. 모든 퍼블릭 API는 비동기로 호출해야 합니다.
    - Docstring의 예시는 이해를 돕기 위한 축약본입니다. 실제 응답은 서버/모델
      설정에 따라 달라질 수 있습니다.
"""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Union
from uuid import uuid4

import httpx
import structlog
from a2a.client import A2ACardResolver, A2AClientError, ClientConfig, ClientFactory
from a2a.client.auth.credentials import CredentialService
from a2a.client.helpers import create_text_message_object
from a2a.types import (
    AgentCard,
    DataPart,
    FilePart,
    FileWithBytes,
    FileWithUri,
    Message,
    Part,
    Role,
    TextPart,
    TransportProtocol,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from src.lg_agents.base.a2a_interface import A2AOutput

logger = structlog.get_logger(__name__)
wrapper_logger = logging.getLogger(__name__)

# ==================== Response Types ====================

@dataclass
class TextResponse:
    """텍스트 전송 응답.

    Attributes
        text: 최종 병합된 텍스트(모든 이벤트를 반영한 결과).
        streaming_chunks: 이벤트 수신 중에 누적된 증분 텍스트 조각들.
        metadata: 서버 또는 전송 레이어에서 제공하는 부가 정보.
        event_count: 처리된 이벤트 개수(디버깅/관찰용).
    """
    text: str
    streaming_chunks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_count: int = 0


@dataclass
class DataResponse:
    """데이터 전송 응답.

    Attributes
        data_parts: 이벤트/아티팩트에서 수집된 원본 데이터 파트 목록.
        merged_data: 병합 전략에 따라 합성된 최종 데이터 딕셔너리.
        validation_errors: 데이터 유효성 검증 시 감지된 오류 목록.
        event_count: 처리된 이벤트 개수.
    """
    data_parts: List[Dict[str, Any]]
    merged_data: Optional[Dict[str, Any]] = None
    validation_errors: List[str] = field(default_factory=list)
    event_count: int = 0


@dataclass
class FileResponse:
    """파일 전송 응답.

    Attributes
        file_uri: 서버가 반환한 파일 리소스의 URI(있는 경우).
        file_bytes: 메모리 상의 파일 바이트(있는 경우).
        mime_type: 파일 MIME 타입(기본: application/octet-stream).
        size: 파일 크기(바이트).
        metadata: 파일 및 전송 관련 부가 정보.
    """
    file_uri: Optional[str] = None
    file_bytes: Optional[bytes] = None
    mime_type: str = "application/octet-stream"
    size: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedResponse:
    """통합 응답 - 모든 Part 타입 포함.

    Notes
        A2A 서버는 응답을 여러 아티팩트 및 메시지 파트로 분산하여 보낼 수
        있습니다. 이 클래스는 텍스트/데이터/파일 파트를 수집하고, 최종
        병합 텍스트와 데이터, 처리 이벤트 수 등 관찰 정보를 함께 보관합니다.

    Attributes
        text_parts: 스트리밍 중 누적된 텍스트 델타 목록.
        data_parts: 수집된 데이터 파트 목록.
        file_parts: 수집된 파일 응답 목록.
        merged_text: 최종 병합된 텍스트.
        merged_data: 병합된 데이터(필요 시).
        history: 전체 메시지 히스토리(옵션).
        event_count: 처리한 이벤트 수.
        errors: 처리 도중 수집된 파트 단위 오류 목록.
    """
    text_parts: List[str] = field(default_factory=list)
    data_parts: List[Dict[str, Any]] = field(default_factory=list)
    file_parts: List[FileResponse] = field(default_factory=list)
    merged_text: str = ""
    merged_data: Optional[Dict[str, Any]] = None
    history: Optional[List[Message]] = None
    event_count: int = 0
    errors: List['PartError'] = field(default_factory=list)


@dataclass
class PartError:
    """Part 처리 중 발생한 에러.

    Attributes
        part_type: 에러가 발생한 파트 타입("text"|"data"|"file").
        error: 원본 예외 객체.
        retry_count: 재시도 횟수(관찰/백오프 정책 수립용).
        recoverable: 복구 가능성 플래그. 정책에 따라 처리 전략을 달리할 수
            있습니다.
    """
    part_type: Literal["text", "data", "file"]
    error: Exception
    retry_count: int = 0
    recoverable: bool = True


class ErrorStrategy(Enum):
    """에러 처리 전략.

    FAIL_FAST
        첫 에러 발생 시 즉시 중단합니다.

    CONTINUE_ON_ERROR
        에러를 기록하되 가능한 처리를 계속 진행합니다.

    PARTIAL_SUCCESS
        성공한 결과만 반환하고 실패 파트는 오류 목록에 남깁니다.
    """
    FAIL_FAST = "fail_fast"          # 첫 에러 시 중단
    CONTINUE_ON_ERROR = "continue"    # 에러 무시하고 계속
    PARTIAL_SUCCESS = "partial"       # 성공한 것만 반환


# ==================== Core Engine ====================

class A2AMessageEngine:
    """A2A 메시지 처리 엔진.

    역할
        - A2A 카드 조회 및 클라이언트 생성/수명주기 관리
        - 메시지 전송 및 이벤트 스트림 처리
        - 태스크 완료 보장을 위한 GetTask 폴링
        - 텍스트/데이터 파트 추출 및 병합
        - 네트워크/클라이언트 오류에 대한 재시도(backoff)

    Parameters
        base_url: A2A 에이전트의 베이스 URL.
        streaming: 스트리밍 모드 사용 여부. False인 경우 폴링 위주.
        max_retries: 재시도 최대 횟수.
        retry_delay: 최초 재시도 지연(초). 지수 백오프에 사용.
        credential_service: 인증이 필요한 경우 전달하는 자격 증명 서비스.

    Attributes
        client: 초기화 후 생성되는 A2A 클라이언트 인스턴스.
        agent_card: 원격 에이전트의 카드 정보.
        _httpx_client: 공유 HTTPX AsyncClient.
        task_cache: 요청 해시 -> task_id 매핑(중복 방지/재활용).
        current_task_id: 최근/진행 중 태스크의 식별자.
    """

    def __init__(
        self,
        base_url: str,
        streaming: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        credential_service: Optional[CredentialService] = None,
    ):
        """엔진 설정을 초기화합니다.

        주로 연결/재시도/스트리밍에 관한 정책을 구성합니다. 실제 네트워크
        리소스(HTTPX/A2A 클라이언트)는 :meth:`initialize` 호출 시 생성됩니다.
        """
        self.base_url = base_url
        self.streaming = streaming
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.credential_service = credential_service
        self.client = None
        self.agent_card: Optional[AgentCard] = None
        self._httpx_client = None

        # Task ID 캐싱 및 중복 방지를 위한 새로운 속성들
        self.task_cache: Dict[str, str] = {}  # {request_hash: task_id}
        self.current_task_id: Optional[str] = None  # 현재 실행 중인 task_id

    async def initialize(self) -> 'A2AMessageEngine':
        """엔진을 초기화합니다.

        절차
            1) HTTPX AsyncClient 생성
            2) 에이전트 카드 조회 및 Docker 로컬 호스트명 보정
            3) A2A ClientFactory로 클라이언트 생성(인증 인터셉터 포함 가능)

        Returns
            self: 체이닝을 위해 자기 자신을 반환합니다.

        Raises
            Exception: 초기화 과정에서의 예외는 로깅 후 전파됩니다.
        """
        try:
            logger.debug(f"Initializing A2A engine for {self.base_url}")

            # HTTPX 클라이언트 생성
            self._httpx_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=60.0,
                    read=600.0,
                    write=60.0,
                    pool=600.0,
                ),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=50,
                    keepalive_expiry=60.0,
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": "A2AClientManager/2.0",
                    "Accept": "application/json; charset=utf-8",
                    "Connection": "keep-alive",
                },
            )

            # Agent Card 가져오기
            # - 원격 에이전트의 기능/경로/입출력 모드 등을 확인합니다.
            resolver = A2ACardResolver(
                httpx_client=self._httpx_client,
                base_url=self.base_url,
            )

            self.agent_card = await resolver.get_agent_card()
            logger.debug(f"Successfully fetched agent card: {self.agent_card.name}")

            # Docker 호스트명 변환 (로컬 개발용)
            # - docker-compose 네트워크 호스트명을 localhost로 치환하여
            #   브라우저/로컬 환경에서도 동일한 URL로 접근 가능하게 합니다.
            if self.agent_card.url and not os.getenv("IS_DOCKER", "false").lower() == "true":
                docker_hosts = ["data-collector-agent", "analysis-agent", "trading-agent", "supervisor-agent"]
                for docker_host in docker_hosts:
                    if docker_host in self.agent_card.url:
                        self.agent_card.url = self.agent_card.url.replace(f"http://{docker_host}", "http://localhost")
                        logger.debug(f"Converted Docker URL to localhost: {self.agent_card.url}")
                        break

            # A2A 클라이언트 설정
            config = ClientConfig(
                streaming=self.streaming,
                polling=not self.streaming,
                httpx_client=self._httpx_client,
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                    TransportProtocol.grpc,
                ],
                accepted_output_modes=[
                    "text/plain",
                    "text/markdown",
                    "application/json",
                    "text/event-stream",
                ],
                use_client_preference=True,
            )

            factory = ClientFactory(config=config)

            # 인터셉터 추가 (인증이 필요한 경우)
            # - 토큰 기반 인증 등 환경에서 자동 헤더 주입을 지원합니다.
            interceptors = []
            if self.credential_service:
                from a2a.client.auth.interceptor import AuthInterceptor
                interceptors.append(AuthInterceptor(self.credential_service))
                logger.debug("Auth interceptor added")

            self.client = factory.create(
                card=self.agent_card,
                interceptors=interceptors,
            )

            logger.debug(f"A2A client created successfully for {self.agent_card.name}")
            return self

        except Exception as e:
            logger.error(f"Failed to initialize A2A engine: {e}")
            if self._httpx_client:
                await self._httpx_client.aclose()
            raise

    async def close(self):
        """리소스를 정리합니다.

        HTTP 커넥션 풀과 A2A 클라이언트를 안전하게 종료합니다.
        호출은 중복되어도 안전합니다(idempotent).
        """
        if self._httpx_client:
            await self._httpx_client.aclose()
        if self.client:
            await self.client.close()

    async def send_message_core(
        self,
        message: Message,
        process_callback: Optional[Callable] = None,
    ) -> UnifiedResponse:
        """핵심 메시지 전송 메서드.

        설명
            A2A 클라이언트를 통해 메시지를 전송하고, 스트리밍 이벤트를
            순차 처리합니다. 이벤트 루프 종료 후에는 항상 GetTask 폴링을
            수행하여 아티팩트/히스토리에서 최종 결과를 한 번 더 확정합니다.

        Args
            message: 전송할 :class:`a2a.types.Message` 객체.
            process_callback: 각 이벤트 처리 시 호출할 비동기 콜백. 형태는
                ``async def cb(evt: dict) -> None`` 이며, ``evt``는
                ``{"type": "text|data|file", "content": Any}`` 입니다.

        Returns
            UnifiedResponse: 텍스트/데이터/파일 정보를 통합한 결과 객체.

        Raises
            ValueError: 초기화가 되지 않은 상태에서 호출한 경우.
        """
        if not self.client:
            raise ValueError("Engine not initialized. Call initialize() first.")

        response = UnifiedResponse()
        text_accumulator = ""

        # Step 1: Task 캐싱 비활성화 - 항상 새 task 생성
        # 이유: GetTask API가 완료된 task의 artifacts/history를
        #       완전히 가져오지 못하는 문제를 피하기 위해 명시적으로
        #       새 태스크를 생성하여 일관된 결과를 보장합니다.
        logger.info("Creating new task (caching disabled to prevent data loss)")

        # Step 2: 항상 새로운 task 생성
        logger.info("Creating new task - sending message")

        # 메시지 해시 생성 (새 task를 캐시하기 위해)
        request_hash = self._generate_request_hash(message)

        event_counter = 0
        task_id = None

        # 이벤트 스트리밍 처리
        # - 서버가 보내는 증분 이벤트(텍스트/데이터)를 순서대로 병합합니다.
        logger.info("Starting event loop for NEW message processing")
        async for event in self.client.send_message(message):
            event_counter += 1
            logger.info(f"Received event #{event_counter}: {type(event)}")

            # Task ID 추출 및 캐시 저장
            # - 이벤트에서 태스크 식별자를 포착하여 후속 폴링에 사용합니다.
            if isinstance(event, tuple) and len(event) > 0:
                task = event[0]
                if hasattr(task, 'id'):
                    task_id = task.id
                    self.current_task_id = task_id
                    # 새로운 task_id를 캐시에 저장
                    self.task_cache[request_hash] = task_id
                    logger.info(f"Cached new task_id: {task_id} with hash: {request_hash}")

            event_data = await self._process_event(event)

            # 텍스트 누적
            # - 증분 텍스트를 안정적으로 병합하여 델타를 콜백으로 전달합니다.
            if event_data.get("text"):
                new_text = self._merge_incremental_text(text_accumulator, event_data["text"])
                if new_text != text_accumulator:
                    delta = new_text[len(text_accumulator):]
                    if delta:
                        response.text_parts.append(delta)
                        if process_callback:
                            await process_callback({"type": "text", "content": delta})
                    text_accumulator = new_text

            # 데이터 수집
            # - 이벤트에서 발견되는 구조화 데이터 파트를 그대로 누적합니다.
            if event_data.get("data"):
                response.data_parts.append(event_data["data"])
                if process_callback:
                    await process_callback({"type": "data", "content": event_data["data"]})

            # TODO: 파일 처리 (추후 구현)
            # if event_data.get("file"):
            #     file_resp = FileResponse(
            #         file_uri=event_data["file"].get("uri"),
            #         file_bytes=event_data["file"].get("bytes"),
            #         mime_type=event_data["file"].get("mime_type", "application/octet-stream"),
            #     )
            #     response.file_parts.append(file_resp)
            #     if process_callback:
            #         await process_callback({"type": "file", "content": file_resp})

            response.event_count += 1

        logger.info(f"Event loop completed. Total events processed: {event_counter}")

        # FIX: Always poll for task completion to ensure complete data retrieval
        # - 스트림 종료 이후에도 태스크 완료를 한 번 더 확인하여, 아티팩트에만
        #   남아 있는 권위(authoritative) 결과를 놓치지 않도록 합니다.
        if task_id:
            logger.info(f"Always polling for NEW task completion (task_id: {task_id})")

            completed_task = await self._wait_for_task_completion(task_id)

            if completed_task:
                text_accumulator = await self._extract_task_results(completed_task, response, text_accumulator)
            else:
                logger.warning("NEW task completion polling failed")

        # 최종 텍스트 병합
        response.merged_text = text_accumulator.strip()
        if response.data_parts:
            response.merged_data = self._merge_data_parts(response.data_parts)

        logger.info(f"Successfully completed NEW task processing: {task_id}")
        return response

    async def _process_event(self, event) -> Dict[str, Any]:
        """단일 이벤트를 처리하여 Part들을 추출합니다.

        이벤트 구조
            ``(task, ...)`` 형태의 튜플을 예상합니다. 아티팩트가 우선이며,
            없을 경우 히스토리의 최신 에이전트 메시지에서 파트를 추출합니다.

        Returns
            dict: ``{"text": str, "data": dict, "file": dict}`` 중
                존재하는 키만 포함합니다.
        """
        result = {}

        # 이벤트 구조 로깅
        logger.info(f"Raw event type: {type(event)}, length: {len(event) if isinstance(event, (tuple, list)) else 'N/A'}")

        if not isinstance(event, tuple) or len(event) < 1:
            logger.info("Invalid event format, returning empty result")
            return result

        task = event[0]
        logger.info(f"Task type: {type(task)}, has artifacts: {hasattr(task, 'artifacts')}, has history: {hasattr(task, 'history')}")

        # Status.message에서 Part 추출 (권위 있는 최신 상태 메시지)
        try:
            task_status = getattr(task, 'status', None)
            status_message = getattr(task_status, 'message', None) if task_status else None
            if status_message and hasattr(status_message, 'parts') and status_message.parts:
                logger.info(f"Status message has {len(status_message.parts)} parts")
                for j, part in enumerate(status_message.parts):
                    root = getattr(part, 'root', None)
                    logger.info(f"Status Part {j}: root type: {type(root)}, has text: {hasattr(root, 'text') if root else False}, has data: {hasattr(root, 'data') if root else False}")
                    if root:
                        if hasattr(root, 'text') and root.text:
                            result["text"] = root.text
                            logger.info(f"Extracted TextPart from status.message, length: {len(root.text)}")
                        elif hasattr(root, 'data') and root.data:
                            result["data"] = root.data
                            logger.info("Extracted DataPart from status.message")
        except Exception as e:
            logger.debug(f"Failed to extract parts from status.message: {e}")

        # Artifacts에서 Part 추출
        # - 아티팩트의 파트는 서버가 보낸 최종 결과에 가까운 경향이 있습니다.
        if hasattr(task, "artifacts") and task.artifacts:
            logger.info(f"Found {len(task.artifacts)} artifacts")
            for i, artifact in enumerate(task.artifacts):
                logger.info(f"Artifact {i}: has parts: {hasattr(artifact, 'parts')}, parts length: {len(artifact.parts) if hasattr(artifact, 'parts') and artifact.parts else 0}")
                if hasattr(artifact, "parts") and artifact.parts:
                    for j, part in enumerate(artifact.parts):
                        root = getattr(part, "root", None)
                        logger.info(f"Part {j}: root type: {type(root)}, has text: {hasattr(root, 'text') if root else False}, has data: {hasattr(root, 'data') if root else False}")
                        if root:
                            # TextPart
                            if hasattr(root, "text") and root.text:
                                result["text"] = root.text
                                logger.info(f"Extracted TextPart, length: {len(root.text)}")
                            # DataPart
                            elif hasattr(root, "data") and root.data:
                                result["data"] = root.data
                                logger.info(f"Extracted DataPart, type: {type(root.data)}")
                            # FilePart
                            elif hasattr(root, "kind") and root.kind == "file":
                                result["file"] = {
                                    "uri": getattr(root, "file_with_uri", None),
                                    "bytes": getattr(root, "file_with_bytes", None),
                                    "mime_type": getattr(root, "mime_type", "application/octet-stream"),
                                }
                                logger.info("Extracted FilePart")

        # History에서 Part 추출 (artifacts가 없는 경우)
        elif hasattr(task, "history") and task.history:
            logger.info(f"Found history with {len(task.history)} messages")
            last_message = task.history[-1]
            logger.info(f"Last message role: {last_message.role.value if hasattr(last_message, 'role') else 'no role'}")
            if hasattr(last_message, "role") and last_message.role.value == "agent":
                if hasattr(last_message, "parts") and last_message.parts:
                    logger.info(f"Agent message has {len(last_message.parts)} parts")
                    for j, part in enumerate(last_message.parts):
                        root = getattr(part, "root", None)
                        logger.info(f"History Part {j}: root type: {type(root)}, has text: {hasattr(root, 'text') if root else False}, has data: {hasattr(root, 'data') if root else False}")
                        if root:
                            if hasattr(root, "text") and root.text:
                                result["text"] = root.text
                                logger.info(f"Extracted TextPart from history, length: {len(root.text)}")
                            elif hasattr(root, "data") and root.data:
                                result["data"] = root.data
                                logger.info(f"Extracted DataPart from history, type: {type(root.data)}")
        else:
            logger.info("No artifacts or history found in task")

        logger.info(f"Event processing result: {result}")
        return result

    def _merge_incremental_text(self, existing: str, new: str) -> str:
        """증분 텍스트를 병합합니다.

        전략
            - 신규 텍스트가 기존을 앞부분으로 포함하면 신규 전체를 채택
            - 기존 텍스트가 신규를 앞부분으로 포함하면 기존을 유지
            - 두 문자열 사이의 최대 접미사/접두사 겹침을 찾아 이어붙임

        Returns
            str: 병합된 문자열
        """
        if not existing:
            return new
        if new.startswith(existing):
            return new
        if existing.startswith(new):
            return existing

        # 겹치는 부분 찾기
        max_overlap = min(len(existing), len(new))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if existing.endswith(new[:k]):
                overlap = k
                break

        return existing + new[overlap:]

    def _merge_data_parts(
        self,
        parts: List[Dict[str, Any]],
        mode: str = "smart"
    ) -> Dict[str, Any]:
        """여러 DataPart를 하나로 병합합니다.

        병합 규칙
            - mode == "last": 마지막 파트를 그대로 채택
            - mode == "smart":
                - dict: 재귀 병합
                - list: 이어붙인 뒤 항목 문자열화 키 기준 중복 제거
                - 그 외 스칼라: 마지막 값 우선

        Returns
            dict: 병합된 결과 딕셔너리
        """
        if not parts:
            return {}

        if mode == "last":
            return parts[-1] if parts else {}

        # Smart merge
        result = {}
        for part in parts:
            if not isinstance(part, dict):
                continue

            for key, value in part.items():
                if key not in result:
                    result[key] = value
                elif isinstance(result[key], list) and isinstance(value, list):
                    # 리스트는 합치고 중복 제거
                    combined = result[key] + value
                    seen = set()
                    deduped = []
                    for item in combined:
                        item_key = str(item) if not isinstance(item, dict) else json.dumps(item, sort_keys=True)
                        if item_key not in seen:
                            seen.add(item_key)
                            deduped.append(item)
                    result[key] = deduped
                elif isinstance(result[key], dict) and isinstance(value, dict):
                    # 딕셔너리는 재귀적으로 병합
                    result[key] = self._merge_data_parts([result[key], value], mode)
                else:
                    # 그 외는 마지막 값 우선
                    result[key] = value

        return result

    async def execute_with_retry(self, func, *args, **kwargs):
        """재시도 로직을 적용하여 함수를 실행합니다.

        지수 백오프(초기 ``retry_delay`` 기준)로 ``max_retries`` 회까지
        재시도합니다. ValueError는 비복구성으로 간주하여 즉시 전파합니다.

        Raises
            A2AClientError: A2A 클라이언트 계층의 오류(최종 실패 시).
            httpx.HTTPError: 네트워크 오류(최종 실패 시).
            RuntimeError: 예기치 못한 예외 래핑.
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except A2AClientError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    logger.warning(f"A2A client error, retry {attempt + 1}/{self.max_retries}: {e}")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                else:
                    logger.error(f"Max retries exceeded: {e}")
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    logger.warning(f"HTTP error, retry {attempt + 1}/{self.max_retries}: {e}")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                else:
                    logger.error(f"Max retries exceeded: {e}")
            except ValueError as e:
                # 값 오류는 재시도 무의미
                logger.error(f"ValueError (no retry): {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise RuntimeError(f"Unexpected error in A2A client: {str(e)}") from e

        if last_error:
            raise last_error

        raise RuntimeError("Unknown error after retries")

    # ==================== Task ID 캐싱 및 중복 방지 메서드들 ====================

    def _generate_request_hash(self, message: Message) -> str:
        """메시지 내용을 기반으로 고유한 해시를 생성합니다.

        구성요소
            - TextPart: 텍스트 내용
            - DataPart: 정렬된 JSON 문자열
            - FilePart: URI 또는 파일 이름

        Returns
            str: 16자리로 축약된 SHA-256 해시 문자열
        """
        try:
            # 메시지의 핵심 내용들을 추출하여 해시 생성
            content_parts = []

            if hasattr(message, 'parts') and message.parts:
                for part in message.parts:
                    if hasattr(part, 'root'):
                        root = part.root
                        if hasattr(root, 'text') and root.text:
                            content_parts.append(f"text:{root.text}")
                        elif hasattr(root, 'data') and root.data:
                            content_parts.append(f"data:{json.dumps(root.data, sort_keys=True)}")
                        elif hasattr(root, 'file'):
                            # 파일의 경우 URI나 이름 등 식별 가능한 정보 사용
                            file_info = root.file
                            if hasattr(file_info, 'uri') and file_info.uri:
                                content_parts.append(f"file_uri:{file_info.uri}")
                            elif hasattr(file_info, 'name') and file_info.name:
                                content_parts.append(f"file_name:{file_info.name}")

            # 내용이 없다면 빈 문자열 해시
            content_string = "|".join(content_parts) if content_parts else "empty_message"

            # SHA256 해시 생성 (짧게 truncate)
            hash_object = hashlib.sha256(content_string.encode('utf-8'))
            return hash_object.hexdigest()[:16]  # 16자리로 축약

        except Exception as e:
            logger.warning(f"Failed to generate request hash: {e}")
            # fallback으로 현재 시간 기반 해시 생성
            import time
            return hashlib.sha256(f"fallback_{time.time()}".encode()).hexdigest()[:16]

    async def _get_task_direct(self, task_id: str) -> Optional[Any]:
        """GetTask API를 직접 호출하여 task 정보를 가져옵니다.

        주의
            전송 계층의 ``_transport.get_task`` 가용 시 이를 우선 사용하여
            불필요한 새 메시지 생성을 피합니다. 사용 불가하면 클라이언트의
            ``get_task`` 로 폴백합니다.

        Returns
            Any | None: 태스크 객체 또는 실패 시 ``None``.
        """
        try:
            from a2a.types import TaskQueryParams

            logger.info(f"Direct GetTask API call for task_id: {task_id}")

            # ClientTaskManager
            query_params = TaskQueryParams(id=task_id, history_length=20)

            # Transport layer를 통한 직접 호출 시도
            if hasattr(self.client, '_transport') and hasattr(self.client._transport, 'get_task'):
                task = await self.client._transport.get_task(query_params)
                logger.info(f"Successfully retrieved task via transport layer: {task_id}")
                return task
            else:
                # Fallback: client.get_task 사용 (다만 이것도 새 메시지를 생성할 가능성이 있음)
                logger.warning("Transport layer not available, using client.get_task as fallback")
                task = await self.client.get_task(query_params)
                return task

        except Exception as e:
            logger.error(f"Direct GetTask failed for {task_id}: {e}")
            return None

    async def _get_or_create_task_id(self, message: Message) -> tuple[Optional[str], bool]:
        """기존 ``task_id`` 를 찾거나 새로 생성합니다.

        캐시된 동일 요청의 태스크가 살아있다면 이를 재사용하거나 완료까지
        대기하고, 유효하지 않다면 캐시에서 제거한 뒤 새 태스크 생성이 필요함을
        알립니다.

        Returns
            tuple[Optional[str], bool]: (task_id, is_new_task)
        """
        try:
            # 메시지 해시 생성
            request_hash = self._generate_request_hash(message)
            logger.info(f"Generated request hash: {request_hash}")

            # 캐시에서 기존 task_id 확인
            if request_hash in self.task_cache:
                existing_task_id = self.task_cache[request_hash]
                logger.info(f"Found existing task_id in cache: {existing_task_id}")

                # 기존 task가 여전히 유효한지 확인
                existing_task = await self._get_task_direct(existing_task_id)
                if existing_task:
                    # Task 상태 확인
                    task_status_obj = getattr(existing_task, 'status', None)
                    if task_status_obj:
                        current_state = getattr(task_status_obj, 'state', None)
                        state_str = str(current_state).lower() if current_state else ""

                        # 완료된 task라면 재사용 가능
                        if 'completed' in state_str or 'failed' in state_str or 'cancelled' in state_str:
                            logger.info(f"Reusing completed task: {existing_task_id}")
                            return existing_task_id, False
                        elif 'working' in state_str or 'running' in state_str:
                            logger.info(f"Found running task, will wait for completion: {existing_task_id}")
                            return existing_task_id, False

                # 유효하지 않은 task라면 캐시에서 제거
                logger.warning(f"Removing invalid task from cache: {existing_task_id}")
                del self.task_cache[request_hash]

            # 새로운 task가 필요함
            logger.info("No existing valid task found, will create new one")
            return None, True

        except Exception as e:
            logger.error(f"Error in _get_or_create_task_id: {e}")
            # 에러가 발생하면 새 task 생성으로 fallback
            return None, True

    async def _wait_for_task_completion(self, task_id: str, max_wait: int = 120, poll_interval: float = 10.0) -> Optional[Any]:
        """태스크 완료 폴링.

        설명
            일정 간격으로 GetTask를 호출해 태스크 상태를 점검합니다. 완료,
            실패, 취소, 또는 아티팩트/히스토리의 유효 신호가 발견되면 종료합니다.

        Parameters
            task_id: 대상 태스크 식별자.
            max_wait: 최대 대기 시간(초).
            poll_interval: 폴링 간격(초).

        Returns
            Any | None: 완료/실패된 태스크 객체 또는 타임아웃/오류 시 ``None``.
        """
        logger.info(f"Task completion polling for task {task_id} (max_wait: {max_wait}s)")

        consecutive_failures = 0
        max_consecutive_failures = 5

        for attempt in range(int(max_wait / poll_interval)):
            try:
                # 직접 GetTask API 호출
                task = await self._get_task_direct(task_id)
                if not task:
                    consecutive_failures += 1
                    logger.warning(f"Could not retrieve task {task_id}, attempt {attempt + 1}")

                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"Too many consecutive failures retrieving task {task_id}")
                        return None

                    await asyncio.sleep(poll_interval * (1 + consecutive_failures * 0.5))
                    continue

                consecutive_failures = 0  # 성공 시 리셋

                # Task 상태 확인
                task_status_obj = getattr(task, 'status', None)
                logger.info(f"Task status object: {task_status_obj}")
                if task_status_obj:
                    current_state = getattr(task_status_obj, 'state', None)
                    state_str = str(current_state).lower() if current_state else ""

                    logger.info(f"Attempt {attempt + 1}: Task {task_id} state: {current_state} state_str: {state_str}")

                    if 'completed' in state_str:
                        # logger.info(f"Task {task_id} completed successfully after {attempt + 1} attempts")
                        return task
                    elif 'failed' in state_str or 'cancelled' in state_str:
                        # logger.warning(f"Task {task_id} failed or cancelled")
                        return task  # 실패한 task도 반환하여 에러 정보 추출 가능
                    elif 'working' in state_str or 'running' in state_str:
                        # 작업 중이지만, 아티팩트나 에이전트 메시지가 있으면 완료로 간주하고 반환
                        has_artifacts = hasattr(task, 'artifacts') and task.artifacts
                        has_agent_history = False
                        if hasattr(task, 'history') and task.history:
                            for msg in task.history:
                                if hasattr(msg, 'role') and str(msg.role).lower() == 'agent':
                                    has_agent_history = True
                                    break

                        if has_artifacts or has_agent_history:
                            logger.info(f"Task {task_id} is working but has artifacts/history - treating as completed")
                            return task

                        logger.info(f"Task {task_id} is still working - reducing polling frequency")
                        await asyncio.sleep(poll_interval * 2)
                        continue
                    else:
                        # 알 수 없는 상태면 내용이 있는지 확인
                        if hasattr(task, 'artifacts') and task.artifacts:
                            logger.info(f"Task {task_id} has artifacts despite unknown state - assuming completed")
                            return task
                        elif hasattr(task, 'history') and task.history:
                            for msg in task.history:
                                if hasattr(msg, 'role') and str(msg.role).lower() == 'agent':
                                    logger.info(f"Task {task_id} has agent messages - assuming completed")
                                    return task

                await asyncio.sleep(poll_interval)

            except Exception as e:
                consecutive_failures += 1
                logger.warning(f"Enhanced polling attempt {attempt + 1} failed: {e}")

                if consecutive_failures >= max_consecutive_failures:
                    logger.error("Too many consecutive polling failures, giving up")
                    return None

                await asyncio.sleep(poll_interval * (1 + consecutive_failures * 0.5))

        logger.warning(f"Enhanced task completion polling timed out after {max_wait}s")
        return None

    async def _extract_task_results(self, task: Any, response: UnifiedResponse, text_accumulator: str) -> str:
        """태스크에서 결과를 추출하여 ``response`` 에 저장합니다.

        우선순위
            1) Artifacts: 권위 있는 최종 결과로 간주하여 바로 채택
            2) History: 아티팩트가 없을 때 최신 에이전트 메시지에서 추출

        Returns
            str: 업데이트된 텍스트 누적값
        """
        try:
            logger.info("Extracting results from completed task")

            # Artifacts에서 데이터 추출 (우선순위 높음)
            if hasattr(task, 'artifacts') and task.artifacts:
                logger.info(f"Found {len(task.artifacts)} artifacts")
                for artifact in task.artifacts:
                    if hasattr(artifact, 'parts') and artifact.parts:
                        for part in artifact.parts:
                            root = getattr(part, 'root', None)
                            if root:
                                if hasattr(root, 'text') and root.text:
                                    # Authoritative text from artifacts
                                    response.text_parts = [root.text]
                                    text_accumulator = root.text
                                    logger.info(f"Extracted authoritative text: {len(root.text)} chars")
                                elif hasattr(root, 'data') and root.data:
                                    # Authoritative data from artifacts
                                    response.data_parts = [root.data]
                                    logger.info("Extracted authoritative data from artifacts")

            # Status.message에서 데이터 추출 (아티팩트가 없거나 추가 보강)
            if (not response.text_parts and not response.data_parts) and hasattr(task, 'status'):
                status_message = getattr(task.status, 'message', None)
                if status_message and hasattr(status_message, 'parts') and status_message.parts:
                    logger.info("Extracting from status.message as authoritative source")
                    for part in status_message.parts:
                        root = getattr(part, 'root', None)
                        if root:
                            if hasattr(root, 'text') and root.text:
                                response.text_parts = [root.text]
                                text_accumulator = root.text
                                logger.info(f"Extracted text from status.message: {len(root.text)} chars")
                            elif hasattr(root, 'data') and root.data:
                                response.data_parts = [root.data]
                                logger.info("Extracted data from status.message")

            # History에서 데이터 추출 (fallback)
            if hasattr(task, 'history') and task.history and not response.text_parts and not response.data_parts:
                logger.info("No artifacts found, extracting from history")
                for msg in reversed(task.history):
                    if hasattr(msg, 'role') and str(msg.role).lower() == 'agent':
                        if hasattr(msg, 'parts') and msg.parts:
                            for part in msg.parts:
                                root = getattr(part, 'root', None)
                                if root:
                                    if hasattr(root, 'text') and root.text:
                                        response.text_parts.append(root.text)
                                        text_accumulator = root.text
                                        logger.info(f"Extracted text from history: {len(root.text)} chars")
                                    elif hasattr(root, 'data') and root.data:
                                        response.data_parts.append(root.data)
                                        logger.info("Extracted data from history")
                        break  # 첫 번째 agent 메시지만 사용

            logger.info(f"Task result extraction complete - text parts: {len(response.text_parts)}, data parts: {len(response.data_parts)}")
            return text_accumulator

        except Exception as e:
            logger.error(f"Error extracting task results: {e}")
            return text_accumulator


# ==================== Specialized Clients ====================

class A2ATextClient:
    """텍스트 전송 특화 클라이언트.

    사용 목적
        간단한 텍스트 프롬프트를 보내고 최종 텍스트 응답을 받는 케이스에
        최적화된 경량 래퍼입니다. 내부적으로 :class:`A2AMessageEngine` 을
        사용합니다.
    """

    def __init__(self, engine: A2AMessageEngine):
        self.engine = engine

    async def send(
        self,
        text: str,
        streaming_callback: Optional[Callable] = None,
    ) -> TextResponse:
        """텍스트를 전송합니다.

        Args
            text: 사용자 프롬프트 텍스트.
            streaming_callback: 증분 텍스트 델타를 수신할 콜백.

        Returns
            TextResponse: 최종 텍스트와 스트리밍 조각, 이벤트 수를 포함.
        """
        message = create_text_message_object(
            role=Role.user,
            content=text,
        )

        # 엔진을 통해 전송
        unified = await self.engine.execute_with_retry(
            self.engine.send_message_core,
            message,
            streaming_callback,
        )

        # TextResponse로 변환
        return TextResponse(
            text=unified.merged_text,
            streaming_chunks=unified.text_parts,
            event_count=unified.event_count,
        )


class A2ADataClient:
    """데이터 전송 특화 클라이언트.

    사용 목적
        구조화된 JSON 유사 데이터(dict)를 ``DataPart`` 로 전송하고, 서버가
        반환하는 데이터 파트를 수집/병합합니다.
    """

    def __init__(self, engine: A2AMessageEngine):
        self.engine = engine

    async def send(
        self,
        data: Dict[str, Any],
        merge_mode: str = "smart",
        streaming_callback: Optional[Callable] = None,
    ) -> DataResponse:
        """구조화된 데이터를 전송합니다.

        Args
            data: 전송할 딕셔너리 형태의 데이터.
            merge_mode: "smart" 또는 "last" 또는 "none".
            streaming_callback: 스트리밍 데이터 파트 수신 콜백.

        Returns
            DataResponse: 원본 파트, 병합 결과, 이벤트 수 포함.
        """
        # DataPart로 Message 생성 (dictionary 객체를 직접 전달)
        message = Message(
            role=Role.user,
            parts=[Part(root=DataPart(data=data))],
            message_id=str(uuid4()),
        )

        # 엔진을 통해 전송
        unified = await self.engine.execute_with_retry(
            self.engine.send_message_core,
            message,
            streaming_callback,
        )

        # DataResponse로 변환
        return DataResponse(
            data_parts=unified.data_parts,
            merged_data=unified.merged_data if merge_mode != "none" else None,
            event_count=unified.event_count,
        )


class A2AFileClient:
    """파일 전송 특화 클라이언트.

    사용 목적
        파일 경로/바이트를 ``FilePart`` 로 전송하고 서버가 반환하는 파일
        응답(URI/바이트)을 수신합니다.
    """

    def __init__(self, engine: A2AMessageEngine):
        self.engine = engine

    async def send(
        self,
        file: Union[bytes, str, Path],
        mime_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FileResponse:
        """파일을 전송합니다.

        Args
            file: 파일 바이트 또는 파일 경로.
            mime_type: 파일 MIME 타입.
            metadata: 호출자가 보관하고 싶은 부가 메타데이터.

        Returns
            FileResponse: 서버가 반환한 파일 관련 응답.

        Raises
            FileNotFoundError: 경로가 존재하지 않는 경우.
        """
        # FilePart 생성
        if isinstance(file, (str, Path)):
            # 파일 경로인 경우
            file_path = Path(file)
            if file_path.exists():
                file_with_uri = FileWithUri(uri=str(file_path.absolute()), mime_type=mime_type)
                file_part = FilePart(file=file_with_uri)
            else:
                raise FileNotFoundError(f"File not found: {file}")
        else:
            # 바이트 데이터인 경우
            file_with_bytes = FileWithBytes(bytes=file, mime_type=mime_type)
            file_part = FilePart(file=file_with_bytes)

        # Message 생성
        message = Message(
            role=Role.user,
            parts=[Part(root=file_part)],
            message_id=str(uuid4()),
        )

        # 엔진을 통해 전송
        unified = await self.engine.execute_with_retry(
            self.engine.send_message_core,
            message,
        )

        # FileResponse로 변환
        if unified.file_parts:
            return unified.file_parts[0]
        else:
            return FileResponse(mime_type=mime_type, metadata=metadata or {})


# ==================== Unified Manager (Legacy Compatible) ====================

class A2AClientManagerV2:
    """A2A 클라이언트 통합 관리자 V2.

    설명
        레거시 :class:`A2AClientManager` 와 API 호환을 유지하면서 내부 구조를
        개선한 통합 래퍼입니다. 텍스트/데이터/파일 전송에 대한 단일 진입점을
        제공하며, 필요 시 엔진을 직접 다루지 않고도 대부분의 작업을 처리할 수
        있습니다.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        streaming: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        credential_service: Optional[CredentialService] = None,
    ):
        """매니저를 초기화합니다.

        Args
            base_url: A2A 에이전트 베이스 URL.
            streaming: 스트리밍 모드 사용 여부.
            max_retries: 재시도 최대 횟수.
            retry_delay: 재시도 초기 지연.
            credential_service: 인증 서비스(옵션).
        """
        # 엔진 초기화
        self.engine = A2AMessageEngine(
            base_url=base_url,
            streaming=streaming,
            max_retries=max_retries,
            retry_delay=retry_delay,
            credential_service=credential_service,
        )

        # 전문 클라이언트 초기화
        self.text_client = A2ATextClient(self.engine)
        self.data_client = A2ADataClient(self.engine)
        self.file_client = A2AFileClient(self.engine)

        # 레거시 호환성을 위한 속성들
        self.base_url = base_url
        self.streaming = streaming
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.credential_service = credential_service
        self.client = None  # engine.client로 대체
        self.agent_card = None  # engine.agent_card로 대체
        self._httpx_client = None  # engine._httpx_client로 대체

    async def __aenter__(self):
        """비동기 컨텍스트 진입 시 자동 초기화."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 종료 시 리소스 정리."""
        await self.close()

    async def initialize(self) -> 'A2AClientManagerV2':
        """클라이언트를 초기화합니다.

        엔진을 초기화하고, 레거시 호환성을 위해 주요 속성을 매핑합니다.

        Returns
            A2AClientManagerV2: 자기 자신.
        """
        await self.engine.initialize()

        # 레거시 호환성을 위한 속성 매핑
        self.client = self.engine.client
        self.agent_card = self.engine.agent_card
        self._httpx_client = self.engine._httpx_client

        return self

    async def close(self):
        """리소스를 정리합니다."""
        await self.engine.close()

    async def get_agent_card(self) -> AgentCard:
        """Agent Card를 반환합니다."""
        return self.engine.agent_card

    def get_agent_info(self) -> Dict[str, Any]:
        """Agent 정보를 반환합니다.

        Returns
            dict: 이름/설명/URL/기능/스킬 등의 요약 정보.
        """
        if not self.engine.agent_card:
            return {}

        return {
            "name": self.engine.agent_card.name,
            "description": self.engine.agent_card.description,
            "url": self.engine.agent_card.url,
            "capabilities": self.engine.agent_card.capabilities.model_dump(),
            "default_input_modes": self.engine.agent_card.default_input_modes,
            "default_output_modes": self.engine.agent_card.default_output_modes,
            "skills": [
                {"name": skill.name, "description": skill.description}
                for skill in self.engine.agent_card.skills
            ],
        }

    async def health_check(self) -> bool:
        """연결 상태를 확인합니다.

        Returns
            bool: 에이전트 카드 엔드포인트 응답이 200이면 True.
        """
        try:
            if not self.engine._httpx_client:
                return False

            response = await self.engine._httpx_client.get(
                f"{self.base_url}{AGENT_CARD_WELL_KNOWN_PATH}",
                timeout=5.0,
                headers={
                    "User-Agent": "A2AClientManager/2.0",
                    "Accept": "application/json; charset=utf-8",
                },
            )
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Health check failed for {self.base_url}: {e}")
            return False

    async def ensure_connection(self):
        """연결 상태를 확인하고 필요 시 재연결합니다."""
        if not await self.health_check():
            logger.info(f"Connection lost to {self.base_url}, reconnecting...")
            await self.close()
            await self.initialize()

    # ==================== Legacy Compatible Methods ====================

    async def send_query(self, user_query: str) -> str:
        """텍스트 질의를 전송합니다. (레거시 호환)

        Args
            user_query: 전송할 텍스트

        Returns
            str: 응답 텍스트
        """
        response = await self.text_client.send(user_query)
        return response.text

    async def send_data(self, data: Dict[str, Any]) -> dict[str, Any]:
        """데이터를 전송합니다.

        Args
            data: 전송할 데이터

        Returns
            dict: ``DataResponse`` 를 ``asdict`` 한 결과
        """
        response = await self.data_client.send(data)
        return asdict(response)

    async def send_data_with_full_messages(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """데이터를 전송하고 전체 메시지 히스토리를 반환합니다. (레거시 호환)

        Args
            data: 전송할 데이터

        Returns
            dict: ``data_parts``, ``full_message_history``(미구현),
                ``streaming_text``, ``event_count`` 포함
        """
        # 히스토리 수집/텍스트 활용을 위해 엔진 코어를 직접 사용
        # 메시지 생성 후 UnifiedResponse를 받아 텍스트/데이터를 모두 반영
        message = Message(
            role=Role.user,
            parts=[Part(root=DataPart(data=data))],
            message_id=str(uuid4()),
        )

        unified = await self.engine.execute_with_retry(
            self.engine.send_message_core,
            message,
        )

        # 루트 결과 구성
        root: Dict[str, Any] = {
            "data_parts": unified.data_parts,
            "full_message_history": [],  # TODO: 히스토리 수집 구현
            "streaming_text": "".join(unified.text_parts) if unified.text_parts else "",
            "event_count": unified.event_count,
        }

        # 텍스트: 병합 텍스트가 있으면 우선 노출
        if unified.merged_text:
            root["text_content"] = unified.merged_text

        # 데이터: 병합 결과 우선, 없으면 첫 data_part 노출
        if unified.merged_data:
            root["data_content"] = unified.merged_data
        elif unified.data_parts:
            first = unified.data_parts[0]
            root["data_content"] = first

            # text_content가 비어 있으면 data_parts의 raw_analysis로 보강
            if not root.get("text_content"):
                text_candidate = first.get("result", {}).get("raw_analysis")
                if text_candidate:
                    root["text_content"] = text_candidate

            # 메타 신호 보강: analysis_signal → metadata.final_signal
            final_sig = first.get("result", {}).get("analysis_signal")
            if final_sig:
                meta = dict(root.get("metadata", {}))
                meta["final_signal"] = final_sig
                root["metadata"] = meta

        # 안전 기본값 보강
        root.setdefault("agent_type", "AnalysisA2AAgent")
        root.setdefault("status", "completed")
        root.setdefault("final", True)

        return root

    async def send_data_merged(
        self,
        data: Dict[str, Any],
        merge_mode: str = "smart"
    ) -> Dict[str, Any]:
        """데이터를 전송하고 병합된 결과를 반환합니다. (레거시 호환)

        Args
            data: 전송할 데이터
            merge_mode: 병합 모드("smart"/"last"/"none")

        Returns
            dict: 병합된 데이터 딕셔너리
        """
        response = await self.data_client.send(data, merge_mode=merge_mode)
        return response.merged_data or {}

    # ==================== New Unified Methods ====================

    async def send_parts(
        self,
        parts: List[Part],
        include_history: bool = False,
        error_strategy: ErrorStrategy = ErrorStrategy.FAIL_FAST,
    ) -> UnifiedResponse:
        """여러 Part를 한 번에 전송합니다.

        Args
            parts: 전송할 Part 리스트
            include_history: 히스토리 포함 여부(미구현)
            error_strategy: 에러 처리 전략(미구현)

        Returns
            UnifiedResponse: 통합 응답
        """
        # Message 생성
        message = Message(
            role=Role.user,
            parts=parts,
            message_id=str(uuid4()),
        )

        # 엔진을 통해 전송
        response = await self.engine.execute_with_retry(
            self.engine.send_message_core,
            message,
        )

        # TODO: include_history, error_strategy 구현

        return response

    async def send_text(self, text: str, **options) -> TextResponse:
        """텍스트를 전송합니다. (새 API)"""
        return await self.text_client.send(text, **options)

    async def send_file(
        self,
        file: Union[bytes, str, Path],
        mime_type: str = "application/octet-stream",
        **options
    ) -> FileResponse:
        """파일을 전송합니다. (새 API)"""
        return await self.file_client.send(file, mime_type, **options)


# ==================== A2A Interface Integration ====================

def convert_a2a_output_to_message(output: A2AOutput) -> Message:
    """LangGraph 표준 ``A2AOutput`` 을 A2A ``Message`` 로 변환합니다.

    매핑 규칙
        - ``text_content`` -> ``TextPart``
        - ``data_content`` -> ``DataPart``
        - ``agent_type`` 가 ``user`` 가 아니면 역할을 ``assistant`` 로 설정

    Args
        output: 에이전트가 표준화하여 내보낸 출력 딕셔너리.

    Returns
        Message: A2A 프로토콜 메시지.
    """
    parts = []

    # Add text part if present
    text_content = output.get("text_content")
    if text_content:
        parts.append(Part(root=TextPart(text=text_content)))

    # Add data part if present
    data_content = output.get("data_content")
    if data_content:
        parts.append(Part(root=DataPart(data=data_content)))

    # Determine role based on agent type
    agent_type = output.get("agent_type", "unknown")
    role = Role.assistant if agent_type != "user" else Role.user

    # Create message with metadata
    message = Message(
        role=role,
        parts=parts,
        message_id=str(uuid4()),
        metadata=output.get("metadata", {})
    )

    return message


def convert_a2a_output_to_parts(output: A2AOutput) -> List[Part]:
    """``A2AOutput`` 을 A2A ``Part`` 목록으로 변환합니다.

    Args
        output: 에이전트 표준 출력 딕셔너리.

    Returns
        list[Part]: 텍스트/데이터 파트를 포함하는 목록.
    """
    parts = []

    # Add text part if present
    text_content = output.get("text_content")
    if text_content:
        parts.append(Part(root=TextPart(text=text_content)))

    # Add data part if present
    data_content = output.get("data_content")
    if data_content:
        parts.append(Part(root=DataPart(data=data_content)))

    return parts


async def send_a2a_output(
    client_manager: 'A2AClientManagerV2',
    output: A2AOutput,
    streaming_callback: Optional[Callable] = None
) -> UnifiedResponse:
    """표준 ``A2AOutput`` 을 A2A 클라이언트를 통해 전송합니다.

    Args
        client_manager: 초기화가 완료된 클라이언트 매니저.
        output: 에이전트 표준 출력.
        streaming_callback: 스트리밍 콜백(옵션).

    Returns
        UnifiedResponse: 서버 응답의 통합 표현.
    """
    # Convert to message
    message = convert_a2a_output_to_message(output)

    # Send through engine
    return await client_manager.engine.send_message_core(
        message,
        streaming_callback
    )


class A2AOutputProcessor:
    """``A2AOutput`` 스트림 처리를 돕는 보조 클래스.

    용도
        에이전트로부터 순차적으로 전달되는 ``A2AOutput`` 조각들을 수집하고,
        텍스트/데이터/메타데이터를 최종 결과로 합성합니다.
    """

    def __init__(self):
        """버퍼와 상태를 초기화합니다."""
        self.text_buffer = []
        self.data_parts = []
        self.final_output = None
        self.metadata = {}

    def process_output(self, output: A2AOutput):
        """단일 ``A2AOutput`` 을 처리하여 내부 버퍼를 갱신합니다.

        수신된 텍스트/데이터/메타데이터를 누적하고, ``final=True`` 가 표시된
        조각이 들어오면 ``final_output`` 으로 보관합니다.
        """
        # Accumulate text
        if output.get("text_content"):
            self.text_buffer.append(output["text_content"])

        # Collect data parts
        if output.get("data_content"):
            self.data_parts.append(output["data_content"])

        # Update metadata
        if output.get("metadata"):
            self.metadata.update(output["metadata"])

        # Check if final
        if output.get("final", False):
            self.final_output = output

    def get_merged_text(self) -> str:
        """모든 출력에서 병합된 텍스트를 반환합니다."""
        return "".join(self.text_buffer)

    def get_merged_data(self) -> Dict[str, Any]:
        """모든 출력에서 병합된 데이터를 반환합니다.

        단순 병합 전략으로, 뒤에서 온 키가 앞의 값을 덮어씁니다.
        데이터가 없으면 빈 딕셔너리를 반환합니다.
        """
        if not self.data_parts:
            return {}

        # Simple merge strategy - later parts override earlier ones
        merged = {}
        for part in self.data_parts:
            if isinstance(part, dict):
                merged.update(part)

        return merged

    def get_final_result(self) -> Dict[str, Any]:
        """최종 합성 결과를 반환합니다."""
        return {
            "text": self.get_merged_text(),
            "data": self.get_merged_data(),
            "metadata": self.metadata,
            "final_output": self.final_output
        }
