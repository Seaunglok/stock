"""
Rate Limiting implementation for MCP servers.

This module provides various rate limiting algorithms including:
- Token Bucket Algorithm
- Sliding Window Algorithm
- Fixed Window Algorithm

Supports both in-memory and Redis backends for distributed environments.
"""

import asyncio
import hashlib
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RateLimitAlgorithm(str, Enum):
    """Rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


class RateLimitExceeded(Exception):
    """Rate limit exceeded exception."""

    def __init__(
        self, message: str, retry_after: float, limit: int, remaining: int = 0
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    # Basic settings
    requests_per_second: float = 10.0
    burst_size: int = 20
    window_size: int = 60  # seconds

    # Algorithm selection
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET

    # Key generation
    key_func: Callable[..., str] | None = None

    # Response settings
    include_headers: bool = True
    error_message_template: str = (
        "Rate limit exceeded. Try again in {retry_after:.1f} seconds"
    )

    # Backend settings
    backend: str = "memory"  # "memory" or "redis"
    redis_url: str | None = None
    redis_key_prefix: str = "rate_limit:"

    # Cleanup settings
    cleanup_interval: int = 300  # seconds
    max_keys: int = 10000


class RateLimitBackend(Protocol):
    """Protocol for rate limiting backends."""

    async def get_bucket_state(self, key: str) -> tuple[float, float]:
        """Get current bucket state (tokens, last_refill)."""
        ...

    async def update_bucket_state(
        self, key: str, tokens: float, last_refill: float
    ) -> None:
        """Update bucket state."""
        ...

    async def get_window_requests(self, key: str, window_start: float) -> list[float]:
        """Get requests within window."""
        ...

    async def add_request(
        self, key: str, timestamp: float, ttl: int | None = None
    ) -> None:
        """Add request timestamp."""
        ...

    async def cleanup_expired(self) -> int:
        """Cleanup expired entries."""
        ...


class MemoryBackend(BaseModel):
    """In-memory rate limiting backend."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._buckets: dict[str, tuple[float, float]] = {}
        self._windows: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    async def get_bucket_state(self, key: str) -> tuple[float, float]:
        """Get current bucket state."""
        async with self._lock:
            return self._buckets.get(key, (self.config.burst_size, time.time()))

    async def update_bucket_state(
        self, key: str, tokens: float, last_refill: float
    ) -> None:
        """Update bucket state."""
        async with self._lock:
            self._buckets[key] = (tokens, last_refill)
            await self._maybe_cleanup()

    async def get_window_requests(self, key: str, window_start: float) -> list[float]:
        """Get requests within window."""
        async with self._lock:
            if key not in self._windows:
                return []

            # Remove old requests
            window = self._windows[key]
            while window and window[0] <= window_start:
                window.popleft()

            return list(window)

    async def add_request(
        self, key: str, timestamp: float, ttl: int | None = None
    ) -> None:
        """Add request timestamp."""
        async with self._lock:
            self._windows[key].append(timestamp)
            await self._maybe_cleanup()

    async def cleanup_expired(self) -> int:
        """Cleanup expired entries."""
        current_time = time.time()
        cleanup_threshold = current_time - self.config.window_size
        cleaned = 0

        async with self._lock:
            # Cleanup buckets
            expired_buckets = [
                key
                for key, (_, last_refill) in self._buckets.items()
                if current_time - last_refill > self.config.window_size
            ]
            for key in expired_buckets:
                del self._buckets[key]
                cleaned += 1

            # Cleanup windows
            for key, window in list(self._windows.items()):
                # Remove old requests
                while window and window[0] <= cleanup_threshold:
                    window.popleft()

                # Remove empty windows
                if not window:
                    del self._windows[key]
                    cleaned += 1

            self._last_cleanup = current_time

        return cleaned

    async def _maybe_cleanup(self) -> None:
        """Perform cleanup if needed."""
        current_time = time.time()
        if (
            current_time - self._last_cleanup > self.config.cleanup_interval
            or len(self._buckets) + len(self._windows) > self.config.max_keys
        ):
            await self.cleanup_expired()


