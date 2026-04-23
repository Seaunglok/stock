# `src/mcp_servers/macroeconomic_analysis_mcp` 코드 인덱스

거시경제 지표 분석 및 경제 동향 예측을 제공하는 MCP 서버입니다. FRED API, BOK API 등을 활용하여 글로벌 경제 데이터를 제공합니다.

## 📋 Breadcrumb

- 프로젝트 루트: [README.md](../../../README.md)
- 상위로: [mcp_servers](../code_index.md)
- 최상위: [src](../../code_index.md)
- **현재 위치**: `src/mcp_servers/macroeconomic_analysis_mcp/` - 거시경제 분석 서버

## 🗂️ 하위 디렉토리 코드 인덱스

- (하위 디렉토리 없음)

## 📁 디렉토리 트리

```text
macroeconomic_analysis_mcp/
├── __init__.py                      # 패키지 초기화
├── server.py                        # FastMCP 서버 구현
├── macro_client.py                  # 외부 API 클라이언트
└── code_index.md                    # 이 문서
```

## 📊 주요 컴포넌트

### 🎯 **server.py** - FastMCP 서버

#### 서버 초기화
```python
from fastmcp import FastMCP

mcp = FastMCP("macroeconomic_analysis")
mcp.description = "Macroeconomic indicators and economic trend analysis"
```

#### 주요 도구 (Tools)

##### 1️⃣ **get_economic_indicators** - 경제 지표 조회
```python
@mcp.tool()
async def get_economic_indicators(
    indicators: List[str],
    countries: List[str] = ["KR", "US"],
    period: str = "1Y"
) -> Dict[str, Any]:
    """주요 경제 지표 조회
    
    지표:
    - GDP: 국내총생산
    - CPI: 소비자물가지수
    - Interest Rate: 기준금리
    - Unemployment: 실업률
    - Trade Balance: 무역수지
    """
```

##### 2️⃣ **analyze_monetary_policy** - 통화정책 분석
```python
@mcp.tool()
async def analyze_monetary_policy(
    country: str = "KR"
) -> Dict[str, Any]:
    """중앙은행 통화정책 분석
    
    분석 내용:
    - 현재 기준금리
    - 금리 전망
    - 통화정책 스탠스
    - 정책 변화 영향
    """
```

##### 3️⃣ **get_market_correlation** - 시장 상관관계
```python
@mcp.tool()
async def get_market_correlation(
    asset_classes: List[str]
) -> Dict[str, Any]:
    """자산 클래스 간 상관관계 분석
    
    자산 클래스:
    - Equity: 주식
    - Bond: 채권
    - Commodity: 원자재
    - Currency: 통화
    - Real Estate: 부동산
    """
```

##### 4️⃣ **forecast_economic_trend** - 경제 전망
```python
@mcp.tool()
async def forecast_economic_trend(
    horizon: str = "6M"
) -> Dict[str, Any]:
    """경제 트렌드 예측
    
    예측 항목:
    - 성장률 전망
    - 인플레이션 전망
    - 금리 전망
    - 환율 전망
    """
```

### 🔌 **macro_client.py** - API 클라이언트

#### MacroeconomicClient 클래스
```python
class MacroeconomicClient:
    """거시경제 데이터 API 클라이언트
    
    연동 API:
    - FRED (Federal Reserve Economic Data)
    - BOK (한국은행 경제통계시스템)
    - IMF Data API
    - World Bank API
    """
    
    def __init__(self):
        self.fred_client = FREDClient()
        self.bok_client = BOKClient()
        self.imf_client = IMFClient()
```

#### 데이터 수집 메서드
```python
async def fetch_gdp_data(
    self,
    countries: List[str],
    period: str
) -> DataFrame:
    """GDP 데이터 수집"""

async def fetch_inflation_data(
    self,
    countries: List[str],
    period: str
) -> DataFrame:
    """인플레이션 데이터 수집"""

async def fetch_interest_rates(
    self,
    central_banks: List[str]
) -> Dict[str, float]:
    """중앙은행 기준금리 수집"""
```

## 📈 경제 지표 체계

### 주요 지표 카테고리

#### 📊 성장 지표
- **GDP**: 실질/명목 GDP, 성장률
- **Industrial Production**: 산업생산지수
- **Retail Sales**: 소매판매
- **PMI**: 구매관리자지수

