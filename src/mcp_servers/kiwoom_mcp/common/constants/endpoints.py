"""
키움증권 API 엔드포인트 정의

API 서버 URL과 엔드포인트 경로를 중앙 관리합니다.
"""

import os
from typing import Optional


class KiwoomEndpoints:
    """키움 API 엔드포인트 중앙 관리 클래스"""

    # ===== Base URLs =====
    # 모의투자 (Paper Trading) - 키움증권 공식 Paper Trading URL
    PAPER_BASE_URL = "https://mockapi.kiwoom.com"
    # 실제 운영서버 거래 (Production Trading - 주의!!)
    PRODUCTION_BASE_URL = "https://openapi.kiwoom.com"

    # WebSocket URLs
    PAPER_WS_URL = "wss://mockapi.kiwoom.com:10000"
    # 실제 운영서버 거래 (Production Trading - 주의!!)
    PRODUCTION_WS_URL = "wss://openapi.kiwoom.com:19443"

    # 현재 모드
    _current_mode: str = "paper"

    # ===== API 카테고리별 베이스 경로 =====
    CATEGORY_ENDPOINTS = {
        # OAuth
        "auth": "",  # OAuth는 베이스 경로 없음
        # 국내주식
        "stkinfo": "/api/dostk/stkinfo",  # 종목정보
        "mrkcond": "/api/dostk/mrkcond",  # 시세
        "frgnistt": "/api/dostk/frgnistt",  # 기관/외국인
        "sect": "/api/dostk/sect",  # 업종
        "shsa": "/api/dostk/shsa",  # 공매도
        "rkinfo": "/api/dostk/rkinfo",  # 순위정보
        "chart": "/api/dostk/chart",  # 차트
        "slb": "/api/dostk/slb",  # 대차거래
        "acnt": "/api/dostk/acnt",  # 계좌
        "elw": "/api/dostk/elw",  # ELW
        "etf": "/api/dostk/etf",  # ETF
        "thme": "/api/dostk/thme",  # 테마
        "ordr": "/api/dostk/ordr",  # 주문
        "crdordr": "/api/dostk/crdordr",  # 신용주문
        # WebSocket
        "websocket": "/api/dostk/websocket",
    }

    # ===== OAuth 엔드포인트 =====
    # 토큰 발급
    OAUTH_TOKEN = "/oauth2/token"
    # 토큰 만료
    OAUTH_REVOKE = "/oauth2/revoke"

    @classmethod
    def set_mode(cls, mode: str):
        """
        전역 모드 설정

        Args:
            mode: 'paper', 'production' 중 하나
        """
        if mode not in ["paper", "production"]:
            raise ValueError(f"Invalid mode: {mode}. Must be one of: paper, production")

        cls._current_mode = mode

        # 모드 설정 시 로깅으로 확인
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f" KiwoomEndpoints 모드 설정: {mode} → {cls.get_base_url(mode)}")

    @classmethod
    def get_base_url(cls, mode: Optional[str] = None) -> str:
        """
        현재 모드에 따른 Base URL 반환

        Args:
            mode: 'paper', 'production' 중 하나
                 None일 경우 _current_mode 사용

        Returns:
            Base URL 문자열
        """
        if mode is None:
            # 설정된 현재 모드 사용
            mode = cls._current_mode

        url_map = {
            "paper": cls.PAPER_BASE_URL,
            "production": cls.PRODUCTION_BASE_URL,
        }

        return url_map.get(mode, cls.PAPER_BASE_URL)

    @classmethod
    def get_websocket_url(cls, mode: Optional[str] = None) -> str:
        """
        현재 모드에 따른 WebSocket URL 반환

        Args:
            mode: 'paper', 'production' 중 하나
                 None일 경우 _current_mode 사용

        Returns:
            WebSocket URL 문자열
        """
        if mode is None:
            mode = cls._current_mode

        url_map = {
            "paper": cls.PAPER_WS_URL,
            "production": cls.PRODUCTION_WS_URL,
        }

        return url_map.get(mode, cls.PAPER_WS_URL)

    @classmethod
    def get_endpoint_path(cls, category: str, api_id: Optional[str] = None) -> str:
        """
        카테고리별 엔드포인트 경로 반환

        Args:
            category: API 카테고리
            api_id: API ID (OAuth용)

        Returns:
            엔드포인트 경로
        """
        # OAuth는 특별 처리
        if category == "auth":
            if api_id == "au10001":
                return cls.OAUTH_TOKEN
            elif api_id == "au10002":
                return cls.OAUTH_REVOKE
            else:
                raise ValueError(f"Unknown OAuth API ID: {api_id}")

        # 일반 카테고리
        return cls.CATEGORY_ENDPOINTS.get(category, "")

    @classmethod
    def get_full_url(
        cls, api_id: str, category: str, mode: Optional[str] = None
    ) -> str:
        """
        완전한 API URL 생성

        Args:
            api_id: API ID
            category: API 카테고리
            mode: 서버 모드

        Returns:
            완전한 URL
        """
        base_url = cls.get_base_url(mode)
        endpoint_path = cls.get_endpoint_path(category, api_id)
        return f"{base_url}{endpoint_path}"

    @classmethod
    def get_kiwoom_headers(
        cls,
        api_id: str,
        access_token: str,
        app_key: str,
        app_secret: str,
        **kwargs,
    ) -> dict:
        """
        API 호출용 헤더 생성

        Args:
            api_id: API ID
            access_token: OAuth 토큰
            app_key: 앱 키
            app_secret: 앱 시크릿
            **kwargs: 추가 헤더

        Returns:
            헤더 딕셔너리
        """
        headers = {
            "api-id": api_id,
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "content-type": "application/json; charset=utf-8",
            "custtype": kwargs.get("custtype", "P"),  # 개인고객
        }

        # 추가 헤더 병합
        headers.update(kwargs)

        return headers

    @classmethod
    def get_config_info(cls) -> dict:
        """
        현재 설정 정보 반환 (디버깅용)

        Returns:
            설정 정보 딕셔너리
        """
        return {
            "current_mode": cls._current_mode,
            "base_url": cls.get_base_url(),
            "websocket_url": cls.get_websocket_url(),
            "paper_mode": os.getenv("KIWOOM_PAPER_MODE", "false"),
            "production_mode": os.getenv("KIWOOM_PRODUCTION_MODE", "false"),
            "categories": list(cls.CATEGORY_ENDPOINTS.keys()),
            "total_categories": len(cls.CATEGORY_ENDPOINTS),
        }


# 싱글톤 인스턴스
endpoints = KiwoomEndpoints()
