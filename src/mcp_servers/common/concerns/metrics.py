"""
MetricsCollector: 성능 최적화된 메트릭 수집 시스템.

이 모듈은 MCP 서버의 메트릭 수집 로직을 별도로 분리하여 관찰가능성(Observability)을
제공합니다. 메트릭 수집이 서버 성능에 미치는 영향을 최소화하면서 상세한 통계를 제공합니다.

주요 기능:
- Counter, Gauge, Histogram, Summary 메트릭 타입 지원
- 비동기 메트릭 수집으로 성능 영향 최소화
- Prometheus, JSON 포맷 지원
- 메모리/CPU 사용량 모니터링
- 배치 처리를 통한 효율적인 메트릭 플러시
"""

import asyncio
import gc
import json
import threading
import time

# 선택적 임포트
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False
from collections import defaultdict
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from typing import Any, Protocol

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class MetricType(str, Enum):
    """메트릭 타입 열거형."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class MetricValue(BaseModel):
    """개별 메트릭 값을 나타내는 데이터 클래스."""

    name: str
    value: int | float
    timestamp: float = Field(default_factory=time.time)
    labels: dict[str, str] = Field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE


class HistogramBucket(BaseModel):
    """히스토그램 버킷."""

    le: float  # Less than or equal to
    count: int = 0


class HistogramData(BaseModel):
    """히스토그램 데이터."""

    buckets: list[HistogramBucket] = Field(default_factory=list)
    sum: float = 0.0
    count: int = 0

    def model_post_init(self, __context: Any) -> None:
        """기본 버킷 설정."""
        if not self.buckets:
            # 기본 레이턴시 버킷 (ms 단위)
            default_buckets = [
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                2.5,
                5.0,
                10.0,
                float("inf"),
            ]
            self.buckets = [HistogramBucket(le=le) for le in default_buckets]


class SummaryData(BaseModel):
    """요약 통계 데이터."""

    sum: float = 0.0
    count: int = 0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    quantiles: dict[float, float] = Field(default_factory=dict)  # p50, p95, p99 등

    def add_value(self, value: float):
        """값 추가 및 통계 업데이트."""
        self.sum += value
        self.count += 1
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)

    @property
    def mean(self) -> float:
        """평균값."""
        return self.sum / self.count if self.count > 0 else 0.0


class MetricFormatter(Protocol):
    """메트릭 포맷터 인터페이스."""

    def format(self, metrics: dict[str, any]) -> str:
        """메트릭을 특정 형식으로 포맷."""
        ...


class PrometheusFormatter(BaseModel):
    """Prometheus 형식 포맷터."""

    def format(self, metrics: dict[str, Any]) -> str:
        """Prometheus 형식으로 메트릭 포맷."""
        lines = []

        for metric_name, metric_data in metrics.items():
            if isinstance(metric_data, dict):
                metric_type = metric_data.get("type", "gauge")

                # TYPE 선언
                lines.append(f"# TYPE {metric_name} {metric_type}")

                if metric_type == "counter" or metric_type == "gauge":
                    value = metric_data.get("value", 0)
                    labels = metric_data.get("labels", {})
                    label_str = self._format_labels(labels)
                    lines.append(f"{metric_name}{label_str} {value}")

                elif metric_type == "histogram":
                    hist_data = metric_data.get("histogram", HistogramData())
                    labels = metric_data.get("labels", {})

                    # 버킷별 카운트
                    for bucket in hist_data.buckets:
                        bucket_labels = {**labels, "le": str(bucket.le)}
                        label_str = self._format_labels(bucket_labels)
                        lines.append(f"{metric_name}_bucket{label_str} {bucket.count}")

                    # 총합과 카운트
                    label_str = self._format_labels(labels)
                    lines.append(f"{metric_name}_sum{label_str} {hist_data.sum}")
                    lines.append(f"{metric_name}_count{label_str} {hist_data.count}")

                elif metric_type == "summary":
                    summary_data = metric_data.get("summary", SummaryData())
                    labels = metric_data.get("labels", {})

                    # 분위수
                    for quantile, value in summary_data.quantiles.items():
                        quantile_labels = {**labels, "quantile": str(quantile)}
                        label_str = self._format_labels(quantile_labels)
                        lines.append(f"{metric_name}{label_str} {value}")

                    # 총합과 카운트
                    label_str = self._format_labels(labels)
                    lines.append(f"{metric_name}_sum{label_str} {summary_data.sum}")
                    lines.append(f"{metric_name}_count{label_str} {summary_data.count}")

        return "\n".join(lines)

    def _format_labels(self, labels: dict[str, str]) -> str:
        """라벨을 Prometheus 형식으로 포맷."""
        if not labels:
            return ""

        label_pairs = [f'{key}="{value}"' for key, value in labels.items()]
        return "{" + ",".join(label_pairs) + "}"


class JSONFormatter(BaseModel):
    """JSON 형식 포맷터."""

    def format(self, metrics: dict[str, Any]) -> str:
        """JSON 형식으로 메트릭 포맷."""

        def serialize_metric(obj: any) -> any:
            """커스텀 직렬화."""
            if isinstance(obj, HistogramData | SummaryData | HistogramBucket):
                return obj.__dict__
            elif isinstance(obj, datetime):
                return obj.isoformat()
            return obj

        return json.dumps(
            metrics, default=serialize_metric, indent=2, ensure_ascii=False
        )


class MetricsConfig(BaseModel):
    """메트릭 수집 설정."""

    # 기본 설정
    enabled: bool = True
    collection_interval: float = 1.0  # 메트릭 수집 간격 (초)
    flush_interval: float = 10.0  # 배치 플러시 간격 (초)

    # 성능 설정
    async_collection: bool = True  # 비동기 수집 활성화
    batch_size: int = 1000  # 배치 크기
    buffer_size: int = 10000  # 버퍼 크기

    # 시스템 메트릭
    collect_system_metrics: bool = True
    collect_memory_metrics: bool = True
    collect_cpu_metrics: bool = True
    collect_gc_metrics: bool = True

    # 히스토그램 설정
    default_buckets: list[float] = Field(
        default_factory=lambda: [
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
            float("inf"),
        ]
    )

    # 요약 통계 분위수
    default_quantiles: list[float] = Field(
        default_factory=lambda: [0.5, 0.9, 0.95, 0.99]
    )


class MetricsCollector(BaseModel):
    """
    성능 최적화된 메트릭 수집기.

    이 클래스는 다양한 메트릭 타입을 효율적으로 수집하고 저장합니다.
    비동기 처리와 배치 처리를 통해 성능 영향을 최소화합니다.
    """

    def __init__(self, config: MetricsConfig | None = None):
        """
        메트릭 수집기 초기화.

        Args:
            config: 메트릭 수집 설정

        """
        self.config = config or MetricsConfig()

        # 메트릭 저장소
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, HistogramData] = defaultdict(HistogramData)
        self._summaries: dict[str, SummaryData] = defaultdict(SummaryData)

        # 메트릭 메타데이터
        self._metric_metadata: dict[str, dict[str, Any]] = {}

        # 비동기 처리를 위한 큐
        self._metric_queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.config.buffer_size
        )

        # 배치 처리용 버퍼
        self._batch_buffer: list[MetricValue] = []
        self._buffer_lock = threading.RLock()

        # 포맷터
        self._formatters: dict[str, MetricFormatter] = {
            "prometheus": PrometheusFormatter(),
            "json": JSONFormatter(),
        }

        # 시스템 정보 캐시
        self._process = (
            psutil.Process()
            if (HAS_PSUTIL and self.config.collect_system_metrics)
            else None
        )
        self._last_cpu_times = None

        # 백그라운드 태스크
        self._collection_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False

        # 시작 시간
        self._start_time = time.time()

        logger.info("metrics_collector_initialized", config=self.config)

    async def start(self):
        """메트릭 수집 시작."""
        if self._running:
            return

        self._running = True

        if self.config.async_collection:
            try:
                # 현재 실행 중인 이벤트 루프 확인
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # 실행 중인 이벤트 루프가 없는 경우 비동기 수집 비활성화
                    logger.warning("no_running_event_loop_disabling_async_collection")
                    return

                # 이벤트 루프가 닫혔는지 확인
                if loop.is_closed():
                    logger.warning("event_loop_is_closed_disabling_async_collection")
                    return

                # 안전하게 태스크 생성
                self._collection_task = asyncio.create_task(
                    self._collection_loop(), name=f"metrics_collection_{id(self)}"
                )
                self._flush_task = asyncio.create_task(
                    self._flush_loop(), name=f"metrics_flush_{id(self)}"
                )

                logger.info(
                    "metrics_collector_started_async",
                    collection_task_id=id(self._collection_task),
                    flush_task_id=id(self._flush_task),
                    loop_id=id(loop),
                )

            except RuntimeError as e:
                # 이벤트 루프 관련 RuntimeError 처리
                logger.warning(
                    "event_loop_error_disabling_async_collection",
                    error=str(e),
                    error_type=type(e).__name__,
                )
            except Exception as e:
                # 기타 예상치 못한 오류 처리
                logger.error(
                    "unexpected_error_during_metrics_start",
                    error=str(e),
                    error_type=type(e).__name__,
                )
        else:
            logger.info("metrics_collector_started_sync")

    async def stop(self):
        """메트릭 수집 중지."""
        if not self._running:
            return

        self._running = False

        # 백그라운드 태스크 종료
        if self._collection_task:
            self._collection_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._collection_task

        if self._flush_task:
            self._flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._flush_task

        # 남은 메트릭 플러시
        await self._flush_batch()

        logger.info("metrics_collector_stopped")

    # Counter 메서드들
    def increment_counter(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ):
        """카운터 증가."""
        if not self.config.enabled:
            return

        key = self._make_key(name, labels)
        self._counters[key] += value
        self._set_metadata(name, MetricType.COUNTER, labels)

        if self.config.async_collection:
            try:
                self._metric_queue.put_nowait(
                    MetricValue(
                        name=name,
                        value=value,
                        labels=labels or {},
                        metric_type=MetricType.COUNTER,
                    )
                )
            except asyncio.QueueFull:
                logger.warning("metric_queue_full", metric=name)

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        """카운터 값 조회."""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0.0)

    # Gauge 메서드들
    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """게이지 값 설정."""
        if not self.config.enabled:
            return

        key = self._make_key(name, labels)
        self._gauges[key] = value
        self._set_metadata(name, MetricType.GAUGE, labels)

        if self.config.async_collection:
            try:
                self._metric_queue.put_nowait(
                    MetricValue(
                        name=name,
                        value=value,
                        labels=labels or {},
                        metric_type=MetricType.GAUGE,
                    )
                )
            except asyncio.QueueFull:
                logger.warning("metric_queue_full", metric=name)

    def get_gauge(
        self, name: str, labels: dict[str, str] | None = None
    ) -> float | None:
        """게이지 값 조회."""
        key = self._make_key(name, labels)
        return self._gauges.get(key)

    def increment_gauge(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ):
        """게이지 값 증가."""
        key = self._make_key(name, labels)
        current = self._gauges.get(key, 0.0)
        self.set_gauge(name, current + value, labels)

    def decrement_gauge(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ):
        """게이지 값 감소."""
        key = self._make_key(name, labels)
        current = self._gauges.get(key, 0.0)
        self.set_gauge(name, current - value, labels)

    # Histogram 메서드들
    def observe_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ):
        """히스토그램 값 관찰."""
        if not self.config.enabled:
            return

        key = self._make_key(name, labels)
        if key not in self._histograms:
            hist_data = HistogramData()
            hist_data.buckets = [
                HistogramBucket(le=le) for le in self.config.default_buckets
            ]
            self._histograms[key] = hist_data

        hist = self._histograms[key]
        hist.sum += value
        hist.count += 1

        # 적절한 버킷에 추가
        for bucket in hist.buckets:
            if value <= bucket.le:
                bucket.count += 1

        self._set_metadata(name, MetricType.HISTOGRAM, labels)

    def get_histogram(
        self, name: str, labels: dict[str, str] | None = None
    ) -> HistogramData | None:
        """히스토그램 데이터 조회."""
        key = self._make_key(name, labels)
        return self._histograms.get(key)

    # Summary 메서드들
    def observe_summary(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ):
        """요약 통계 값 관찰."""
        if not self.config.enabled:
            return

        key = self._make_key(name, labels)
        if key not in self._summaries:
            summary_data = SummaryData()
            # 기본 분위수 초기화
            for q in self.config.default_quantiles:
                summary_data.quantiles[q] = 0.0
            self._summaries[key] = summary_data

        self._summaries[key].add_value(value)
        self._set_metadata(name, MetricType.SUMMARY, labels)

    def get_summary(
        self, name: str, labels: dict[str, str] | None = None
    ) -> SummaryData | None:
        """요약 통계 데이터 조회."""
        key = self._make_key(name, labels)
        return self._summaries.get(key)

    # 시스템 메트릭 수집
    def collect_system_metrics(self):
        """시스템 메트릭 수집."""
        if not self.config.collect_system_metrics:
            return

        try:
            # psutil이 사용 가능한 경우에만 시스템 메트릭 수집
            if HAS_PSUTIL and self._process:
                # 메모리 메트릭
                if self.config.collect_memory_metrics:
                    memory_info = self._process.memory_info()
                    self.set_gauge("system_memory_rss_bytes", memory_info.rss)
                    self.set_gauge("system_memory_vms_bytes", memory_info.vms)

                    # 시스템 전체 메모리
                    sys_memory = psutil.virtual_memory()
                    self.set_gauge("system_memory_total_bytes", sys_memory.total)
                    self.set_gauge(
                        "system_memory_available_bytes", sys_memory.available
                    )
                    self.set_gauge("system_memory_used_percent", sys_memory.percent)

                # CPU 메트릭
                if self.config.collect_cpu_metrics:
                    cpu_percent = self._process.cpu_percent()
                    self.set_gauge("system_cpu_usage_percent", cpu_percent)

                    # 시스템 전체 CPU
                    sys_cpu_percent = psutil.cpu_percent()
                    self.set_gauge("system_cpu_total_percent", sys_cpu_percent)

                    # CPU 코어별 사용률
                    cpu_percents = psutil.cpu_percent(percpu=True)
                    for i, cpu_p in enumerate(cpu_percents):
                        self.set_gauge(
                            "system_cpu_core_percent", cpu_p, {"core": str(i)}
                        )

            # 가비지 컬렉션 메트릭 (psutil 없이도 가능)
            if self.config.collect_gc_metrics:
                gc_stats = gc.get_stats()
                for i, stat in enumerate(gc_stats):
                    generation = str(i)
                    self.set_gauge(
                        "python_gc_collections_total",
                        stat.get("collections", 0),
                        {"generation": generation},
                    )
                    self.set_gauge(
                        "python_gc_collected_total",
                        stat.get("collected", 0),
                        {"generation": generation},
                    )
                    self.set_gauge(
                        "python_gc_uncollectable_total",
                        stat.get("uncollectable", 0),
                        {"generation": generation},
                    )

                # 현재 객체 수
                self.set_gauge("python_gc_objects_count", len(gc.get_objects()))

        except Exception as e:
            logger.warning("system_metrics_collection_failed", error=str(e))

    # 타이밍 데코레이터
    def time_function(self, metric_name: str, labels: dict[str, str] | None = None):
        """함수 실행 시간을 측정하는 데코레이터."""

        def decorator(func: Callable):
            if asyncio.iscoroutinefunction(func):

                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    start_time = time.time()
                    try:
                        result = await func(*args, **kwargs)
                        duration = time.time() - start_time
                        self.observe_histogram(metric_name, duration, labels)
                        self.increment_counter(f"{metric_name}_total", labels=labels)
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        error_labels = {**(labels or {}), "error": type(e).__name__}
                        self.observe_histogram(
                            f"{metric_name}_error", duration, error_labels
                        )
                        self.increment_counter(
                            f"{metric_name}_error_total", labels=error_labels
                        )
                        raise

                return async_wrapper
            else:

                @wraps(func)
                def sync_wrapper(*args, **kwargs):
                    start_time = time.time()
                    try:
                        result = func(*args, **kwargs)
                        duration = time.time() - start_time
                        self.observe_histogram(metric_name, duration, labels)
                        self.increment_counter(f"{metric_name}_total", labels=labels)
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        error_labels = {**(labels or {}), "error": type(e).__name__}
                        self.observe_histogram(
                            f"{metric_name}_error", duration, error_labels
                        )
                        self.increment_counter(
                            f"{metric_name}_error_total", labels=error_labels
                        )
                        raise

                return sync_wrapper

        return decorator

    # 컨텍스트 매니저
    @asynccontextmanager
    async def time_context(
        self, metric_name: str, labels: dict[str, str] | None = None
    ):
        """시간 측정 컨텍스트 매니저."""
        start_time = time.time()
        try:
            yield
            duration = time.time() - start_time
            self.observe_histogram(metric_name, duration, labels)
            self.increment_counter(f"{metric_name}_total", labels=labels)
        except Exception as e:
            duration = time.time() - start_time
            error_labels = {**(labels or {}), "error": type(e).__name__}
            self.observe_histogram(f"{metric_name}_error", duration, error_labels)
            self.increment_counter(f"{metric_name}_error_total", labels=error_labels)
            raise

    # 메트릭 내보내기
    def export_metrics(self, format_type: str = "json") -> str:
        """
        메트릭을 지정된 형식으로 내보내기.

        Args:
            format_type: 출력 형식 ("json", "prometheus")

        Returns:
            포맷된 메트릭 문자열

        """
        formatter = self._formatters.get(format_type)
        if not formatter:
            raise ValueError(f"Unsupported format: {format_type}")

        # 시스템 메트릭 수집
        self.collect_system_metrics()

        # 모든 메트릭 수집
        all_metrics = {}

        # 카운터
        for key, value in self._counters.items():
            name, labels = self._parse_key(key)
            all_metrics[name] = {
                "type": "counter",
                "value": value,
                "labels": labels,
                **self._metric_metadata.get(name, {}),
            }

        # 게이지
        for key, value in self._gauges.items():
            name, labels = self._parse_key(key)
            all_metrics[name] = {
                "type": "gauge",
                "value": value,
                "labels": labels,
                **self._metric_metadata.get(name, {}),
            }

        # 히스토그램
        for key, hist_data in self._histograms.items():
            name, labels = self._parse_key(key)
            all_metrics[name] = {
                "type": "histogram",
                "histogram": hist_data,
                "labels": labels,
                **self._metric_metadata.get(name, {}),
            }

        # 요약 통계
        for key, summary_data in self._summaries.items():
            name, labels = self._parse_key(key)
            all_metrics[name] = {
                "type": "summary",
                "summary": summary_data,
                "labels": labels,
                **self._metric_metadata.get(name, {}),
            }

        # 메타 정보 추가
        all_metrics["_meta"] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": time.time() - self._start_time,
            "collector_config": self.config.__dict__,
            "metrics_count": len(all_metrics) - 1,  # _meta 제외
        }

        return formatter.format(all_metrics)

    def get_metrics_summary(self) -> dict[str, Any]:
        """메트릭 요약 정보 반환."""
        return {
            "counters": len(self._counters),
            "gauges": len(self._gauges),
            "histograms": len(self._histograms),
            "summaries": len(self._summaries),
            "total_metrics": len(self._counters)
            + len(self._gauges)
            + len(self._histograms)
            + len(self._summaries),
            "uptime_seconds": time.time() - self._start_time,
            "queue_size": self._metric_queue.qsize()
            if self.config.async_collection
            else 0,
            "buffer_size": len(self._batch_buffer),
        }

    # 내부 메서드들
    def _make_key(self, name: str, labels: dict[str, str] | None = None) -> str:
        """메트릭 키 생성."""
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}#{label_str}"

    def _parse_key(self, key: str) -> tuple[str, dict[str, str]]:
        """메트릭 키 파싱."""
        if "#" not in key:
            return key, {}

        name, label_str = key.split("#", 1)
        labels = {}

        if label_str:
            for pair in label_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    labels[k] = v

        return name, labels

    def _set_metadata(
        self, name: str, metric_type: MetricType, labels: dict[str, str] | None = None
    ):
        """메트릭 메타데이터 설정."""
        if name not in self._metric_metadata:
            self._metric_metadata[name] = {
                "type": metric_type.value,
                "created_at": datetime.now(UTC).isoformat(),
            }

    async def _collection_loop(self):
        """비동기 메트릭 수집 루프."""
        while self._running:
            try:
                # 큐에서 메트릭 수집
                metric = await asyncio.wait_for(
                    self._metric_queue.get(), timeout=self.config.collection_interval
                )

                # 배치 버퍼에 추가
                with self._buffer_lock:
                    self._batch_buffer.append(metric)

                    # 배치 크기 확인
                    if len(self._batch_buffer) >= self.config.batch_size:
                        await self._flush_batch()

            except TimeoutError:
                # 타임아웃은 정상적인 동작
                continue
            except Exception as e:
                logger.error("metrics_collection_error", error=str(e))
                await asyncio.sleep(1)  # 에러 시 잠시 대기

    async def _flush_loop(self):
        """배치 플러시 루프."""
        while self._running:
            try:
                await asyncio.sleep(self.config.flush_interval)
                await self._flush_batch()
            except Exception as e:
                logger.error("metrics_flush_error", error=str(e))

    async def _flush_batch(self):
        """배치 메트릭 플러시."""
        if not self._batch_buffer:
            return

        with self._buffer_lock:
            batch = self._batch_buffer.copy()
            self._batch_buffer.clear()

        # 배치 처리
        for metric in batch:
            try:
                if metric.metric_type == MetricType.COUNTER:
                    self.increment_counter(metric.name, metric.value, metric.labels)
                elif metric.metric_type == MetricType.GAUGE:
                    self.set_gauge(metric.name, metric.value, metric.labels)
                elif metric.metric_type == MetricType.HISTOGRAM:
                    self.observe_histogram(metric.name, metric.value, metric.labels)
                elif metric.metric_type == MetricType.SUMMARY:
                    self.observe_summary(metric.name, metric.value, metric.labels)
            except Exception as e:
                logger.warning(
                    "metric_flush_item_error", metric=metric.name, error=str(e)
                )

        logger.debug("metrics_batch_flushed", count=len(batch))

    def reset_metrics(self):
        """모든 메트릭 초기화."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._summaries.clear()
        self._metric_metadata.clear()

        # 큐와 버퍼 클리어
        while not self._metric_queue.empty():
            try:
                self._metric_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        with self._buffer_lock:
            self._batch_buffer.clear()

        logger.info("metrics_reset_completed")


