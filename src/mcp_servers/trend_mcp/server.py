"""대형주 추세추종 MCP 서버 — signals.py 순수함수를 외부 호출용 도구로 노출.

데이터 fetching 은 호출자(추세추종 데몬 등)가 다른 MCP/pykrx 로 처리.
이 서버는 표준 입력을 받아 결정론적 신호/판단/사이징만 반환한다 (.env·DB·로깅 부수효과 없음).

데몬(scripts/trend_follow.py) 은 성능을 위해 signals.py 를 직접 import 하고,
이 서버는 외부 에이전트/대시보드/자동화 도구의 진입점 역할.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402


_DEFAULT_EXITS = ("ma", "hold")     # 2026-08-28 워크포워드 채택


def _live_exits() -> tuple[str, ...]:
    """운용 중인 청산 사다리 구성.

    `scripts/trend_config` 를 import 하지 않는다 — 순수 도메인(src/)이 스크립트(scripts/)를
    참조하는 역방향 의존은 2026-08-17 에 제거한 것이다. 대신 **같은 환경변수**를 읽어
    데몬과 값을 공유한다. 미설정 시 채택 기본값.
    """
    raw = os.getenv("TREND_EXITS", "")
    toks = tuple(t.strip() for t in raw.split(",") if t.strip())
    valid = {"partial", "trail", "ma", "hold"}
    return tuple(t for t in toks if t in valid) or _DEFAULT_EXITS

from src.mcp_servers.trend_mcp.signals import (  # noqa: E402
    TrendConfig,
    classify_zone,
    entry_signal,
    exit_decision,
    leading_sectors,
    position_size,
)

logger = logging.getLogger(__name__)


class TrendMCPServer(BaseMCPServer):
    """대형주 추세추종 계산기 MCP 서버"""

    def __init__(
        self,
        server_name: str = "Trend Follow MCP Server",
        port: int = 8061,
        host: str = "0.0.0.0",
        debug: bool = False,
        **kwargs,
    ):
        super().__init__(
            server_name=server_name,
            port=port,
            host=host,
            debug=debug,
            server_instructions=(
                "대형주 추세추종(블로그A/B 룰) 계산기. 데이터 수집은 호출자가 처리하고, "
                "이 서버는 OHLCV/KOSPI 종가/업종지수 데이터를 받아 진입·청산·사이징 신호를 반환한다. "
                "결정론적이고 백테스트 검증된 함수들."
            ),
            **kwargs,
        )

    def _initialize_clients(self) -> None:
        # 외부 의존성 없음
        pass

    def _register_tools(self) -> None:
        @self.mcp.tool()
        async def evaluate_entry_signal(
            ohlcv: list[dict[str, Any]],
            kospi_closes: list[float],
            mode: str = "largecap",
            rs_pass: bool | None = None,
            foreign_net: float | None = None,
            inst_net: float | None = None,
        ) -> dict[str, Any]:
            """추세추종 진입 게이트 + 점수 + 손절/목표 평가.

            Args:
                ohlcv: 일봉 리스트 [{date, open, high, low, close, volume, value}], 최소 121봉 권장.
                kospi_closes: KOSPI 일봉 종가 시계열 (상대강도 RS 계산용).
                mode: gainers | largecap | watchlist.
                rs_pass: RS 게이트 외부 오버라이드 (None=절대 RS>KOSPI 기본).
                foreign_net, inst_net: 외인/기관 5일 순매수 (가점 계산용, 선택).

            Returns:
                passed, score, breakdown(게이트별), entry_price, stop_price, target, atr, ...
            """
            try:
                cfg = TrendConfig(mode=mode)
                sig = entry_signal(
                    ohlcv=ohlcv, kospi_closes=kospi_closes, cfg=cfg,
                    foreign_net=foreign_net, inst_net=inst_net, rs_pass=rs_pass,
                )
                return self.create_standard_response(
                    success=True,
                    query=f"evaluate_entry_signal: mode={mode}",
                    data=asdict(sig),   # TrendSignal 은 dataclass — to_dict 없음(구 분기 제거)
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="evaluate_entry_signal", error=e,
                )

        @self.mcp.tool()
        async def evaluate_exit_decision(
            entry: float,
            cur: float,
            qty: int,
            target: float,
            stop: float,
            partial_done: bool = False,
            hard_stop_pct: float = 0.0,
            partial_pct: float = 30.0,
            ma_exit: float | None = None,
            exit_ma_label: int = 120,
            foreign_net: float | None = None,
            use_foreign: bool = False,
            exits: list[str] | None = None,
        ) -> dict[str, Any]:
            """포지션 청산/부분익절 판정 → (action, reason, sell_qty).

            우선순위: 하드손절 → 첫목표 부분익절 → 트레일/손절 이탈 → 이평선 이탈 → 외인 전환.
            ma_exit/foreign_net 은 청산 phase(15:20) 에서만 호출자가 채워 넘김.

            exits: 사다리 구성(partial/trail/ma/hold). 생략하면 **운용 중인 구성**을 쓴다.
            2026-08-28 워크포워드 채택은 `["ma","hold"]` — 트레일·부분익절은 12년 표본에서
            거래당 -0.57% 를 만든 원인이라 제거됐다. 이 도구가 구 4단 사다리로 고정돼 있으면
            외부 에이전트가 운용하지 않는 전략의 판정을 받는다.
            하드손절은 목록에 없다: 전략 선택지가 아니라 위험 바닥이라 항상 적용된다.
            """
            try:
                ladder = tuple(exits) if exits else _live_exits()
                action, reason, sell_qty = exit_decision(
                    entry=entry, cur=cur, qty=qty, target=target, stop=stop,
                    partial_done=partial_done, hard_stop_pct=hard_stop_pct,
                    partial_pct=partial_pct, ma_exit=ma_exit, exit_ma_label=exit_ma_label,
                    foreign_net=foreign_net, use_foreign=use_foreign, exits=ladder,
                )
                pnl_pct = (cur - entry) / entry * 100 if entry > 0 else 0.0
                return self.create_standard_response(
                    success=True,
                    query="evaluate_exit_decision",
                    data={
                        "action": action,                 # None | "PARTIAL" | "EXIT"
                        "reason": reason,
                        "sell_qty": sell_qty,
                        "pnl_pct": round(pnl_pct, 2),
                        "exits": list(ladder),            # 어떤 사다리로 판정했는지 명시
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="evaluate_exit_decision", error=e,
                )

        @self.mcp.tool()
        async def classify_jh_zone(
            price: float,
            ma60: float | None,
            ma120: float | None,
            held: bool = False,
            stop_price: float | None = None,
        ) -> dict[str, Any]:
            """JH ZONE 판정 (PDF 설계가이드) — GO/HOLD/CAUTION/STOP_LOSS/WATCH.

            미보유(후보): GO=60일선 부근 정배열 진입최적 / WATCH=추세 위지만 진입존 밖.
            보유: STOP_LOSS=손절가/MA120 이탈 / CAUTION=MA60 이탈 / HOLD=추세 유지.
            """
            try:
                zone = classify_zone(price, ma60, ma120, held=held, stop_price=stop_price)
                return self.create_standard_response(
                    success=True,
                    query="classify_jh_zone",
                    data={"zone": zone, "held": held, "price": price,
                          "ma60": ma60, "ma120": ma120, "stop_price": stop_price},
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="classify_jh_zone", error=e,
                )

        @self.mcp.tool()
        async def detect_leading_sectors(
            sector_rows: list[dict[str, Any]],
            min_avg_pct: float = 1.0,
            min_breadth: float = 0.6,
            min_count: int = 3,
            top_k: int = 3,
        ) -> dict[str, Any]:
            """당일 주도섹터(집단상승) 판정 — 키움 ka20001 업종지수 스냅샷 기반.

            Args:
                sector_rows: [{sector, change_pct, rising, falling, flat}] (구성종목 수 포함).
                min_avg_pct: 등락률 하한(%) (기본 1.0).
                min_breadth: 상승종목 비율 하한 (기본 0.6).
                min_count: 구성종목 최소 수 (기본 3).
                top_k: 상위 N (기본 3).
            """
            try:
                leaders = leading_sectors(
                    sector_rows, min_avg_pct=min_avg_pct, min_breadth=min_breadth,
                    min_count=min_count, top_k=top_k,
                )
                return self.create_standard_response(
                    success=True,
                    query=f"detect_leading_sectors: top_k={top_k}",
                    data={"leaders": leaders, "input_count": len(sector_rows)},
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="detect_leading_sectors", error=e,
                )

        @self.mcp.tool()
        async def calculate_position_size(
            price: float,
            mode: str = "pct_equity",
            equity: float = 0.0,
            cash: float = 0.0,
            pct: float = 8.0,
            invest_fixed: float = 500000.0,
        ) -> dict[str, Any]:
            """매수 수량 계산.

            mode=pct_equity: 예탁자산 pct% (현금 한도 내). equity<=0 또는 mode=fixed: 고정금액(invest_fixed).
            """
            try:
                qty = position_size(
                    price=price, mode=mode, equity=equity, cash=cash,
                    pct=pct, invest_fixed=invest_fixed,
                )
                est_cost = qty * price
                return self.create_standard_response(
                    success=True,
                    query=f"calculate_position_size: price={price}",
                    data={
                        "qty": qty,
                        "est_cost": round(est_cost),
                        "mode": mode, "price": price,
                        "equity": equity, "cash": cash,
                        "pct": pct, "invest_fixed": invest_fixed,
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="calculate_position_size", error=e,
                )

        @self.mcp.tool()
        async def get_strategy_rules() -> dict[str, Any]:
            """대형주 추세추종 전략 룰 요약 (외부 에이전트 시스템 프롬프트 보조용)."""
            return self.create_standard_response(
                success=True,
                query="get_strategy_rules",
                data={
                    "universe": (
                        f"KOSPI 시총상위 {os.getenv('TREND_TOP_N', '100')} "
                        f"(거래대금 {int(float(os.getenv('TREND_MIN_VALUE_KRW', '1e11'))) // 100000000:,}억 이상). "
                        "백테스트는 시점별 시총 재산정(--pit) 사용 — 현재 스냅샷 소급은 생존편향"
                    ),
                    "entry_gate": (
                        "현재가 > MA60 & MA120(정배열) + RS(60일) > KOSPI(절대) + "
                        "MA20 ≤ 현재가 ≤ MA20×1.12(눌림 상·하한) + 거래량 ≥ 20일평균"
                    ),
                    "market_gate": (
                        f"KOSPI > MA{os.getenv('TREND_REGIME_MA', '60')}(레짐) + "
                        f"breadth ≥ {os.getenv('TREND_BREADTH_MIN_PCT', '0.4')} + "
                        f"일일손실 서킷 {os.getenv('TREND_DAILY_LOSS_LIMIT_PCT', '2')}%"
                    ),
                    "entry_timing": (
                        f"{os.getenv('TREND_ENTRY_TIME', '11:00')} "
                        f"(상승중 즉시 / 하락중 보류→반등 진입, "
                        f"{os.getenv('TREND_ENTRY_CUTOFF', '14:00')} 마감)"
                    ),
                    "exit": (
                        f"사다리 {','.join(_live_exits())} — "
                        f"MA{os.getenv('TREND_EXIT_MA', '120')} 종가 이탈 / "
                        f"{os.getenv('TREND_MAX_HOLD', '120')}영업일 시간청산. "
                        f"하드손절 {os.getenv('TREND_HARD_STOP_PCT', '10')}%(구성과 무관한 위험 바닥)"
                    ),
                    "exit_removed": (
                        "ATR 트레일·첫목표 30% 부분익절·외인 5일 순매도 — 2026-08-28 제거. "
                        "12년 시점별 표본에서 트레일이 거래당 -0.57%(PF 0.84)의 원인이었고, "
                        "같은 진입에 청산만 바꾸면 +7.40%(PF 2.15). "
                        "워크포워드 8폴드에서 구 4단 사다리는 한 번도 선택되지 않았다"
                    ),
                    "stop_target": (
                        "ATR 기준손절·목표(진입+3×손절폭)는 **청산을 발동하지 않는다** — "
                        "그림자 원장의 R 배수 측정 기준으로만 쓰인다"
                    ),
                    "sizing": (
                        f"예탁자산 {os.getenv('TREND_POSITION_PCT', '5')}% 균등 × "
                        f"최대 {os.getenv('TREND_MAX_POS', '20')}종목. "
                        "⚠️ 정수 주식수 제약 때문에 계좌 크기가 결과를 바꾼다 — "
                        "소액 계좌는 비싼 종목이 통째로 매수 불가가 되어 검증 유니버스와 갈린다"
                    ),
                    "pyramiding": "영구 비활성 — 12년 표본 마이너스, 2026-06-22 손실의 67%",
                    "validated_backtest": (
                        "워크포워드(학습4년/검증1년 롤링, 실계좌 예탁 기준, 2015-2026 8폴드): "
                        "OOS 누적 +234.8% · CAGR 17.6% · MDD 18.4% · MAR 0.96 "
                        "(동일가중 벤치마크 MAR 0.58) · 플러스 7/8 연도. "
                        "유니버스 생존편향은 전략·벤치마크가 공유 — 상대 비교만 유효"
                    ),
                    "validation_policy": (
                        "단일 구간 in-sample 채택 금지. 판정 기준을 측정 전에 코드 상수로 "
                        "선언·커밋하고, 워크포워드 OOS 로만 채택한다. "
                        "매년 1월 `walkforward_trend.py --select-now` 로 규칙 재선택"
                    ),
                    "tools_workflow": [
                        "1) 데이터 수집(다른 MCP·pykrx): OHLCV + KOSPI 종가 + (선택) 외인/기관/업종지수",
                        "2) evaluate_entry_signal — 진입 게이트/점수/손절/목표",
                        "3) detect_leading_sectors — 주도섹터 가점/게이트(선택)",
                        "4) calculate_position_size — 사이징",
                        "5) (보유 중) evaluate_exit_decision — 청산 판정",
                        "6) (옵션) classify_jh_zone — JH ZONE 시각 표시",
                    ],
                },
            )


if __name__ == "__main__":
    try:
        server = TrendMCPServer()

        @server.mcp.custom_route(
            path="/health",
            methods=["GET", "OPTIONS"],
            include_in_schema=True,
        )
        async def health_check(request):
            from starlette.responses import JSONResponse
            return JSONResponse(
                content=server.create_standard_response(
                    success=True, query="MCP Server Health check", data="OK",
                ),
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )

        @server.mcp.custom_route(
            path="/{path:path}",
            methods=["OPTIONS"],
            include_in_schema=False,
        )
        async def handle_options(request):
            from starlette.responses import Response
            return Response(
                content="",
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "3600",
                },
            )

        logger.info(f"Starting Trend Follow MCP Server on {server.host}:{server.port}")
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Trend Follow MCP Server stopped")
