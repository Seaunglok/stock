"""
캐시 관리 모듈.

이 모듈은 MCP 서버들이 사용할 수 있는 통합 캐시 관리 시스템을 제공합니다.
스레드 세이프하고 비동기 지원하며, 다양한 캐시 전략을 지원합니다.
"""

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from functools import wraps
from threading import Lock
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

# Optional dependency for memory monitoring
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class CacheStrategy(str, Enum):
    """캐시 전략 열거형."""

    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In First Out


class CacheStats(BaseModel):
    """캐시 통계 정보."""

    hits: int = 0
    misses: int = 0
    total_size: int = 0
    max_size: int = 0
    evictions: int = 0
    memory_cleanups: int = 0
    last_memory_cleanup: float | None = None
    memory_pressure_triggers: int = 0

    @property
    def hit_rate(self) -> float:
        """캐시 적중률 계산."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def miss_rate(self) -> float:
        """캐시 미스율 계산."""
        return 1.0 - self.hit_rate


class CacheEntry(BaseModel):
    """캐시 항목."""

    value: any
    timestamp: float
    ttl: int | None = None
    access_count: int = Field(default=1)
    last_accessed: float = Field(default_factory=time.time)

    def is_expired(self) -> bool:
        """TTL 기반 만료 확인."""
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl

    def touch(self) -> None:
        """접근 시간 및 카운트 업데이트."""
        self.last_accessed = time.time()
        self.access_count += 1


class CacheEvictionStrategy(ABC):
    """캐시 축출 전략 추상 클래스."""

    @abstractmethod
    def should_evict(self, entries: dict[str, CacheEntry], max_size: int) -> list[str]:
        """축출할 키 목록 반환."""
        pass


class LRUEvictionStrategy(CacheEvictionStrategy):
    """LRU (Least Recently Used) 축출 전략."""

    def should_evict(self, entries: dict[str, CacheEntry], max_size: int) -> list[str]:
        if len(entries) <= max_size:
            return []

        # 마지막 접근 시간 기준 정렬
        sorted_entries = sorted(entries.items(), key=lambda x: x[1].last_accessed)

        # 가장 오래된 항목들 선택
        evict_count = len(entries) - max_size
        return [key for key, _ in sorted_entries[:evict_count]]


class LFUEvictionStrategy(CacheEvictionStrategy):
    """LFU (Least Frequently Used) 축출 전략."""

    def should_evict(self, entries: dict[str, CacheEntry], max_size: int) -> list[str]:
        if len(entries) <= max_size:
            return []

        # 접근 횟수 기준 정렬 (동일한 경우 오래된 것 우선)
        sorted_entries = sorted(
            entries.items(), key=lambda x: (x[1].access_count, x[1].last_accessed)
        )

        evict_count = len(entries) - max_size
        return [key for key, _ in sorted_entries[:evict_count]]


class FIFOEvictionStrategy(CacheEvictionStrategy):
    """FIFO (First In First Out) 축출 전략."""

    def should_evict(self, entries: dict[str, CacheEntry], max_size: int) -> list[str]:
        if len(entries) <= max_size:
            return []

        # 생성 시간 기준 정렬
        sorted_entries = sorted(entries.items(), key=lambda x: x[1].timestamp)

        evict_count = len(entries) - max_size
        return [key for key, _ in sorted_entries[:evict_count]]


class CacheManager(BaseModel):
    """
    통합 캐시 관리자.

    특징:
    - 스레드/코루틴 세이프
    - TTL 지원
    - 다양한 캐시 전략 (LRU, LFU, FIFO)
    - 캐시 통계 수집
    - 메모리 효율적인 구현
    """

    # Public config fields
    max_size: int = 1000
    default_ttl: int | None = 300
    strategy: CacheStrategy = CacheStrategy.LRU
    enable_stats: bool = True
    memory_threshold: float = 0.8
    background_cleanup_interval: int = 60
    enable_background_cleanup: bool = True

    # Pydantic v2: allow arbitrary runtime types (e.g., asyncio primitives, locks)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Private runtime fields
    _cache: dict[str, CacheEntry] = PrivateAttr(default_factory=dict)
    _lock: Lock = PrivateAttr(default_factory=Lock)
    _stats: CacheStats = PrivateAttr(default_factory=lambda: CacheStats(max_size=1000))
    _cleanup_task: asyncio.Task | None = PrivateAttr(default=None)
    _shutdown_event: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _last_memory_check: float = PrivateAttr(default=0.0)
    _eviction_strategies: dict[CacheStrategy, CacheEvictionStrategy] = PrivateAttr(
        default=None
    )
    _shutdown_initiated: bool = PrivateAttr(default=False)

    def __hash__(self):
        """Make CacheManager hashable for WeakSet."""
        return hash(id(self))

    def __eq__(self, other):
        """Equality comparison for hashable objects."""
        if not isinstance(other, CacheManager):
            return False
        return id(self) == id(other)

    def model_post_init(self, __context: Any) -> None:
        # Initialize eviction strategies mapping
        self._eviction_strategies = {
            CacheStrategy.LRU: LRUEvictionStrategy(),
            CacheStrategy.LFU: LFUEvictionStrategy(),
            CacheStrategy.FIFO: FIFOEvictionStrategy(),
        }

        # Initialize stats with current max_size
        self._stats = CacheStats(max_size=self.max_size)

        # Start background cleanup if enabled
        if self.enable_background_cleanup:
            self._start_background_cleanup()

        logger.info(
            "cache_manager_initialized",
            max_size=self.max_size,
            default_ttl=self.default_ttl,
            strategy=self.strategy.value,
            memory_threshold=self.memory_threshold,
            has_psutil=HAS_PSUTIL,
            background_cleanup_enabled=self.enable_background_cleanup,
        )

    def _generate_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """캐시 키 자동 생성."""
        # 인자들을 문자열로 변환하여 해시 생성
        args_str = str(args) + str(sorted(kwargs.items()))
        key_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
        return f"{func_name}_{key_hash}"

    def _cleanup_expired(self) -> int:
        """만료된 항목 정리."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]

        for key in expired_keys:
            del self._cache[key]

        if expired_keys and self.enable_stats:
            self._stats.evictions += len(expired_keys)

        return len(expired_keys)

    def _evict_if_needed(self) -> int:
        """필요시 항목 축출."""
        if len(self._cache) < self.max_size:
            return 0

        strategy = self._eviction_strategies[self.strategy]
        keys_to_evict = strategy.should_evict(self._cache, self.max_size)

        for key in keys_to_evict:
            if key in self._cache:
                del self._cache[key]

        if keys_to_evict and self.enable_stats:
            self._stats.evictions += len(keys_to_evict)

        return len(keys_to_evict)

    def get(self, key: str) -> any | None:
        """캐시에서 값 조회."""
        with self._lock:
            # 만료된 항목 정리
            self._cleanup_expired()

            if key not in self._cache:
                if self.enable_stats:
                    self._stats.misses += 1
                return None

            entry = self._cache[key]

            # 만료 확인
            if entry.is_expired():
                del self._cache[key]
                if self.enable_stats:
                    self._stats.misses += 1
                    self._stats.evictions += 1
                return None

            # 접근 정보 업데이트
            entry.touch()

            if self.enable_stats:
                self._stats.hits += 1

            logger.debug("cache_hit", key=key)
            return entry.value

    def set(
        self,
        key: str,
        value: any,
        ttl: int | None = None,
    ) -> None:
        """캐시에 값 저장."""
        with self._lock:
            # 만료된 항목 정리
            self._cleanup_expired()

            # TTL 결정
            effective_ttl = ttl if ttl is not None else self.default_ttl

            # 캐시 항목 생성
            entry = CacheEntry(
                value=value,
                timestamp=time.time(),
                ttl=effective_ttl,
            )

            self._cache[key] = entry

            # 크기 초과 시 축출 수행
            self._evict_if_needed()

            if self.enable_stats:
                self._stats.total_size = len(self._cache)

            logger.debug("cache_set", key=key, ttl=effective_ttl)

    def delete(self, key: str) -> bool:
        """캐시에서 항목 삭제."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if self.enable_stats:
                    self._stats.total_size = len(self._cache)
                logger.debug("cache_delete", key=key)
                return True
            return False

    def clear(self, pattern: str | None = None) -> int:
        """캐시 클리어."""
        with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                logger.info("cache_cleared_all", count=count)
            else:
                keys_to_delete = [key for key in self._cache if pattern in key]
                for key in keys_to_delete:
                    del self._cache[key]
                count = len(keys_to_delete)
                logger.info("cache_cleared_pattern", pattern=pattern, count=count)

            if self.enable_stats:
                self._stats.total_size = len(self._cache)

            return count

    def invalidate(self, keys: str | list[str]) -> int:
        """특정 키들 무효화."""
        if isinstance(keys, str):
            keys = [keys]

        count = 0
        for key in keys:
            if self.delete(key):
                count += 1

        return count

    def get_stats(self) -> CacheStats:
        """캐시 통계 조회."""
        with self._lock:
            self._stats.total_size = len(self._cache)
            return self._stats

    def get_size(self) -> int:
        """현재 캐시 크기 조회."""
        with self._lock:
            return len(self._cache)

    def get_keys(self, pattern: str | None = None) -> list[str]:
        """캐시 키 목록 조회."""
        with self._lock:
            if pattern is None:
                return list(self._cache.keys())
            return [key for key in self._cache if pattern in key]

    # Memory Management and Background Cleanup Methods

    def _start_background_cleanup(self) -> None:
        """백그라운드 정리 작업 시작."""
        try:
            # 현재 실행 중인 이벤트 루프 확인
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 실행 중인 이벤트 루프가 없는 경우
                logger.info(
                    "no_running_event_loop_disabling_background_cleanup",
                    cache_id=id(self),
                )
                self.enable_background_cleanup = False
                return

            # 이벤트 루프가 닫혔는지 확인
            if loop.is_closed():
                logger.warning(
                    "event_loop_is_closed_disabling_background_cleanup",
                    cache_id=id(self),
                )
                self.enable_background_cleanup = False
                return

            # 안전하게 태스크 생성
            self._cleanup_task = asyncio.create_task(
                self._background_cleanup_loop(), name=f"cache_cleanup_{id(self)}"
            )

            # 태스크 완료 시 콜백 추가
            def cleanup_callback(task):
                if task.cancelled():
                    logger.debug("background_cleanup_task_cancelled", cache_id=id(self))
                elif task.exception():
                    logger.error(
                        "background_cleanup_task_failed",
                        cache_id=id(self),
                        error=str(task.exception()),
                    )
                else:
                    logger.debug("background_cleanup_task_completed", cache_id=id(self))

            self._cleanup_task.add_done_callback(cleanup_callback)

            logger.debug(
                "background_cleanup_started",
                cache_id=id(self),
                interval=self.background_cleanup_interval,
                task_id=id(self._cleanup_task),
                loop_id=id(loop),
            )

        except RuntimeError as e:
            # 이벤트 루프 관련 RuntimeError 처리
            logger.warning(
                "event_loop_error_disabling_background_cleanup",
                cache_id=id(self),
                error=str(e),
                error_type=type(e).__name__,
            )
            self.enable_background_cleanup = False
        except Exception as e:
            # 기타 예상치 못한 오류 처리
            logger.error(
                "unexpected_error_during_background_cleanup_start",
                cache_id=id(self),
                error=str(e),
                error_type=type(e).__name__,
            )
            self.enable_background_cleanup = False

    async def _background_cleanup_loop(self) -> None:
        """백그라운드 정리 루프."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.background_cleanup_interval)

                # 메모리 압박 상태 확인
                if self._check_memory_pressure():
                    await self._aggressive_cleanup()
                else:
                    await self._routine_cleanup()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("background_cleanup_error", error=str(e))
                await asyncio.sleep(5)  # 오류 시 짧은 대기 후 재시도

    def _check_memory_pressure(self) -> bool:
        """시스템 메모리 압박 상태 확인."""
        if not HAS_PSUTIL:
            # psutil이 없으면 캐시 크기 기반으로만 판단
            return len(self._cache) > self.max_size * 0.9

        try:
            # 메모리 사용량 확인 (최대 5초마다만)
            current_time = time.time()
            if current_time - self._last_memory_check < 5.0:
                return False

            self._last_memory_check = current_time
            memory = psutil.virtual_memory()
            memory_usage = memory.percent / 100

            is_pressure = memory_usage > self.memory_threshold

            if is_pressure and self.enable_stats:
                self._stats.memory_pressure_triggers += 1

            logger.debug(
                "memory_pressure_check",
                memory_usage_percent=round(memory_usage * 100, 1),
                threshold_percent=round(self.memory_threshold * 100, 1),
                is_pressure=is_pressure,
            )

            return is_pressure

        except Exception as e:
            logger.warning("memory_pressure_check_failed", error=str(e))
            return False

    async def _routine_cleanup(self) -> None:
        """일상적인 정리 작업."""
        with self._lock:
            expired_count = self._cleanup_expired()
            if expired_count > 0:
                logger.debug(
                    "routine_cleanup_completed",
                    expired_items=expired_count,
                    cache_size=len(self._cache),
                )

    async def _aggressive_cleanup(self) -> None:
        """적극적인 정리 작업 (메모리 압박 시)."""
        with self._lock:
            # 1단계: 만료된 항목 정리
            expired_count = self._cleanup_expired()

            # 2단계: 여전히 메모리 압박이 있다면 LRU 기반 축출 수행
            if self._check_memory_pressure():
                evicted_count = self._evict_if_needed()

                # 3단계: 극심한 압박 시 추가 축출 (최대 25% 축출)
                target_size = max(self.max_size // 2, len(self._cache) * 3 // 4)
                while len(self._cache) > target_size:
                    additional_evicted = self._evict_if_needed()
                    if additional_evicted == 0:
                        break
                    evicted_count += additional_evicted
            else:
                evicted_count = 0

            if self.enable_stats:
                self._stats.memory_cleanups += 1
                self._stats.last_memory_cleanup = time.time()

            logger.info(
                "aggressive_cleanup_completed",
                expired_items=expired_count,
                evicted_items=evicted_count,
                final_cache_size=len(self._cache),
                memory_pressure=self._check_memory_pressure(),
            )

    async def cleanup(self) -> None:
        """캐시 매니저 정리 (graceful shutdown)."""
        # 중복 호출 방지
        if self._shutdown_initiated:
            logger.debug("cache_manager_cleanup_already_initiated")
            return

        self._shutdown_initiated = True

        # shutdown 이벤트 설정
        self._shutdown_event.set()

        # 백그라운드 작업 정리
        if self._cleanup_task and not self._cleanup_task.done():
            logger.debug("cancelling_background_cleanup_task")
            self._cleanup_task.cancel()

            # 태스크가 완전히 종료될 때까지 대기
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("background_cleanup_task_cancellation_timeout")
            except asyncio.CancelledError:
                pass  # 정상적으로 취소됨
            except Exception as e:
                logger.error("background_cleanup_task_cancellation_error", error=str(e))

            self._cleanup_task = None

        # 캐시 클리어
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            logger.debug("cache_cleared_on_cleanup", cleared_items=cache_size)

        logger.info(
            "cache_manager_cleanup_completed",
            final_stats=self.get_stats() if self.enable_stats else None,
        )

    def get_memory_stats(self) -> dict[str, any]:
        """메모리 관련 통계 정보 조회."""
        stats = {
            "memory_threshold": self.memory_threshold,
            "background_cleanup_enabled": self.enable_background_cleanup,
            "has_psutil": HAS_PSUTIL,
            "last_memory_check": self._last_memory_check,
        }

        if HAS_PSUTIL:
            try:
                memory = psutil.virtual_memory()
                stats.update(
                    {
                        "system_memory_usage_percent": round(memory.percent, 1),
                        "system_memory_available_gb": round(
                            memory.available / (1024**3), 2
                        ),
                        "memory_pressure_detected": memory.percent / 100
                        > self.memory_threshold,
                    }
                )
            except Exception as e:
                stats["memory_check_error"] = str(e)

        return stats

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료 - 자동 정리."""
        await self.cleanup()
        return False


def cache_result(
    cache_manager: CacheManager,
    ttl: int | None = None,
    key_func: Callable[..., str] | None = None,
    cache_none: bool = False,
) -> Callable[[F], F]:
    """
    결과 캐싱 데코레이터.

    Args:
        cache_manager: 사용할 캐시 매니저
        ttl: 캐시 유효 시간 (초)
        key_func: 커스텀 캐시 키 생성 함수
        cache_none: None 값도 캐시할지 여부

    Returns:
        데코레이터 함수

    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 캐시 키 생성
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache_manager._generate_key(func.__name__, args, kwargs)

            # 캐시 조회
            cached_value = cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 함수 실행
            result = await func(*args, **kwargs)

            # 결과 캐싱 (None 값 처리)
            if result is not None or cache_none:
                cache_manager.set(cache_key, result, ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 캐시 키 생성
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = cache_manager._generate_key(func.__name__, args, kwargs)

            # 캐시 조회
            cached_value = cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 함수 실행
            result = func(*args, **kwargs)

            # 결과 캐싱 (None 값 처리)
            if result is not None or cache_none:
                cache_manager.set(cache_key, result, ttl)

            return result

        # 비동기 함수인지 확인
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# 편의를 위한 전역 캐시 매니저 인스턴스
default_cache_manager = CacheManager()


def cached(
    ttl: int | None = None,
    key_func: Callable[..., str] | None = None,
    cache_none: bool = False,
    manager: CacheManager | None = None,
) -> Callable[[F], F]:
    """
    편의 데코레이터 - 기본 캐시 매니저 사용.

    Args:
        ttl: 캐시 유효 시간 (초)
        key_func: 커스텀 캐시 키 생성 함수
        cache_none: None 값도 캐시할지 여부
        manager: 사용할 캐시 매니저 (기본값: default_cache_manager)

    Returns:
        데코레이터 함수

    """
    cache_mgr = manager or default_cache_manager
    return cache_result(cache_mgr, ttl, key_func, cache_none)


# 타입 힌트를 위한 별칭
CacheKeyGenerator = Callable[..., str]
CacheDecorator = Callable[[F], F]
