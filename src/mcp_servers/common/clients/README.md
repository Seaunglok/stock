# MCP Common HTTP Clients

## 개요

MCP 서버 전반에 걸쳐 사용되는 재사용 가능한 HTTP 클라이언트 유틸리티입니다.
안정적이고 확장 가능한 HTTP 통신을 위한 추상화 계층을 제공합니다.

## 주요 컴포넌트

### BaseHTTPClient

표준화된 HTTP 요청 처리를 위한 기본 클라이언트

#### 주요 기능

- 일관된 요청/응답 처리
- 자동 재시도 메커니즘
- 타임아웃 관리
- 에러 핸들링

## 설계 패턴

- 의존성 주입
- 전략 패턴
- 데코레이터 패턴

## 사용 예시

```python
from src.mcp_servers.common.clients import BaseHTTPClient

class NewsAPIClient(BaseHTTPClient):
    def fetch_news(self, symbol):
        return self.get(
            f'/news/{symbol}', 
            timeout=5, 
            retries=3
        )

client = NewsAPIClient(base_url='https://newsapi.example.com')
news_data = client.fetch_news('AAPL')
```

## 고급 기능

- Circuit Breaker 통합
- 로깅 및 메트릭스 지원
- 인증 메커니즘 추상화

## 성능 최적화

- 최소 오버헤드
- 비동기 요청 지원
- 효율적인 메모리 관리

## 버전

현재 버전: 1.1.0

## 라이선스

내부 전용 라이선스 적용
