# `src/mcp_servers` 코드 인덱스

Model Context Protocol(MCP) 서버 생태계의 핵심 구현체들입니다. FastMCP 기반으로 도구 제공 마이크로서비스 아키텍처를 구성합니다.

## 📋 Breadcrumb

- 프로젝트 루트: [README.md](../../README.md)
- 상위로: [src](../code_index.md)
- **현재 위치**: `src/mcp_servers/` - MCP 서버 생태계

## 🗂️ 하위 디렉토리 코드 인덱스

### 🏗️ 인프라 컴포넌트
- **[base/](base/)** - MCP 서버 베이스 클래스 및 추상화
- **[common/](common/)** - 공통 유틸리티 및 미들웨어
- **[utils/](utils/code_index.md)** - 헬퍼 함수 및 유틸리티

### 🏦 도메인 서버 (Kiwoom OpenAPI 기반)
- **[kiwoom_mcp/](kiwoom_mcp/code_index.md)** - 키움증권 통합 MCP 서버
  - **[domains/](kiwoom_mcp/domains/code_index.md)** - 5개 도메인 서버 구현

### 📊 분석 서버
- **[financial_analysis_mcp/](financial_analysis_mcp/code_index.md)** - 재무 분석 서버
- **[stock_analysis_mcp/](stock_analysis_mcp/code_index.md)** - 기술적 분석 서버
- **[macroeconomic_analysis_mcp/](macroeconomic_analysis_mcp/)** - 거시경제 분석 서버

### 📰 데이터 수집 서버
- **[naver_news_mcp/](naver_news_mcp/)** - 네이버 뉴스 수집 서버
- **[tavily_search_mcp/](tavily_search_mcp/)** - 웹 검색 서버

## 📁 디렉토리 트리

```text
mcp_servers/
├── __init__.py                        # 패키지 초기화
├── code_index.md                      # 이 문서
│
├── base/                              # 🏗️ MCP 서버 기반 클래스
│   ├── __init__.py
│   └── base_mcp_server.py            # BaseMCPServer 추상 클래스
│
├── common/                            # 🔧 공통 컴포넌트
│   ├── auth/                         # 인증 관리
│   │   └── kiwoom_auth.py
│   ├── clients/                      # 기본 클라이언트
│   │   ├── base_client.py
│   │   └── kiwoom_base.py
│   ├── concerns/                      # 횡단 관심사
│   │   ├── cache.py                 # 캐싱 전략
│   │   ├── metrics.py               # 메트릭 수집
│   │   └── rate_limit.py           # Rate limiting
│   ├── middleware/                    # 미들웨어
│   │   ├── cors.py
│   │   ├── error_handling.py
│   │   └── logging.py
│   └── exceptions.py                 # 예외 정의
│
├── kiwoom_mcp/                        # 🏦 키움증권 통합 서버
│   ├── common/                       # 키움 전용 공통
│   │   ├── api_registry/           # API 레지스트리
│   │   ├── auth/                   # 키움 인증
│   │   ├── client/                 # REST API 클라이언트
│   │   ├── constants/              # 상수 정의
│   │   └── domain_base.py         # 도메인 베이스
│   └── domains/                      # 5개 도메인 서버
│       ├── market_domain.py        # 시장 데이터 (8031)
│       ├── info_domain.py          # 종목 정보 (8032)
│       ├── trading_domain.py       # 거래 관리 (8030)
│       ├── investor_domain.py      # 투자자 동향 (8033)
│       └── portfolio_domain.py     # 포트폴리오 (8034)
│
├── financial_analysis_mcp/            # 재무 분석 서버 (8040)
│   ├── server.py
│   └── financial_client.py
│
├── stock_analysis_mcp/                # 기술적 분석 서버 (8041)
│   ├── server.py
│   ├── stock_client.py
│   └── korean_market.py
│
├── macroeconomic_analysis_mcp/        # 거시경제 서버 (8042)
│   ├── server.py
│   └── macro_client.py
│
├── naver_news_mcp/                    # 뉴스 수집 서버 (8050)
│   ├── server.py
│   └── news_client.py
│
├── tavily_search_mcp/                 # 웹 검색 서버 (3020)
│   ├── server.py
│   └── tavily_search_client.py
│
└── utils/                             # 유틸리티
    ├── env_validator.py              # 환경변수 검증
    ├── error_handler.py              # 에러 처리
    ├── formatters.py                 # 데이터 포맷터
    ├── market_time.py                # 시장 시간 관리
    ├── security.py                   # 보안 유틸
    ├── serialization.py              # 직렬화
    └── validators.py                 # 입력 검증
```

## 🏗️ MCP 서버 아키텍처

