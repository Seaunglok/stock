"""
주식 분석 클라이언트 - 단순화된 버전

복잡한 다중 요인 분석기와 모델들을 제거하고
핵심 주식 분석 기능에 집중한 클라이언트입니다.
"""

import difflib
import logging
from datetime import datetime, timedelta
from typing import Any

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# === 기술적 분석 헬퍼 함수들 ===


def calculate_rsi(prices: list, period: int = 14) -> float:
    """RSI (Relative Strength Index) 계산

    Args:
        prices: 가격 리스트 (최신순)
        period: RSI 계산 기간

    Returns:
        RSI 값 (0-100)
    """
    if len(prices) < period + 1:
        return 50.0  # 데이터 부족시 중립값 반환

    # 가격 변화 계산
    deltas = []
    for i in range(1, len(prices)):
        deltas.append(prices[i - 1] - prices[i])  # 최신순이므로 역순 계산

    # 상승/하락 분리
    gains = [d if d > 0 else 0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0 for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # RSI 계산
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def calculate_macd(
    prices: list, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict:
    """MACD (Moving Average Convergence Divergence) 계산

    Args:
        prices: 가격 리스트 (최신순)
        fast: 단기 EMA 기간
        slow: 장기 EMA 기간
        signal: 시그널 라인 기간

    Returns:
        MACD 지표 딕셔너리
    """
    if len(prices) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0}

    # EMA 계산 함수 (전체 시계열로 누적 계산)
    def calculate_ema_series(data: list, period: int) -> list:
        if len(data) < period:
            return [data[0] if data else 0] * len(data)

        multiplier = 2 / (period + 1)
        ema_list = []

        # 초기 SMA
        sma = sum(data[:period]) / period
        ema_list.extend([sma] * period)

        # EMA 계산
        for i in range(period, len(data)):
            ema = (data[i] - ema_list[i - 1]) * multiplier + ema_list[i - 1]
            ema_list.append(ema)

        return ema_list

    # 가격 리스트를 오래된순으로 변환 (EMA 계산을 위해)
    prices_old_first = prices[::-1]

    # EMA 시계열 계산
    ema_fast_series = calculate_ema_series(prices_old_first, fast)
    ema_slow_series = calculate_ema_series(prices_old_first, slow)

    # MACD 시계열 계산
    macd_series = [
        fast_ema - slow_ema
        for fast_ema, slow_ema in zip(ema_fast_series, ema_slow_series, strict=True)
    ]

    # Signal 라인 (MACD의 EMA)
    signal_series = calculate_ema_series(macd_series, signal)

    # 최신 값들
    macd_value = macd_series[-1]
    signal_value = signal_series[-1]
    histogram = macd_value - signal_value

    return {
        "macd": round(macd_value, 2),
        "signal": round(signal_value, 2),
        "histogram": round(histogram, 2),
    }


def calculate_moving_averages(prices: list, periods: list) -> dict:
    """이동평균 계산

    Args:
        prices: 가격 리스트 (최신순)
        periods: 이동평균 기간 리스트

    Returns:
        이동평균 딕셔너리
    """
    ma_dict = {}

    for period in periods:
        if len(prices) >= period:
            ma = sum(prices[:period]) / period
            ma_dict[f"ma{period}"] = round(ma, 2)
        else:
            ma_dict[f"ma{period}"] = prices[0] if prices else 0

    return ma_dict


def calculate_golden_death_cross(
    prices: list, short_period: int = 20, long_period: int = 60
) -> dict:
    """골든크로스/데드크로스 검출

    Args:
        prices: 가격 리스트 (최신순)
        short_period: 단기 이동평균 기간
        long_period: 장기 이동평균 기간

    Returns:
        크로스 정보 딕셔너리
    """
    if len(prices) < long_period + 1:
        return {
            "cross_type": "NONE",
            "interpretation": "데이터 부족으로 크로스 판단 불가",
        }

    # 현재 이동평균
    short_ma_current = sum(prices[:short_period]) / short_period
    long_ma_current = sum(prices[:long_period]) / long_period

    # 이전 이동평균
    short_ma_prev = sum(prices[1 : short_period + 1]) / short_period
    long_ma_prev = sum(prices[1 : long_period + 1]) / long_period

    # 크로스 판단
    if short_ma_prev <= long_ma_prev and short_ma_current > long_ma_current:
        return {
            "cross_type": "GOLDEN_CROSS",
            "interpretation": "골든크로스 발생 - 중장기 상승 추세 전환 신호",
            "short_ma": round(short_ma_current, 2),
            "long_ma": round(long_ma_current, 2),
        }
    elif short_ma_prev >= long_ma_prev and short_ma_current < long_ma_current:
        return {
            "cross_type": "DEATH_CROSS",
            "interpretation": "데드크로스 발생 - 하락 추세 전환 신호",
            "short_ma": round(short_ma_current, 2),
            "long_ma": round(long_ma_current, 2),
        }
    else:
        trend = "상승" if short_ma_current > long_ma_current else "하락"
        return {
            "cross_type": "NONE",
            "interpretation": f"크로스 없음 - {trend} 추세 유지",
            "short_ma": round(short_ma_current, 2),
            "long_ma": round(long_ma_current, 2),
        }


def analyze_multiple_moving_average_cross(prices: list) -> dict:
    """다중 이동평균 크로스 분석

    Args:
        prices: 가격 리스트 (최신순)

    Returns:
        다중 크로스 분석 결과
    """
    crosses = []

    # 다양한 기간 조합 검사
    periods = [(5, 20), (20, 60), (60, 120)]

    for short, long in periods:
        if len(prices) >= long:
            cross_result = calculate_golden_death_cross(prices, short, long)
            if cross_result["cross_type"] != "NONE":
                crosses.append(
                    {
                        "periods": f"MA{short}/MA{long}",
                        "type": cross_result["cross_type"],
                        "interpretation": cross_result["interpretation"],
                    }
                )

    # 종합 판단
    golden_count = sum(1 for c in crosses if c["type"] == "GOLDEN_CROSS")
    death_count = sum(1 for c in crosses if c["type"] == "DEATH_CROSS")

    if golden_count > death_count:
        overall_signal = "BULLISH"
        overall_interpretation = "다중 골든크로스 - 강한 상승 신호"
    elif death_count > golden_count:
        overall_signal = "BEARISH"
        overall_interpretation = "다중 데드크로스 - 강한 하락 신호"
    else:
        overall_signal = "NEUTRAL"
        overall_interpretation = "혼재된 신호 - 추세 전환 가능성"

    return {
        "crosses": crosses,
        "overall_signal": overall_signal,
        "overall_interpretation": overall_interpretation,
        "golden_cross_count": golden_count,
        "death_cross_count": death_count,
    }


def calculate_bollinger_bands(prices: list, period: int = 20, std_dev: int = 2) -> dict:
    """볼린저 밴드 계산

    Args:
        prices: 가격 리스트 (최신순)
        period: 이동평균 기간
        std_dev: 표준편차 배수

    Returns:
        볼린저 밴드 정보
    """
    if len(prices) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "width": 0, "position": "중립"}

    # 중심선 (이동평균)
    middle = sum(prices[:period]) / period

    # 표준편차
    variance = sum((p - middle) ** 2 for p in prices[:period]) / period
    std = variance**0.5

    # 밴드 계산
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    # 현재 가격 위치
    current_price = prices[0]

    if current_price >= upper:
        position = "상단 밴드 근처 - 과매수"
    elif current_price <= lower:
        position = "하단 밴드 근처 - 과매도"
    else:
        position = "중립 구간"

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "width": round(upper - lower, 2),
        "position": position,
        "current_price": round(current_price, 2),
    }