#### 💰 물가 지표
- **CPI**: 소비자물가지수
- **PPI**: 생산자물가지수
- **Core Inflation**: 근원 인플레이션
- **Import/Export Prices**: 수출입 물가

#### 💼 고용 지표
- **Unemployment Rate**: 실업률
- **Nonfarm Payrolls**: 비농업 고용
- **Jobless Claims**: 실업수당 청구
- **Labor Force Participation**: 경제활동참가율

#### 🏦 금융 지표
- **Interest Rates**: 기준금리, 시장금리
- **Money Supply**: 통화공급량 (M0, M1, M2)
- **Credit Growth**: 신용 증가율
- **Yield Curve**: 수익률 곡선

## 🌍 글로벌 경제 분석

### 국가별 데이터
```python
SUPPORTED_COUNTRIES = {
    "KR": "대한민국",
    "US": "미국",
    "CN": "중국",
    "JP": "일본",
    "EU": "유럽연합",
    "UK": "영국"
}
```

### 경제 블록 분석
- **G7**: 주요 7개국
- **G20**: 주요 20개국
- **OECD**: OECD 회원국
- **Emerging Markets**: 신흥시장

## 🔄 데이터 업데이트 주기

| 데이터 유형 | 업데이트 주기 | 지연 시간 |
|------------|--------------|----------|
| GDP | 분기별 | 1-2개월 |
| CPI/PPI | 월별 | 2주 |
| 고용 지표 | 월별 | 1주 |
| 금리 | 실시간 | 즉시 |
| PMI | 월별 | 월초 |

## 🚀 서버 실행

### 직접 실행
```bash
python -m src.mcp_servers.macroeconomic_analysis_mcp.server
```

### 환경 변수 설정
```bash
export MCP_MACRO_PORT=8042
export FRED_API_KEY=your-fred-key
export BOK_API_KEY=your-bok-key
python -m src.mcp_servers.macroeconomic_analysis_mcp.server
```

### Docker 실행
```bash
docker run -p 8042:8042 \
  -e FRED_API_KEY=your-key \
  macro-analysis-mcp
```

## 🔧 환경 변수

```bash
# 서버 설정
MCP_MACRO_PORT=8042                 # 서버 포트
MCP_MACRO_HOST=0.0.0.0             # 서버 호스트

# API 키
FRED_API_KEY=your-fred-api-key      # FRED API
BOK_API_KEY=your-bok-api-key        # 한국은행 API
IMF_API_KEY=your-imf-api-key        # IMF API

# 캐싱 설정
MACRO_CACHE_ENABLED=true            # 캐싱 활성화
MACRO_CACHE_TTL=3600                # 캐시 TTL (초)

# 데이터 설정
DEFAULT_LOOKBACK_PERIOD=5Y          # 기본 조회 기간
MAX_DATA_POINTS=1000                # 최대 데이터 포인트
```

## 📊 응답 예시

### 경제 지표 조회 응답
```json
{
    "indicators": {
        "GDP": {
            "KR": {
                "value": 1.8,
                "unit": "%",
                "period": "2024Q1",
                "yoy_change": -0.5
            },
            "US": {
                "value": 2.5,
                "unit": "%",
                "period": "2024Q1",
                "yoy_change": 0.3
            }
        },
        "CPI": {
            "KR": {
                "value": 3.1,
                "unit": "%",
                "period": "2024-01",
                "mom_change": 0.2
            }
        }
    },
    "timestamp": "2024-01-20T10:00:00Z"
}
```

## 🧪 테스팅

### 유닛 테스트
```bash
pytest tests/mcp_servers/macroeconomic_analysis_mcp/test_server.py
```

### API 테스트
```bash
# 경제 지표 조회
curl http://localhost:8042/tools/get_economic_indicators \
  -d '{"indicators": ["GDP", "CPI"], "countries": ["KR", "US"]}'
```

## 📈 성능 메트릭

- **응답 시간**: < 2초 (캐시 히트 시 < 200ms)
- **동시 요청**: 50 concurrent requests
- **캐시 히트율**: > 80%
- **API 호출 최적화**: 배치 요청 사용

## 🔗 관련 문서

- [상위: MCP Servers](../code_index.md)
- [Financial Analysis MCP](../financial_analysis_mcp/code_index.md)
- [Stock Analysis MCP](../stock_analysis_mcp/code_index.md)
- [Analysis Agent](../../a2a_agents/analysis/code_index.md)