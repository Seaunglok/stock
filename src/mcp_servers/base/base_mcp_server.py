"""
**DO NOT UPDATE THIS FILE. ONLY HUMAN CAN UPDATE THIS FILE.**
MCP 서버들의 공통 베이스 클래스.
이 모듈은 모든 MCP 서버가 상속받아 사용할 수 있는 기본 클래스를 제공합니다.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from fastmcp.server.http import StarletteWithLifespan
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import JSONResponse


class StandardResponse(BaseModel):
    """표준화된 MCP Server 응답 모델"""

    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
    )  # 추가 필드 허용 및 임의 타입 허용

    success: bool = Field(True, description="성공 여부 (항상 True)")
    query: str = Field(..., description="원본 쿼리")
    data: Any | None = Field(None, description="응답 데이터 (성공 시)")


class ErrorResponse(BaseModel):
    """표준 에러 MCP Server 응답 모델"""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    success: bool = Field(False, description="성공 여부 (항상 False)")
    query: str = Field(..., description="원본 쿼리")
    error: str = Field(..., description="에러 메시지")
    func_name: str | None = Field(None, description="에러가 발생한 함수명")


class BaseMCPServer(ABC):
    """MCP 서버의 베이스 클래스"""

    MCP_PATH = "/mcp"

    def __init__(
        self,
        server_name: str,
        port: int,
        host: str = "0.0.0.0",
        debug: bool = False,
        transport: Literal["streamable-http", "stdio"] = "streamable-http",
        server_instructions: str = "",
        json_response: bool = False,
        shutdown_timeout: float = 30.0,
        enable_middlewares: Optional[list[str]] = None,
        middleware_config: Optional[dict] = None,
    ):
        """
        MCP 서버 초기화

        Args:
            server_name: 서버 이름
            port: 서버 포트
            host: 호스트 주소 (기본값: "0.0.0.0")
            debug: 디버그 모드 (기본값: False)
            transport: MCP 전송 방식 (기본값: "streamable-http")
            server_instructions: 서버 설명 (기본값: "")
            json_response: JSON 응답 검증 여부 (기본값: False)
            shutdown_timeout: Graceful shutdown 타임아웃 (기본값: 30.0초)
            enable_middlewares: 활성화할 미들웨어 리스트 (예: ["logging", "error_handling", "cors"])
            middleware_config: 미들웨어별 설정 딕셔너리
        """
        from fastmcp import FastMCP

        self.server_name = server_name
        self.host = host
        self.port = port
        self.debug = debug
        self.transport = transport
        self.server_instructions = server_instructions
        self.json_response = json_response
        self.enable_middlewares = enable_middlewares or []
        self.middleware_config = middleware_config or {}

        # FastMCP 인스턴스 생성
        self.mcp = FastMCP(name=server_name, instructions=server_instructions)

        # 로거 설정 (미들웨어보다 먼저 초기화)
        self.logger = logging.getLogger(self.__class__.__name__)

        # 미들웨어 설정
        self._setup_middlewares()

        # 백그라운드 태스크 추적을 위한 딕셔너리
        self._background_tasks: dict[str, asyncio.Task] = {}

        # 클라이언트 초기화
        self._initialize_clients()

        # 도구 등록
        self._register_tools()

    @abstractmethod
    def _initialize_clients(self) -> None:
        """클라이언트 인스턴스를 초기화합니다. 하위 클래스에서 구현해야 합니다."""
        pass

    @abstractmethod
    def _register_tools(self) -> None:
        """MCP 도구들을 등록합니다. 하위 클래스에서 구현해야 합니다."""
        pass

    def _setup_middlewares(self) -> None:
        """미들웨어를 설정하고 FastMCP에 등록합니다."""
        if not self.enable_middlewares:
            return

        # 미들웨어 매핑 (CORS 제외 - Starlette CORSMiddleware 사용)
        middleware_classes = {
            "error_handling": self._get_error_handling_middleware,
            "logging": self._get_logging_middleware,
        }

        for middleware_name in self.enable_middlewares:
            try:
                # CORS는 Starlette CORSMiddleware로 처리하므로 건너뜀
                if middleware_name == "cors":
                    self.logger.info(
                        "CORS middleware handled by Starlette CORSMiddleware"
                    )
                    continue

                if middleware_name in middleware_classes:
                    middleware_factory = middleware_classes[middleware_name]
                    middleware = middleware_factory()
                    if middleware:
                        self.mcp.add_middleware(middleware)
                        self.logger.info(f"Enabled {middleware_name} middleware")
                else:
                    self.logger.warning(f"Unknown middleware: {middleware_name}")
            except Exception as e:
                self.logger.error(f"Failed to setup {middleware_name} middleware: {e}")

    def _get_error_handling_middleware(self):
        """ErrorHandling 미들웨어 생성"""
        try:
            from src.mcp_servers.common.middleware import ErrorHandlingMiddleware

            config = self.middleware_config.get("error_handling", {})
            return ErrorHandlingMiddleware(
                include_traceback=config.get("include_traceback", self.debug),
                **{k: v for k, v in config.items() if k != "include_traceback"},
            )
        except ImportError as e:
            self.logger.warning(f"ErrorHandling middleware not available: {e}")
            return None

    def _get_logging_middleware(self):
        """Logging 미들웨어 생성"""
        try:
            from src.mcp_servers.common.middleware import LoggingMiddleware

            config = self.middleware_config.get("logging", {})
            return LoggingMiddleware(
                log_requests=config.get("log_requests", True),
                log_responses=config.get("log_responses", self.debug),
                **{
                    k: v
                    for k, v in config.items()
                    if k not in ["log_requests", "log_responses"]
                },
            )
        except ImportError as e:
            self.logger.warning(f"Logging middleware not available: {e}")
            return None

    def _get_cors_middleware(self):
        """
        CORS 미들웨어는 이제 Starlette CORSMiddleware로 처리됩니다.
        create_app() 메서드에서 custom_middleware로 적용됩니다.
        """
        self.logger.info(
            "CORS is now handled by Starlette CORSMiddleware in create_app()"
        )
        return None

    def get_enabled_middlewares(self) -> list[str]:
        """
        현재 활성화된 미들웨어 목록을 반환합니다.

        Returns:
            활성화된 미들웨어 이름 리스트
        """
        return self.enable_middlewares.copy()

    def is_middleware_enabled(self, middleware_name: str) -> bool:
        """
        특정 미들웨어가 활성화되어 있는지 확인합니다.

        Args:
            middleware_name: 확인할 미들웨어 이름

        Returns:
            미들웨어 활성화 여부
        """
        return middleware_name in self.enable_middlewares

    def create_standard_response(
        self,
        success: bool,
        query: str,
        data: Any = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        표준화된 응답 형식을 생성합니다.

        Args:
            success: 성공 여부
            query: 원본 쿼리
            data: 응답 데이터
            error: 에러 메시지 (실패 시)
            **kwargs: 추가 필드

        Returns:
            표준화된 응답 딕셔너리 (JSON 직렬화 가능)
        """

        response_model = StandardResponse(
            success=success,
            query=query,
            data=data,
            **kwargs,
        )

        return response_model.model_dump(exclude_none=True)

    def create_error_response(
        self,
        error: str,
        query: str | None = None,
        func_name: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        표준화된 에러 처리

        Args:
            func_name: 함수 이름
            error: 발생한 예외
            **context: 에러 컨텍스트 정보

        Returns:
            에러 응답 딕셔너리
        """
        # 에러 응답 데이터 구성
        error_model = ErrorResponse(
            success=False,
            query=str(query),
            error=str(error),
            func_name=func_name,
            **kwargs,
        )

        return error_model.model_dump(exclude_none=True)

    def create_background_task(self, coro, name: Optional[str] = None) -> asyncio.Task:
        """
        백그라운드 태스크를 생성하고 추적합니다.

        Args:
            coro: 실행할 코루틴
            name: 태스크 이름 (디버깅 및 추적용)

        Returns:
            생성된 asyncio.Task 객체
        """
        # 태스크 생성
        task = asyncio.create_task(coro)

        # 이름 설정
        if name:
            task_name = name
        else:
            task_name = f"task_{id(task)}"

        # 태스크 추적
        self._background_tasks[task_name] = task

        # 태스크 완료 시 추적 딕셔너리에서 제거
        def cleanup_callback(t):
            self._background_tasks.pop(task_name, None)
            if t.exception():
                self.logger.error(
                    f"Background task {task_name} failed with exception",
                    exc_info=t.exception(),
                )

        task.add_done_callback(cleanup_callback)

        self.logger.debug(f"Created background task: {task_name}")
        return task

    async def shutdown(self, timeout: Optional[float] = None):
        """
        서버를 안전하게 종료합니다.

        Args:
            timeout: 종료 타임아웃 (초). None이면 초기화 시 설정된 값 사용

        Returns:
            종료 성공 여부
        """
        import sys

        await asyncio.sleep(float(timeout))
        self.logger.info(f"Shutting down {self.server_name}...")
        sys.exit(0)

    def get_active_tasks(self) -> list[str]:
        """
        현재 실행 중인 백그라운드 태스크 목록을 반환합니다.

        Returns:
            실행 중인 태스크 이름 목록
        """
        return [
            name for name, task in self._background_tasks.items() if not task.done()
        ]

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입."""
        await self.lifecycle.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료 - 자동 정리."""
        await self.shutdown()
        return False

    def create_app(self) -> StarletteWithLifespan:
        """
        ASGI 앱을 생성합니다.
        - /health 라우트를 1회만 등록합니다.
        - FastMCP의 http_app을 반환합니다.
        - Starlette CORSMiddleware를 적용합니다.
        """

        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware

        # CORS 미들웨어는 항상 설정
        cors_middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
                allow_credentials=False,  # * origins와 함께 사용할 수 없음
                expose_headers=["*"],
                max_age=600,
            )
        ]

        if not getattr(self, "_health_route_registered", False):

            @self.mcp.custom_route(
                path="/health",
                methods=["GET", "OPTIONS"],
                include_in_schema=True,
            )
            async def health_check(request: Request) -> JSONResponse:
                """Health check endpoint - CORS is handled by CORSMiddleware"""
                response_data = self.create_standard_response(
                    success=True,
                    query="MCP Server Health check",
                    data="OK",
                )
                return JSONResponse(content=response_data)

            self._health_route_registered = True
            self.logger.info("Health check endpoint registered at /health")
            self.logger.info(f"Simple GET handler registered at {self.MCP_PATH}")

        self.logger.info("Development CORS configured: allow all origins (*)")

        return self.mcp.streamable_http_app(
            path=self.MCP_PATH,
            custom_middleware=cors_middleware,
            transport=self.transport,
        )


"""
**DO NOT UPDATE THIS FILE. ONLY HUMAN CAN UPDATE THIS FILE.**
"""