### FastMCP 기반 구조
```python
from fastmcp import FastMCP

# 모든 MCP 서버의 기본 구조
mcp = FastMCP("server_name")

@mcp.tool()
async def tool_function():
    """에이전트가 호출 가능한 도구"""
    pass

@mcp.resource()
async def resource_provider():
    """데이터 리소스 제공"""
    pass
```

### 계층별 책임

#### 1️⃣ **Base Layer** (`base/`)
- `BaseMCPServer`: 모든 MCP 서버의 추상 기반 클래스
- 공통 초기화, 설정, 생명주기 관리

#### 2️⃣ **Common Layer** (`common/`)
- **Auth**: API 키, OAuth 인증 관리
- **Clients**: HTTP/WebSocket 클라이언트 베이스
- **Concerns**: 캐싱, 메트릭, Rate limiting
- **Middleware**: CORS, 에러 처리, 로깅

#### 3️⃣ **Domain Servers** (`kiwoom_mcp/domains/`)
도메인 기반 설계(DDD)로 5개 전문 서버 분리:

| 도메인 | 포트 | 책임 | 주요 도구 |
|--------|------|------|----------|
| `trading_domain` | 8030 | 주문 실행 | buy_stock, sell_stock, get_orders |
| `market_domain` | 8031 | 시장 데이터 | get_price, get_chart, get_volume |
| `info_domain` | 8032 | 종목 정보 | get_stock_info, get_financials |
| `investor_domain` | 8033 | 투자자 동향 | get_institutional, get_foreign |
| `portfolio_domain` | 8034 | 포트폴리오 | get_holdings, calculate_var |

#### 4️⃣ **Analysis Servers**
- **Financial**: DCF, 재무비율 분석
- **Stock**: RSI, MACD 등 기술적 지표
- **Macro**: GDP, 금리, 인플레이션 분석

#### 5️⃣ **Data Collection Servers**
- **News**: 실시간 뉴스, 감성 분석
- **Search**: 웹 검색, 소셜 미디어

## 🚀 서버 실행

### 개별 서버 실행
```bash
# 도메인 서버 실행
python -m src.mcp_servers.kiwoom_mcp.domains.market_domain

# 분석 서버 실행
python -m src.mcp_servers.financial_analysis_mcp.server

# 뉴스 서버 실행
python -m src.mcp_servers.naver_news_mcp.server
```

### Docker Compose 실행
```bash
docker-compose up -d mcp-servers
```

## 🔌 포트 할당 맵

### 도메인 서버 (8030-8034)
```yaml
trading_domain:   8030  # 거래 실행
market_domain:    8031  # 시장 데이터
info_domain:      8032  # 종목 정보
investor_domain:  8033  # 투자자 동향
portfolio_domain: 8034  # 포트폴리오
```

### 분석 서버 (8040-8049)
```yaml
financial_analysis: 8040  # 재무 분석
stock_analysis:     8041  # 기술적 분석
macro_analysis:     8042  # 거시경제
```

### 데이터 서버 (8050+)
```yaml
naver_news:    8050  # 뉴스 수집
tavily_search: 3020  # 웹 검색
```

## 🔧 환경 변수 설정

### 공통 설정
```bash
# MCP 서버 공통
MCP_LOG_LEVEL=INFO
MCP_TIMEOUT=30
MCP_MAX_RETRIES=3

# 인증
KIWOOM_APP_KEY=your-app-key
KIWOOM_APP_SECRET=your-app-secret
KIWOOM_ACCOUNT_NO=your-account

# 외부 API
TAVILY_API_KEY=your-tavily-key
NAVER_CLIENT_ID=your-naver-id
NAVER_CLIENT_SECRET=your-naver-secret
```

## 📊 성능 메트릭

### 응답 시간 목표
- 시장 데이터: < 100ms
- 종목 정보: < 200ms
- 분석 작업: < 5s
- 뉴스 수집: < 3s

### 동시 처리
- 각 서버: 100 concurrent requests
- Connection pooling 활성화
- 캐싱 전략 적용

## 🧪 테스팅

```bash
# 전체 MCP 서버 테스트
pytest tests/mcp_servers/

# 도메인 서버 테스트
pytest tests/mcp_servers/kiwoom_mcp/domains/

# 통합 테스트
pytest tests/mcp_servers/integration/
```

## 🔗 관련 문서

- [상위: src](../code_index.md)
- [LangGraph Agents](../lg_agents/code_index.md) - MCP 도구 사용자
- [A2A Integration](../a2a_integration/code_index.md) - 에이전트 통합
- [FastMCP 공식 문서](https://github.com/fastmcp/fastmcp)