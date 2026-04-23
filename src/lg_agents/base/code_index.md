# `src/lg_agents/base` 코드 인덱스

LangGraph 에이전트를 위한 베이스 프레임워크와 공통 유틸리티 모듈입니다.

## 📋 Breadcrumb

- 프로젝트 루트: [README.md](../../../README.md)
- 상위로: [lg_agents](../code_index.md)
- 최상위: [src](../../code_index.md)
- **현재 위치**: `src/lg_agents/base/` - 에이전트 기반 클래스

## 🗂️ 하위 디렉토리 코드 인덱스

- (하위 디렉토리 없음)

## 📁 디렉토리 트리

```text
base/
├── __init__.py                    # 패키지 초기화 및 export
├── code_index.md                  # 이 문서
├── base_graph_agent.py            # BaseGraphAgent 추상 클래스
├── base_graph_state.py            # 상태 관리 TypedDict
├── error_handling.py              # 에러 처리 데코레이터
├── mcp_config.py                  # MCP 서버 설정 관리
└── mcp_loader.py                  # MCP 도구 동적 로더
```

## 📊 각 파일 상세 설명

### 1️⃣ **base_graph_agent.py** - 에이전트 추상 기반 클래스

#### 주요 클래스
- `BaseGraphAgent`: 모든 LangGraph 에이전트의 추상 기반 클래스

#### 주요 메서드
```python
class BaseGraphAgent(ABC):
    @abstractmethod
    def build_graph(self) -> StateGraph:
        """StateGraph 구축 - 하위 클래스에서 구현"""
        
    def initialize_node(self, state: BaseState) -> BaseState:
        """공통 초기화 노드"""
        
    def error_handler(self, state: BaseState) -> BaseState:
        """공통 에러 처리 노드"""
        
    def finalize_node(self, state: BaseState) -> BaseState:
        """공통 최종화 노드"""
```

#### 제공 기능
- StateGraph 빌드 템플릿
- 공통 노드 구현 (initialize, finalize, error)
- 에러 복구 메커니즘
- 로깅 및 모니터링 통합

### 2️⃣ **base_graph_state.py** - 상태 관리

#### 주요 TypedDict
```python
class BaseState(TypedDict):
    """기본 상태 정의"""
    messages: List[BaseMessage]      # 대화 히스토리
    task: str                        # 현재 작업
    status: str                      # 상태 (pending|running|completed|error)
    errors: List[str]                # 에러 메시지
    metadata: Dict[str, Any]         # 메타데이터
    
class DataCollectorState(BaseState):
    """데이터 수집 상태"""
    data: Dict[str, Any]             # 수집된 데이터
    data_quality_score: float        # 데이터 품질 점수
    
class AnalysisState(BaseState):
    """분석 상태"""
    analysis_results: Dict[str, Any] # 분석 결과
    recommendations: List[Dict]      # 권장사항
    confidence_score: float          # 신뢰도 점수
    
class TradingState(BaseState):
    """거래 상태"""
    orders: List[Dict]               # 주문 목록
    portfolio: Dict[str, Any]        # 포트폴리오
    risk_metrics: Dict[str, float]  # 리스크 지표
    human_approval_required: bool   # Human 승인 필요 여부
```

#### 상태 전이 관리
- 불변성 보장을 위한 TypedDict 사용
- 상태 검증 로직
- 상태 히스토리 추적

### 3️⃣ **error_handling.py** - 에러 처리

#### 주요 데코레이터
```python
@retry(max_attempts=3, backoff=2.0)
def with_retry(func):
    """재시도 로직이 있는 데코레이터"""
    
@handle_errors(log_errors=True, raise_on_critical=True)
def safe_execution(func):
    """안전한 실행을 위한 에러 처리"""
    
@timeout(seconds=30)
def with_timeout(func):
    """타임아웃 처리 데코레이터"""
```

#### 예외 클래스
- `AgentExecutionError`: 에이전트 실행 오류
- `DataCollectionError`: 데이터 수집 오류
- `AnalysisError`: 분석 오류
- `TradingError`: 거래 실행 오류
- `MCPConnectionError`: MCP 서버 연결 오류

