"""실제 운영과 동일한 동적 유니버스 백테스트.

매 거래일마다:
  1. pykrx로 그날 거래대금 상위 50종목 조회 (실제 production 로직과 동일)
  2. MA20 필터 + 갭 필터(4%/8% 하이브리드) 적용
  3. closing_bet 기술점수 계산
  4. 점수 >= threshold인 상위 top_n 픽
  5. 다음 거래일 시초가 매도 → 익일 수익률 집계

캐시: docs_cache/dynamic_universe/{date}.json — 일자별 top50 결과
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    from pykrx import stock as krx
import FinanceDataReader as fdr

from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores

CACHE_DIR = Path(__file__).parent.parent / "docs_cache" / "dynamic_universe"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OHLCV_CACHE = Path(__file__).parent.parent / "docs_cache" / "ohlcv"
OHLCV_CACHE.mkdir(parents=True, exist_ok=True)

MIN_VALUE_KRW = 1_000 * 10**8  # 1000억


def _suppress():
    return contextlib.redirect_stdout(io.StringIO())


def get_broad_universe() -> list[str]:
    """KOSPI 시가총액 상위 ~150종목 (kiwoom universe cache 기반).

    2026-08-17: 구현이 trend_mcp.market_data 로 이동했다. 과거엔 반대 방향이었다 —
    순수 도메인(market_data)이 sys.path 에 scripts/ 를 끼워넣고 이 함수를 import 해서,
    데몬의 유니버스 조회가 이 모듈(pykrx·FDR·closing_bet scorer)을 전이 import 했다.
    라이브와 백테스트가 **동일 유니버스**를 쓴다는 성질은 그대로 유지된다.
    """
    from src.mcp_servers.trend_mcp.market_data import _broad_codes
    return _broad_codes()


def get_top50_by_date(yyyymmdd: str, broad: dict[str, list[dict]]) -> list[tuple[str, float]]:
    """broad universe 안에서 그날 거래대금 상위 50.

    broad: code → ohlcv list (미리 로드된 데이터)
    """
    date_fmt = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    daily = []
    for code, ohlcv in broad.items():
        for c in ohlcv:
            if c["date"] == date_fmt:
                daily.append((code, c["value"]))
                break
    daily = [(c, v) for c, v in daily if v >= MIN_VALUE_KRW]
    daily.sort(key=lambda x: -x[1])
    return daily[:50]


def get_ohlcv(code: str, end_date: str, days: int = 100) -> list[dict]:
    """역사적 OHLCV (FDR 우선, 캐시 활용)."""
    cache_path = OHLCV_CACHE / f"{code}_{end_date}_{days}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=days * 2)  # 영업일 보정
    try:
        df = fdr.DataReader(code, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
        if df.empty:
            return []
        out = []
        for date, row in df.tail(days).iterrows():
            close = float(row["Close"])
            volume = float(row["Volume"])
            out.append({
                "date": date.strftime("%Y-%m-%d"),
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  close,
                "volume": volume,
                "value":  volume * close,
            })
        cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out
    except Exception:
        return []


def _above_ma20(ohlcv: list[dict]) -> bool:
    if len(ohlcv) < 20:
        return True
    ma20 = sum(c["close"] for c in ohlcv[-20:]) / 20
    return ohlcv[-1]["close"] >= ma20


def _gap_pct(ohlcv: list[dict]) -> float:
    if len(ohlcv) < 2:
        return 0.0
    prev = ohlcv[-2]["close"]
    if prev <= 0:
        return 0.0
    return (ohlcv[-1]["close"] - prev) / prev * 100


def simulate_dynamic(
    start: str,
    end: str,
    threshold: float = 50.0,
    top_n: int = 5,
    gap_mode: str = "current",  # current/strict/none
) -> list[dict]:
    """gap_mode:
      strict:  >= 4% 모두 제외
      current: >= 8% 하드컷 (catalyst 데이터 없어 4-8% 모두 통과)
      none:    갭 필터 없음
    """
    # 영업일 추출 (KOSPI 인덱스 기준)
    kospi = fdr.DataReader("^KS11", start, end)
    dates = [d.strftime("%Y%m%d") for d in kospi.index]
    print(f"백테스트 기간: {start} ~ {end} ({len(dates)} 영업일)")
    print(f"파라미터: threshold={threshold}, top_n={top_n}, gap_mode={gap_mode}")
    print("=" * 70)

    # broad universe 사전 로드 (KOSPI 시총 상위 150)
    universe = get_broad_universe()
    print(f"Broad universe: {len(universe)}종목 로드 중...")
    broad: dict[str, list[dict]] = {}
    # 백테스트 시작일 95일 전부터 끝일까지 한 번에 fetch
    fetch_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=140)).strftime("%Y-%m-%d")
    for idx, code in enumerate(universe, 1):
        h = get_ohlcv(code, dates[-1] if dates else end.replace("-", ""), days=200)
        if h:
            broad[code] = h
        if idx % 30 == 0:
            print(f"  [{idx}/{len(universe)}] 로드됨")
    print(f"  → {len(broad)}종목 로드 완료")
    print()

    results = []
    ma20_filtered_total = 0
    gap_filtered_total = 0
    scored_total = 0
    candidate_total = 0

    for i, date_str in enumerate(dates[:-1]):  # 마지막 날은 익일 시초가 없음
        if i < 1:
            continue  # 첫날은 익일 매도 불가
        date_next = dates[i + 1]

        top50 = get_top50_by_date(date_str, broad)
        if not top50:
            continue

        candidates_today = []
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        for code, value in top50:
            full_ohlcv = broad.get(code, [])
            # date_str까지의 데이터만 사용 (lookahead 방지)
            ohlcv = [c for c in full_ohlcv if c["date"] <= date_fmt][-95:]
            if len(ohlcv) < 21:
                continue
            if ohlcv[-1]["date"] != date_fmt:
                continue

            if not _above_ma20(ohlcv):
                ma20_filtered_total += 1
                continue

            gap = _gap_pct(ohlcv)
            if gap_mode == "strict" and gap >= 4.0:
                gap_filtered_total += 1
                continue
            if gap_mode == "current" and gap >= 8.0:
                gap_filtered_total += 1
                continue

            ts = compute_technical_scores(ohlcv)
            scored_total += 1
            score = ts.composite()
            if score >= threshold:
                candidates_today.append({
                    "code": code,
                    "score": score,
                    "gap": gap,
                    "entry": ohlcv[-1]["close"],
                    "ts": ts,
                })

        candidates_today.sort(key=lambda x: -x["score"])
        picks = candidates_today[:top_n]
        candidate_total += len(picks)

        for p in picks:
            next_date_fmt = f"{date_next[:4]}-{date_next[4:6]}-{date_next[6:]}"
            full_ohlcv = broad.get(p["code"], [])
            future = next((c for c in full_ohlcv if c["date"] == next_date_fmt), None)
            if future is None or p["entry"] <= 0:
                continue
            ret_pct = (future["open"] - p["entry"]) / p["entry"] * 100
            # +3% 익절 / -2% 손절 / 그 외는 시초가 청산 (단순 룰)
            results.append({
                "date": date_fmt,
                "code": p["code"],
                "score": p["score"],
                "gap": p["gap"],
                "ret_open": ret_pct,
                "entry": p["entry"],
                "next_open": future["open"],
                "next_high": future["high"],
                "next_low":  future["low"],
                "ts": {
                    "volume_surge": p["ts"].volume_surge,
                    "resistance": p["ts"].resistance_proximity,
                    "candle": p["ts"].candle_shape,
                    "consolidation": p["ts"].consolidation,
                },
            })

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(dates)}] {date_fmt}: 누적 픽 {len(results)}건")

    print()
    print(f"통계: 채점 {scored_total}회, MA20제외 {ma20_filtered_total}, 갭제외 {gap_filtered_total}")
    print(f"      픽 {candidate_total}회 → 매도성공 {len(results)}건")
    return results


def report(results: list[dict], label: str = "") -> None:
    if not results:
        print(f"{label} 결과 없음")
        return
    n = len(results)
    wins = sum(1 for r in results if r["ret_open"] > 0)
    avg = sum(r["ret_open"] for r in results) / n
    gains = [r["ret_open"] for r in results if r["ret_open"] > 0]
    losses = [r["ret_open"] for r in results if r["ret_open"] <= 0]
    print()
    print(f"=== {label} ===")
    print(f"전체: {n}건  승률 {wins/n*100:.1f}%  평균 {avg:+.2f}%  "
          f"최대익 {max(gains) if gains else 0:+.2f}%  최대손 {min(losses) if losses else 0:+.2f}%")
    print()
    print(f"{'점수':>10}  {'건':>4}  {'승률':>6}  {'평균':>7}")
    for lo, hi in [(40, 50), (50, 55), (55, 60), (60, 70), (70, 100)]:
        bucket = [r for r in results if lo <= r["score"] < hi]
        if not bucket:
            continue
        w = sum(1 for r in bucket if r["ret_open"] > 0)
        a = sum(r["ret_open"] for r in bucket) / len(bucket)
        print(f'  {lo:>3}-{hi:<5}  {len(bucket):>4}  {w/len(bucket)*100:>5.1f}%  {a:>+6.2f}%')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-02-01")
    parser.add_argument("--end",   default="2026-05-09")
    parser.add_argument("--threshold", type=float, default=50.0)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--gap-mode", choices=["current", "strict", "none"], default="current")
    args = parser.parse_args()

    results = simulate_dynamic(args.start, args.end, args.threshold, args.top_n, args.gap_mode)
    report(results, f"threshold={args.threshold} top_n={args.top_n} gap={args.gap_mode}")


if __name__ == "__main__":
    main()
