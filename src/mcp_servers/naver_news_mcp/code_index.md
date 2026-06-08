# `src/mcp_servers/naver_news_mcp` 코드 인덱스

네이버 뉴스 수집 및 감성 분석을 제공하는 MCP 서버입니다. 실시간 뉴스, 공시, 리포트를 수집하고 투자 관련 인사이트를 추출합니다.

## 📋 Breadcrumb

- 프로젝트 루트: [README.md](../../../README.md)
- 상위로: [mcp_servers](../code_index.md)
- 최상위: [src](../../code_index.md)
- **현재 위치**: `src/mcp_servers/naver_news_mcp/` - 네이버 뉴스 수집 서버

## 🗂️ 하위 디렉토리 코드 인덱스

- (하위 디렉토리 없음)

## 📁 디렉토리 트리

```text
naver_news_mcp/
├── __init__.py                      # 패키지 초기화
├── server.py                        # FastMCP 서버 구현
├── news_client.py                   # 네이버 뉴스 API 클라이언트
└── code_index.md                    # 이 문서
```

## 📊 주요 컴포넌트

### 🎯 **server.py** - FastMCP 서버

#### 서버 초기화
```python
from fastmcp import FastMCP

mcp = FastMCP("naver_news")
mcp.description = "Naver news collection and sentiment analysis"
```

#### 주요 도구 (Tools)

##### 1️⃣ **search_news** - 뉴스 검색
```python
@mcp.tool()
async def search_news(
    query: str,
    stock_code: Optional[str] = None,
    count: int = 20,
    sort: str = "sim",  # sim(유사도), date(날짜)
    period: Optional[str] = None
) -> List[Dict[str, Any]]:
    """네이버 뉴스 검색
    
    Returns:
        뉴스 리스트 (제목, 내용, 링크, 날짜, 출처)
    """
```

##### 2️⃣ **get_stock_news** - 종목 뉴스
```python
@mcp.tool()
async def get_stock_news(
    stock_code: str,
    stock_name: str,
    count: int = 30,
    include_related: bool = True
) -> Dict[str, Any]:
    """특정 종목 관련 뉴스 수집
    
    수집 범위:
    - 종목명 직접 언급 뉴스
    - 업종/테마 관련 뉴스
    - 경쟁사 뉴스 (optional)
    - 공시 정보
    """
```

##### 3️⃣ **analyze_sentiment** - 감성 분석
```python
@mcp.tool()
async def analyze_sentiment(
    news_items: List[Dict[str, str]],
    context: Optional[str] = None
) -> Dict[str, Any]:
    """뉴스 감성 분석
    
    분석 결과:
    - overall_sentiment: 전체 감성 (-1.0 ~ 1.0)
    - positive_count: 긍정 뉴스 수
    - negative_count: 부정 뉴스 수
    - neutral_count: 중립 뉴스 수
    - key_topics: 주요 토픽
    """
```

##### 4️⃣ **get_trending_keywords** - 트렌딩 키워드
```python
@mcp.tool()
async def get_trending_keywords(
    category: str = "finance",
    timeframe: str = "1d"
) -> List[Dict[str, Any]]:
    """실시간 트렌딩 키워드
    
    카테고리:
    - finance: 금융/증권
    - economy: 경제 일반
    - industry: 산업/기업
    - global: 글로벌 시장
    """
```

##### 5️⃣ **get_disclosure** - 공시 정보
```python
@mcp.tool()
async def get_disclosure(
    stock_code: str,
    disclosure_type: Optional[str] = None,
    days: int = 7
) -> List[Dict[str, Any]]:
    """기업 공시 정보 수집
    
    공시 유형:
    - 주요사항보고서
    - 정기공시
    - 조회공시
    - 공정공시
    - 자율공시
    """
```

### 🔌 **news_client.py** - 뉴스 클라이언트

#### NaverNewsClient 클래스
```python
class NaverNewsClient:
    """네이버 뉴스 API 클라이언트
    
    기능:
    - 뉴스 검색 API 호출
    - 페이지네이션 처리
    - Rate limiting
    - 결과 파싱 및 정제
    """
    
    def __init__(
        self,
        client_id: str,
        client_secret: str
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = aiohttp.ClientSession()
```

#### 핵심 메서드
```python
async def search(
    self,
    query: str,
    display: int = 20,
    start: int = 1,
    sort: str = "sim"
) -> Dict[str, Any]:
    """뉴스 검색 API 호출"""

async def fetch_article_content(
    self,
    url: str
) -> str:
    """뉴스 본문 추출"""

async def extract_keywords(
    self,
    text: str,
    top_n: int = 10
) -> List[str]:
    """키워드 추출"""
```

## 📰 뉴스 수집 전략

### 검색 쿼리 최적화
```python
def build_search_query(
    stock_name: str,
    additional_keywords: List[str] = []
) -> str:
    """효과적인 검색 쿼리 생성
    
    예시:
    - "삼성전자" + ["실적", "반도체"]
    - "SK하이닉스" + ["HBM", "AI"]
    """
```

