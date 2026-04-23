"""
키움증권 인증 관리자

OAuth 토큰 관리를 중앙화하고 Redis를 활용한 토큰 캐싱을 제공합니다.
여러 MCP 서버가 동일한 토큰을 공유할 수 있도록 합니다.

Beginner notes:
    - Redis optional: If Redis is unavailable, an in-process memory cache is
      used automatically. This is fine for local dev but not for multi-process
      deployments.
    - Token shape: Kiwoom token endpoint returns ``token`` (not access_token)
      and optionally ``expires_dt``. We normalize to ``TokenInfo``.
    - Cache key: App key is SHA-256 hashed to avoid leaking secrets in Redis.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

# Redis는 선택적 의존성
try:
    import redis
    from redis import asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    aioredis = None
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class TokenInfo(BaseModel):
    """토큰 정보 모델"""

    access_token: str
    expires_at: datetime
    token_type: str = "Bearer"
    app_key: str
    is_paper_mode: bool

    @property
    def is_expired(self) -> bool:
        """토큰 만료 여부 확인 (5분 여유시간 포함)"""
        return datetime.now() >= (self.expires_at - timedelta(minutes=5))

    @property
    def expires_in_seconds(self) -> int:
        """토큰 만료까지 남은 시간 (초)"""
        return max(0, int((self.expires_at - datetime.now()).total_seconds()))


class AuthError(Exception):
    """인증 관련 오류"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


# 호환성을 위한 별칭
KiwoomOAuthError = AuthError


