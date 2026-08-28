"""시세/유니버스 데이터 레이어 — pykrx OHLCV·KOSPI지수·시총상위 유니버스.

trend 도메인 순수 데이터 함수. 외부 의존 (config·logger·env) 없음 — 호출자가 모드/한계값을 파라미터로 주입.
trend daemon(scripts/trend_follow.py) 과 backtest(scripts/backtest_trend.py) 모두 이 모듈을 공유한다.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

with contextlib.redirect_stdout(io.StringIO()):
    from pykrx import stock as krx

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]   # src/mcp_servers/trend_mcp/market_data.py → repo root


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
            close = float(row.get("종가", 0))
            volume = float(row.get("거래량", 0))
            # ⚠️ pykrx get_market_ohlcv_by_date 는 **거래대금 컬럼을 주지 않는다**
            #    (시가/고가/저가/종가/거래량/등락률뿐). 과거엔 row.get("거래대금", 0) 로 읽어
            #    value 가 **전 종목 항상 0** 이었다. score_volume_surge 는 `value or volume`
            #    폴백이 있어 조용히 넘어갔지만, 2026-08-21 유동성 필터를 붙이자 모든 후보가
            #    걸러져 스크리닝 결과가 0종이 됐다(발견 계기).
            #    backtest_dynamic.get_ohlcv 는 처음부터 volume*close 로 계산한다 — 동일하게 맞춘다.
            value = float(row.get("거래대금", 0)) or volume * close
            out.append({"date": d.strftime("%Y-%m-%d"), "open": float(row.get("시가", 0)),
                        "high": float(row.get("고가", 0)), "low": float(row.get("저가", 0)),
                        "close": close, "volume": volume, "value": value})
        # 장중이면 오늘 미완성 일봉 제거 — 거래량·종가가 미완성이라 게이트 판정 왜곡(과소평가) 방지.
        # 추세추종은 '완성된 일봉'으로 신호를 잡고 익일 진입하는 검증 방식과 동일.
        if out and _market_open_now() and out[-1]["date"] == datetime.now().strftime("%Y-%m-%d"):
            out = out[:-1]
        return out[-days:]
    except Exception as e:
        logger.debug("[OHLCV] %s %s", symbol, e)
        return []


def _clean_index_pairs(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """지수 (date, close) → NaN/0 제거 + 장중 미완성 오늘봉 제거 (날짜 유지)."""
    out = [(d, c) for d, c in pairs if c == c and c > 0]   # c==c → NaN 제거
    if out and _market_open_now() and out[-1][0] == datetime.now().strftime("%Y-%m-%d"):
        out = out[:-1]
    return out


def _expected_last_close_date() -> str:
    """가장 최근 '완성된' 영업일 (장중 오늘·주말 제외) — KOSPI staleness 판정 기준."""
    d = datetime.now()
    if _market_open_now() or d.hour < 16:   # 장중/장전 → 오늘봉 미완성 → 직전 영업일 기대
        d -= timedelta(days=1)
    while d.weekday() >= 5:                  # 주말 → 직전 금요일
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def get_kospi_closes(days: int = 320) -> list[float]:
    """KOSPI 종가 시계열 (RS 게이트용).

    소스 우선순위: FDR ^KS11 (현행 유일 동작). pykrx 지수 API(ka `get_index_ohlcv_by_date`)는
    2026-07 KRX 지수 엔드포인트 인증화로 빈 DataFrame/티커명 KeyError 를 내 사실상 사망 → 2순위 폴백으로만 둔다.
    데이터 미확보/지연 시 경고 로그 — RS 게이트는 KOSPI 없으면 RS=0(fail-open) 처리되므로 조용히 무력화되는 것 방지.
    """
    pairs: list[tuple[str, float]] = []
    try:                                     # 1순위: FDR ^KS11
        import FinanceDataReader as fdr
        with _suppress():
            df = fdr.DataReader("^KS11", _days_ago(days + 60), _today())
        pairs = [(d.strftime("%Y-%m-%d"), float(c)) for d, c in zip(df.index, df["Close"])]
    except Exception as e:
        logger.debug("[KOSPI] FDR 실패: %s", e)
    if not [c for _, c in pairs if c == c and c > 0]:
        try:                                 # 2순위: pykrx 지수 (KRX 복구 대비, name_display=False 로 티커명 버그 우회)
            with _suppress():
                df = krx.get_index_ohlcv_by_date(_days_ago(days + 60), _today(), "1001", name_display=False)
            pairs = [(d.strftime("%Y-%m-%d"), float(row["종가"])) for d, row in df.iterrows()]
        except Exception as e:
            logger.debug("[KOSPI] pykrx 지수 폴백 실패: %s", e)

    clean = _clean_index_pairs(pairs)
    if not clean:
        logger.warning("[KOSPI] 지수 데이터 확보 실패 (FDR·pykrx 모두) — RS 게이트가 RS=0 으로 무력화됨")
        return []
    exp = _expected_last_close_date()
    if clean[-1][0] < exp:                    # 최신 봉이 기대 영업일보다 뒤처짐 → RS 신뢰도 저하
        logger.warning("[KOSPI] 데이터 %s 까지 (기대 %s) — 소스 갱신 지연으로 RS 게이트 신뢰도 저하",
                       clean[-1][0], exp)
    return [c for _, c in clean][-days:]


def _name(code: str) -> str:
    # pykrx KRX 로그인 간헐 실패 시 예외 대신 빈 DataFrame 반환 → 문자열 아니면 code 폴백
    # (DataFrame 이 name 에 섞이면 후보 저장 JSON 직렬화 크래시. 2026-07-01 screen 오류 원인).
    try:
        n = krx.get_market_ticker_name(code)
        if isinstance(n, str) and n.strip():
            return n
    except Exception:
        pass
    return code


_BROAD_CACHE = _ROOT / "docs_cache" / "broad_universe.json"
_BROAD_LIMIT = 150
_BROAD_VERSION = 2          # 올리면 기존 캐시를 무효화하고 재생성한다(필터 규칙 변경 시)
_STALE_DAYS = 45            # 스냅샷이 이보다 오래되면 경고 — 시총 상위 구성은 분기마다 바뀐다


def _is_preferred(code: str, name: str = "") -> bool:
    """우선주 판정. KRX 코드 끝자리: 0=보통주, 5/7/9(및 K/L/M)=우선주. 종목명 접미도 병행 확인."""
    c = str(code).zfill(6)
    if c[-1] not in "0":
        return True
    n = (name or "").strip()
    return n.endswith("우") or n.endswith("우B")


def same_issuer(a: str, b: str) -> bool:
    """같은 발행사인가 — 보통주/우선주 동시 보유 차단용.

    KRX 6자리 코드는 발행사별로 앞 5자리를 공유하고 끝자리만 다르다:
      005930 삼성전자 / 005935 삼성전자우
      005380 현대차   / 005385 현대차우 / 005387 현대차2우B
    둘 다 사면 한 회사에 2배 노출이라 슬롯 5개 중 2개를 같은 리스크에 쓴다.
    2026-08-21 기준 상위 150 에 이런 쌍이 3건 있다.
    """
    a, b = str(a).zfill(6), str(b).zfill(6)
    return a != b and a[:5] == b[:5]


def _broad_codes() -> list[str]:
    """KOSPI 시총상위 ~150 보통주 (docs_cache/universe_kiwoom_*.json) — 무네트워크·안정 소스.

    2026-08-17: 과거엔 sys.path 에 scripts/ 를 끼워넣고 `backtest_dynamic.get_broad_universe`
    를 import 했다. 순수 도메인이 스크립트를 의존하는 역방향 참조이자, 데몬의 유니버스 경로가
    backtest_dynamic 을 통해 pykrx·FDR·closing_bet scorer 를 전이 import 하는 원인이었다
    (이 파일 docstring 의 "외부 의존 없음" 이 사실이 아니게 된 지점). 구현을 여기로 가져오고
    backtest_dynamic 이 이걸 쓰도록 방향을 뒤집었다.

    ⚠️ 이 목록은 **스냅샷 시점의 시총 순위**다(point-in-time 아님). 라이브에선 그 시점 이후
    상위로 올라온 종목이 후보가 못 되고, 백테스트에 소급 적용하면 생존편향·look-ahead 가 된다.
    스냅샷이 오래되면 기동 시 경고한다 — `scripts/_universe_kiwoom.py` 로 갱신할 것.
    """
    cached = _read_broad_cache()
    if cached:
        return cached
    snaps = sorted((_ROOT / "docs_cache").glob("universe_kiwoom_*.json"), reverse=True)
    if not snaps:
        raise RuntimeError("docs_cache/universe_kiwoom_*.json 없음 — scripts/_universe_kiwoom.py 로 생성")
    raw = json.loads(snaps[0].read_text(encoding="utf-8"))
    kospi = [s for s in raw if s.get("market") in ("거래소", "KOSPI") and s.get("market_cap", 0) > 0]
    kospi.sort(key=lambda s: -s["market_cap"])
    # 우선주도 유니버스에 남긴다 — 백테스트상 기여가 (-)가 아니었고(제외 시 기대값 3.38→3.31%),
    # 실제 위험은 '보통주+우선주 동시 보유'뿐이다. 그건 진입 시 발행사 중복 가드로 막는다
    # (trend_follow._buy_one). 후보를 영구히 버리는 것보다 발생 시점에 막는 쪽이 정확하다.
    kept = [str(s["code"]).zfill(6) for s in kospi[:_BROAD_LIMIT]]
    snap_date = snaps[0].stem.replace("universe_kiwoom_", "")
    try:
        _BROAD_CACHE.write_text(json.dumps(
            {"version": _BROAD_VERSION, "snapshot": snap_date, "codes": kept},
            ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("[UNIVERSE] broad 캐시 기록 실패(무시): %s", e)
    _warn_if_stale(snap_date)
    return kept


def _read_broad_cache() -> list[str] | None:
    """캐시 판독 — 버전이 낮거나 형식이 구형(list)이면 None 을 돌려 재생성시킨다."""
    if not _BROAD_CACHE.exists():
        return None
    try:
        d = json.loads(_BROAD_CACHE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[UNIVERSE] broad 캐시 판독 실패(재생성): %s", e)
        return None
    if not isinstance(d, dict) or d.get("version") != _BROAD_VERSION:
        logger.info("[UNIVERSE] broad 캐시 구버전 — 재생성(우선주 제외 규칙 반영)")
        return None
    # 더 새 스냅샷이 있으면 캐시를 버린다. 과거엔 version 만 봐서, `_universe_kiwoom.py` 로
    # 스냅샷을 새로 받아도 이 캐시가 옛 목록을 영구히 물고 있었다 — stale 경고가 안내하는
    # 갱신 절차 자체가 무효였다(2026-08-28).
    newest = _newest_snapshot_date()
    if newest and str(d.get("snapshot", "")) < newest:
        logger.info("[UNIVERSE] 새 스냅샷 %s 발견 — broad 캐시 재생성(기존 %s)",
                    newest, d.get("snapshot"))
        return None
    codes = d.get("codes") or []
    if codes:
        _warn_if_stale(str(d.get("snapshot", "")))
    return codes or None


def _newest_snapshot_date() -> str:
    """docs_cache 의 가장 최근 universe 스냅샷 날짜(YYYYMMDD). 없으면 빈 문자열."""
    snaps = sorted((_ROOT / "docs_cache").glob("universe_kiwoom_*.json"), reverse=True)
    return snaps[0].stem.replace("universe_kiwoom_", "") if snaps else ""


def _warn_if_stale(snap_date: str) -> None:
    """스냅샷이 오래됐으면 경고 — 조용히 낡은 유니버스로 도는 것을 막는다."""
    try:
        age = (datetime.now() - datetime.strptime(snap_date, "%Y%m%d")).days
    except Exception:
        return
    if age > _STALE_DAYS:
        logger.warning("[UNIVERSE] ⚠️ 유니버스 스냅샷이 %d일 경과(%s) — 그 이후 시총 상위로 올라온 "
                       "종목은 후보가 되지 못합니다. `python scripts/_universe_kiwoom.py` 로 갱신 권장",
                       age, snap_date)


def get_universe(mode: str, top_n: int, watchlist: list[str],
                 min_value: float) -> list[tuple[str, str]]:
    """모드별 유니버스 [(code, name)]. 모든 설정값은 호출자가 주입 (config 의존 0)."""
    if mode == "watchlist":
        return [(c, _name(c)) for c in watchlist]
    # largecap: 시총상위 캐시 우선(pykrx 전종목 조회가 장중 실패해도 안정) — 백테스트와 동일.
    if mode == "largecap":
        try:
            codes = _broad_codes()[:top_n]
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
            df = df[df["거래대금"] >= min_value]
            if mode == "gainers" and "등락률" in df.columns:
                df = df.sort_values("등락률", ascending=False)
            else:  # largecap 캐시 실패 시 거래대금 상위 근사
                df = df.sort_values("거래대금", ascending=False)
            codes = list(df.head(top_n).index)
            return [(c, _name(c)) for c in codes]
        except Exception:
            continue
    # 최종 폴백: 시총상위 캐시 → watchlist (조용한 2종목 폴백 방지)
    try:
        codes = _broad_codes()[:top_n]
        if codes:
            return [(c, _name(c)) for c in codes]
    except Exception:
        pass
    return [(c, _name(c)) for c in watchlist]
