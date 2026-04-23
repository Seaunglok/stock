"""
재무 분석 클라이언트
핵심 재무 분석 기능에 집중한 클라이언트입니다.

재무 데이터는 FinancialDataReader, DART(금융감독원 공시시스템) 를 통해서 습득하게 됩니다.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from difflib import get_close_matches
from typing import Any, Literal

import FinanceDataReader as fdr
import pandas as pd

logger = logging.getLogger(__name__)


class FinancialAnalysisError(Exception):
    """재무 분석 에러"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class FinancialClient:
    """
    한국 주식 재무 분석 클라이언트

    주요 기능:
    - DCF 밸류에이션 (할인현금흐름법) - 한국 시장 파라미터
    - 재무비율 분석 (수익성, 안전성, 활동성, 성장성) - K-IFRS 기준
    - 재무제표 분석 (손익계산서, 재무상태표, 현금흐름표) - DART 데이터
    - 기업 가치 평가 (PER, PBR, EV/EBITDA) - 코스피/코스닥 기준
    - 투자 수익률 분석 (ROE, ROA, ROIC) - 한국 시장 평균 대비
    """

    # 한국 재무제표 용어 매핑
    KOREAN_FINANCIAL_TERMS = {
        "revenue": "매출액",
        "operating_income": "영업이익",
        "net_income": "당기순이익",
        "total_assets": "자산총계",
        "total_equity": "자본총계",
        "total_debt": "부채총계",
        "current_assets": "유동자산",
        "current_liabilities": "유동부채",
        "operating_cash_flow": "영업활동현금흐름",
        "investing_cash_flow": "투자활동현금흐름",
        "financing_cash_flow": "재무활동현금흐름",
        "free_cash_flow": "잉여현금흐름",
        "ebitda": "EBITDA",
        "eps": "주당순이익",
        "bps": "주당순자산",
        "shares_outstanding": "발행주식수",
    }

    # 한국 시장 DCF 기본 파라미터
    DEFAULT_DISCOUNT_RATE = 10.0  # 한국 무위험수익률 + 리스크프리미엄
    DEFAULT_TERMINAL_GROWTH = 1.3  # 한국 GDP 성장률 기준
    DEFAULT_GROWTH_RATE = 3.0  # 보수적 성장률

    def __init__(self, dart_api_key: str | None = None):
        """한국 재무 분석 클라이언트 초기화

        Args:
            dart_api_key: DART API 키 (선택)

        """
        # 기본 설정
        self.timeout = 30.0
        self.max_retries = 3
        self.dart_api_key = dart_api_key or os.getenv("DART_API_KEY")

        # DART API 키는 선택사항 (FinanceDataReader로 대체 가능)
        if not self.dart_api_key:
            logger.warning("DART API 키가 없습니다. FinanceDataReader만 사용합니다.")

        # 종목 코드 캐시
        self._stock_code_cache = {}
        self._stock_list_cache = None
        self._cache_timestamp = None

        # 한국 시장 재무 분석 임계값 설정
        self.financial_thresholds = {
            "excellent_roe": 12.0,  # ROE 12% 이상 우수 (한국 우량기업 기준)
            "good_roe": 8.0,  # ROE 8% 이상 양호
            "safe_debt_ratio": 100.0,  # 부채비율 100% 이하 안전 (한국 기준)
            "high_debt_ratio": 200.0,  # 부채비율 200% 이상 위험
            "undervalued_per": 10.0,  # PER 10배 이하 저평가 (한국 시장 평균)
            "overvalued_per": 20.0,  # PER 20배 이상 고평가
            "undervalued_pbr": 1.0,  # PBR 1배 이하 저평가
            "overvalued_pbr": 2.0,  # PBR 2배 이상 고평가
        }

        logger.info(
            f"FinancialClient initialized: "
            f"dart_key={'*' * 10 if self.dart_api_key else 'None'}"
        )

    # === 헬퍼 메서드들 ===

    def normalize_symbol(self, symbol: str) -> str:
        """종목코드 정규화

        Args:
            symbol: 종목코드 또는 종목명

        Returns:
            6자리 종목코드
        """
        # 캐시 확인
        if symbol in self._stock_code_cache:
            return self._stock_code_cache[symbol]

        # 숫자로만 구성된 경우 6자리로 패딩
        if symbol.isdigit():
            code = symbol.zfill(6)
            self._stock_code_cache[symbol] = code
            return code

        # 종목명인 경우 코드 검색
        try:
            # 캐시 업데이트 필요 확인 (1시간마다 갱신)
            if self._stock_list_cache is None or (
                self._cache_timestamp
                and (datetime.now() - self._cache_timestamp).seconds > 3600
            ):
                # KOSPI + KOSDAQ 종목 리스트
                kospi = fdr.StockListing("KOSPI")
                kosdaq = fdr.StockListing("KOSDAQ")
                self._stock_list_cache = pd.concat([kospi, kosdaq], ignore_index=True)
                self._cache_timestamp = datetime.now()

            # 종목명으로 검색
            matched = self._fuzzy_search_stock_name(symbol, n=5, cutoff=0.6)

            if not matched.empty:
                code = matched.iloc[0]["Code"]
                self._stock_code_cache[symbol] = code
                return code

            # 부분 일치 검색
            matched = self._fuzzy_search_stock_name(symbol, n=5, cutoff=0.6)

            if not matched.empty:
                code = matched.iloc[0]["Code"]
                logger.warning(
                    f"Partial match: {symbol} -> {matched.iloc[0]['Name']} ({code})"
                )
                self._stock_code_cache[symbol] = code
                return code

        except Exception as e:
            logger.error(f"Failed to normalize symbol {symbol}: {e}")

        # 기본값: 입력값 그대로 반환
        return symbol.zfill(6) if symbol.isdigit() else symbol

    def _fuzzy_search_stock_name(
        self,
        symbol: str,
        n: int = 5,
        cutoff: float = 0.6,
    ) -> pd.DataFrame:
        """
        종목명 유사도 기반 검색 함수

        Args:
            symbol (str): 검색할 종목명(또는 일부)
            n (int): 반환할 최대 결과 수
            cutoff (float): 유사도 임계값(0~1)

        Returns:
            pd.DataFrame: 유사도가 높은 종목 리스트
        """
        if self._stock_list_cache is None:
            return pd.DataFrame()
        names = self._stock_list_cache["Name"].tolist()
        close_matches = get_close_matches(symbol, names, n=n, cutoff=cutoff)
        return self._stock_list_cache[
            self._stock_list_cache["Name"].isin(close_matches)
        ]

    def get_market_type(self, symbol: str) -> str:
        """종목의 시장 구분 반환

        Args:
            symbol: 종목코드

        Returns:
            'KOSPI', 'KOSDAQ', 'KONEX', 또는 'UNKNOWN'
        """
        try:
            code = self.normalize_symbol(symbol)

            # 시장별 종목 확인
            for market in ["KOSPI", "KOSDAQ", "KONEX"]:
                stocks = fdr.StockListing(market)
                if code in stocks["Code"].values:
                    return market

        except Exception as e:
            logger.error(f"Failed to get market type for {symbol}: {e}")

        return "UNKNOWN"

    # === 재무 데이터 수집 메서드들 ===

    async def get_financial_data(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cashflow", "all"] = "all",
    ) -> dict[str, Any]:
        """한국 주식 재무제표 데이터 조회

        FinanceDataReader 한국 주식 데이터 수집
        """
        try:
            # 종목코드 정규화
            _symbol = self.normalize_symbol(symbol)

            # 실제 데이터 조회 - FinanceDataReader 사용
            try:
                # 1. 주가 데이터 및 기본 정보 (FDR)
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)

                # 주가 데이터
                price_data = await asyncio.to_thread(
                    fdr.DataReader,
                    _symbol,
                    start_date,
                    end_date,
                )

                if price_data.empty:
                    raise FinancialAnalysisError(
                        f"종목 {_symbol}에 대한 가격 데이터를 찾을 수 없습니다. "
                        f"종목코드를 확인해주세요.",
                        "NO_PRICE_DATA",
                    )

                current_price = price_data["Close"].iloc[-1]

                # 2. 재무제표 데이터
                # TODO: DART API 구현 예정
                # 현재는 FDR에서 제공하는 기본 정보로 대체
                financial_data = await self._get_basic_financial_data_fdr(
                    _symbol, current_price
                )

                # DART API가 있는 경우 상세 재무제표 조회
                if self.dart_api_key:
                    try:
                        dart_data = await self._get_dart_financial_statements(_symbol)
                        if dart_data:
                            financial_data.update(dart_data)
                            financial_data["source"] = "FDR+DART"
                    except Exception as e:
                        logger.warning(f"DART API failed for {_symbol}: {e}")

                return financial_data

            except FinancialAnalysisError:
                raise
            except Exception as e:
                logger.error(f"Failed to get real data for {_symbol}: {e}")
                raise FinancialAnalysisError(
                    f"재무 데이터 수집 실패: {e}", "DATA_COLLECTION_ERROR"
                ) from e

        except FinancialAnalysisError:
            raise
        except Exception as e:
            logger.error(f"Financial data collection error: {e}")
            raise FinancialAnalysisError(
                f"Financial data error: {e}", "DATA_ERROR"
            ) from e

    async def _get_basic_financial_data_fdr(
        self, symbol: str, current_price: float
    ) -> dict[str, Any]:
        """
        FinanceDataReader를 통한 기본 재무 데이터 수집
        """
        try:
            # 종목 기본 정보
            stock_info = await asyncio.to_thread(fdr.SnapDataReader, f"NAVER/STOCK/{symbol}/FINSTATE")

            if stock_info is None or stock_info.empty:
                raise FinancialAnalysisError(
                    f"종목 {symbol}에 대한 기본 정보를 찾을 수 없습니다.", "NO_STOCK_INFO"
                )

            # 시가총액, PER, PBR 등 추출
            market_cap = stock_info.get("MarketCap", 0) / 100000000  # 억원 단위
            per = stock_info.get("PER", 0)
            pbr = stock_info.get("PBR", 0)
            eps = current_price / per if per > 0 else 0
            bps = current_price / pbr if pbr > 0 else 0
            shares_outstanding = (
                (market_cap * 100000000) / current_price if current_price > 0 else 0
            )

            # 기본 재무 데이터 구조 (추정치)
            estimated_revenue = market_cap * 1.5  # 매출액 추정 (PSR 1.5 가정)
            estimated_net_income = market_cap / per if per > 0 else market_cap * 0.05
            estimated_equity = market_cap / pbr if pbr > 0 else market_cap * 0.4
            estimated_assets = estimated_equity * 2.5  # 자기자본비율 40% 가정

            return {
                "income_statement": {
                    "revenue": estimated_revenue,
                    "operating_income": estimated_revenue * 0.1,  # 영업이익률 10% 가정
                    "net_income": estimated_net_income,
                    "ebitda": estimated_revenue * 0.12,
                    "eps": eps,
                    "operating_margin": 10.0,
                    "net_margin": (estimated_net_income / estimated_revenue * 100)
                    if estimated_revenue > 0
                    else 0,
                },
                "balance_sheet": {
                    "total_assets": estimated_assets,
                    "total_equity": estimated_equity,
                    "total_debt": estimated_assets - estimated_equity,
                    "current_assets": estimated_assets * 0.4,
                    "current_liabilities": (estimated_assets - estimated_equity) * 0.5,
                    "book_value_per_share": bps,
                },
                "cash_flow": {
                    "operating_cash_flow": estimated_net_income * 1.1,
                    "investing_cash_flow": -estimated_revenue * 0.1,
                    "financing_cash_flow": -estimated_net_income * 0.5,
                    "free_cash_flow": estimated_net_income * 0.6,
                },
                "market_data": {
                    "current_price": current_price,
                    "market_cap": market_cap,
                    "shares_outstanding": shares_outstanding,
                    "per": per,
                    "pbr": pbr,
                },
                "source": "FDR",
                "currency": "KRW",
                "unit": "억원",
                "market": self.get_market_type(symbol),
            }

        except FinancialAnalysisError:
            raise
        except Exception as e:
            logger.error(f"FDR data collection failed for {symbol}: {e}")
            raise FinancialAnalysisError(
                f"FinanceDataReader 데이터 수집 실패: {e}", "FDR_ERROR"
            ) from e

    async def _get_dart_financial_statements(self, code: str) -> dict[str, Any] | None:
        """
        DART API를 통한 상세 재무제표 조회
        TODO: PublicDataReader DART API 구현
        """
        # 향후 DART API 연동 구현 예정
        return None

    # === 재무 비율 분석 메서드들 ===

    def calculate_profitability_ratios(
        self, financial_data: dict[str, Any]
    ) -> dict[str, float]:
        """수익성 비율 계산"""
        income = financial_data["income_statement"]
        balance = financial_data["balance_sheet"]

        revenue = income["revenue"]
        net_income = income["net_income"]
        operating_income = income["operating_income"]
        total_assets = balance["total_assets"]
        total_equity = balance["total_equity"]

        ratios = {}

        # ROE (자기자본수익률)
        if total_equity > 0:
            ratios["roe"] = (net_income / total_equity) * 100
        else:
            ratios["roe"] = 0

        # ROA (총자산수익률)
        if total_assets > 0:
            ratios["roa"] = (net_income / total_assets) * 100
        else:
            ratios["roa"] = 0

        # 영업이익률
        if revenue > 0:
            ratios["operating_margin"] = (operating_income / revenue) * 100
            ratios["net_margin"] = (net_income / revenue) * 100
        else:
            ratios["operating_margin"] = 0
            ratios["net_margin"] = 0

        # ROIC (투자자본수익률) - 근사치
        invested_capital = total_equity + balance.get("total_debt", 0)
        if invested_capital > 0:
            ratios["roic"] = (
                operating_income * 0.8 / invested_capital
            ) * 100  # 세후 영업이익 근사
        else:
            ratios["roic"] = 0

        return ratios

    def calculate_stability_ratios(
        self, financial_data: dict[str, Any]
    ) -> dict[str, float]:
        """안전성 비율 계산"""
        balance = financial_data["balance_sheet"]

        total_assets = balance["total_assets"]
        total_equity = balance["total_equity"]
        total_debt = balance["total_debt"]
        current_assets = balance["current_assets"]
        current_liabilities = balance["current_liabilities"]

        ratios = {}

        # 부채비율
        if total_equity > 0:
            ratios["debt_to_equity"] = (total_debt / total_equity) * 100
        else:
            ratios["debt_to_equity"] = 999  # 매우 높은 값

        # 자기자본비율
        if total_assets > 0:
            ratios["equity_ratio"] = (total_equity / total_assets) * 100
        else:
            ratios["equity_ratio"] = 0

        # 유동비율
        if current_liabilities > 0:
            ratios["current_ratio"] = (current_assets / current_liabilities) * 100
        else:
            ratios["current_ratio"] = 999  # 매우 높은 값

        # 부채비율 (총자산 대비)
        if total_assets > 0:
            ratios["debt_to_assets"] = (total_debt / total_assets) * 100
        else:
            ratios["debt_to_assets"] = 0

        return ratios

    def calculate_activity_ratios(
        self, financial_data: dict[str, Any]
    ) -> dict[str, float]:
        """활동성 비율 계산"""
        income = financial_data["income_statement"]
        balance = financial_data["balance_sheet"]

        revenue = income["revenue"]
        total_assets = balance["total_assets"]
        total_equity = balance["total_equity"]

        ratios = {}

        # 총자산회전율
        if total_assets > 0:
            ratios["asset_turnover"] = revenue / total_assets
        else:
            ratios["asset_turnover"] = 0

        # 자기자본회전율
        if total_equity > 0:
            ratios["equity_turnover"] = revenue / total_equity
        else:
            ratios["equity_turnover"] = 0

        # 매출액 증가율 (추후 구현 예정)
        ratios["revenue_growth"] = 0.0  # TODO: 전년 대비 증가율 계산

        return ratios

    # === DCF 밸류에이션 메서드들 ===

    async def calculate_dcf_valuation(
        self,
        symbol: str,
        growth_rate: float | None = None,
        terminal_growth_rate: float | None = None,
        discount_rate: float | None = None,
        projection_years: int = 5,
    ) -> dict[str, Any]:
        """DCF (할인현금흐름) 밸류에이션 계산 - 한국 시장 기준

        Args:
            symbol: 종목코드 또는 종목명
            growth_rate: 성장률 (%, 기본값: 5.0)
            terminal_growth_rate: 영구성장률 (%, 기본값: 2.0)
            discount_rate: 할인률 (%, 기본값: 8.0)
            projection_years: 예측 기간 (년)
        """
        try:
            # 한국 시장 기본 파라미터 사용
            growth_rate = growth_rate or self.DEFAULT_GROWTH_RATE
            terminal_growth_rate = terminal_growth_rate or self.DEFAULT_TERMINAL_GROWTH
            discount_rate = discount_rate or self.DEFAULT_DISCOUNT_RATE

            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # 재무 데이터 수집
            financial_data = await self.get_financial_data(code)
            cash_flow = financial_data["cash_flow"]
            market_data = financial_data.get("market_data", {})

            base_fcf = cash_flow["free_cash_flow"]
            if base_fcf <= 0:
                # FCF가 음수이거나 0인 경우, 순이익 기반으로 추정
                base_fcf = financial_data["income_statement"]["net_income"] * 0.7

            # 시장 유형에 따른 할인률 조정
            market_type = self.get_market_type(code)
            if market_type == "KOSDAQ":
                discount_rate += 1.0  # 코스닥 리스크 프리미엄
            elif market_type == "KONEX":
                discount_rate += 2.0  # 코넥스 리스크 프리미엄

            # 미래 현금흐름 추정 (억원 단위)
            projected_fcf = []
            for year in range(1, projection_years + 1):
                fcf = base_fcf * ((1 + growth_rate / 100) ** year)
                projected_fcf.append(fcf)

            # 터미널 가치 계산
            terminal_fcf = projected_fcf[-1] * (1 + terminal_growth_rate / 100)
            terminal_value = terminal_fcf / (
                discount_rate / 100 - terminal_growth_rate / 100
            )

            # 현재가치로 할인
            pv_fcf = []
            for year, fcf in enumerate(projected_fcf, 1):
                pv = fcf / ((1 + discount_rate / 100) ** year)
                pv_fcf.append(pv)

            pv_terminal = terminal_value / (
                (1 + discount_rate / 100) ** projection_years
            )

            # 기업가치 계산
            enterprise_value = sum(pv_fcf) + pv_terminal

            # 주주가치 계산 (부채 차감)
            total_debt = financial_data["balance_sheet"]["total_debt"]
            equity_value = enterprise_value - total_debt

            # 현금 추가 (현금 및 현금성 자산)
            current_assets = financial_data["balance_sheet"]["current_assets"]
            equity_value += current_assets * 0.2  # 현금성 자산 비중 추정

            # 주당 가치
            shares_outstanding = market_data.get("shares_outstanding")
            if not shares_outstanding or shares_outstanding <= 0:
                raise FinancialAnalysisError(
                    "발행주식수 정보를 찾을 수 없습니다.", "MISSING_SHARES_DATA"
                )
            intrinsic_value_per_share = (
                equity_value * 100000000
            ) / shares_outstanding  # 억원 -> 원

            # 현재 주가와 비교
            current_price = market_data.get("current_price")
            if not current_price or current_price <= 0:
                raise FinancialAnalysisError(
                    "현재 주가 정보를 찾을 수 없습니다.", "MISSING_PRICE_DATA"
                )
            upside_potential = (
                (intrinsic_value_per_share - current_price) / current_price * 100
            )

            return {
                "symbol": code,
                "valuation_method": "DCF",
                "market_type": market_type,
                "assumptions": {
                    "growth_rate": growth_rate,
                    "terminal_growth_rate": terminal_growth_rate,
                    "discount_rate": discount_rate,
                    "projection_years": projection_years,
                },
                "base_free_cash_flow": base_fcf,
                "projected_fcf": projected_fcf,
                "terminal_value": terminal_value,
                "enterprise_value": enterprise_value,
                "equity_value": equity_value,
                "intrinsic_value_per_share": intrinsic_value_per_share,
                "current_price": current_price,
                "upside_potential": upside_potential,
                "recommendation": "매수"
                if upside_potential > 20
                else "매도"
                if upside_potential < -20
                else "보유",
                "currency": "KRW",
                "unit": "억원 (기업가치), 원 (주가)",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"DCF valuation error: {e}")
            raise FinancialAnalysisError(
                f"DCF valuation failed: {e}", "DCF_ERROR"
            ) from e

    # === 종합 재무 분석 메서드들 ===

    async def analyze_financial_comprehensive(self, symbol: str) -> dict[str, Any]:
        """한국 주식 종합 재무 분석

        K-IFRS 기준 재무 분석 및 한국 시장 평가 기준 적용
        """
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # 재무 데이터 수집
            financial_data = await self.get_financial_data(code)

            # 각종 비율 계산
            profitability_ratios = self.calculate_profitability_ratios(financial_data)
            stability_ratios = self.calculate_stability_ratios(financial_data)
            activity_ratios = self.calculate_activity_ratios(financial_data)

            # DCF 밸류에이션
            dcf_result = await self.calculate_dcf_valuation(code)

            # 시장 데이터
            market_data = financial_data.get("market_data", {})
            market_type = self.get_market_type(code)

            # 한국 시장 재무 건전성 점수 계산
            financial_score = 0
            score_components = []

            # 1. 수익성 평가 (30점)
            roe = profitability_ratios["roe"]
            if roe >= self.financial_thresholds["excellent_roe"]:
                financial_score += 30
                score_components.append(
                    {
                        "category": "수익성",
                        "score": 30,
                        "reason": f"우수한 ROE {roe:.1f}% (한국 우량기업 수준)",
                    }
                )
            elif roe >= self.financial_thresholds["good_roe"]:
                financial_score += 20
                score_components.append(
                    {
                        "category": "수익성",
                        "score": 20,
                        "reason": f"양호한 ROE {roe:.1f}% (업종 평균 수준)",
                    }
                )
            else:
                financial_score += 10
                score_components.append(
                    {
                        "category": "수익성",
                        "score": 10,
                        "reason": f"저조한 ROE {roe:.1f}% (개선 필요)",
                    }
                )

            # 2. 안전성 평가 (25점)
            debt_ratio = stability_ratios["debt_to_equity"]
            if debt_ratio <= self.financial_thresholds["safe_debt_ratio"]:
                financial_score += 25
                score_components.append(
                    {
                        "category": "안전성",
                        "score": 25,
                        "reason": f"안전한 부채비율 {debt_ratio:.1f}% (한국 기준 100% 이하)",
                    }
                )
            elif debt_ratio <= self.financial_thresholds["high_debt_ratio"]:
                financial_score += 15
                score_components.append(
                    {
                        "category": "안전성",
                        "score": 15,
                        "reason": f"보통 부채비율 {debt_ratio:.1f}% (관리 필요)",
                    }
                )
            else:
                financial_score += 5
                score_components.append(
                    {
                        "category": "안전성",
                        "score": 5,
                        "reason": f"위험한 부채비율 {debt_ratio:.1f}% (200% 초과)",
                    }
                )

            # 3. 활동성 평가 (20점)
            asset_turnover = activity_ratios["asset_turnover"]
            if asset_turnover >= 1.2:  # 한국 제조업 기준
                financial_score += 20
                score_components.append(
                    {
                        "category": "활동성",
                        "score": 20,
                        "reason": f"우수한 자산회전율 {asset_turnover:.2f}회",
                    }
                )
            elif asset_turnover >= 0.7:
                financial_score += 12
                score_components.append(
                    {
                        "category": "활동성",
                        "score": 12,
                        "reason": f"양호한 자산회전율 {asset_turnover:.2f}회",
                    }
                )
            else:
                financial_score += 5
                score_components.append(
                    {
                        "category": "활동성",
                        "score": 5,
                        "reason": f"저조한 자산회전율 {asset_turnover:.2f}회",
                    }
                )

            # 4. 밸류에이션 평가 (25점)
            upside_potential = dcf_result["upside_potential"]
            per = market_data.get("per", 0)
            pbr = market_data.get("pbr", 0)

            valuation_score = 0
            valuation_reason = []

            # DCF 평가
            if upside_potential > 20:
                valuation_score += 15
                valuation_reason.append(f"DCF 저평가 {upside_potential:.1f}%")
            elif upside_potential > -10:
                valuation_score += 8
                valuation_reason.append(f"DCF 적정가 {upside_potential:.1f}%")
            else:
                valuation_score += 3
                valuation_reason.append(f"DCF 고평가 {upside_potential:.1f}%")

            # PER 평가
            if 0 < per <= self.financial_thresholds["undervalued_per"]:
                valuation_score += 5
                valuation_reason.append(f"PER {per:.1f}배 저평가")
            elif per <= self.financial_thresholds["overvalued_per"]:
                valuation_score += 3
                valuation_reason.append(f"PER {per:.1f}배 적정")
            else:
                valuation_score += 1
                valuation_reason.append(f"PER {per:.1f}배 고평가")

            # PBR 평가
            if 0 < pbr <= self.financial_thresholds["undervalued_pbr"]:
                valuation_score += 5
                valuation_reason.append(f"PBR {pbr:.2f}배 저평가")
            elif pbr <= self.financial_thresholds["overvalued_pbr"]:
                valuation_score += 3
                valuation_reason.append(f"PBR {pbr:.2f}배 적정")
            else:
                valuation_score += 1
                valuation_reason.append(f"PBR {pbr:.2f}배 고평가")

            financial_score += valuation_score
            score_components.append(
                {
                    "category": "밸류에이션",
                    "score": valuation_score,
                    "reason": ", ".join(valuation_reason),
                }
            )

            # 한국 시장 투자 등급 결정
            if financial_score >= 80:
                investment_grade = "A"
                recommendation = "적극 매수"
                grade_description = "우수"
            elif financial_score >= 60:
                investment_grade = "B"
                recommendation = "매수"
                grade_description = "양호"
            elif financial_score >= 40:
                investment_grade = "C"
                recommendation = "보유"
                grade_description = "보통"
            else:
                investment_grade = "D"
                recommendation = "매도"
                grade_description = "주의"

            # 시장별 특성 반영
            market_note = ""
            if market_type == "KOSDAQ":
                market_note = " (코스닥 시장 - 성장성 중심 평가)"
            elif market_type == "KOSPI":
                market_note = " (코스피 시장 - 안정성 중심 평가)"

            return {
                "symbol": code,
                "company_name": symbol if symbol != code else code,
                "market_type": market_type,
                "financial_analysis": {
                    "financial_score": financial_score,
                    "investment_grade": investment_grade,
                    "grade_description": grade_description,
                    "recommendation": recommendation,
                    "score_components": score_components,
                },
                "ratios": {
                    "profitability": profitability_ratios,
                    "stability": stability_ratios,
                    "activity": activity_ratios,
                },
                "valuation": dcf_result,
                "market_data": market_data,
                "analysis_summary": {
                    "strengths": [
                        comp["reason"]
                        for comp in score_components
                        if (comp["category"] == "수익성" and comp["score"] >= 20)
                        or (comp["category"] == "안전성" and comp["score"] >= 20)
                        or (comp["category"] == "활동성" and comp["score"] >= 15)
                        or (comp["category"] == "밸류에이션" and comp["score"] >= 20)
                    ],
                    "weaknesses": [
                        comp["reason"]
                        for comp in score_components
                        if comp["score"] <= 10
                    ],
                    "overall_assessment": f"재무 건전성 {financial_score}점 ({investment_grade}등급-{grade_description}){market_note}",
                    "key_recommendation": recommendation,
                    "investment_opinion": (
                        f"현재 {code} 종목은 재무 건전성 {financial_score}점으로 "
                        f"{investment_grade}등급({grade_description})에 해당합니다. "
                        f"DCF 분석 결과 {upside_potential:.1f}%의 상승 여력을 보이며, "
                        f"'{recommendation}' 의견을 제시합니다."
                    ),
                },
                "currency": "KRW",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Comprehensive financial analysis error: {e}")
            raise FinancialAnalysisError(
                f"Comprehensive financial analysis failed: {e}", "COMPREHENSIVE_ERROR"
            ) from e

    async def close(self):
        """클라이언트 리소스 정리"""
        logger.info("FinancialClient closed")
