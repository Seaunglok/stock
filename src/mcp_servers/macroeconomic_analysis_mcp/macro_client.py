"""
거시경제 분석 클라이언트 (FRED API 중심)
미국 경제 지표를 중심으로 한 거시경제 분석 클라이언트입니다.

미국 경제가 한국 시장에 미치는 영향이 크므로, FRED API를 활용하여
실제 사용 가능한 경제 데이터를 제공합니다.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from fredapi import Fred

logger = logging.getLogger(__name__)


class MacroEconomicAPIError(Exception):
    """거시경제 API 에러"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class MacroClient:
    """
    거시경제 분석 클라이언트 (FRED API 중심)

    주요 기능:
    - FRED API를 통한 미국 경제지표 수집
    - 글로벌 경제 상황이 한국 시장에 미치는 영향 분석
    - 실시간 금리, 인플레이션, 고용, GDP 데이터 제공
    """

    def __init__(self):
        """거시경제 클라이언트 초기화 (FRED API 필수)"""
        # 환경변수에서 FRED API 키 로드 (필수)
        self.fred_api_key = os.getenv("FRED_API_KEY")

        if not self.fred_api_key:
            error_msg = (
                "FRED_API_KEY 환경변수가 설정되지 않았습니다. FRED API는 필수입니다."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # API 기본 설정
        self.timeout = 30.0
        self.max_retries = 3
        self.request_delay = 0.1

        # FRED API 클라이언트 초기화 (필수)
        try:
            self.fred_client = Fred(api_key=self.fred_api_key)
            logger.info("FRED API client initialized successfully")

            # FRED API 연결 테스트
            test_data = self.fred_client.get_series("FEDFUNDS", limit=1)
            if not test_data.empty:
                logger.info("FRED API connection verified")
            else:
                error_msg = "FRED API 테스트 실패: 빈 데이터 반환"
                logger.error(error_msg)
                raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"FRED API 초기화 실패: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg) from e

        logger.info(f"MacroClient initialized: fred_key={'*' * 10}, fred_active=True")

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        # FRED는 동기식이므로 별도 정리 불필요
        pass

    # === FRED API 기반 경제지표 수집 메서드들 ===

    async def get_interest_rates(self, lookback_days: int = 360) -> dict[str, Any]:
        """금리 데이터 조회 (FRED API 필수)"""
        try:
            # FRED API를 통한 실제 데이터 조회
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)

            try:
                # 연방기금금리
                fed_funds = self.fred_client.get_series(
                    "FEDFUNDS", start=start_date, end=end_date
                )

                # 10년 국채 수익률
                treasury_10y = self.fred_client.get_series(
                    "GS10", start=start_date, end=end_date
                )

                # 2년 국채 수익률
                treasury_2y = self.fred_client.get_series(
                    "GS2", start=start_date, end=end_date
                )

                # 실질 금리 (10년 TIPS)
                real_rate = self.fred_client.get_series(
                    "FII10", start=start_date, end=end_date
                )

                # 데이터 정리
                result = {
                    "source": "FRED-API",
                    "last_updated": datetime.now().isoformat(),
                    "period_days": lookback_days,
                }

                if not fed_funds.empty:
                    fed_data = fed_funds.dropna().tail(12)
                    result["fed_funds_rate"] = fed_data.tolist()
                    result["dates"] = [d.strftime("%Y-%m") for d in fed_data.index]

                if not treasury_10y.empty:
                    result["us_10y_treasury"] = treasury_10y.dropna().tail(12).tolist()

                if not treasury_2y.empty:
                    treasury_2y_data = treasury_2y.dropna().tail(12)
                    result["us_2y_treasury"] = treasury_2y_data.tolist()

                    # 수익률 곡선 기울기 계산 (10Y - 2Y)
                    if not treasury_10y.empty:
                        treasury_10y_aligned = treasury_10y.reindex(
                            treasury_2y_data.index, method="ffill"
                        )
                        yield_spread = treasury_10y_aligned - treasury_2y_data
                        result["yield_curve_spread"] = yield_spread.dropna().tolist()

                if not real_rate.empty:
                    result["us_real_rate"] = real_rate.dropna().tail(12).tolist()

                result["data_count"] = len(result.get("dates", []))
                return result

            except Exception as fred_error:
                error_msg = f"FRED API 금리 데이터 조회 실패: {fred_error}"
                logger.error(error_msg)
                raise MacroEconomicAPIError(error_msg, "FRED_API_ERROR") from fred_error

        except Exception as e:
            logger.error(f"Interest rate data collection error: {e}")
            raise MacroEconomicAPIError(
                f"Interest rate data error: {e}", "DATA_ERROR"
            ) from e

    async def get_inflation_data(self, lookback_days: int = 180) -> dict[str, Any]:
        """인플레이션 데이터 조회 (FRED API 필수)"""
        try:
            # FRED API를 통한 실제 데이터 조회
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)

            try:
                # 미국 CPI (Consumer Price Index)
                us_cpi = self.fred_client.get_series(
                    "CPIAUCSL", start=start_date, end=end_date
                )

                # 미국 Core CPI (식품, 에너지 제외)
                us_core_cpi = self.fred_client.get_series(
                    "CPILFESL", start=start_date, end=end_date
                )

                # PCE (Personal Consumption Expenditures) - Fed의 선호 지표
                us_pce = self.fred_client.get_series(
                    "PCEPI", start=start_date, end=end_date
                )

                result = {
                    "source": "fred_api",
                    "last_updated": datetime.now().isoformat(),
                    "period_days": lookback_days,
                }

                # CPI 전년동월비 계산
                if not us_cpi.empty:
                    cpi_yoy = us_cpi.pct_change(periods=12) * 100
                    cpi_data = cpi_yoy.dropna().tail(12)
                    result["us_cpi_yoy"] = cpi_data.tolist()
                    result["dates"] = [d.strftime("%Y-%m") for d in cpi_data.index]

                # Core CPI 전년동월비
                if not us_core_cpi.empty:
                    core_cpi_yoy = us_core_cpi.pct_change(periods=12) * 100
                    result["us_core_cpi_yoy"] = core_cpi_yoy.dropna().tail(12).tolist()

                # PCE 전년동월비
                if not us_pce.empty:
                    pce_yoy = us_pce.pct_change(periods=12) * 100
                    result["us_pce_yoy"] = pce_yoy.dropna().tail(12).tolist()

                result["data_count"] = len(result.get("dates", []))
                return result

            except Exception as fred_error:
                error_msg = f"FRED API 인플레이션 데이터 조회 실패: {fred_error}"
                logger.error(error_msg)
                raise MacroEconomicAPIError(error_msg, "FRED_API_ERROR") from fred_error

        except Exception as e:
            logger.error(f"Inflation data collection error: {e}")
            raise MacroEconomicAPIError(
                f"Inflation data error: {e}", "DATA_ERROR"
            ) from e

    async def get_employment_data(self, lookback_days: int = 90) -> dict[str, Any]:
        """고용 데이터 조회 (FRED API 필수)"""
        try:
            # FRED API를 통한 실제 데이터 조회
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)

            try:
                # 실업률
                unemployment = self.fred_client.get_series(
                    "UNRATE", start=start_date, end=end_date
                )

                # 경제활동참가율
                participation = self.fred_client.get_series(
                    "CIVPART", start=start_date, end=end_date
                )

                # 비농업 고용 변화 (월간)
                nonfarm_payrolls = self.fred_client.get_series(
                    "PAYEMS", start=start_date, end=end_date
                )

                result = {
                    "source": "fred_api",
                    "last_updated": datetime.now().isoformat(),
                    "period_days": lookback_days,
                }

                if not unemployment.empty:
                    unemployment_data = unemployment.dropna().tail(12)
                    result["us_unemployment_rate"] = unemployment_data.tolist()
                    result["dates"] = [
                        d.strftime("%Y-%m") for d in unemployment_data.index
                    ]

                if not participation.empty:
                    result["us_participation_rate"] = (
                        participation.dropna().tail(12).tolist()
                    )

                if not nonfarm_payrolls.empty:
                    # 월간 변화량 계산 (전월 대비)
                    payrolls_change = nonfarm_payrolls.diff() * 1000  # 단위: 천명 -> 명
                    result["us_nonfarm_payrolls_change"] = (
                        payrolls_change.dropna().tail(12).tolist()
                    )

                result["data_count"] = len(result.get("dates", []))
                return result

            except Exception as fred_error:
                error_msg = f"FRED API 고용 데이터 조회 실패: {fred_error}"
                logger.error(error_msg)
                raise MacroEconomicAPIError(error_msg, "FRED_API_ERROR") from fred_error

        except Exception as e:
            logger.error(f"Employment data collection error: {e}")
            raise MacroEconomicAPIError(
                f"Employment data error: {e}", "DATA_ERROR"
            ) from e

    async def get_gdp_data(self, lookback_quarters: int = 8) -> dict[str, Any]:
        """GDP 데이터 조회 (FRED API 필수)"""
        try:
            # FRED API를 통한 실제 데이터 조회
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_quarters * 90)

            try:
                # 실질 GDP (분기별)
                real_gdp = self.fred_client.get_series(
                    "GDPC1", start=start_date, end=end_date
                )

                # GDP 디플레이터
                gdp_deflator = self.fred_client.get_series(
                    "GDPDEF", start=start_date, end=end_date
                )

                result = {
                    "source": "fred_api",
                    "last_updated": datetime.now().isoformat(),
                    "period_quarters": lookback_quarters,
                }

                if not real_gdp.empty:
                    gdp_data = real_gdp.dropna().tail(lookback_quarters)

                    # 분기 포맷팅
                    quarters = []
                    for date in gdp_data.index:
                        year = date.year
                        quarter = (date.month - 1) // 3 + 1
                        quarters.append(f"{year}Q{quarter}")

                    result["quarters"] = quarters

                    # 전년동기비 성장률 계산
                    gdp_yoy = real_gdp.pct_change(periods=4) * 100
                    result["us_gdp_growth_yoy"] = (
                        gdp_yoy.dropna().tail(lookback_quarters).tolist()
                    )

                    # 전분기 대비 연율화 성장률
                    gdp_qoq = real_gdp.pct_change() * 400  # 연율화
                    result["us_gdp_growth_qoq_annualized"] = (
                        gdp_qoq.dropna().tail(lookback_quarters).tolist()
                    )

                if not gdp_deflator.empty:
                    deflator_yoy = gdp_deflator.pct_change(periods=4) * 100
                    result["us_gdp_deflator_yoy"] = (
                        deflator_yoy.dropna().tail(lookback_quarters).tolist()
                    )

                result["data_count"] = len(result.get("quarters", []))
                return result

            except Exception as fred_error:
                error_msg = f"FRED API GDP 데이터 조회 실패: {fred_error}"
                logger.error(error_msg)
                raise MacroEconomicAPIError(error_msg, "FRED_API_ERROR") from fred_error

        except Exception as e:
            logger.error(f"GDP data collection error: {e}")
            raise MacroEconomicAPIError(f"GDP data error: {e}", "DATA_ERROR") from e

    # === 종합 분석 메서드들 ===

    async def analyze_economic_cycle(self, lookback_days: int = 360) -> dict[str, Any]:
        """경기 사이클 분석 (FRED 데이터 기반)"""
        try:
            # 주요 지표 수집
            interest_data = await self.get_interest_rates()
            inflation_data = await self.get_inflation_data()
            employment_data = await self.get_employment_data()
            gdp_data = await self.get_gdp_data()

            # 경기 사이클 신호 분석
            signals = []
            cycle_scores = {"expansion": 0.0, "contraction": 0.0, "neutral": 0.0}

            # 1. 금리 환경 분석
            if (
                interest_data.get("fed_funds_rate")
                and len(interest_data["fed_funds_rate"]) >= 3
            ):
                recent_rates = interest_data["fed_funds_rate"][-3:]
                rate_trend = recent_rates[-1] - recent_rates[0]

                # 수익률 곡선 기울기 분석
                yield_spread = None
                if interest_data.get("yield_curve_spread"):
                    yield_spread = interest_data["yield_curve_spread"][-1]

                if rate_trend > 0.25:  # 금리 상승
                    if yield_spread and yield_spread < 0:  # 역전 수익률 곡선
                        signals.append(
                            {
                                "type": "monetary_policy",
                                "signal": "restrictive_with_inversion",
                                "weight": 0.35,
                                "detail": f"Fed 긴축 + 수익률 곡선 역전 (기울기: {yield_spread:.2f})",
                            }
                        )
                        cycle_scores["contraction"] += 0.35
                    else:
                        signals.append(
                            {
                                "type": "monetary_policy",
                                "signal": "tightening",
                                "weight": 0.25,
                                "detail": f"Fed 금리 상승 추세 (+{rate_trend:.2f}%p)",
                            }
                        )
                        cycle_scores["contraction"] += 0.25
                elif rate_trend < -0.25:  # 금리 하락
                    signals.append(
                        {
                            "type": "monetary_policy",
                            "signal": "easing",
                            "weight": 0.25,
                            "detail": f"Fed 금리 하락 추세 ({rate_trend:.2f}%p)",
                        }
                    )
                    cycle_scores["expansion"] += 0.25

            # 2. GDP 성장률 분석
            if (
                gdp_data.get("us_gdp_growth_yoy")
                and len(gdp_data["us_gdp_growth_yoy"]) >= 2
            ):
                recent_gdp = gdp_data["us_gdp_growth_yoy"][-2:]
                avg_gdp = sum(recent_gdp) / len(recent_gdp)
                gdp_trend = recent_gdp[-1] - recent_gdp[-2]

                if avg_gdp > 2.5 and gdp_trend > 0:
                    signals.append(
                        {
                            "type": "economic_growth",
                            "signal": "strong_growth",
                            "weight": 0.30,
                            "detail": f"GDP 성장률 {avg_gdp:.1f}%, 가속화",
                        }
                    )
                    cycle_scores["expansion"] += 0.30
                elif avg_gdp < 1.5 or gdp_trend < -0.5:
                    signals.append(
                        {
                            "type": "economic_growth",
                            "signal": "weakness",
                            "weight": 0.30,
                            "detail": f"GDP 성장률 {avg_gdp:.1f}%, 둔화",
                        }
                    )
                    cycle_scores["contraction"] += 0.30

            # 3. 고용 시장 분석
            if (
                employment_data.get("us_unemployment_rate")
                and len(employment_data["us_unemployment_rate"]) >= 3
            ):
                recent_unemployment = employment_data["us_unemployment_rate"][-3:]
                unemployment_trend = recent_unemployment[-1] - recent_unemployment[0]

                # 논팜 페이롤 분석
                payrolls_strength = "unknown"
                if employment_data.get("us_nonfarm_payrolls_change"):
                    avg_payrolls = (
                        sum(employment_data["us_nonfarm_payrolls_change"][-3:]) / 3
                    )
                    payrolls_strength = "strong" if avg_payrolls > 200000 else "weak"

                if unemployment_trend < -0.2:  # 실업률 하락
                    signals.append(
                        {
                            "type": "labor_market",
                            "signal": "strengthening",
                            "weight": 0.20,
                            "detail": f"실업률 개선 ({unemployment_trend:.2f}%p), 일자리 증가 {payrolls_strength}",
                        }
                    )
                    cycle_scores["expansion"] += 0.20
                elif unemployment_trend > 0.3:  # 실업률 상승
                    signals.append(
                        {
                            "type": "labor_market",
                            "signal": "weakening",
                            "weight": 0.20,
                            "detail": f"실업률 악화 (+{unemployment_trend:.2f}%p)",
                        }
                    )
                    cycle_scores["contraction"] += 0.20

            # 4. 인플레이션 압력 분석
            if (
                inflation_data.get("us_cpi_yoy")
                and len(inflation_data["us_cpi_yoy"]) >= 3
            ):
                recent_cpi = inflation_data["us_cpi_yoy"][-3:]
                avg_inflation = sum(recent_cpi) / len(recent_cpi)
                recent_cpi[-1] - recent_cpi[0]

                if avg_inflation > 3.5:  # 고인플레이션
                    signals.append(
                        {
                            "type": "inflation",
                            "signal": "elevated_pressure",
                            "weight": 0.15,
                            "detail": f"인플레이션 압력 ({avg_inflation:.1f}%), Fed 긴축 압박",
                        }
                    )
                    cycle_scores["contraction"] += 0.15
                elif avg_inflation < 2.0:  # 저인플레이션
                    signals.append(
                        {
                            "type": "inflation",
                            "signal": "disinflationary",
                            "weight": 0.10,
                            "detail": f"디스인플레이션 ({avg_inflation:.1f}%)",
                        }
                    )
                    cycle_scores["expansion"] += 0.10

            # 경기 사이클 단계 결정
            max_score = max(cycle_scores.values()) if cycle_scores.values() else 0
            cycle_stage = (
                max(cycle_scores, key=cycle_scores.get) if cycle_scores else "neutral"
            )
            confidence_score = max_score / (sum(cycle_scores.values()) + 0.1)

            # 한국 시장에 대한 함의
            korea_implications = {
                "expansion": {
                    "market_impact": "긍정적",
                    "sector_recommendation": "수출주, 기술주, 성장주",
                    "risk_factors": ["환율 강세", "원자재 가격 상승"],
                },
                "contraction": {
                    "market_impact": "부정적",
                    "sector_recommendation": "방어주, 내수주, 배당주",
                    "risk_factors": ["수출 둔화", "외국인 투자 감소"],
                },
                "neutral": {
                    "market_impact": "혼재",
                    "sector_recommendation": "균형 포트폴리오",
                    "risk_factors": ["변동성 확대"],
                },
            }

            return {
                "cycle_stage": cycle_stage,
                "confidence_score": round(confidence_score, 2),
                "cycle_scores": cycle_scores,
                "signals": signals,
                "korea_market_implications": korea_implications.get(
                    cycle_stage, korea_implications["neutral"]
                ),
                "data_sources": {
                    "interest_rates": interest_data.get("source", "unknown"),
                    "inflation": inflation_data.get("source", "unknown"),
                    "employment": employment_data.get("source", "unknown"),
                    "gdp": gdp_data.get("source", "unknown"),
                },
                "analysis_timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Economic cycle analysis error: {e}")
            raise MacroEconomicAPIError(
                f"Economic cycle analysis failed: {e}", "ANALYSIS_ERROR"
            ) from e

    async def close(self):
        """클라이언트 리소스 정리"""
        # FRED는 동기식이므로 별도 정리 불필요
        logger.info("MacroClient closed")
