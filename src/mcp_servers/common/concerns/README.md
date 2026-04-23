# Common Concerns

MCP 서버의 공통 관심사(Cross-cutting concerns)를 구현한 모듈들입니다.
관심사 분리 원칙에 따라 메트릭 수집, 캐싱, Rate Limiting 등의 기능을 별도 모듈로 구성했습니다.

## 📊 MetricsCollector

성능 최적화된 메트릭 수집 시스템으로, 다양한 메트릭 타입을 효율적으로 수집하고 관찰가능성(Observability)을 제공합니다.

### 주요 특징

- **다양한 메트릭 타입**: Counter, Gauge, Histogram, Summary 지원
- **비동기 처리**: 메트릭 수집이 서버 성능에 미치는 영향 최소화
- **배치 처리**: 효율적인 메트릭 플러시로 리소스 절약
- **포맷 지원**: Prometheus, JSON 형식 내보내기
- **시스템 메트릭**: 메모리, CPU, GC 통계 자동 수집
- **성능 최적화**: 비동기 큐와 배치 처리로 오버헤드 최소화

### 사용법

#### 기본 사용

```python
from src.mcp_servers.common.concerns.metrics import MetricsCollector, MetricsConfig

# 설정 생성
config = MetricsConfig(
    enabled=True,
    collection_interval=1.0,  # 메트릭 수집 간격 (초)
    flush_interval=10.0,      # 배치 플러시 간격 (초)
    async_collection=True,    # 비동기 수집
    collect_system_metrics=True,
)

# 메트릭 수집기 생성 및 시작
collector = MetricsCollector(config)
await collector.start()

try:
    # Counter: 누적 카운트
    collector.increment_counter("api_requests_total", labels={"method": "GET"})
    
    # Gauge: 현재 값
    collector.set_gauge("active_connections", 42)
    collector.increment_gauge("queue_size", 5)
    
    # Histogram: 분포 (응답 시간 등)
    collector.observe_histogram("request_duration_seconds", 0.123)
    
    # Summary: 통계 요약
    collector.observe_summary("response_size_bytes", 1024)
    
    # 시스템 메트릭 수집
    collector.collect_system_metrics()
    
finally:
    await collector.stop()
```

#### 데코레이터 사용

```python
# 함수 실행 시간 측정
@collector.time_function("business_logic_duration", labels={"operation": "process"})
async def process_data(data):
    # 비즈니스 로직
    return result

# 컨텍스트 매니저
async with collector.time_context("database_query", labels={"table": "users"}):
    result = await db.query("SELECT * FROM users")
```

#### 전역 함수 사용

```python
from src.mcp_servers.common.concerns.metrics import (
    increment_counter,
    set_gauge,
    observe_histogram,
    time_function,
    export_metrics,
)

# 전역 함수로 간편하게 사용
increment_counter("operations_total")
set_gauge("system_load", 0.75)
observe_histogram("latency_seconds", 0.234)

# 메트릭 내보내기
json_metrics = export_metrics("json")
prometheus_metrics = export_metrics("prometheus")
```

### 메트릭 타입

#### Counter

누적 카운터로 항상 증가만 하는 값입니다.

```python
collector.increment_counter("http_requests_total", labels={"method": "GET", "status": "200"})
collector.increment_counter("errors_total", 1.0, labels={"type": "validation"})
```

#### Gauge  

현재 상태를 나타내는 값으로 증가/감소가 가능합니다.

```python
collector.set_gauge("memory_usage_bytes", 1048576)
collector.increment_gauge("active_sessions", 1)
collector.decrement_gauge("pending_jobs", 1)
```

#### Histogram

값의 분포를 측정합니다 (레이턴시, 응답 크기 등).

```python
collector.observe_histogram("request_duration_seconds", 0.123, labels={"endpoint": "/api/data"})
```

#### Summary

통계 요약 정보를 제공합니다 (평균, min/max, 분위수).