class RedisBackend(BaseModel):
    """Redis-based rate limiting backend."""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._redis = None
        self._redis_url = config.redis_url
        self._key_prefix = config.redis_key_prefix

    async def _get_redis(self):
        """Get Redis connection."""
        if self._redis is None:
            try:
                import redis.asyncio as redis

                self._redis = redis.from_url(self._redis_url)
            except ImportError as err:
                raise ImportError("redis package required for Redis backend") from err
        return self._redis

    def _make_key(self, key: str, suffix: str = "") -> str:
        """Make Redis key."""
        return f"{self._key_prefix}{key}{suffix}"

    async def get_bucket_state(self, key: str) -> tuple[float, float]:
        """Get current bucket state."""
        redis = await self._get_redis()
        bucket_key = self._make_key(key, ":bucket")

        data = await redis.hmget(bucket_key, "tokens", "last_refill")
        if data[0] is None:
            return (self.config.burst_size, time.time())

        return (float(data[0]), float(data[1]))

    async def update_bucket_state(
        self, key: str, tokens: float, last_refill: float
    ) -> None:
        """Update bucket state."""
        redis = await self._get_redis()
        bucket_key = self._make_key(key, ":bucket")

        pipe = redis.pipeline()
        pipe.hset(
            bucket_key, mapping={"tokens": str(tokens), "last_refill": str(last_refill)}
        )
        pipe.expire(bucket_key, self.config.window_size * 2)
        await pipe.execute()

    async def get_window_requests(self, key: str, window_start: float) -> list[float]:
        """Get requests within window."""
        redis = await self._get_redis()
        window_key = self._make_key(key, ":window")

        # Remove old requests and get current ones
        pipe = redis.pipeline()
        pipe.zremrangebyscore(window_key, 0, window_start)
        pipe.zrange(window_key, 0, -1)
        pipe.expire(window_key, self.config.window_size * 2)

        results = await pipe.execute()
        return [float(ts) for ts in results[1]]

    async def add_request(
        self, key: str, timestamp: float, ttl: int | None = None
    ) -> None:
        """Add request timestamp."""
        redis = await self._get_redis()
        window_key = self._make_key(key, ":window")

        pipe = redis.pipeline()
        pipe.zadd(window_key, {str(timestamp): timestamp})
        if ttl:
            pipe.expire(window_key, ttl)
        else:
            pipe.expire(window_key, self.config.window_size * 2)
        await pipe.execute()

    async def cleanup_expired(self) -> int:
        """Cleanup expired entries."""
        # Redis handles TTL automatically
        return 0


class TokenBucketLimiter(BaseModel):
    """Token bucket rate limiter implementation."""

    def __init__(self, config: RateLimitConfig, backend: RateLimitBackend):
        self.config = config
        self.backend = backend

    async def is_allowed(self, key: str) -> tuple[bool, dict[str, any]]:
        """Check if request is allowed."""
        current_time = time.time()

        # Get current bucket state
        tokens, last_refill = await self.backend.get_bucket_state(key)

        # Calculate new token count
        time_passed = current_time - last_refill
        tokens_to_add = time_passed * self.config.requests_per_second
        tokens = min(self.config.burst_size, tokens + tokens_to_add)

        # Check if request can be served
        if tokens >= 1.0:
            tokens -= 1.0
            await self.backend.update_bucket_state(key, tokens, current_time)

            return True, {
                "limit": int(self.config.burst_size),
                "remaining": int(tokens),
                "reset": current_time
                + (self.config.burst_size - tokens) / self.config.requests_per_second,
                "retry_after": 0,
            }
        else:
            # Calculate retry after
            retry_after = (1.0 - tokens) / self.config.requests_per_second

            return False, {
                "limit": int(self.config.burst_size),
                "remaining": 0,
                "reset": current_time + retry_after,
                "retry_after": retry_after,
            }


class SlidingWindowLimiter(BaseModel):
    """Sliding window rate limiter implementation."""

    def __init__(self, config: RateLimitConfig, backend: RateLimitBackend):
        self.config = config
        self.backend = backend

    async def is_allowed(self, key: str) -> tuple[bool, dict[str, any]]:
        """Check if request is allowed."""
        current_time = time.time()
        window_start = current_time - self.config.window_size

        # Get current requests in window
        requests = await self.backend.get_window_requests(key, window_start)
        request_count = len(requests)

        # Calculate limit for the window
        limit = int(self.config.requests_per_second * self.config.window_size)

        if request_count < limit:
            # Add current request
            await self.backend.add_request(
                key, current_time, self.config.window_size * 2
            )

            return True, {
                "limit": limit,
                "remaining": limit - request_count - 1,
                "reset": current_time + self.config.window_size,
                "retry_after": 0,
            }
        else:
            # Calculate retry after (time until oldest request expires)
            retry_after = (
                requests[0] + self.config.window_size - current_time
                if requests
                else 1.0
            )
            retry_after = max(0.1, retry_after)  # Minimum 100ms

            return False, {
                "limit": limit,
                "remaining": 0,
                "reset": current_time + retry_after,
                "retry_after": retry_after,
            }