### 중복 제거
```python
def deduplicate_news(
    news_items: List[Dict]
) -> List[Dict]:
    """중복 뉴스 제거
    
    기준:
    - 제목 유사도 > 0.9
    - 동일 출처 + 유사 시간
    - URL 패턴 매칭
    """
```

## 😊 감성 분석 시스템

### 감성 점수 계산
```python
class SentimentAnalyzer:
    """뉴스 감성 분석기
    
    방법:
    - 한국어 감성 사전 활용
    - 금융 도메인 특화 키워드
    - 문맥 기반 가중치
    """
    
    POSITIVE_KEYWORDS = [
        "상승", "호재", "성장", "개선",
        "돌파", "최고", "흑자", "호조"
    ]
    
    NEGATIVE_KEYWORDS = [
        "하락", "악재", "부진", "악화",
        "우려", "리스크", "적자", "침체"
    ]
```

### 가중치 시스템
```python
def calculate_weighted_sentiment(
    news_item: Dict,
    weights: Dict[str, float]
) -> float:
    """가중 감성 점수
    
    가중치 요소:
    - 뉴스 출처 신뢰도
    - 발행 시간 (최신 > 과거)
    - 제목 vs 본문
    - 조회수/댓글수
    """
```

## 📊 데이터 구조

### 뉴스 아이템 스키마
```python
@dataclass
class NewsItem:
    title: str                 # 뉴스 제목
    content: str              # 본문 요약
    url: str                  # 원문 링크
    published_at: datetime    # 발행 시간
    source: str               # 언론사
    category: str             # 카테고리
    sentiment: float          # 감성 점수
    keywords: List[str]       # 핵심 키워드
    relevance: float          # 관련도
```

### 감성 분석 결과
```python
@dataclass
class SentimentResult:
    overall_score: float           # -1.0 ~ 1.0
    confidence: float              # 0.0 ~ 1.0
    positive_ratio: float          # 긍정 비율
    negative_ratio: float          # 부정 비율
    neutral_ratio: float           # 중립 비율
    dominant_sentiment: str        # POSITIVE|NEGATIVE|NEUTRAL
    key_factors: List[str]         # 주요 감성 요인
```

## 🚀 서버 실행

### 직접 실행
```bash
python -m src.mcp_servers.naver_news_mcp.server
```

### 환경 변수 설정
```bash
export MCP_NEWS_PORT=8050
export NAVER_CLIENT_ID=your-client-id
export NAVER_CLIENT_SECRET=your-client-secret
python -m src.mcp_servers.naver_news_mcp.server
```

## 🔧 환경 변수

```bash
# 서버 설정
MCP_NEWS_PORT=8050                   # 서버 포트
MCP_NEWS_HOST=0.0.0.0               # 서버 호스트

# 네이버 API
NAVER_CLIENT_ID=your-client-id       # 네이버 API ID
NAVER_CLIENT_SECRET=your-secret      # 네이버 API Secret

# 수집 설정
DEFAULT_NEWS_COUNT=20                 # 기본 뉴스 개수
MAX_NEWS_COUNT=100                   # 최대 뉴스 개수
NEWS_CACHE_TTL=300                   # 캐시 TTL (5분)

# 감성 분석
SENTIMENT_MODEL=korean-finbert       # 감성 분석 모델
SENTIMENT_THRESHOLD=0.3              # 감성 판단 임계값
```

## 📈 수집 메트릭

### 성능 지표
- **검색 응답 시간**: < 1초
- **감성 분석**: < 500ms per article
- **동시 처리**: 20 requests
- **캐시 히트율**: > 70%

### 품질 지표
- **뉴스 관련도**: > 0.7
- **중복 제거율**: > 95%
- **감성 정확도**: > 80%

## 🔍 사용 예시

### 종목 뉴스 수집
```python
# API 호출
response = await client.call_tool(
    "get_stock_news",
    {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "count": 30
    }
)

# 응답 예시
{
    "news": [
        {
            "title": "삼성전자, 4분기 실적 발표",
            "content": "...",
            "sentiment": 0.65,
            "published_at": "2024-01-20T09:00:00",
            "source": "한국경제"
        }
    ],
    "sentiment_summary": {
        "overall": 0.42,
        "positive": 18,
        "negative": 7,
        "neutral": 5
    },
    "key_topics": ["실적", "반도체", "HBM"]
}
```

## 🧪 테스팅

### 유닛 테스트
```bash
pytest tests/mcp_servers/naver_news_mcp/test_server.py
pytest tests/mcp_servers/naver_news_mcp/test_client.py
```

### 통합 테스트
```bash
# 뉴스 검색 테스트
curl http://localhost:8050/tools/search_news \
  -d '{"query": "삼성전자", "count": 10}'

# 감성 분석 테스트
curl http://localhost:8050/tools/analyze_sentiment \
  -d '{"news_items": [...]}'
```

## 🔗 관련 문서

- [상위: MCP Servers](../code_index.md)
- [Tavily Search MCP](../tavily_search_mcp/code_index.md)