#### 에러 복구 전략
- Exponential backoff 재시도
- Circuit breaker 패턴
- Fallback 메커니즘
- 에러 로깅 및 알림

### 4️⃣ **mcp_config.py** - MCP 설정 관리

#### 설정 구조
```python
@dataclass
class MCPServerConfig:
    name: str                # 서버 이름
    port: int                # 포트 번호
    host: str = "localhost"  # 호스트
    enabled: bool = True     # 활성화 여부
    timeout: int = 30        # 타임아웃 (초)
    
class MCPConfigManager:
    def load_config(self) -> Dict[str, MCPServerConfig]:
        """설정 로드"""
        
    def get_server_url(self, server_name: str) -> str:
        """서버 URL 조회"""
        
    def validate_config(self):
        """설정 검증"""
```

#### 서버 매핑
```python
MCP_SERVERS = {
    "trading_domain": MCPServerConfig("trading_domain", 8030),
    "market_domain": MCPServerConfig("market_domain", 8031),
    "info_domain": MCPServerConfig("info_domain", 8032),
    "investor_domain": MCPServerConfig("investor_domain", 8033),
    "portfolio_domain": MCPServerConfig("portfolio_domain", 8034),
    "financial_analysis_mcp": MCPServerConfig("financial_analysis", 8040),
    "naver_news_mcp": MCPServerConfig("naver_news", 8050),
    "tavily_search_mcp": MCPServerConfig("tavily_search", 3020),
}
```

### 5️⃣ **mcp_loader.py** - MCP 도구 로더

#### 주요 클래스
- `MCPToolLoader`: MCP 도구 동적 로딩 관리

#### 주요 기능
```python
class MCPToolLoader:
    def load_tools(self, server_names: List[str]) -> Dict[str, Tool]:
        """도구 로드"""
        
    def register_tool(self, tool: Tool):
        """도구 등록"""
        
    def get_tool(self, tool_name: str) -> Tool:
        """도구 조회"""
        
    def validate_tools(self):
        """도구 검증"""
        
    async def initialize_connections(self):
        """연결 초기화"""
```

#### 도구 레지스트리
- 동적 도구 발견
- 도구 버전 관리
- 의존성 해결
- 도구 캐싱

#### 연결 관리
- Connection pooling
- Health check
- 자동 재연결
- Load balancing

## 🎯 사용 예시

### BaseGraphAgent 상속
```python
from src.lg_agents.base import BaseGraphAgent, BaseState

class MyCustomAgent(BaseGraphAgent):
    def build_graph(self) -> StateGraph:
        graph = StateGraph(BaseState)
        
        # 노드 추가
        graph.add_node("initialize", self.initialize_node)
        graph.add_node("process", self.process_node)
        graph.add_node("finalize", self.finalize_node)
        
        # 엣지 추가
        graph.add_edge("initialize", "process")
        graph.add_edge("process", "finalize")
        
        return graph.compile()
```

### 에러 처리 사용
```python
from src.lg_agents.base.error_handling import with_retry, handle_errors

@with_retry(max_attempts=3)
@handle_errors(log_errors=True)
async def fetch_market_data(stock_code: str):
    # 시장 데이터 수집 로직
    pass
```

### MCP 도구 로딩
```python
from src.lg_agents.base.mcp_loader import MCPToolLoader

loader = MCPToolLoader()
tools = await loader.load_tools(["market_domain", "info_domain"])

# 도구 사용
market_tool = tools["get_real_time_quote"]
result = await market_tool.ainvoke({"stock_code": "005930"})
```

## 🔗 관련 문서

- [상위: LangGraph Agents](../code_index.md)
- [SupervisorAgent 구현](../supervisor_agent.py)
- [DataCollectorAgent 구현](../data_collector_agent.py)
- [AnalysisAgent 구현](../analysis_agent.py)
- [TradingAgent 구현](../trading_agent.py)