class FixedWindowLimiter(BaseModel):
    """Fixed window rate limiter implementation."""

    def __init__(self, config: RateLimitConfig, backend: RateLimitBackend):
        self.config = config
        self.backend = backend

    async def is_allowed(self, key: str) -> tuple[bool, dict[str, any]]:
        """Check if request is allowed."""
        current_time = time.time()
        window_start = (
            int(current_time) // self.config.window_size * self.config.window_size
        )
        window_key = f"{key}:window:{window_start}"

        # Get requests in current window
        requests = await self.backend.get_window_requests(window_key, window_start)
        request_count = len(requests)

        # Calculate limit for the window
        limit = int(self.config.requests_per_second * self.config.window_size)

        if request_count < limit:
            # Add current request
            await self.backend.add_request(
                window_key, current_time, self.config.window_size * 2
            )

            return True, {
                "limit": limit,
                "remaining": limit - request_count - 1,
                "reset": window_start + self.config.window_size,
                "retry_after": 0,
            }
        else:
            # Calculate retry after (time until next window)
            retry_after = window_start + self.config.window_size - current_time

            return False, {
                "limit": limit,
                "remaining": 0,
                "reset": window_start + self.config.window_size,
                "retry_after": retry_after,
            }


class RateLimiter(BaseModel):
    """Main rate limiter class supporting multiple algorithms and backends."""

    def __init__(self, config: RateLimitConfig):
        self.config = config

        # Initialize backend
        if config.backend == "redis":
            self.backend = RedisBackend(config)
        else:
            self.backend = MemoryBackend(config)

        # Initialize limiter based on algorithm
        if config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            self.limiter = TokenBucketLimiter(config, self.backend)
        elif config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            self.limiter = SlidingWindowLimiter(config, self.backend)
        elif config.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            self.limiter = FixedWindowLimiter(config, self.backend)
        else:
            raise ValueError(f"Unsupported algorithm: {config.algorithm}")

        # Start cleanup task for memory backend
        if isinstance(self.backend, MemoryBackend):
            self._cleanup_task = None
            self._start_cleanup_task()

    def _start_cleanup_task(self) -> None:
        """Start periodic cleanup task."""

        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(self.config.cleanup_interval)
                    cleaned = await self.backend.cleanup_expired()
                    if cleaned > 0:
                        logger.debug(f"Cleaned up {cleaned} expired rate limit entries")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in rate limit cleanup: {e}")

        try:
            # 현재 실행 중인 이벤트 루프 확인
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 실행 중인 이벤트 루프가 없는 경우 정리 작업 비활성화
                logger.info("no_running_event_loop_skipping_cleanup_task")
                return

            # 이벤트 루프가 닫혔는지 확인
            if loop.is_closed():
                logger.warning("event_loop_is_closed_skipping_cleanup_task")
                return

            # 안전하게 태스크 생성
            self._cleanup_task = asyncio.create_task(
                cleanup_loop(), name=f"rate_limit_cleanup_{id(self)}"
            )

            logger.debug(
                "rate_limit_cleanup_task_started",
                cleanup_interval=self.config.cleanup_interval,
                task_id=id(self._cleanup_task),
                loop_id=id(loop),
            )

        except RuntimeError as e:
            # 이벤트 루프 관련 RuntimeError 처리
            logger.warning(
                "event_loop_error_skipping_cleanup_task",
                error=str(e),
                error_type=type(e).__name__,
            )
        except Exception as e:
            # 기타 예상치 못한 오류 처리
            logger.error(
                "unexpected_error_during_cleanup_task_start",
                error=str(e),
                error_type=type(e).__name__,
            )

    def generate_key(self, *args, **kwargs) -> str:
        """Generate rate limit key."""
        if self.config.key_func:
            return self.config.key_func(*args, **kwargs)

        # Default key generation based on arguments
        key_parts = []
        for arg in args:
            if hasattr(arg, "remote_addr"):  # Request object
                key_parts.append(arg.remote_addr)
            elif hasattr(arg, "client"):  # FastAPI Request
                key_parts.append(arg.client.host if arg.client else "unknown")
            else:
                key_parts.append(str(arg))

        for k, v in kwargs.items():
            key_parts.append(f"{k}:{v}")

        if not key_parts:
            key_parts.append("default")

        # Create hash to ensure consistent key length
        key_str = ":".join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()[:16]

    async def check_rate_limit(self, *args, **kwargs) -> dict[str, any]:
        """Check rate limit for given arguments."""
        key = self.generate_key(*args, **kwargs)
        allowed, info = await self.limiter.is_allowed(key)

        if not allowed:
            raise RateLimitExceeded(
                message=self.config.error_message_template.format(
                    retry_after=info["retry_after"]
                ),
                retry_after=info["retry_after"],
                limit=info["limit"],
                remaining=info["remaining"],
            )

        return info

    async def is_allowed(self, *args, **kwargs) -> tuple[bool, dict[str, any]]:
        """Check if request is allowed without raising exception."""
        key = self.generate_key(*args, **kwargs)
        return await self.limiter.is_allowed(key)

    @asynccontextmanager
    async def acquire(self, *args, **kwargs):
        """Context manager for rate limiting."""
        info = await self.check_rate_limit(*args, **kwargs)
        try:
            yield info
        finally:
            pass  # No cleanup needed for current implementation

    def decorator(self, *decorator_args, **decorator_kwargs):
        """Decorator for rate limiting functions."""

        def outer_decorator(func):
            async def wrapper(*args, **kwargs):
                # Combine decorator and function arguments for key generation
                all_args = decorator_args + args
                all_kwargs = {**decorator_kwargs, **kwargs}

                info = await self.check_rate_limit(*all_args, **all_kwargs)
                result = await func(*args, **kwargs)

                # Add rate limit info to response if it's a dict
                if isinstance(result, dict) and self.config.include_headers:
                    result["_rate_limit"] = info

                return result

            return wrapper

        return outer_decorator

    async def get_stats(self) -> dict[str, any]:
        """Get rate limiter statistics."""
        stats = {
            "algorithm": self.config.algorithm.value,
            "backend": self.config.backend,
            "requests_per_second": self.config.requests_per_second,
            "burst_size": self.config.burst_size,
            "window_size": self.config.window_size,
        }

        if isinstance(self.backend, MemoryBackend):
            async with self.backend._lock:
                stats.update(
                    {
                        "active_buckets": len(self.backend._buckets),
                        "active_windows": len(self.backend._windows),
                        "last_cleanup": self.backend._last_cleanup,
                    }
                )

        return stats

    async def reset_key(self, key: str) -> bool:
        """Reset rate limit for a specific key."""
        try:
            if isinstance(self.backend, MemoryBackend):
                async with self.backend._lock:
                    if key in self.backend._buckets:
                        del self.backend._buckets[key]
                    if key in self.backend._windows:
                        del self.backend._windows[key]
                return True
            elif isinstance(self.backend, RedisBackend):
                redis = await self.backend._get_redis()
                bucket_key = self.backend._make_key(key, ":bucket")
                window_key = self.backend._make_key(key, ":window")

                pipe = redis.pipeline()
                pipe.delete(bucket_key)
                pipe.delete(window_key)
                await pipe.execute()
                return True
        except Exception as e:
            logger.error(f"Error resetting rate limit key {key}: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task

        if isinstance(self.backend, RedisBackend) and self.backend._redis:
            await self.backend._redis.close()


# Convenience functions for common use cases


def create_token_bucket_limiter(
    requests_per_second: float = 10.0,
    burst_size: int = 20,
    key_func: Callable | None = None,
    backend: str = "memory",
    redis_url: str | None = None,
) -> RateLimiter:
    """Create a token bucket rate limiter."""
    config = RateLimitConfig(
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        requests_per_second=requests_per_second,
        burst_size=burst_size,
        key_func=key_func,
        backend=backend,
        redis_url=redis_url,
    )
    return RateLimiter(config)


def create_sliding_window_limiter(
    requests_per_second: float = 10.0,
    window_size: int = 60,
    key_func: Callable | None = None,
    backend: str = "memory",
    redis_url: str | None = None,
) -> RateLimiter:
    """Create a sliding window rate limiter."""
    config = RateLimitConfig(
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        requests_per_second=requests_per_second,
        window_size=window_size,
        key_func=key_func,
        backend=backend,
        redis_url=redis_url,
    )
    return RateLimiter(config)


def create_fixed_window_limiter(
    requests_per_second: float = 10.0,
    window_size: int = 60,
    key_func: Callable | None = None,
    backend: str = "memory",
    redis_url: str | None = None,
) -> RateLimiter:
    """Create a fixed window rate limiter."""
    config = RateLimitConfig(
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
        requests_per_second=requests_per_second,
        window_size=window_size,
        key_func=key_func,
        backend=backend,
        redis_url=redis_url,
    )
    return RateLimiter(config)


# IP-based key function
def ip_key_func(*args, **kwargs) -> str:
    """Generate key based on IP address."""
    for arg in args:
        if hasattr(arg, "remote_addr"):
            return f"ip:{arg.remote_addr}"
        elif hasattr(arg, "client") and arg.client:
            return f"ip:{arg.client.host}"
    return "ip:unknown"


# User-based key function
def user_key_func(*args, **kwargs) -> str:
    """Generate key based on user ID."""
    user_id = kwargs.get("user_id")
    if user_id:
        return f"user:{user_id}"

    for arg in args:
        if hasattr(arg, "user") and hasattr(arg.user, "id"):
            return f"user:{arg.user.id}"
        elif isinstance(arg, dict) and "user_id" in arg:
            return f"user:{arg['user_id']}"

    return "user:anonymous"


# Method-based key function
def method_key_func(*args, **kwargs) -> str:
    """Generate key based on method name."""
    method = kwargs.get("method", "unknown")
    user_id = kwargs.get("user_id", "anonymous")
    return f"method:{method}:user:{user_id}"