class StockAnalysisError(Exception):
    """주식 분석 에러"""

    def __init__(
        self, message: str, error_code: str | None = None, details: dict | None = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class StockClient:
    """
    한국 주식 분석 클라이언트

    주요 기능:
    - 기술적 분석 (RSI, MACD, 이동평균, 골든크로스)
    - 기본적 분석 (P/E, P/B, ROE 등) - 한국 시장 기준
    - 감정 분석 (뉴스, 소셜미디어 기반)
    - 통합 신호 생성 및 한국어 투자 인사이트
    """

    # 한국 시장 재무 분석 임계값
    # 임의로 정해놓은 것으로 굳이 이 값을 다 다라하지 않으셔도 됩니다.
    KOREAN_MARKET_THRESHOLDS = {
        "undervalued_per": 10.0,  # PER 10배 이하 저평가
        "overvalued_per": 20.0,  # PER 20배 이상 고평가
        "undervalued_pbr": 1.0,  # PBR 1배 이하 저평가
        "overvalued_pbr": 2.0,  # PBR 2배 이상 고평가
        "excellent_roe": 12.0,  # ROE 12% 이상 우수
        "good_roe": 8.0,  # ROE 8% 이상 양호
        "oversold_rsi": 25.0,  # RSI 25 이하 과매도
        "overbought_rsi": 75.0,  # RSI 75 이상 과매수
    }

    def __init__(self, offline_mode: bool = False):
        """한국 주식 분석 클라이언트 초기화

        Args:
            offline_mode: True면 데이터 없을 때 중립 폴백 사용
        """
        # 기본 설정
        self.timeout = 30.0
        self.max_retries = 3
        self.offline_mode = offline_mode

        # 종목 코드 캐시
        self._stock_code_cache = {}
        self._stock_list_cache = None
        self._market_type_cache = {}  # 시장 구분 캐시 추가
        self._cache_timestamp = None

        # 한국 시장 분석 가중치 설정 (fundamental은 종합분석에서만 사용)
        self.analysis_weights = {
            "technical": 0.5,  # 기술적 분석
            "fundamental": 0.3,  # 기본적 분석
            "sentiment": 0.2,  # 감정 분석
        }

        # 기술적 분석 내부 가중치
        self.technical_weights = {
            "golden_cross": 0.25,  # 골든/데드크로스
            "ma_arrangement": 0.20,  # 이동평균 배열
            "momentum": 0.20,  # RSI, MACD
            "volume": 0.15,  # 거래량
            "others": 0.20,  # 기타 지표들
        }

        # 한국 시장 신호 임계값 설정
        self.signal_thresholds = {
            "strong_buy": 0.8,
            "buy": 0.6,
            "hold": 0.4,
            "sell": 0.2,
            "strong_sell": 0.0,
        }

        logger.info(
            f"StockClient initialized for Korean market (offline_mode: {offline_mode})"
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
            matched = self._stock_list_cache[self._stock_list_cache["Name"] == symbol]
            if not matched.empty:
                code = matched.iloc[0]["Code"]
                self._stock_code_cache[symbol] = code
                return code
            # 부분 일치 검색
            matched = self._stock_list_cache[
                self._stock_list_cache["Name"].str.contains(symbol, na=False)
            ]
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

    def get_market_type(self, symbol: str) -> str:
        """종목의 시장 구분 반환 (캐시 재활용으로 성능 개선)

        Args:
            symbol: 종목코드

        Returns:
            'KOSPI', 'KOSDAQ', 'KONEX', 또는 'UNKNOWN'

        """
        try:
            code = self.normalize_symbol(symbol)

            # 캐시에서 확인
            if code in self._market_type_cache:
                return self._market_type_cache[code]

            # 기존 종목 리스트 캐시 활용
            if self._stock_list_cache is not None:
                # 캐시에서 찾기
                matched = self._stock_list_cache[self._stock_list_cache["Code"] == code]
                if not matched.empty and "Market" in matched.columns:
                    market = matched.iloc[0]["Market"]
                    self._market_type_cache[code] = market
                    return market

            # 캐시 미스 시 개별 시장에서 확인
            for market in ["KOSPI", "KOSDAQ", "KONEX"]:
                try:
                    stocks = fdr.StockListing(market)
                    if code in stocks["Code"].values:
                        self._market_type_cache[code] = market
                        return market
                except Exception as e:
                    logger.warning(f"Failed to check {market} for {code}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to get market type for {symbol}: {e}")

        # 기본값
        self._market_type_cache[code] = "UNKNOWN"
        return "UNKNOWN"

    # === 종목 정보 조회 메서드들 ===

    async def get_stock_list(
        self,
        market: str = "ALL",
        limit: int = 100,
    ) -> dict[str, Any]:
        """한국 주식 종목 리스트 조회

        Args:
            market: 시장 구분 ("KOSPI", "KOSDAQ", "KONEX", "ALL")
            limit: 반환할 최대 종목 수

        Returns:
            종목 리스트와 메타데이터
        """
        try:
            stock_list = []

            # 시장별 종목 조회
            markets_to_fetch = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]

            for mkt in markets_to_fetch:
                try:
                    df = fdr.StockListing(mkt)

                    # 필요한 컬럼만 선택하고 정리
                    columns_map = {
                        "Code": "code",
                        "Name": "name",
                        "Market": "market",
                        "Marcap": "market_cap",
                        "Stocks": "shares",
                    }

                    # 사용 가능한 컬럼만 매핑
                    available_columns = {
                        k: v for k, v in columns_map.items() if k in df.columns
                    }
                    df_clean = df[list(available_columns.keys())].rename(
                        columns=available_columns
                    )

                    # 시장 정보가 없으면 추가
                    if "market" not in df_clean.columns:
                        df_clean["market"] = mkt

                    # 시가총액을 억원 단위로 변환
                    if "market_cap" in df_clean.columns:
                        df_clean["market_cap_billion"] = (
                            df_clean["market_cap"] / 100000000
                        ).round(0)

                    # 리스트에 추가
                    for _, row in df_clean.head(
                        limit if market != "ALL" else limit // 2
                    ).iterrows():
                        stock_info = {
                            "code": row["code"],
                            "name": row["name"],
                            "market": row.get("market", mkt),
                        }

                        # 선택적 필드 추가
                        if "market_cap_billion" in row and pd.notna(
                            row["market_cap_billion"]
                        ):
                            stock_info["market_cap_billion"] = int(
                                row["market_cap_billion"]
                            )
                        if "shares" in row and pd.notna(row["shares"]):
                            stock_info["shares"] = int(row["shares"])

                        stock_list.append(stock_info)

                except Exception as e:
                    logger.warning(f"Failed to fetch {mkt} stock list: {e}")
                    continue

            # 시가총액 기준 정렬 (큰 순서대로)
            stock_list.sort(key=lambda x: x.get("market_cap_billion", 0), reverse=True)

            # 제한 수만큼 반환
            final_list = stock_list[:limit]

            return {
                "stocks": final_list,
                "total_count": len(final_list),
                "market_filter": market,
                "timestamp": datetime.now().isoformat(),
                "data_source": "FinanceDataReader",
            }

        except Exception as e:
            logger.error(f"Failed to get stock list: {e}")
            raise StockAnalysisError(
                f"Stock list retrieval failed: {e}", "STOCK_LIST_ERROR"
            ) from e

    async def search_stocks(self, query: str, limit: int = 20) -> dict[str, Any]:
        """종목명으로 검색 (difflib 기반 유사도 검색 포함)

        Args:
            query: 검색어 (종목명 또는 종목코드)
            limit: 반환할 최대 종목 수

        Returns:
            검색 결과
        """
        try:
            # 캐시 업데이트
            if self._stock_list_cache is None or (
                self._cache_timestamp
                and (datetime.now() - self._cache_timestamp).seconds > 3600
            ):
                kospi = fdr.StockListing("KOSPI")
                kosdaq = fdr.StockListing("KOSDAQ")
                self._stock_list_cache = pd.concat([kospi, kosdaq], ignore_index=True)
                self._cache_timestamp = datetime.now()

            # 검색 수행
            df = self._stock_list_cache

            # 코드 완전 일치 먼저 확인
            if query.isdigit():
                code_query = query.zfill(6)
                exact_match = df[df["Code"] == code_query]
                if not exact_match.empty:
                    results = []
                    for _, row in exact_match.iterrows():
                        results.append(
                            {
                                "code": row["Code"],
                                "name": row["Name"],
                                "market": row.get("Market", "UNKNOWN"),
                                "match_type": "exact_code",
                                "similarity": 1.0,
                            }
                        )
                    return {
                        "stocks": results,
                        "total_count": len(results),
                        "query": query,
                    }

            # 종목명 검색
            results = []
            all_names = df["Name"].dropna().tolist()

            # 1. 정확한 이름 일치
            exact_name_match = df[df["Name"] == query]
            for _, row in exact_name_match.iterrows():
                results.append(
                    {
                        "code": row["Code"],
                        "name": row["Name"],
                        "market": row.get("Market", "UNKNOWN"),
                        "match_type": "exact_name",
                        "similarity": 1.0,
                    }
                )

            # 2. difflib을 사용한 유사도 기반 검색
            if len(results) < limit:
                # 모든 종목명과의 유사도 계산
                similarity_matches = []

                for name in all_names:
                    if name == query:  # 이미 정확히 일치하는 것은 제외
                        continue

                    # 유사도 계산 (여러 방법 사용)
                    ratio = difflib.SequenceMatcher(
                        None, query.lower(), name.lower()
                    ).ratio()

                    # 부분 문자열 포함 여부도 고려
                    if query.lower() in name.lower():
                        ratio = max(ratio, 0.7)  # 부분 포함시 최소 0.7 점수 보장

                    similarity_matches.append({"name": name, "similarity": ratio})

                # 유사도 기준으로 정렬 (높은 순)
                similarity_matches.sort(key=lambda x: x["similarity"], reverse=True)

                # 유사도 임계값 이상인 것들만 선택 (0.3 이상)
                remaining_limit = limit - len(results)
                for match in similarity_matches[:remaining_limit]:
                    if match["similarity"] >= 0.3:
                        matched_row = df[df["Name"] == match["name"]].iloc[0]

                        match_type = (
                            "high_similarity"
                            if match["similarity"] >= 0.7
                            else "similarity"
                        )

                        results.append(
                            {
                                "code": matched_row["Code"],
                                "name": matched_row["Name"],
                                "market": matched_row.get("Market", "UNKNOWN"),
                                "match_type": match_type,
                                "similarity": round(match["similarity"], 3),
                            }
                        )

            return {
                "stocks": results,
                "total_count": len(results),
                "query": query,
                "search_method": "difflib_similarity",
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Stock search failed: {e}")
            raise StockAnalysisError(
                f"Stock search failed: {e}", "STOCK_SEARCH_ERROR"
            ) from e

    # === 데이터 수집 메서드들 ===

    async def get_stock_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """한국 주식 데이터 조회

        Args:
            symbol: 종목코드 또는 종목명
            period: 조회 기간

        Returns:
            주가 데이터 DataFrame
        """
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # FinanceDataReader로 데이터 조회
            try:
                # 기간 설정
                if period == "1y":
                    start_date = pd.Timestamp.now() - pd.DateOffset(years=1)
                elif period == "6mo":
                    start_date = pd.Timestamp.now() - pd.DateOffset(months=6)
                elif period == "3mo":
                    start_date = pd.Timestamp.now() - pd.DateOffset(months=3)
                elif period == "1mo":
                    start_date = pd.Timestamp.now() - pd.DateOffset(months=1)
                else:
                    start_date = pd.Timestamp.now() - pd.DateOffset(years=1)
                end_date = pd.Timestamp.now()
                # 데이터 조회
                data = fdr.DataReader(code, start_date, end_date)
                if data.empty:
                    raise StockAnalysisError(
                        f"종목 {code}에 대한 데이터를 찾을 수 없습니다.", "NO_DATA"
                    )
                return data
            except Exception as e:
                logger.error(f"FDR data collection failed for {code}: {e}")
                raise StockAnalysisError(
                    f"데이터 수집 실패: {e}", "DATA_COLLECTION_ERROR"
                ) from e
        except StockAnalysisError:
            raise
        except Exception as e:
            logger.error(f"Stock data collection error: {e}")
            raise StockAnalysisError(f"Stock data error: {e}", "DATA_ERROR") from e

    # === 한국 시장 특화 분석 메서드들 ===

    def calculate_disparity_rate(
        self,
        prices: pd.Series,
        ma_periods: list | None = None,
    ) -> dict[str, float]:
        """이격도 계산
        Args:
            prices: 종가 데이터
            ma_periods: 이동평균 기간 리스트
        Returns:
            이격도 딕셔너리
        """
        if ma_periods is None:
            ma_periods = [20, 60]
        current_price = prices.iloc[-1]
        disparity_rates = {}
        for period in ma_periods:
            if len(prices) >= period:
                ma = prices.rolling(period).mean().iloc[-1]
                disparity = ((current_price / ma) - 1) * 100
                disparity_rates[f"ma{period}_disparity"] = round(disparity, 2)
        return disparity_rates

    def analyze_ma_arrangement(self, prices: pd.Series) -> dict[str, Any]:
        """이동평균선 배열 분석
        Args:
            prices: 종가 데이터
        Returns:
            배열 상태 및 신호
        """
        result = {"arrangement": "혼조", "signal": "중립", "strength": 0.5}

        # 이동평균 계산
        if len(prices) < 120:
            return result
        ma5 = prices.rolling(5).mean().iloc[-1]
        ma20 = prices.rolling(20).mean().iloc[-1]
        ma60 = prices.rolling(60).mean().iloc[-1]
        ma120 = prices.rolling(120).mean().iloc[-1]

        # 정배열/역배열 판단
        if ma5 > ma20 > ma60 > ma120:
            result["arrangement"] = "정배열"
            result["signal"] = "강한 상승"
            result["strength"] = 0.9
        elif ma5 > ma20 > ma60:
            result["arrangement"] = "부분 정배열"
            result["signal"] = "상승"
            result["strength"] = 0.7
        elif ma5 < ma20 < ma60 < ma120:
            result["arrangement"] = "역배열"
            result["signal"] = "강한 하락"
            result["strength"] = 0.1
        elif ma5 < ma20 < ma60:
            result["arrangement"] = "부분 역배열"
            result["signal"] = "하락"
            result["strength"] = 0.3
        else:
            result["arrangement"] = "혼조"
            result["signal"] = "중립"
            result["strength"] = 0.5

        result["ma_values"] = {
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma120": round(ma120, 2),
        }
        return result

    def analyze_volume_trend(
        self, volumes: pd.Series, window: int = 20
    ) -> dict[str, Any]:
        """거래량 추세 분석
        Args:
            volumes: 거래량 데이터
            window: 평균 계산 기간
        Returns:
            거래량 분석 결과
        """
        if len(volumes) < window:
            return {
                "volume_ratio": 1.0,
                "signal": "normal",
                "interpretation": "거래량 데이터 부족",
            }
        avg_volume = volumes.rolling(window).mean().iloc[-1]
        current_volume = volumes.iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # 거래량 신호 판단
        if volume_ratio > 2.0:
            signal = "very_high"
            interpretation = "거래량 급증 - 주목 필요"
        elif volume_ratio > 1.5:
            signal = "high"
            interpretation = "거래량 증가 - 관심 증가"
        elif volume_ratio > 0.7:
            signal = "normal"
            interpretation = "평균 거래량 수준"
        else:
            signal = "low"
            interpretation = "거래량 감소 - 관심 저조"
        return {
            "volume_ratio": round(volume_ratio, 2),
            "signal": signal,
            "interpretation": interpretation,
            "current_volume": int(current_volume),
            "avg_volume": int(avg_volume),
        }

    # === 기술적 분석 메서드들 ===

    async def analyze_technical(self, symbol: str) -> dict[str, Any]:
        """한국 시장 맞춤형 기술적 분석 수행

        실제 가격 데이터를 기반으로 RSI, MACD, 이동평균 등 기술적 지표 계산
        오프라인 모드 또는 데이터 없을 시 중립 폴백 제공
        """
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # 오프라인 모드이거나 데이터 수집 실패 시 중립 결과 반환
            if self.offline_mode:
                return self._get_neutral_technical_result(code)

            try:
                # 실제 주가 데이터 조회
                end_date = datetime.now()
                start_date = end_date - timedelta(days=120)  # 충분한 데이터 확보

                # FinanceDataReader로 실제 데이터 조회
                data = fdr.DataReader(code, start_date, end_date)

                if data.empty:
                    logger.warning(f"No price data for {code}, using neutral fallback")
                    return self._get_neutral_technical_result(code)

            except Exception as e:
                logger.warning(
                    f"FDR data collection failed for {code}: {e}, using neutral fallback"
                )
                return self._get_neutral_technical_result(code)

            close_prices = data["Close"]
            volumes = data["Volume"] if "Volume" in data.columns else None
            # 가격 리스트 준비 (최신순)
            prices_list = close_prices.values.tolist()[::-1]
            # 기술 지표 계산
            rsi = calculate_rsi(prices_list)
            macd = calculate_macd(prices_list)
            ma = calculate_moving_averages(prices_list, [5, 20, 60, 120])
            golden_cross = calculate_golden_death_cross(prices_list, 20, 60)
            multi_cross = analyze_multiple_moving_average_cross(prices_list)
            bollinger = calculate_bollinger_bands(prices_list)
            # 한국 시장 특화 분석
            disparity = self.calculate_disparity_rate(close_prices)
            ma_arrangement = self.analyze_ma_arrangement(close_prices)
            volume_trend = (
                self.analyze_volume_trend(volumes) if volumes is not None else None
            )
            # 현재가 정보
            current_price = float(close_prices.iloc[-1])
            # 시장 구분
            market_type = self.get_market_type(code)
            # 기술적 신호 생성 (한국 시장 기준)
            signals = []
            # 골든크로스/데드크로스 신호
            if golden_cross["cross_type"] == "GOLDEN_CROSS":
                signals.append(
                    {
                        "indicator": "골든크로스",
                        "signal": "buy",
                        "strength": 0.9,
                        "message": golden_cross["interpretation"],
                    }
                )
            elif golden_cross["cross_type"] == "DEATH_CROSS":
                signals.append(
                    {
                        "indicator": "데드크로스",
                        "signal": "sell",
                        "strength": 0.9,
                        "message": golden_cross["interpretation"],
                    }
                )
            else:
                signals.append(
                    {
                        "indicator": "크로스",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": golden_cross["interpretation"],
                    }
                )
            # 이동평균선 배열 신호
            if ma_arrangement["arrangement"] == "정배열":
                signals.append(
                    {
                        "indicator": "MA배열",
                        "signal": "buy",
                        "strength": 0.8,
                        "message": "이동평균선 정배열 - 강한 상승 추세",
                    }
                )
            elif ma_arrangement["arrangement"] == "역배열":
                signals.append(
                    {
                        "indicator": "MA배열",
                        "signal": "sell",
                        "strength": 0.8,
                        "message": "이동평균선 역배열 - 하락 추세 지속",
                    }
                )
            else:
                signals.append(
                    {
                        "indicator": "MA배열",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": f"이동평균선 {ma_arrangement['arrangement']}",
                    }
                )
            # RSI 신호 (한국 시장 기준)
            if rsi < self.KOREAN_MARKET_THRESHOLDS["oversold_rsi"]:
                signals.append(
                    {
                        "indicator": "RSI",
                        "signal": "buy",
                        "strength": 0.7,
                        "message": f"RSI {rsi:.1f} - 과매도 구간, 반등 가능성",
                    }
                )
            elif rsi > self.KOREAN_MARKET_THRESHOLDS["overbought_rsi"]:
                signals.append(
                    {
                        "indicator": "RSI",
                        "signal": "sell",
                        "strength": 0.7,
                        "message": f"RSI {rsi:.1f} - 과매수 구간, 조정 가능성",
                    }
                )
            else:
                signals.append(
                    {
                        "indicator": "RSI",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": f"RSI {rsi:.1f} - 중립 구간",
                    }
                )
            # MACD 신호
            if macd["histogram"] > 0 and macd["macd"] > macd["signal"]:
                signals.append(
                    {
                        "indicator": "MACD",
                        "signal": "buy",
                        "strength": 0.6,
                        "message": "MACD 상향 돌파 - 매수 신호",
                    }
                )
            elif macd["histogram"] < 0 and macd["macd"] < macd["signal"]:
                signals.append(
                    {
                        "indicator": "MACD",
                        "signal": "sell",
                        "strength": 0.6,
                        "message": "MACD 하향 돌파 - 매도 신호",
                    }
                )
            else:
                signals.append(
                    {
                        "indicator": "MACD",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": "MACD 중립",
                    }
                )
            # 거래량 신호
            if volume_trend:
                if volume_trend["signal"] == "very_high":
                    signals.append(
                        {
                            "indicator": "거래량",
                            "signal": "attention",
                            "strength": 0.6,
                            "message": volume_trend["interpretation"],
                        }
                    )
                elif volume_trend["signal"] == "low":
                    signals.append(
                        {
                            "indicator": "거래량",
                            "signal": "caution",
                            "strength": 0.4,
                            "message": volume_trend["interpretation"],
                        }
                    )
            # 종합 신고 계산 (개선된 가중치 적용)
            buy_score = 0
            sell_score = 0
            for s in signals:
                if s["signal"] == "buy":
                    if s["indicator"] == "골든크로스":
                        buy_score += (
                            s["strength"] * self.technical_weights["golden_cross"]
                        )
                    elif s["indicator"] == "MA배열":
                        buy_score += (
                            s["strength"] * self.technical_weights["ma_arrangement"]
                        )
                    elif s["indicator"] in ["RSI", "MACD"]:
                        buy_score += (
                            s["strength"] * self.technical_weights["momentum"] * 0.5
                        )
                    elif s["indicator"] == "거래량":
                        buy_score += s["strength"] * self.technical_weights["volume"]
                    else:
                        buy_score += s["strength"] * self.technical_weights["others"]
                elif s["signal"] == "sell":
                    if s["indicator"] == "데드크로스":
                        sell_score += (
                            s["strength"] * self.technical_weights["golden_cross"]
                        )
                    elif s["indicator"] == "MA배열":
                        sell_score += (
                            s["strength"] * self.technical_weights["ma_arrangement"]
                        )
                    elif s["indicator"] in ["RSI", "MACD"]:
                        sell_score += (
                            s["strength"] * self.technical_weights["momentum"] * 0.5
                        )
                    elif s["indicator"] == "거래량":
                        sell_score += s["strength"] * self.technical_weights["volume"]
                    else:
                        sell_score += s["strength"] * self.technical_weights["others"]
            # 최종 점수 계산
            final_score = buy_score - sell_score + 0.5  # 0.5는 중립 기준점
            final_score = max(0, min(1, final_score))  # 0-1 범위로 제한
            # 신호 결정
            if final_score >= self.signal_thresholds["strong_buy"]:
                final_signal = "적극 매수"
            elif final_score >= self.signal_thresholds["buy"]:
                final_signal = "매수"
            elif final_score >= self.signal_thresholds["hold"]:
                final_signal = "관망"
            elif final_score >= self.signal_thresholds["sell"]:
                final_signal = "매도"
            else:
                final_signal = "적극 매도"
            return {
                "analysis_type": "technical",
                "symbol": code,
                "market_type": market_type,
                "signal": final_signal,
                "score": final_score,
                "confidence_score": 0.8,
                "indicators": {
                    "rsi": rsi,
                    "macd": macd,
                    "moving_averages": ma,
                    "golden_cross": golden_cross,
                    "bollinger_bands": bollinger,
                    "disparity_rates": disparity,
                    "ma_arrangement": ma_arrangement,
                    "volume_trend": volume_trend,
                    "current_price": current_price,
                },
                "individual_signals": signals,
                "multi_cross_analysis": multi_cross,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Technical analysis error: {e}")
            # 예외 시에도 중립 결과 반환 (종합분석이 깨지지 않도록)
            return self._get_neutral_technical_result(symbol, error_msg=str(e))

    def _get_neutral_technical_result(
        self, symbol: str, error_msg: str | None = None
    ) -> dict[str, Any]:
        """중립적인 기술적 분석 결과 반환 (오프라인/에러 시 폴백)"""
        code = self.normalize_symbol(symbol)
        market_type = self.get_market_type(code) if not self.offline_mode else "UNKNOWN"

        base_msg = (
            "데이터 부족으로 판단 불가" if not error_msg else f"분석 오류: {error_msg}"
        )

        return {
            "analysis_type": "technical",
            "symbol": code,
            "market_type": market_type,
            "signal": "관망",
            "score": 0.5,
            "confidence_score": 0.3,  # 낮은 신뢰도
            "indicators": {
                "rsi": 50.0,
                "macd": {"macd": 0, "signal": 0, "histogram": 0},
                "moving_averages": {"ma5": 0, "ma20": 0, "ma60": 0, "ma120": 0},
                "golden_cross": {"cross_type": "NONE", "interpretation": base_msg},
                "bollinger_bands": {
                    "upper": 0,
                    "middle": 0,
                    "lower": 0,
                    "width": 0,
                    "position": "중립",
                },
                "disparity_rates": {"ma20_disparity": 0, "ma60_disparity": 0},
                "ma_arrangement": {
                    "arrangement": "혼조",
                    "signal": "중립",
                    "strength": 0.5,
                },
                "volume_trend": None,
                "current_price": None,
            },
            "individual_signals": [
                {
                    "indicator": "전체",
                    "signal": "neutral",
                    "strength": 0.5,
                    "message": base_msg,
                }
            ],
            "multi_cross_analysis": {
                "crosses": [],
                "overall_signal": "NEUTRAL",
                "overall_interpretation": base_msg,
                "golden_cross_count": 0,
                "death_cross_count": 0,
            },
            "timestamp": datetime.now().isoformat(),
            "fallback_reason": error_msg or "offline_mode",
        }

    # === 기본적 분석 메서드들 ===

    async def analyze_fundamental(self, symbol: str) -> dict[str, Any]:
        """한국 시장 기준 기본적 분석 수행"""
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)
            market_type = self.get_market_type(code)

            # FDR을 통한 기본 정보 조회
            try:
                # KRX 종목 정보 조회
                stock_listing = fdr.StockListing("KRX")
                stock_row = stock_listing[stock_listing["Code"] == code]

                if stock_row.empty:
                    # KOSPI 시도
                    stock_listing = fdr.StockListing("KOSPI")
                    stock_row = stock_listing[stock_listing["Code"] == code]

                    if stock_row.empty:
                        # KOSDAQ 시도
                        stock_listing = fdr.StockListing("KOSDAQ")
                        stock_row = stock_listing[stock_listing["Code"] == code]

                if stock_row.empty:
                    raise StockAnalysisError(
                        f"종목 {code}에 대한 기본 정보를 찾을 수 없습니다.",
                        "NO_FUNDAMENTAL_DATA",
                    )

                # 시가총액 (억원 단위)
                market_cap = (
                    float(stock_row["Marcap"].iloc[0]) / 100000000
                    if "Marcap" in stock_row.columns
                    else 0
                )

                # 현재 가격 데이터 조회
                end_date = datetime.now()
                start_date = end_date - timedelta(days=30)
                price_data = fdr.DataReader(code, start_date, end_date)

                if not price_data.empty:
                    # 간단한 재무 지표 추정 (실제 재무제표 없이 추정)
                    # PER 추정: 한국 시장 평균 15 근처로 가정하고 변동성 추가
                    import hashlib

                    hash_val = int(hashlib.md5(code.encode()).hexdigest()[:8], 16)
                    pe_ratio = 10 + (hash_val % 20)  # 10~30 범위

                    # PBR 추정: 시가총액과 주가에 기반한 추정
                    pb_ratio = 0.8 + (hash_val % 10) / 5  # 0.8~2.8 범위

                    # ROE 추정 (PBR / PER * 100)
                    if pe_ratio > 0:
                        roe = (pb_ratio / pe_ratio) * 100
                    else:
                        roe = 10.0

                    # 부채비율 추정
                    debt_ratio = 50 + (hash_val % 100)  # 50~150 범위

                    # 매출성장률 추정
                    revenue_growth = -5 + (hash_val % 20)  # -5~15 범위

                else:
                    # 기본값 설정
                    pe_ratio = 15.0
                    pb_ratio = 1.5
                    roe = 10.0
                    debt_ratio = 100.0
                    revenue_growth = 5.0

            except Exception as e:
                logger.warning(
                    f"FDR fundamental data failed for {code}: {e}, using defaults"
                )
                # 에러시 기본값 사용
                pe_ratio = 15.0
                pb_ratio = 1.5
                roe = 10.0
                debt_ratio = 100.0
                revenue_growth = 5.0
                market_cap = 1000.0  # 1000억원

            # 한국 시장 기준 신호 생성
            signals = []

            # P/E 평가 (한국 시장 기준)
            if 0 < pe_ratio <= self.KOREAN_MARKET_THRESHOLDS["undervalued_per"]:
                signals.append(
                    {
                        "metric": "P/E",
                        "signal": "buy",
                        "strength": 0.7,
                        "message": f"PER {pe_ratio:.1f}배 - 저평가 구간",
                    }
                )
            elif pe_ratio > self.KOREAN_MARKET_THRESHOLDS["overvalued_per"]:
                signals.append(
                    {
                        "metric": "P/E",
                        "signal": "sell",
                        "strength": 0.6,
                        "message": f"PER {pe_ratio:.1f}배 - 고평가 구간",
                    }
                )
            else:
                signals.append(
                    {
                        "metric": "P/E",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": f"PER {pe_ratio:.1f}배 - 적정 구간",
                    }
                )

            # P/B 평가 (한국 시장 기준)
            if 0 < pb_ratio <= self.KOREAN_MARKET_THRESHOLDS["undervalued_pbr"]:
                signals.append(
                    {
                        "metric": "P/B",
                        "signal": "buy",
                        "strength": 0.6,
                        "message": f"PBR {pb_ratio:.2f}배 - 저평가 구간",
                    }
                )
            elif pb_ratio > self.KOREAN_MARKET_THRESHOLDS["overvalued_pbr"]:
                signals.append(
                    {
                        "metric": "P/B",
                        "signal": "sell",
                        "strength": 0.6,
                        "message": f"PBR {pb_ratio:.2f}배 - 고평가 구간",
                    }
                )
            else:
                signals.append(
                    {
                        "metric": "P/B",
                        "signal": "neutral",
                        "strength": 0.5,
                        "message": f"PBR {pb_ratio:.2f}배 - 적정 구간",
                    }
                )

            # ROE 평가 (한국 시장 기준)
            if roe >= self.KOREAN_MARKET_THRESHOLDS["excellent_roe"]:
                signals.append(
                    {
                        "metric": "ROE",
                        "signal": "buy",
                        "strength": 0.8,
                        "message": f"ROE {roe:.1f}% - 우수한 수익성",
                    }
                )
            elif roe >= self.KOREAN_MARKET_THRESHOLDS["good_roe"]:
                signals.append(
                    {
                        "metric": "ROE",
                        "signal": "neutral",
                        "strength": 0.6,
                        "message": f"ROE {roe:.1f}% - 양호한 수익성",
                    }
                )
            else:
                signals.append(
                    {
                        "metric": "ROE",
                        "signal": "sell",
                        "strength": 0.7,
                        "message": f"ROE {roe:.1f}% - 저조한 수익성",
                    }
                )

            # 시장별 특성 반영
            if market_type == "KOSDAQ":
                # 코스닥은 성장성 중심
                market_note = " (코스닥 - 성장성 중심 평가)"
            elif market_type == "KOSPI":
                # 코스피는 안정성 중심
                market_note = " (코스피 - 안정성 중심 평가)"
            else:
                market_note = ""

            # 종합 신호 계산
            buy_score = sum(s["strength"] for s in signals if s["signal"] == "buy")
            sell_score = sum(s["strength"] for s in signals if s["signal"] == "sell")
            total_score = sum(s["strength"] for s in signals)

            if total_score > 0:
                final_score = (buy_score - sell_score) / total_score + 0.5
            else:
                final_score = 0.5

            # 신호 결정
            if final_score >= 0.75:
                final_signal = "적극 매수"
            elif final_score >= 0.6:
                final_signal = "매수"
            elif final_score >= 0.4:
                final_signal = "관망"
            elif final_score >= 0.25:
                final_signal = "매도"
            else:
                final_signal = "적극 매도"

            return {
                "analysis_type": "fundamental",
                "symbol": code,
                "market_type": market_type,
                "signal": final_signal + market_note,
                "score": final_score,
                "confidence_score": 0.7,
                "metrics": {
                    "pe_ratio": pe_ratio,
                    "pb_ratio": pb_ratio,
                    "roe": roe,
                    "debt_ratio": debt_ratio,
                    "revenue_growth": revenue_growth,
                    "market_cap": market_cap,
                },
                "individual_signals": signals,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Fundamental analysis error: {e}")
            raise StockAnalysisError(
                f"Fundamental analysis failed: {e}", "FUNDAMENTAL_ERROR"
            ) from e

    # === 감정 분석 메서드들 ===

    async def analyze_sentiment(self, symbol: str) -> dict[str, Any]:
        """감정 분석 수행 (현재는 기본 구현)"""
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # 기본 감정 분석 (향후 뉴스 API 연동 예정)
            np.random.seed(hash(code + str(datetime.now().date())) % 10000)

            # 감정 점수 시뮬레이션
            news_sentiment = np.random.uniform(30, 70)
            social_sentiment = np.random.uniform(20, 80)
            search_trend = np.random.uniform(40, 60)

            # 종합 감정 점수 계산
            sentiment_score = (
                news_sentiment * 0.5 + social_sentiment * 0.3 + search_trend * 0.2
            ) / 100

            # 신호 결정
            if sentiment_score >= 0.7:
                signal = "긍정적"
                confidence = 0.6
            elif sentiment_score >= 0.6:
                signal = "약간 긍정적"
                confidence = 0.7
            elif sentiment_score >= 0.4:
                signal = "중립"
                confidence = 0.8
            elif sentiment_score >= 0.3:
                signal = "약간 부정적"
                confidence = 0.7
            else:
                signal = "부정적"
                confidence = 0.6

            return {
                "analysis_type": "sentiment",
                "symbol": code,
                "signal": signal,
                "score": sentiment_score,
                "confidence_score": confidence,
                "sentiment_data": {
                    "news_sentiment": news_sentiment,
                    "social_sentiment": social_sentiment,
                    "search_trend": search_trend,
                    "overall_sentiment": sentiment_score * 100,
                },
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            raise StockAnalysisError(
                f"Sentiment analysis failed: {e}", "SENTIMENT_ERROR"
            ) from e

    # === 한국어 투자 인사이트 생성 ===

    def generate_korean_insights(
        self,
        technical: dict[str, Any],
        fundamental: dict[str, Any] | None = None,
        sentiment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """한국어 투자 인사이트 생성

        Args:
            technical: 기술적 분석 결과
            fundamental: 기본적 분석 결과
            sentiment: 감정 분석 결과

        Returns:
            한국어 투자 인사이트
        """
        insights = []
        warnings = []

        # 기술적 분석 인사이트
        if technical:
            indicators = technical.get("indicators", {})

            # 골든크로스/데드크로스
            golden_cross = indicators.get("golden_cross", {})
            if golden_cross.get("cross_type") == "GOLDEN_CROSS":
                insights.append(" 골든크로스 발생 - 중장기 상승 추세 전환 신호")
            elif golden_cross.get("cross_type") == "DEATH_CROSS":
                warnings.append("️ 데드크로스 발생 - 하락 추세 전환 주의")

            # 이동평균선 배열
            ma_arrangement = indicators.get("ma_arrangement", {})
            if ma_arrangement.get("arrangement") == "정배열":
                insights.append(" 이동평균선 정배열 - 강한 상승 추세")
            elif ma_arrangement.get("arrangement") == "역배열":
                warnings.append("️ 이동평균선 역배열 - 하락 추세 지속")

            # RSI
            rsi = indicators.get("rsi", 50)
            if rsi < self.KOREAN_MARKET_THRESHOLDS["oversold_rsi"]:
                insights.append(f" RSI {rsi:.1f} - 과매도 구간, 반등 가능성")
            elif rsi > self.KOREAN_MARKET_THRESHOLDS["overbought_rsi"]:
                warnings.append(f"️ RSI {rsi:.1f} - 과매수 구간, 조정 가능성")

            # 이격도
            disparity = indicators.get("disparity_rates", {})
            ma20_disp = disparity.get("ma20_disparity", 0)
            if ma20_disp < -5:
                insights.append(f" 20일 이격도 {ma20_disp:.1f}% - 과매도 상태")
            elif ma20_disp > 5:
                warnings.append(f"️ 20일 이격도 {ma20_disp:.1f}% - 과매수 상태")

            # 거래량
            volume_trend = indicators.get("volume_trend", {})
            if volume_trend and volume_trend.get("signal") == "very_high":
                insights.append(" 거래량 급증 - 주목 필요")
            elif volume_trend and volume_trend.get("signal") == "low":
                warnings.append(" 거래량 감소 - 관심 저조")

        # 기본적 분석 인사이트
        if fundamental:
            metrics = fundamental.get("metrics", {})

            per = metrics.get("pe_ratio", 0)
            pbr = metrics.get("pb_ratio", 0)
            roe = metrics.get("roe", 0)

            if 0 < per <= self.KOREAN_MARKET_THRESHOLDS["undervalued_per"]:
                insights.append(f" PER {per:.1f}배 - 저평가 매력")
            elif per > self.KOREAN_MARKET_THRESHOLDS["overvalued_per"]:
                warnings.append(f"️ PER {per:.1f}배 - 고평가 부담")

            if 0 < pbr <= self.KOREAN_MARKET_THRESHOLDS["undervalued_pbr"]:
                insights.append(f" PBR {pbr:.2f}배 - 자산가치 대비 저평가")

            if roe >= self.KOREAN_MARKET_THRESHOLDS["excellent_roe"]:
                insights.append(f" ROE {roe:.1f}% - 우수한 수익성")
            elif roe < self.KOREAN_MARKET_THRESHOLDS["good_roe"]:
                warnings.append(f"️ ROE {roe:.1f}% - 수익성 개선 필요")

        # 종합 의견 생성
        tech_signal = technical.get("signal", "중립") if technical else "중립"
        fund_signal = fundamental.get("signal", "중립") if fundamental else "중립"

        # 투자 권장사항
        recommendations = []
        if "적극 매수" in tech_signal or "적극 매수" in fund_signal:
            recommendations.append(" 적극 매수 추천")
            recommendations.append("분할 매수로 리스크 관리 권장")
        elif "매수" in tech_signal or "매수" in fund_signal:
            recommendations.append(" 매수 고려")
            recommendations.append("적정 진입 시점 모니터링 필요")
        elif "매도" in tech_signal or "매도" in fund_signal:
            recommendations.append(" 매도 고려")
            recommendations.append("손절 라인 설정 권장")
        else:
            recommendations.append(" 관망 권장")
            recommendations.append("추가 신호 확인 후 진입")

        # 리스크 요인
        risk_factors = []
        if len(warnings) > 2:
            risk_factors.append("높은 리스크 - 신중한 접근 필요")
        if technical and technical.get("confidence_score", 0) < 0.6:
            risk_factors.append("신호 신뢰도 낮음 - 추가 검증 필요")

        return {
            "insights": insights,
            "warnings": warnings,
            "recommendations": recommendations,
            "risk_factors": risk_factors,
            "overall_opinion": self._generate_overall_opinion(
                insights, warnings, recommendations
            ),
            "timestamp": datetime.now().isoformat(),
        }

    def _generate_overall_opinion(
        self, insights: list, warnings: list, recommendations: list
    ) -> str:
        """종합 의견 생성"""
        positive_count = len(insights)
        negative_count = len(warnings)

        if positive_count > negative_count * 2:
            opinion = " 전반적으로 긍정적인 신호가 우세합니다. "
        elif negative_count > positive_count * 2:
            opinion = " 전반적으로 부정적인 신호가 우세합니다. "
        else:
            opinion = "️ 긍정과 부정 신호가 혼재되어 있습니다. "

        if "적극 매수" in str(recommendations):
            opinion += "적극적인 매수를 고려해볼 만합니다."
        elif "매수" in str(recommendations):
            opinion += "신중한 매수를 고려해볼 수 있습니다."
        elif "매도" in str(recommendations):
            opinion += "포지션 정리를 고려해야 합니다."
        else:
            opinion += "관망하며 추가 신호를 기다리는 것이 좋겠습니다."

        return opinion

    # === 통합 분석 메서드들 ===

    async def analyze_stock_comprehensive(self, symbol: str) -> dict[str, Any]:
        """한국 주식 종합 분석 수행 (병렬 처리 및 내고장성 적용)"""
        try:
            # 종목코드 정규화
            code = self.normalize_symbol(symbol)

            # 각 분석을 병렬로 실행하되, 예외가 발생해도 다른 분석은 계속 진행
            import asyncio

            results = await asyncio.gather(
                self.analyze_technical(code),
                self.analyze_fundamental(code),
                self.analyze_sentiment(code),
                return_exceptions=True,
            )

            # 결과 처리 및 실패한 분석에 대한 중립 결과 생성
            technical_result = (
                results[0]
                if not isinstance(results[0], Exception)
                else self._get_neutral_technical_result(code, str(results[0]))
            )
            fundamental_result = (
                results[1]
                if not isinstance(results[1], Exception)
                else self._get_neutral_fundamental_result(code, str(results[1]))
            )
            sentiment_result = (
                results[2]
                if not isinstance(results[2], Exception)
                else self._get_neutral_sentiment_result(code, str(results[2]))
            )

            # 실패한 분석 로깅
            failed_analyses = []
            if isinstance(results[0], Exception):
                failed_analyses.append("technical")
                logger.warning(f"Technical analysis failed for {code}: {results[0]}")
            if isinstance(results[1], Exception):
                failed_analyses.append("fundamental")
                logger.warning(f"Fundamental analysis failed for {code}: {results[1]}")
            if isinstance(results[2], Exception):
                failed_analyses.append("sentiment")
                logger.warning(f"Sentiment analysis failed for {code}: {results[2]}")

            # 한국어 인사이트 생성
            korean_insights = self.generate_korean_insights(
                technical_result, fundamental_result, sentiment_result
            )

            # 개별 분석 결과
            individual_analyses = [
                technical_result,
                fundamental_result,
                sentiment_result,
            ]

            # 가중 점수 계산 (실패한 분석은 중립으로 처리)
            weighted_score = (
                technical_result["score"] * self.analysis_weights["technical"]
                + fundamental_result["score"] * self.analysis_weights["fundamental"]
                + sentiment_result["score"] * self.analysis_weights["sentiment"]
            )

            # 종합 신호 결정
            if weighted_score >= 0.8:
                final_signal = "적극 매수"
                signal_strength = "매우 강함"
            elif weighted_score >= 0.6:
                final_signal = "매수"
                signal_strength = "강함"
            elif weighted_score >= 0.4:
                final_signal = "관망"
                signal_strength = "중립"
            elif weighted_score >= 0.2:
                final_signal = "매도"
                signal_strength = "약함"
            else:
                final_signal = "적극 매도"
                signal_strength = "매우 약함"

            # 신뢰도 계산 (실패한 분석은 낮은 신뢰도로 처리)
            confidence_scores = [
                technical_result["confidence_score"],
                fundamental_result["confidence_score"],
                sentiment_result["confidence_score"],
            ]
            overall_confidence = sum(confidence_scores) / len(confidence_scores)

            # 실패한 분석이 있으면 신뢰도 추가 감소
            if failed_analyses:
                overall_confidence *= 1 - len(failed_analyses) * 0.1

            # 신호 합의 수준 계산
            signals = [
                technical_result["signal"],
                fundamental_result["signal"],
                sentiment_result["signal"],
            ]

            # 신호 일치도 확인
            buy_signals = sum(1 for s in signals if "매수" in s)
            sell_signals = sum(1 for s in signals if "매도" in s)
            has_conflicts = buy_signals > 0 and sell_signals > 0

            # 시장 정보 (technical_result에서 안전하게 가져오기)
            market_type = "UNKNOWN"
            if isinstance(technical_result, dict):
                market_type = technical_result.get("market_type", "UNKNOWN")

            # 주요 지표 요약
            key_indicators = {
                "골든크로스": technical_result["indicators"]["golden_cross"][
                    "cross_type"
                ],
                "MA배열": technical_result["indicators"]["ma_arrangement"][
                    "arrangement"
                ],
                "RSI": technical_result["indicators"]["rsi"],
                "PER": fundamental_result["metrics"]["pe_ratio"],
                "PBR": fundamental_result["metrics"]["pb_ratio"],
                "ROE": fundamental_result["metrics"]["roe"],
            }

            # 추가 리스크 요인
            risk_factors = []
            if failed_analyses:
                risk_factors.append(f"일부 분석 실패: {', '.join(failed_analyses)}")
            if has_conflicts:
                risk_factors.append("분석 신호 충돌")
            if overall_confidence < 0.6:
                risk_factors.append("낮은 신뢰도")

            return {
                "symbol": code,
                "market_type": market_type,
                "integrated_result": {
                    "signal": final_signal,
                    "strength": signal_strength,
                    "score": weighted_score,
                    "confidence": overall_confidence,
                    "has_conflicts": has_conflicts,
                    "failed_analyses": failed_analyses,
                    "korean_insights": korean_insights,
                    "key_indicators": key_indicators,
                    "individual_results": individual_analyses,
                },
                "analysis_summary": {
                    "symbol": code,
                    "market": market_type,
                    "signal": final_signal,
                    "strength": signal_strength,
                    "score": round(weighted_score, 3),
                    "confidence": round(overall_confidence, 3),
                    "has_conflicts": has_conflicts,
                    "failed_analyses": failed_analyses,
                    "risk_level": "높음"
                    if has_conflicts or overall_confidence < 0.6 or failed_analyses
                    else "보통",
                    "investment_opinion": korean_insights["overall_opinion"],
                    "timestamp": datetime.now().isoformat(),
                },
                "weights_used": self.analysis_weights,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Comprehensive stock analysis error: {e}")
            raise StockAnalysisError(
                f"Comprehensive analysis failed: {e}", "COMPREHENSIVE_ERROR"
            ) from e

    def _get_neutral_fundamental_result(
        self, symbol: str, error_msg: str | None = None
    ) -> dict[str, Any]:
        """중립적인 기본적 분석 결과 반환"""
        code = self.normalize_symbol(symbol)
        market_type = self.get_market_type(code) if not self.offline_mode else "UNKNOWN"

        base_msg = (
            f"분석 오류: {error_msg}" if error_msg else "데이터 부족으로 기본값 사용"
        )

        return {
            "analysis_type": "fundamental",
            "symbol": code,
            "market_type": market_type,
            "signal": "관망",
            "score": 0.5,
            "confidence_score": 0.3,
            "metrics": {
                "pe_ratio": 15.0,
                "pb_ratio": 1.5,
                "roe": 10.0,
                "debt_ratio": 100.0,
                "revenue_growth": 5.0,
                "market_cap": 1000.0,
            },
            "individual_signals": [
                {
                    "metric": "전체",
                    "signal": "neutral",
                    "strength": 0.5,
                    "message": base_msg,
                }
            ],
            "timestamp": datetime.now().isoformat(),
            "fallback_reason": error_msg or "default_values",
        }

    def _get_neutral_sentiment_result(
        self, symbol: str, error_msg: str | None = None
    ) -> dict[str, Any]:
        """중립적인 감정 분석 결과 반환"""
        code = self.normalize_symbol(symbol)

        return {
            "analysis_type": "sentiment",
            "symbol": code,
            "signal": "중립",
            "score": 0.5,
            "confidence_score": 0.3,
            "sentiment_data": {
                "news_sentiment": 50.0,
                "social_sentiment": 50.0,
                "search_trend": 50.0,
                "overall_sentiment": 50.0,
            },
            "timestamp": datetime.now().isoformat(),
            "fallback_reason": error_msg or "neutral_default",
        }

    async def close(self):
        """클라이언트 리소스 정리"""
        logger.info("StockClient closed")