# 편의를 위한 전역 인스턴스
_default_collector: MetricsCollector | None = None


def get_default_collector() -> MetricsCollector:
    """기본 메트릭 수집기 반환."""
    global _default_collector
    if _default_collector is None:
        _default_collector = MetricsCollector()
    return _default_collector


def set_default_collector(collector: MetricsCollector):
    """기본 메트릭 수집기 설정."""
    global _default_collector
    _default_collector = collector


# 편의 함수들
def increment_counter(
    name: str, value: float = 1.0, labels: dict[str, str] | None = None
):
    """기본 수집기를 사용한 카운터 증가."""
    get_default_collector().increment_counter(name, value, labels)


def set_gauge(name: str, value: float, labels: dict[str, str] | None = None):
    """기본 수집기를 사용한 게이지 설정."""
    get_default_collector().set_gauge(name, value, labels)


def observe_histogram(name: str, value: float, labels: dict[str, str] | None = None):
    """기본 수집기를 사용한 히스토그램 관찰."""
    get_default_collector().observe_histogram(name, value, labels)


def observe_summary(name: str, value: float, labels: dict[str, str] | None = None):
    """기본 수집기를 사용한 요약 통계 관찰."""
    get_default_collector().observe_summary(name, value, labels)


def time_function(metric_name: str, labels: dict[str, str] | None = None):
    """기본 수집기를 사용한 함수 타이밍 데코레이터."""
    return get_default_collector().time_function(metric_name, labels)


async def time_context(metric_name: str, labels: dict[str, str] | None = None):
    """기본 수집기를 사용한 시간 측정 컨텍스트 매니저."""
    async with get_default_collector().time_context(metric_name, labels):
        yield


def export_metrics(format_type: str = "json") -> str:
    """기본 수집기를 사용한 메트릭 내보내기."""
    return get_default_collector().export_metrics(format_type)