class KiwoomAuthManager:
    """키움증권 OAuth 토큰 관리자"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        cache_prefix: str = "kiwoom_auth:",
        default_timeout: float = 30.0,
    ):
        """
        인증 관리자 초기화

        Args:
            redis_url: Redis 연결 URL (선택적)
            cache_prefix: Redis 키 접두사
            default_timeout: HTTP 요청 타임아웃
        """
        self.cache_prefix = cache_prefix
        self.default_timeout = default_timeout

        # Redis 클라이언트 (선택적)
        self.redis_client = None
        if REDIS_AVAILABLE and redis_url:
            try:
                self.redis_client = redis.from_url(
                    redis_url, decode_responses=True, health_check_interval=30
                )
                logger.info(f"Redis 클라이언트 초기화 완료: {redis_url}")
            except Exception as e:
                logger.warning(f"Redis 연결 실패: {e}, 메모리 캐시로 대체")
                self.redis_client = None

        # 메모리 캐시 (Redis가 없을 경우)
        self._memory_cache: Dict[str, TokenInfo] = {}

        # HTTP 클라이언트
        self._http_client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        self._http_client = httpx.AsyncClient(
            timeout=self.default_timeout,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

        # Redis 연결 확인
        if self.redis_client:
            try:
                await self.redis_client.ping()
                logger.info("Redis 연결 확인 완료")
            except Exception as e:
                logger.warning(f"Redis 연결 실패: {e}")
                self.redis_client = None

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self.redis_client:
            await self.redis_client.aclose()

    def _generate_cache_key(self, app_key: str, is_paper_mode: bool) -> str:
        """캐시 키 생성"""
        # 보안을 위해 app_key를 해싱
        key_hash = hashlib.sha256(app_key.encode()).hexdigest()[:16]
        mode = "paper" if is_paper_mode else "real"
        return f"{self.cache_prefix}token:{key_hash}:{mode}"

    async def _get_from_cache(self, cache_key: str) -> Optional[TokenInfo]:
        """캐시에서 토큰 정보 조회"""
        try:
            if self.redis_client:
                # Redis 캐시 조회
                data = await self.redis_client.get(cache_key)
                if data:
                    token_data = json.loads(data)
                    token_info = TokenInfo(**token_data)

                    if not token_info.is_expired:
                        return token_info
                    else:
                        # 만료된 토큰 삭제
                        await self.redis_client.delete(cache_key)

            else:
                # 메모리 캐시 조회
                token_info = self._memory_cache.get(cache_key)
                if token_info and not token_info.is_expired:
                    return token_info
                elif token_info:
                    # 만료된 토큰 삭제
                    del self._memory_cache[cache_key]

        except Exception as e:
            logger.warning(f"캐시 조회 실패: {e}")

        return None

    async def _save_to_cache(self, cache_key: str, token_info: TokenInfo) -> None:
        """캐시에 토큰 정보 저장"""
        try:
            if self.redis_client:
                # Redis 캐시 저장
                token_data = token_info.model_dump()
                # datetime을 문자열로 변환
                token_data["expires_at"] = token_info.expires_at.isoformat()

                await self.redis_client.set(
                    cache_key, json.dumps(token_data), ex=token_info.expires_in_seconds
                )
                logger.debug(f"토큰 Redis 캐시 저장: {cache_key}")

            else:
                # 메모리 캐시 저장
                self._memory_cache[cache_key] = token_info
                logger.debug(f"토큰 메모리 캐시 저장: {cache_key}")

        except Exception as e:
            logger.warning(f"캐시 저장 실패: {e}")

    async def get_token(
        self,
        app_key: str,
        app_secret: str,
        is_paper_mode: bool = True,
        force_refresh: bool = False,
    ) -> TokenInfo:
        """
        OAuth 토큰 획득 (캐시된 토큰 우선 사용)

        Args:
            app_key: 키움 앱 키
            app_secret: 키움 앱 시크릿
            is_paper_mode: 모의투자 모드
            force_refresh: 강제 갱신 여부

        Returns:
            TokenInfo: 토큰 정보

        Raises:
            AuthError: 인증 실패 시
        """
        cache_key = self._generate_cache_key(app_key, is_paper_mode)

        # 캐시에서 유효한 토큰 조회 (강제 갱신이 아닌 경우)
        if not force_refresh:
            cached_token = await self._get_from_cache(cache_key)
            if cached_token:
                logger.debug(f"캐시된 토큰 사용: {cache_key}")
                return cached_token

        # 새 토큰 발급
        logger.info(f"새 토큰 발급 요청: paper_mode={is_paper_mode}")
        token_info = await self._request_new_token(app_key, app_secret, is_paper_mode)

        # 캐시에 저장
        await self._save_to_cache(cache_key, token_info)

        return token_info

    async def _request_new_token(
        self, app_key: str, app_secret: str, is_paper_mode: bool
    ) -> TokenInfo:
        """키움 API에서 새 토큰 요청"""
        if not self._http_client:
            raise AuthError(
                "HTTP 클라이언트가 초기화되지 않았습니다", "CLIENT_NOT_INITIALIZED"
            )

        # API 도메인 선택
        api_domain = "mockapi.kiwoom.com" if is_paper_mode else "api.kiwoom.com"
        token_url = f"https://{api_domain}/oauth2/token"

        headers = {
            "Content-Type": "application/json",  #  검증된 Content-Type
            "User-Agent": "KiwoomAuthManager/1.0",
        }

        #  검증된 성공 방식: appkey/secretkey 필드명
        data = {
            "grant_type": "client_credentials",
            "appkey": app_key,  #  검증된 필드명
            "secretkey": app_secret,  #  검증된 필드명 (appsecret 아님)
        }

        try:
            response = await self._http_client.post(
                token_url, headers=headers, json=data
            )
            response.raise_for_status()

            token_data = response.json()

            # 키움 API 응답 구조 확인
            return_code = token_data.get("return_code")
            return_msg = token_data.get("return_msg", "")

            if return_code == 0:
                #  성공: 키움은 'token' 필드 사용 (access_token 아님)
                access_token = token_data.get("token")
                if not access_token:
                    raise AuthError(
                        "토큰 응답에 token 필드가 없습니다",
                        "MISSING_TOKEN_FIELD",
                        {"response": token_data},
                    )

                # 만료 시간 계산
                expires_dt = token_data.get("expires_dt")
                if expires_dt:
                    # 키움 형식: "20250815002830"
                    try:
                        expires_at = datetime.strptime(expires_dt, "%Y%m%d%H%M%S")
                        logger.info(f"토큰 발급 성공, 만료일: {expires_at}")
                    except ValueError:
                        # 파싱 실패시 24시간 후로 설정
                        expires_at = datetime.now() + timedelta(hours=24)
                        logger.warning(
                            f"만료일 파싱 실패, 24시간 후로 설정: {expires_dt}"
                        )
                else:
                    # 만료일 정보 없으면 24시간 후로 설정
                    expires_at = datetime.now() + timedelta(hours=24)
                    logger.warning("만료일 정보 없음, 24시간 후로 설정")

                token_info = TokenInfo(
                    access_token=access_token,
                    expires_at=expires_at,
                    token_type=token_data.get("token_type", "Bearer"),
                    app_key=app_key,
                    is_paper_mode=is_paper_mode,
                )

                logger.info(f" 토큰 발급 성공: {return_msg}")
                return token_info
            else:
                error_msg = (
                    f"키움 API 토큰 발급 오류 (코드: {return_code}): {return_msg}"
                )
                logger.error(error_msg)
                raise AuthError(
                    error_msg,
                    "API_ERROR",
                    {"return_code": return_code, "return_msg": return_msg},
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"키움 토큰 발급 실패 (HTTP {e.response.status_code})"

            # 상세 오류 정보 파싱
            try:
                error_detail = e.response.json()
                if "return_msg" in error_detail:
                    error_msg += f": {error_detail['return_msg']}"
            except Exception:
                pass

            logger.error(error_msg)
            raise AuthError(error_msg, f"HTTP_{e.response.status_code}") from e

        except httpx.RequestError as e:
            error_msg = f"키움 API 연결 실패: {e}"
            logger.error(error_msg)
            raise AuthError(error_msg, "CONNECTION_ERROR") from e

        except Exception as e:
            error_msg = f"토큰 요청 중 예상치 못한 오류: {e}"
            logger.error(error_msg)
            raise AuthError(error_msg, "UNKNOWN_ERROR") from e

    async def refresh_token(
        self, app_key: str, app_secret: str, is_paper_mode: bool = True
    ) -> TokenInfo:
        """토큰 강제 갱신"""
        return await self.get_token(
            app_key, app_secret, is_paper_mode, force_refresh=True
        )

    async def revoke_token(self, app_key: str, is_paper_mode: bool = True) -> None:
        """토큰 폐기 (캐시에서 제거)"""
        cache_key = self._generate_cache_key(app_key, is_paper_mode)

        try:
            if self.redis_client:
                await self.redis_client.delete(cache_key)
                logger.info(f"Redis에서 토큰 삭제: {cache_key}")
            else:
                self._memory_cache.pop(cache_key, None)
                logger.info(f"메모리에서 토큰 삭제: {cache_key}")
        except Exception as e:
            logger.warning(f"토큰 삭제 실패: {e}")

    async def get_cached_tokens_info(self) -> Dict[str, Any]:
        """캐시된 토큰 정보 조회 (디버깅/모니터링 용도)"""
        info = {
            "cache_type": "redis" if self.redis_client else "memory",
            "cached_tokens": [],
        }

        try:
            if self.redis_client:
                # Redis에서 토큰 키 패턴 조회
                pattern = f"{self.cache_prefix}token:*"
                keys = await self.redis_client.keys(pattern)

                for key in keys:
                    ttl = await self.redis_client.ttl(key)
                    info["cached_tokens"].append({"cache_key": key, "ttl_seconds": ttl})
            else:
                # 메모리 캐시 정보
                for cache_key, token_info in self._memory_cache.items():
                    info["cached_tokens"].append(
                        {
                            "cache_key": cache_key,
                            "expires_at": token_info.expires_at.isoformat(),
                            "is_expired": token_info.is_expired,
                            "paper_mode": token_info.is_paper_mode,
                        }
                    )

        except Exception as e:
            logger.warning(f"캐시 정보 조회 실패: {e}")
            info["error"] = str(e)

        return info

    async def cleanup_expired_tokens(self) -> int:
        """만료된 토큰 정리 (메모리 캐시만 해당)"""
        if self.redis_client:
            # Redis는 TTL로 자동 정리됨
            return 0

        expired_keys = [
            key
            for key, token_info in self._memory_cache.items()
            if token_info.is_expired
        ]

        for key in expired_keys:
            del self._memory_cache[key]

        if expired_keys:
            logger.info(f"만료된 토큰 {len(expired_keys)}개 정리 완료")

        return len(expired_keys)


# =============================================================================
# Wrapper Functions for Easy Integration
# =============================================================================

# 글로벌 인증 매니저 (싱글톤 패턴)
_global_auth_manager: Optional[KiwoomAuthManager] = None


def get_kiwoom_auth(redis_url: Optional[str] = None) -> KiwoomAuthManager:
    """
    글로벌 키움 인증 매니저 반환 (싱글톤 패턴)

    Args:
        redis_url: Redis 연결 URL (첫 번째 호출 시만 적용)

    Returns:
        KiwoomAuthManager: 인증 매니저 인스턴스
    """
    global _global_auth_manager

    if _global_auth_manager is None:
        _global_auth_manager = KiwoomAuthManager(redis_url=redis_url)
        logger.info("글로벌 키움 인증 매니저 생성 완료")

    return _global_auth_manager


async def make_kiwoom_api_call(
    method: str,
    endpoint: str,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    is_paper_mode: bool = True,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    키움 API 호출 래퍼 함수

    Args:
        method: HTTP 메소드 (GET, POST, etc.)
        endpoint: API 엔드포인트
        app_key: 키움 앱 키 (환경변수에서 자동 로드)
        app_secret: 키움 앱 시크릿 (환경변수에서 자동 로드)
        is_paper_mode: 모의투자 모드 여부
        params: GET 파라미터
        data: POST 데이터
        headers: 추가 헤더

    Returns:
        Dict[str, Any]: API 응답

    Raises:
        KiwoomOAuthError: 인증 또는 API 호출 실패
    """
    import os

    # 환경변수에서 인증 정보 로드
    if not app_key:
        app_key = os.getenv("KIWOOM_APP_KEY")
    if not app_secret:
        app_secret = os.getenv("KIWOOM_APP_SECRET")

    if not app_key or not app_secret:
        raise KiwoomOAuthError(
            "키움 API 인증 정보가 없습니다. KIWOOM_APP_KEY, KIWOOM_APP_SECRET 환경변수를 설정하세요.",
            "MISSING_CREDENTIALS",
        )

    # 인증 매니저 가져오기
    auth_manager = get_kiwoom_auth()

    try:
        # 인증 매니저가 초기화되지 않은 경우 초기화
        if not auth_manager._http_client:
            await auth_manager.__aenter__()

        # 토큰 획득
        token_info = await auth_manager.get_token(app_key, app_secret, is_paper_mode)

        # API 호출 준비
        api_domain = "mockapi.kiwoom.com" if is_paper_mode else "api.kiwoom.com"
        url = f"https://{api_domain}{endpoint}"

        # 헤더 설정
        request_headers = {
            "Authorization": f"{token_info.token_type} {token_info.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "KiwoomMCPClient/1.0",
        }
        if headers:
            request_headers.update(headers)

        # API 호출
        logger.info(f"키움 API 호출: {method} {endpoint}")

        if method.upper() == "GET":
            response = await auth_manager._http_client.get(
                url, params=params, headers=request_headers
            )
        elif method.upper() == "POST":
            response = await auth_manager._http_client.post(
                url, json=data, params=params, headers=request_headers
            )
        else:
            raise KiwoomOAuthError(
                f"지원하지 않는 HTTP 메소드: {method}", "UNSUPPORTED_METHOD"
            )

        response.raise_for_status()
        response_data = response.json()

        logger.info(f"키움 API 호출 성공: {response.status_code}")
        return response_data
    except httpx.HTTPStatusError as e:
        error_msg = f"키움 API 호출 실패 (HTTP {e.response.status_code}): {endpoint}"
        logger.error(error_msg)

        # 상세 오류 정보 파싱
        try:
            error_detail = e.response.json()
            if "msg1" in error_detail:
                error_msg += f" - {error_detail['msg1']}"
        except Exception:
            pass

        raise KiwoomOAuthError(error_msg, f"HTTP_{e.response.status_code}") from e
    except httpx.RequestError as e:
        error_msg = f"키움 API 연결 실패: {e}"
        logger.error(error_msg)
        raise KiwoomOAuthError(error_msg, "CONNECTION_ERROR") from e
    except Exception as e:
        error_msg = f"키움 API 호출 중 예상치 못한 오류: {e}"
        logger.error(error_msg)
        raise KiwoomOAuthError(error_msg, "UNKNOWN_ERROR") from e
