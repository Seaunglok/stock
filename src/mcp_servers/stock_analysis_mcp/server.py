"""주식 분석 MCP 서버

BaseMCPServer 패턴을 활용하여 복잡한 다중 요인 분석기와 모델들을 제거하고
핵심 주식 분석 기능에 집중한 간소한 구조로 재구성했습니다.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_servers.base.base_mcp_server import BaseMCPServer  # noqa: E402
from src.mcp_servers.stock_analysis_mcp.korean_market import (  # noqa: E402
    KoreanMarketUtils,
)
from src.mcp_servers.stock_analysis_mcp.stock_client import StockClient  # noqa: E402

logger = logging.getLogger(__name__)


class StockAnalysisMCPServer(BaseMCPServer):
    """주식 분석 MCP 서버 구현"""

    def __init__(
        self,
        server_name: str = "Stock Analysis MCP Server",
        port: int = 8042,
        host: str = "0.0.0.0",
        debug: bool = False,
        **kwargs,
    ):
        """
        주식 분석 MCP 서버 초기화

        Args:
            server_name: 서버 이름
            port: 서버 포트
            host: 호스트 주소
            debug: 디버그 모드
            **kwargs: 추가 옵션
        """
        super().__init__(
            server_name=server_name,
            port=port,
            host=host,
            debug=debug,
            server_instructions="기술적/기본적/감정 분석을 통합하여 종합적인 주식 투자 신호를 제공합니다",
            **kwargs,
        )

    def _initialize_clients(self) -> None:
        """주식 분석 클라이언트 초기화"""
        try:
            # 환경변수 검증
            self._validate_environment()

            # 오프라인 모드 설정 (환경변수 또는 기본값)
            offline_mode = os.getenv("STOCK_OFFLINE_MODE", "false").lower() == "true"

            # 주식 분석 클라이언트 초기화
            self.stock_client = StockClient(offline_mode=offline_mode)

            # 한국 시장 유틸리티 초기화
            self.korean_market = KoreanMarketUtils()

            logger.info(
                f"Stock analysis client initialized successfully (offline_mode: {offline_mode})"
            )

        except Exception as e:
            logger.error(f"Failed to initialize stock analysis client: {e}")

    def _validate_environment(self) -> None:
        """환경변수 검증"""
        # 선택적 환경변수들
        recommended_vars = []

        missing_vars = []
        for var in recommended_vars:
            if not os.getenv(var):
                missing_vars.append(var)

        if missing_vars:
            logger.warning(
                f"Recommended environment variables missing: {', '.join(missing_vars)}. "
                "Will run in mock mode with simulated data."
            )

    def _register_tools(self) -> None:
        """MCP 도구들을 등록"""

        # === 개별 분석 도구들 ===

        @self.mcp.tool()
        async def analyze_technical_indicators(
            symbol: str,
        ) -> dict[str, Any]:
            """
            기술적 분석 수행

            Args:
                symbol: 종목코드 (예: "005930")

            Returns:
                RSI, MACD, 이동평균 등 기술적 지표 분석 결과
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="analyze_technical_indicators",
                        error="StockClient not initialized",
                        symbol=symbol,
                    )

                # 실제 기술적 분석 수행
                result = await self.stock_client.analyze_technical(symbol)

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_technical_indicators: {symbol}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_technical_indicators",
                    error=e,
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def analyze_fundamental_metrics(
            symbol: str,
        ) -> dict[str, Any]:
            """
            기본적 분석 수행

            Args:
                symbol: 종목코드

            Returns:
                P/E, P/B, ROE 등 기본적 지표 분석 결과
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="analyze_fundamental_metrics",
                        error="StockClient not initialized",
                        symbol=symbol,
                    )

                # 실제 기본적 분석 수행
                result = await self.stock_client.analyze_fundamental(symbol)

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_fundamental_metrics: {symbol}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_fundamental_metrics",
                    error=e,
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def analyze_market_sentiment(
            symbol: str,
        ) -> dict[str, Any]:
            """
            감정 분석 수행

            Args:
                symbol: 종목코드

            Returns:
                뉴스, 소셜미디어 기반 감정 분석 결과
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="analyze_market_sentiment",
                        error="StockClient not initialized",
                        symbol=symbol,
                    )

                # 실제 감정 분석 수행
                result = await self.stock_client.analyze_sentiment(symbol)

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_market_sentiment: {symbol}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_market_sentiment",
                    error=e,
                    symbol=symbol,
                )

        # === 통합 분석 도구들 ===

        @self.mcp.tool()
        async def generate_comprehensive_analysis(
            symbol: str,
            custom_weights: list[dict[str, float]] | None = None,
        ) -> dict[str, Any]:
            """
            종합 주식 분석 수행

            Args:
                symbol: 종목코드
                custom_weights: 사용자 정의 가중치 (선택)

            Returns:
                기술적/기본적/감정 분석을 통합한 종합 투자 신호
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="generate_comprehensive_analysis",
                        error="StockClient not initialized",
                        symbol=symbol,
                    )

                # 사용자 정의 가중치 적용
                if custom_weights:
                    original_weights = self.stock_client.analysis_weights.copy()
                    self.stock_client.analysis_weights.update(custom_weights)

                # 실제 종합 분석 수행
                result = await self.stock_client.analyze_stock_comprehensive(symbol)

                # 가중치 복원
                if custom_weights:
                    self.stock_client.analysis_weights = original_weights

                return self.create_standard_response(
                    success=True,
                    query=f"generate_comprehensive_analysis: {symbol}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="generate_comprehensive_analysis",
                    error=e,
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def evaluate_investment_consensus(
            individual_signals: list[dict[str, Any]],
        ) -> dict[str, Any]:
            """
            개별 분석 신호간 합의 수준 평가

            Args:
                individual_signals: 개별 분석 결과 리스트

            Returns:
                신호 합의 수준 및 상충 여부 분석
            """
            try:
                # 신호별 개수 계산
                signal_counts = {}
                total_confidence = 0.0

                for signal_data in individual_signals:
                    signal = signal_data.get("signal", "hold")
                    confidence = signal_data.get("confidence_score", 0.5)

                    if signal not in signal_counts:
                        signal_counts[signal] = {"count": 0, "confidence_sum": 0.0}

                    signal_counts[signal]["count"] += 1
                    signal_counts[signal]["confidence_sum"] += confidence
                    total_confidence += confidence

                # 합의 수준 계산
                total_signals = len(individual_signals)
                avg_confidence = (
                    total_confidence / total_signals if total_signals > 0 else 0.0
                )

                if signal_counts:
                    most_common_signal = max(
                        signal_counts.items(), key=lambda x: x[1]["count"]
                    )
                    consensus_level = most_common_signal[1]["count"] / total_signals
                    dominant_signal = most_common_signal[0]
                else:
                    consensus_level = 0.0
                    dominant_signal = "hold"

                # 상충 여부 확인
                buy_signals = sum(
                    data["count"]
                    for signal, data in signal_counts.items()
                    if signal in ["strong_buy", "buy"]
                )
                sell_signals = sum(
                    data["count"]
                    for signal, data in signal_counts.items()
                    if signal in ["strong_sell", "sell"]
                )

                has_conflicts = buy_signals > 0 and sell_signals > 0

                consensus_result = {
                    "consensus_level": round(consensus_level, 2),
                    "avg_confidence": round(avg_confidence, 2),
                    "dominant_signal": dominant_signal,
                    "has_conflicts": has_conflicts,
                    "signal_distribution": signal_counts,
                    "total_signals": total_signals,
                    "interpretation": "높은 합의도"
                    if consensus_level >= 0.8
                    else "중간 합의도"
                    if consensus_level >= 0.6
                    else "낮은 합의도",
                }

                return self.create_standard_response(
                    success=True,
                    query=f"evaluate_investment_consensus: {total_signals} signals",
                    data=consensus_result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="evaluate_investment_consensus",
                    error=e,
                    total_signals=len(individual_signals),
                )

        @self.mcp.tool()
        async def assess_investment_risk(
            symbol: str,
            analysis_results: list[dict[str, Any]],
        ) -> dict[str, Any]:
            """
            투자 리스크 평가

            Args:
                symbol: 종목코드
                analysis_results: 분석 결과 리스트

            Returns:
                종합적인 투자 리스크 평가 결과
            """
            try:
                # 기본 리스크 지표 계산
                total_analyses = len(analysis_results)
                low_confidence_count = sum(
                    1
                    for result in analysis_results
                    if result.get("confidence_score", 0.5) < 0.6
                )

                # 신호 상충 확인
                buy_signals = sum(
                    1
                    for result in analysis_results
                    if result.get("signal", "hold") in ["strong_buy", "buy"]
                )
                sell_signals = sum(
                    1
                    for result in analysis_results
                    if result.get("signal", "hold") in ["strong_sell", "sell"]
                )

                has_conflicts = buy_signals > 0 and sell_signals > 0

                # 평균 신뢰도 계산
                avg_confidence = (
                    sum(
                        result.get("confidence_score", 0.5)
                        for result in analysis_results
                    )
                    / total_analyses
                    if total_analyses > 0
                    else 0.0
                )

                # 리스크 점수 계산
                risk_score = 0.0

                if has_conflicts:
                    risk_score += 0.3

                if low_confidence_count > total_analyses / 2:
                    risk_score += 0.3

                if total_analyses < 3:
                    risk_score += 0.2

                risk_score += (1.0 - avg_confidence) * 0.2

                # 리스크 수준 결정
                if risk_score <= 0.3:
                    risk_level = "낮음"
                    recommendation = "안전한 투자 환경으로 판단됩니다."
                elif risk_score <= 0.6:
                    risk_level = "중간"
                    recommendation = "적절한 주의를 가지고 투자를 고려하세요."
                else:
                    risk_level = "높음"
                    recommendation = "높은 리스크로 신중한 투자 판단이 필요합니다."

                # 리스크 요인 식별
                risk_factors = []
                if has_conflicts:
                    risk_factors.append("분석간 신호 상충")
                if low_confidence_count > total_analyses / 2:
                    risk_factors.append("다수 분석의 낮은 신뢰도")
                if total_analyses < 3:
                    risk_factors.append("제한적인 분석 데이터")
                if avg_confidence < 0.6:
                    risk_factors.append("전반적으로 낮은 신뢰도")

                risk_assessment = {
                    "symbol": symbol,
                    "risk_level": risk_level,
                    "risk_score": round(risk_score, 2),
                    "avg_confidence": round(avg_confidence, 2),
                    "has_conflicts": has_conflicts,
                    "risk_factors": risk_factors,
                    "recommendation": recommendation,
                    "total_analyses": total_analyses,
                    "low_confidence_count": low_confidence_count,
                }

                return self.create_standard_response(
                    success=True,
                    query=f"assess_investment_risk: {symbol}",
                    data=risk_assessment,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="assess_investment_risk",
                    error=e,
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def get_analysis_weights() -> dict[str, Any]:
            """
            현재 분석 가중치 조회

            Returns:
                기술적/기본적/감정 분석의 현재 가중치 설정
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="get_analysis_weights",
                        error="StockClient not initialized",
                    )

                weights = self.stock_client.analysis_weights
                thresholds = self.stock_client.signal_thresholds

                weights_info = {
                    "analysis_weights": weights,
                    "signal_thresholds": thresholds,
                    "total_weight": sum(weights.values()),
                    "description": "분석 유형별 가중치 및 신호 임계값 설정",
                }

                return self.create_standard_response(
                    success=True,
                    query="get_analysis_weights",
                    data=weights_info,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_analysis_weights",
                    error=e,
                )

        # === 종목 정보 조회 도구들 ===

        @self.mcp.tool()
        async def get_stock_list(
            market: str = "ALL",
            limit: int = 50,
        ) -> dict[str, Any]:
            """
            한국 주식 종목 리스트 조회

            Args:
                market: 시장 구분 ("KOSPI", "KOSDAQ", "KONEX", "ALL")
                limit: 반환할 최대 종목 수 (기본값: 50)

            Returns:
                시가총액 기준 정렬된 종목 리스트
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="get_stock_list",
                        error="StockClient not initialized",
                        market=market,
                    )

                # 실제 종목 리스트 조회
                result = await self.stock_client.get_stock_list(
                    market=market, limit=limit
                )

                return self.create_standard_response(
                    success=True,
                    query=f"get_stock_list: {market}, limit={limit}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_stock_list",
                    error=e,
                    market=market,
                    limit=limit,
                )

        @self.mcp.tool()
        async def search_stocks(
            query: str,
            limit: int = 20,
        ) -> dict[str, Any]:
            """
            종목명/코드로 검색 (difflib 기반 유사도 검색)

            Args:
                query: 검색어 (종목명 또는 종목코드)
                limit: 반환할 최대 종목 수 (기본값: 20)

            Returns:
                유사도 순으로 정렬된 검색 결과
            """
            try:
                if not self.stock_client:
                    return await self.create_error_response(
                        func_name="search_stocks",
                        error="StockClient not initialized",
                        query=query,
                    )

                # 실제 종목 검색
                result = await self.stock_client.search_stocks(query=query, limit=limit)

                return self.create_standard_response(
                    success=True,
                    query=f"search_stocks: '{query}', limit={limit}",
                    data=result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="search_stocks",
                    error=e,
                    query=query,
                    limit=limit,
                )

        # === 한국 시장 정보 도구들 ===

        @self.mcp.tool()
        async def get_korean_market_status() -> dict[str, Any]:
            """
            현재 한국 주식 시장 상태 조회

            Returns:
                현재 장중 여부, 시장 상태, 거래 시간 정보
            """
            try:
                if not self.korean_market:
                    return await self.create_error_response(
                        func_name="get_korean_market_status",
                        error="KoreanMarketUtils not initialized",
                    )

                current_time = self.korean_market.get_current_time()
                is_market_open = self.korean_market.is_market_hours()
                is_high_volume = self.korean_market.is_high_volume_period()
                status_message = self.korean_market.get_market_status_message()
                risk_factor = self.korean_market.get_market_risk_factor()

                market_status = {
                    "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S KST"),
                    "is_market_open": is_market_open,
                    "is_high_volume_period": is_high_volume,
                    "status_message": status_message,
                    "risk_factor": risk_factor,
                    "market_config": {
                        "open_time": "09:00",
                        "close_time": "15:30",
                        "lunch_break": "12:00-13:00",
                        "high_volume_periods": ["09:00-09:30", "15:00-15:30"],
                    },
                }

                return self.create_standard_response(
                    success=True,
                    query="get_korean_market_status",
                    data=market_status,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_korean_market_status",
                    error=e,
                )

        @self.mcp.tool()
        async def validate_korean_stock_symbol(
            symbol: str,
        ) -> dict[str, Any]:
            """
            한국 주식 종목 코드 유효성 검증

            Args:
                symbol: 종목코드 (6자리 숫자)

            Returns:
                종목 코드 유효성 및 시장 구분 정보
            """
            try:
                if not self.korean_market:
                    return await self.create_error_response(
                        func_name="validate_korean_stock_symbol",
                        error="KoreanMarketUtils not initialized",
                        symbol=symbol,
                    )

                is_valid, message = self.korean_market.validate_stock_symbol(symbol)
                market_type = self.korean_market.get_market_type(symbol)
                is_kosdaq = self.korean_market.is_kosdaq_symbol(symbol)

                validation_result = {
                    "symbol": symbol,
                    "is_valid": is_valid,
                    "message": message,
                    "market_type": market_type,
                    "is_kosdaq": is_kosdaq,
                    "kosdaq_risk_premium": self.korean_market.config.kosdaq_risk_premium
                    if is_kosdaq
                    else 0.0,
                }

                return self.create_standard_response(
                    success=True,
                    query=f"validate_korean_stock_symbol: {symbol}",
                    data=validation_result,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="validate_korean_stock_symbol",
                    error=e,
                    symbol=symbol,
                )

        @self.mcp.tool()
        async def get_trading_time_recommendations() -> dict[str, Any]:
            """
            현재 시간 기준(Asia/Seoul) 거래 시간 추천

            Returns:
                현재 시간대별 거래 전략 및 리스크 팩터 추천
            """
            try:
                if not self.korean_market:
                    return await self.create_error_response(
                        func_name="get_trading_time_recommendations",
                        error="KoreanMarketUtils not initialized",
                    )

                current_time = self.korean_market.get_current_time()
                is_market_open = self.korean_market.is_market_hours()
                is_high_volume = self.korean_market.is_high_volume_period()
                status_message = self.korean_market.get_market_status_message()
                risk_factor = self.korean_market.get_market_risk_factor()

                # 시간대별 추천사항
                recommendations = []

                if not is_market_open:
                    recommendations.extend(
                        [
                            "장외 시간으로 현재 거래 불가",
                            "다음 거래일 전략 수립에 집중",
                            "해외 시장 동향 및 뉴스 모니터링 권장",
                        ]
                    )
                elif is_high_volume:
                    recommendations.extend(
                        [
                            "집중 거래 시간대로 유동성이 높음",
                            "변동성 증가에 주의하여 거래",
                            "급격한 가격 변동 가능성 높음",
                        ]
                    )
                elif current_time.time().hour < 12:
                    recommendations.extend(
                        [
                            "오전장으로 하루 트렌드 형성 시간",
                            "전일 해외 시장 영향 확인 필요",
                            "신중한 포지션 진입 권장",
                        ]
                    )
                else:
                    recommendations.extend(
                        [
                            "오후장으로 하루 마무리 단계",
                            "포지션 정리 및 익절/손절 고려",
                            "내일 전략 수립 시간",
                        ]
                    )

                time_recommendations = {
                    "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S KST"),
                    "market_status": status_message,
                    "is_market_open": is_market_open,
                    "is_high_volume_period": is_high_volume,
                    "risk_factor": risk_factor,
                    "recommendations": recommendations,
                    "optimal_trading_times": [
                        "09:00-09:30 (개장 초 유동성)",
                        "10:00-11:30 (안정적 거래)",
                        "13:00-14:30 (오후 첫 거래)",
                        "15:00-15:30 (마감 전 정리)",
                    ],
                }

                return self.create_standard_response(
                    success=True,
                    query="get_trading_time_recommendations",
                    data=time_recommendations,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="get_trading_time_recommendations",
                    error=e,
                )

        @self.mcp.tool()
        async def analyze_market_timing_risk(
            intended_action: str = "buy",
        ) -> dict[str, Any]:
            """
            현재 시점의 시장 타이밍 리스크 분석

            Args:
                intended_action: 의도한 거래 행동 ("buy", "sell", "hold")

            Returns:
                현재 시점의 타이밍 리스크 및 권장사항
            """
            try:
                if not self.korean_market:
                    return await self.create_error_response(
                        func_name="analyze_market_timing_risk",
                        error="KoreanMarketUtils not initialized",
                        intended_action=intended_action,
                    )

                current_time = self.korean_market.get_current_time()
                is_market_open = self.korean_market.is_market_hours()
                is_high_volume = self.korean_market.is_high_volume_period()
                base_risk_factor = self.korean_market.get_market_risk_factor()

                # 시간대별 리스크 조정
                timing_risk_score = 0.5  # 기본 리스크

                if not is_market_open:
                    timing_risk_score = 0.2  # 장외 시간은 리스크 낮음
                    risk_level = "낮음"
                    timing_message = "장외 시간으로 즉시 거래 불가"
                elif is_high_volume:
                    timing_risk_score = 0.8  # 집중 거래 시간은 리스크 높음
                    risk_level = "높음"
                    timing_message = "변동성이 높은 집중 거래 시간대"
                else:
                    timing_risk_score = 0.4  # 일반 거래 시간
                    risk_level = "중간"
                    timing_message = "일반적인 거래 시간대"

                # 행동별 추천사항
                action_recommendations = {
                    "buy": [
                        "상승 모멘텀 확인 후 진입",
                        "분할 매수로 리스크 분산",
                        "충분한 유동성 확인",
                    ],
                    "sell": [
                        "목표가 도달 시 즉시 매도",
                        "시장 변동성 고려한 부분 매도",
                        "손절선 엄격히 준수",
                    ],
                    "hold": [
                        "현재 포지션 유지",
                        "시장 상황 지속 모니터링",
                        "변동성 증가 시 재평가",
                    ],
                }.get(intended_action.lower(), ["알 수 없는 행동"])

                timing_analysis = {
                    "intended_action": intended_action,
                    "current_time": current_time.strftime("%Y-%m-%d %H:%M:%S KST"),
                    "timing_risk_score": round(timing_risk_score, 2),
                    "risk_level": risk_level,
                    "timing_message": timing_message,
                    "is_market_open": is_market_open,
                    "is_high_volume_period": is_high_volume,
                    "base_risk_factor": base_risk_factor,
                    "action_recommendations": action_recommendations,
                    "wait_recommendation": "장외 시간"
                    if not is_market_open
                    else "즉시 실행 가능",
                }

                return self.create_standard_response(
                    success=True,
                    query=f"analyze_market_timing_risk: {intended_action}",
                    data=timing_analysis,
                )

            except Exception as e:
                return await self.create_error_response(
                    func_name="analyze_market_timing_risk",
                    error=e,
                    intended_action=intended_action,
                )

        logger.info("Registered 14 tools for Stock Analysis MCP")


if __name__ == "__main__":
    try:
        # 서버 생성 (환경변수에서 포트 읽기)
        port = int(os.getenv("MCP_PORT", "8042"))
        server = StockAnalysisMCPServer(port=port)

        # Health 엔드포인트 등록
        @server.mcp.custom_route(
            path="/health",
            methods=["GET", "OPTIONS"],
            include_in_schema=True,
        )
        async def health_check(request):
            """Health check endpoint with CORS support"""
            from starlette.responses import JSONResponse

            # Manual CORS headers for health endpoint
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Expose-Headers": "*",
            }

            response_data = server.create_standard_response(
                success=True,
                query="MCP Server Health check",
                data="OK",
            )
            return JSONResponse(content=response_data, headers=headers)

        # Add global CORS handler for all custom routes
        @server.mcp.custom_route(
            path="/{path:path}",
            methods=["OPTIONS"],
            include_in_schema=False,
        )
        async def handle_options(request):
            """Handle OPTIONS requests for CORS"""
            from starlette.responses import Response
            return Response(
                content="",
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "3600",
                }
            )

        logger.info(
            f"Starting Stock Analysis MCP Server on {server.host}:{server.port}"
        )
        server.mcp.run(transport="streamable-http", host=server.host, port=server.port)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        logger.info("Stock Analysis MCP Server stopped")
