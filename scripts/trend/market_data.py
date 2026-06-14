"""시세/유니버스 데이터 레이어 — pykrx OHLCV·KOSPI지수·시총상위 유니버스 (scripts/trend/market_data.py)."""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timedelta

with contextlib.redirect_stdout(io.StringIO()):
    from pykrx import stock as krx

from trend.config import _ROOT, MIN_VALUE_KRW, TOP_N, UNIVERSE_MODE, WATCHLIST, logger


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


def _market_open_now() -> bool:
    """정규장 진행 중(평일 09:00–15:30)이면 True — 오늘 일봉이 미완성이라는 뜻."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 9 * 60 <= mins < 15 * 60 + 30


def _suppress():
    return contextlib.redirect_stdout(io.StringIO())


def get_ohlcv(symbol: str, days: int = 320) -> list[dict]:
    try:
        with _suppress():
            df = krx.get_market_ohlcv_by_date(_days_ago(days + 60), _today(), symbol)
        if df.empty:
            return []
        out = []
        for d, row in df.tail(days + 1).iterrows():
            out.append({"date": d.strftime("%Y-%m-%d"), "open": float(row.get("시가", 0)),
                        "high": float(row.get("고가", 0)), "low": float(row.get("저가", 0)),
                        "close": float(row.get("종가", 0)), "volume": float(row.get("거래량", 0)),
                        "value": float(row.get("거래대금", 0))})
        # 장중이면 오늘 미완성 일봉 제거 — 거래량·종가가 미완성이라 게이트 판정 왜곡(과소평가) 방지.
        # 추세추종은 '완성된 일봉'으로 신호를 잡고 익일 진입하는 검증 방식과 동일.
        if out and _market_open_now() and out[-1]["date"] == datetime.now().strftime("%Y-%m-%d"):
            out = out[:-1]
        return out[-days:]
    except Exception as e:
        logger.debug("[OHLCV] %s %s", symbol, e)
        return []


def _clean_index_closes(pairs: list[tuple[str, float]], days: int) -> list[float]:
    """지수 (date, close) → NaN/0 제거 + 장중 미완성 오늘봉 제거 후 마지막 days개."""
    out = [(d, c) for d, c in pairs if c == c and c > 0]   # c==c → NaN 제거
    if out and _market_open_now() and out[-1][0] == datetime.now().strftime("%Y-%m-%d"):
        out = out[:-1]
    return [c for _, c in out][-days:]


def get_kospi_closes(days: int = 320) -> list[float]:
    try:
        with _suppress():
            df = krx.get_index_ohlcv_by_date(_days_ago(days + 60), _today(), "1001")
        pairs = [(d.strftime("%Y-%m-%d"), float(row["종가"])) for d, row in df.iterrows()]
        res = _clean_index_closes(pairs, days)
        if res:
            return res
    except Exception:
        pass
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader("^KS11", _days_ago(days + 60), _today())
        pairs = [(d.strftime("%Y-%m-%d"), float(c)) for d, c in zip(df.index, df["Close"])]
        return _clean_index_closes(pairs, days)
    except Exception:
        return []


def _name(code: str) -> str:
    try:
        return krx.get_market_ticker_name(code)
    except Exception:
        return code


def _broad_codes() -> list[str]:
    """KOSPI 시총상위 캐시(docs_cache/universe_kiwoom_*.json) — 무네트워크·안정 소스."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    from backtest_dynamic import get_broad_universe  # 백테스트와 동일 유니버스
    return get_broad_universe()


def get_universe() -> list[tuple[str, str]]:
    """모드별 유니버스 [(code, name)]."""
    if UNIVERSE_MODE == "watchlist":
        return [(c, _name(c)) for c in WATCHLIST]
    # largecap: 시총상위 캐시 우선(pykrx 전종목 조회가 장중 실패해도 안정) — 백테스트와 동일.
    if UNIVERSE_MODE == "largecap":
        try:
            codes = _broad_codes()[:TOP_N]
            if codes:
                return [(c, _name(c)) for c in codes]
        except Exception as e:
            logger.warning("[UNIVERSE] 시총상위 캐시 실패: %s — pykrx 폴백", e)
    # gainers(또는 largecap 캐시 실패): pykrx 전종목에서 등락률/거래대금 상위
    for off in range(8):
        try:
            date = (datetime.now() - timedelta(days=off)).strftime("%Y%m%d")
            with _suppress():
                df = krx.get_market_ohlcv_by_ticker(date, market="KOSPI")
            if df.empty:
                continue
            df = df[df["거래대금"] >= MIN_VALUE_KRW]
            if UNIVERSE_MODE == "gainers" and "등락률" in df.columns:
                df = df.sort_values("등락률", ascending=False)
            else:  # largecap 캐시 실패 시 거래대금 상위 근사
                df = df.sort_values("거래대금", ascending=False)
            codes = list(df.head(TOP_N).index)
            return [(c, _name(c)) for c in codes]
        except Exception:
            continue
    # 최종 폴백: 시총상위 캐시 → watchlist (조용한 2종목 폴백 방지)
    try:
        codes = _broad_codes()[:TOP_N]
        if codes:
            return [(c, _name(c)) for c in codes]
    except Exception:
        pass
    return [(c, _name(c)) for c in WATCHLIST]