```python
collector.observe_summary("payload_size_bytes", 2048, labels={"content_type": "json"})
```

### 설정 옵션

```python
@dataclass
class MetricsConfig:
    # 기본 설정
    enabled: bool = True
    collection_interval: float = 1.0    # 메트릭 수집 간격 (초)
    flush_interval: float = 10.0        # 배치 플러시 간격 (초)
    
    # 성능 설정
    async_collection: bool = True       # 비동기 수집 활성화
    batch_size: int = 1000             # 배치 크기
    buffer_size: int = 10000           # 버퍼 크기
    
    # 시스템 메트릭
    collect_system_metrics: bool = True # 시스템 메트릭 수집
    collect_memory_metrics: bool = True # 메모리 메트릭
    collect_cpu_metrics: bool = True    # CPU 메트릭  
    collect_gc_metrics: bool = True     # GC 메트릭
    
    # 히스토그램 버킷 (레이턴시 용도, 초 단위)
    default_buckets: List[float] = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf')]
    
    # 요약 통계 분위수
    default_quantiles: List[float] = [0.5, 0.9, 0.95, 0.99]
```

### 포맷터

#### JSON 포맷터

구조화된 JSON 형식으로 메트릭을 내보냅니다.

```python
json_data = collector.export_metrics("json")
```

#### Prometheus 포맷터

Prometheus 모니터링 시스템과 호환되는 형식으로 내보냅니다.

```python
prometheus_data = collector.export_metrics("prometheus")
```

### BaseMCPServer 통합

BaseMCPServer에서 MetricsCollector를 사용하는 방법:

```python
from src.mcp_servers.base.base_mcp_server import BaseMCPServer, BaseMCPConfig

class MyMCPConfig(BaseMCPConfig):
    # 메트릭 관련 설정이 자동으로 포함됨
    pass

class MyMCPServer(BaseMCPServer):
    def register_tools(self):
        @self.mcp.tool()
        async def my_business_logic(data: str) -> str:
            # 자동으로 메트릭 수집
            async with self.time_context("business_logic", labels={"operation": "process"}):
                result = await self.process_data(data)
                
            return result

# 서버 실행 시 메트릭 수집이 자동으로 시작됨
config = MyMCPConfig(name="my-server", enable_metrics=True)
server = MyMCPServer(config)
server.run()
```

### 성능 고려사항

1. **비동기 수집**: `async_collection=True`로 설정하면 메인 스레드를 블록하지 않습니다.
2. **배치 처리**: 메트릭을 배치 단위로 처리하여 I/O 오버헤드를 줄입니다.
3. **버퍼링**: 메모리 버퍼를 사용하여 빈번한 디스크 I/O를 방지합니다.
4. **선택적 수집**: 필요한 메트릭만 활성화하여 리소스를 절약합니다.

### 모니터링 대시보드

수집된 메트릭은 다음과 같은 모니터링 도구와 연동할 수 있습니다:

- **Prometheus + Grafana**: Prometheus 포맷으로 내보내기
- **Custom Dashboard**: JSON 포맷으로 내보내어 커스텀 대시보드 구성
- **Logging**: 구조화된 로그로 메트릭 추적

### 예제 및 테스트

더 자세한 사용 예제는 다음 파일을 참조하세요:

- `example_usage.py`: 다양한 사용 패턴 예제
- `test_metrics_collector.py`: 기능 테스트 및 성능 벤치마크

### 의존성

- **필수**: Python 3.12+, asyncio, structlog
- **선택적**: psutil (시스템 메트릭 수집용, 없어도 기본 기능은 동작)

### 트러블슈팅

1. **psutil 모듈 없음**: 시스템 메트릭 수집이 비활성화되지만 다른 기능은 정상 동작
2. **메모리 사용량 증가**: `buffer_size`와 `batch_size`를 줄여서 조절
3. **성능 저하**: `async_collection=True`로 설정하고 `collection_interval` 증가

## 라이선스

이 모듈은 프로젝트의 라이선스를 따릅니다.
