"""종가배팅(종베) 계산기 MCP 서버.

데이터 fetching은 호출자(DataCollector 등)가 기존 MCP로 처리.
이 서버는 표준 입력을 받아 결정론적 점수/판단만 반환한다.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 프로젝트 루트
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402
from src.mcp_servers.closing_bet_mcp.catalyst import (  # noqa: E402
    TREND_KEYWORDS,
    match_trends,
    score_catalyst,
)
from src.mcp_servers.closing_bet_mcp.exit_rules import (  # noqa: E402
    evaluate_exit,
    evaluate_market_filter,
)
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores  # noqa: E402

logger = logging.getLogger(__name__)


class ClosingBetMCPServer(BaseMCPServer):
    """종가배팅 계산기 MCP 서버"""

    def __init__(
        self,
        server_name: str = "Closing Bet MCP Server",
        port: int = 8060,
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
                "종가배팅(신정재 룰) 계산기. 데이터 수집은 호출자가 다른 MCP로 처리하고, "
                "이 서버는 OHLCV/뉴스/공시/투자자 데이터를 받아 6기준 점수와 청산 신호를 반환한다. "
                "스코어링은 결정론적이며 백테스트 가능."
            ),
            **kwargs,
        )

    def _initialize_clients(self) -> None:
        # 외부 의존성 없음
        pass

    def _register_tools(self) -> None:
        @self.mcp.tool()
        async def score_catalyst_text(
            news_titles: list[str],
            news_descriptions: list[str] | None = None,
            disclosure_titles: list[str] | None = None,
        ) -> dict[str, Any]:
            """기준 1: 재료 점수.

            Args:
                news_titles: 최근 N일 뉴스 제목 리스트 (다른 MCP로 사전 수집)
                news_descriptions: 뉴스 본문 요약 (선택)
                disclosure_titles: DART 공시 제목 (선택)

            Returns:
                score(0-100), has_catalyst, news_count, disclosure_count,
                matched_trends, matched_keywords, rationale
            """
            try:
                result = score_catalyst(
                    news_titles=news_titles,
                    news_descriptions=news_descriptions,
                    disclosure_titles=disclosure_titles,
                )
                return self.create_standard_response(
                    success=True,
                    query="score_catalyst_text",
                    data=result.to_dict(),
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="score_catalyst_text", error=e,
                )

        @self.mcp.tool()
        async def score_technical_indicators(
            ohlcv: list[dict[str, Any]],
            foreign_net_5d: float | None = None,
            institutional_net_5d: float | None = None,
        ) -> dict[str, Any]:
            """기준 2-6: 기술 점수 (거래량/매물대/캔들/조정/외인기관).

            Args:
                ohlcv: 일봉 리스트, 각 항목은 dict{open,high,low,close,volume,value}.
                       한국어 키(시가/고가/저가/종가/거래량/거래대금)도 지원.
                       최소 21봉, 권장 90봉 이상.
                foreign_net_5d: 외국인 5일 누적 순매수 (부호만 사용)
                institutional_net_5d: 기관 5일 누적 순매수 (부호만 사용)

            Returns:
                volume_surge, resistance_proximity, candle_shape, consolidation,
                institutional, composite (가중 합산), 각 breakdown
            """
            try:
                ts = compute_technical_scores(
                    ohlcv=ohlcv,
                    foreign_net_5d=foreign_net_5d,
                    institutional_net_5d=institutional_net_5d,
                )
                return self.create_standard_response(
                    success=True,
                    query="score_technical_indicators",
                    data=ts.to_dict(),
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="score_technical_indicators", error=e,
                )

        @self.mcp.tool()
        async def score_stock_combined(
            symbol: str,
            company_name: str,
            ohlcv: list[dict[str, Any]],
            news_titles: list[str] | None = None,
            news_descriptions: list[str] | None = None,
            disclosure_titles: list[str] | None = None,
            foreign_net_5d: float | None = None,
            institutional_net_5d: float | None = None,
        ) -> dict[str, Any]:
            """6기준 종합 점수 (재료 30% + 기술 70%).

            DataCollector가 종목별 데이터 다 모은 뒤 한 번에 호출.
            """
            try:
                cat = score_catalyst(
                    news_titles=news_titles or [],
                    news_descriptions=news_descriptions or [],
                    disclosure_titles=disclosure_titles or [],
                )
                tech = compute_technical_scores(
                    ohlcv=ohlcv,
                    foreign_net_5d=foreign_net_5d,
                    institutional_net_5d=institutional_net_5d,
                )
                composite = cat.score * 0.30 + tech.composite() * 0.70

                return self.create_standard_response(
                    success=True,
                    query=f"score_stock_combined: {symbol}",
                    data={
                        "symbol": symbol,
                        "company_name": company_name,
                        "composite": round(composite, 1),
                        "catalyst": cat.to_dict(),
                        "technical": tech.to_dict(),
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="score_stock_combined", error=e, symbol=symbol,
                )

        @self.mcp.tool()
        async def rank_candidates(
            scored_stocks: list[dict[str, Any]],
            top_n: int = 5,
            min_score: float = 50.0,
            prefer_small_cap: bool = True,
        ) -> dict[str, Any]:
            """이미 채점된 종목 리스트를 정렬·필터링.

            Args:
                scored_stocks: 각 dict에 최소 'symbol','composite' 필요.
                               'market_cap' 있으면 small-cap 우선 적용.
                top_n: 최종 반환 개수
                min_score: 통과 기준 점수
                prefer_small_cap: 동점이면 시총 작은 쪽 우선
            """
            try:
                filtered = [s for s in scored_stocks if s.get("composite", 0) >= min_score]
                if prefer_small_cap:
                    filtered.sort(
                        key=lambda x: (
                            -float(x.get("composite", 0)),
                            float(x.get("market_cap") or 1e18),
                        )
                    )
                else:
                    filtered.sort(key=lambda x: -float(x.get("composite", 0)))

                return self.create_standard_response(
                    success=True,
                    query="rank_candidates",
                    data={
                        "total_input": len(scored_stocks),
                        "passed_filter": len(filtered),
                        "candidates": filtered[:top_n],
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="rank_candidates", error=e,
                )

        @self.mcp.tool()
        async def check_market_filter(
            kospi_today_pct: float,
            kospi_5d_pct: float | None = None,
            kospi_volatility: float | None = None,
        ) -> dict[str, Any]:
            """오늘 종가배팅 가능한 시장인지 판단.

            호출자가 KOSPI 등락률을 미리 조회해서 전달.
            """
            try:
                data = evaluate_market_filter(
                    kospi_today_pct=kospi_today_pct,
                    kospi_5d_pct=kospi_5d_pct,
                    kospi_volatility=kospi_volatility,
                )
                return self.create_standard_response(
                    success=True,
                    query="check_market_filter",
                    data=data,
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="check_market_filter", error=e,
                )

        @self.mcp.tool()
        async def check_exit_signal(
            symbol: str,
            entry_price: float,
            current_price: float,
            after_hours_price: float | None = None,
        ) -> dict[str, Any]:
            """매수 후 청산 신호 평가."""
            try:
                d = evaluate_exit(
                    entry_price=entry_price,
                    current_price=current_price,
                    after_hours_price=after_hours_price,
                    now=datetime.now(),
                )
                pnl = (
                    (current_price - entry_price) / entry_price * 100.0
                    if entry_price > 0 else 0.0
                )
                return self.create_standard_response(
                    success=True,
                    query=f"check_exit_signal: {symbol}",
                    data={
                        "symbol": symbol,
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "after_hours_price": after_hours_price,
                        "pnl_pct": round(pnl, 2),
                        **d.to_dict(),
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="check_exit_signal", error=e, symbol=symbol,
                )

        @self.mcp.tool()
        async def match_trend_keywords(texts: list[str]) -> dict[str, Any]:
            """현재 트렌드 키워드 사전과 매칭.

            DataCollector가 뉴스 텍스트를 모은 뒤 트렌드 부합 여부만 빠르게 확인할 때.
            """
            try:
                trends, kws = match_trends(texts)
                return self.create_standard_response(
                    success=True,
                    query="match_trend_keywords",
                    data={
                        "matched_trends": trends,
                        "matched_keywords": kws,
                        "available_trends": list(TREND_KEYWORDS.keys()),
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="match_trend_keywords", error=e,
                )

        @self.mcp.tool()
        async def get_strategy_rules() -> dict[str, Any]:
            """종가배팅 전략 룰 요약 (DataCollector 시스템 프롬프트 보조용)."""
            return self.create_standard_response(
                success=True,
                query="get_strategy_rules",
                data={
                    "buy_window": "장중 14:50 ~ 15:20 (종가 30분 전)",
                    "sell_target": "다음날 갭상승 또는 시초가 ~ 9:05 사이",
                    "selection_criteria_6": [
                        "1. 재료(뉴스/공시) 존재 + 현재 트렌드 부합",
                        "2. 거래대금/거래량 surge (최근 평균 대비 1.5배+)",
                        "3. 매물대(전고점)와 이격 -8%~-3%가 이상적",
                        "4. 캔들 위꼬리 짧은 양봉",
                        "5. 충분한 기간 조정 후 회복 (N자/W형)",
                        "6. 외인·기관 양매수 (특히 대형주)",
                    ],
                    "exit_rules": [
                        "★ 시간외 하락 → 즉시 매도",
                        "★ 매수 평단 이탈 → 즉시 손절",
                        "수익 2-3% 시 일부 익절 (탐욕 X)",
                        "시초가 수익 → 1/3 매도, 9:05 이내 전량",
                        "물타기 금지",
                    ],
                    "market_filter": [
                        "KOSPI 오늘 -1.5% 이하면 종베 비추천",
                        "KOSPI 5일 누적 -3% 이하면 추세 약세",
                    ],
                    "available_trends": list(TREND_KEYWORDS.keys()),
                    "tools_workflow": [
                        "1) check_market_filter(kospi_today_pct=...) — 시장 OK?",
                        "2) 다른 MCP로 거래대금 상위 종목 + 종목별 OHLCV/뉴스/공시/투자자 수집",
                        "3) score_stock_combined(symbol=..., ohlcv=..., news_titles=...)",
                        "4) rank_candidates(scored_stocks=[...]) — 최종 후보 선별",
                        "5) (매수 후) check_exit_signal — 매일 청산 판단",
                    ],
                },
            )


        @self.mcp.tool()
        async def classify_breadth_regime(
            kospi_today_pct: float,
            advance_ratio: float,
            weak_kospi_pct: float = -1.0,
            weak_adv_ratio: float = 0.35,
            strong_kospi_pct: float = 0.5,
            strong_adv_ratio: float = 0.55,
        ) -> dict[str, Any]:
            """시장 강도(Breadth) 기반 레짐 분류 — 라이브 거래 흐름 내장용.

            PLAYBOOK A 레짐 판정 로직을 MCP 툴로 노출한다.
            DataCollector가 KOSPI 등락률과 universe 양봉 비율을 계산한 뒤 호출.

            Args:
                kospi_today_pct: KOSPI 당일 등락률 (%) — 시가 대비 현재가 또는 종가
                advance_ratio:   daily universe 내 양봉 비율 (0.0 ~ 1.0)
                weak_kospi_pct:  KOSPI 이 값 미만이면 weak 단독 트리거 (기본 -1.0%)
                weak_adv_ratio:  advance_ratio 이 값 미만이면 weak (기본 0.35)
                strong_kospi_pct: KOSPI 이 값 초과 (기본 +0.5%)
                strong_adv_ratio: advance_ratio 이 값 이상이면 strong (기본 0.55)

            Returns:
                regime: "strong" | "neutral" | "weak"
                recommendation: 레짐별 행동 지침
                inputs: 입력값 에코
            """
            try:
                if kospi_today_pct > strong_kospi_pct and advance_ratio >= strong_adv_ratio:
                    regime = "strong"
                elif kospi_today_pct < weak_kospi_pct or advance_ratio < weak_adv_ratio:
                    regime = "weak"
                else:
                    regime = "neutral"

                recommendations = {
                    "strong": (
                        "강세장 — 종가매매 threshold 70 이상 적용 (노이즈 경고). "
                        "섹터RS 상위 섹터 내 거래량 급증 종목 우선."
                    ),
                    "neutral": (
                        "중립장 — 종가매매 threshold 65, 섹터RS 상위 섹터 집중 권장. "
                        "거래량 신호가 가장 깨끗한 레짐 (역사적 승률 최우수)."
                    ),
                    "weak": (
                        "약세장 — 종가매매 threshold 50 기본 유지 (1차 백테스트 기준 58.7%/+1.10%). "
                        "RS·섹터 필터 적용 시 오히려 역효과 주의. 포지션 수 축소 고려."
                    ),
                }

                return self.create_standard_response(
                    success=True,
                    query="classify_breadth_regime",
                    data={
                        "regime": regime,
                        "recommendation": recommendations[regime],
                        "inputs": {
                            "kospi_today_pct": round(kospi_today_pct, 2),
                            "advance_ratio": round(advance_ratio, 3),
                            "weak_trigger": (
                                kospi_today_pct < weak_kospi_pct or
                                advance_ratio < weak_adv_ratio
                            ),
                            "strong_trigger": (
                                kospi_today_pct > strong_kospi_pct and
                                advance_ratio >= strong_adv_ratio
                            ),
                        },
                    },
                )
            except Exception as e:
                return await self.create_error_response(
                    func_name="classify_breadth_regime", error=e,
                )


if __name__ == "__main__":
    try:
        server = ClosingBetMCPServer()

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

        logger.info(f"Starting Closing Bet MCP Server on {server.host}:{server.port}")
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Closing Bet MCP Server stopped")
