"""closing_bet_mcp 점수 임계값 튜닝용 백테스트.

각 거래일마다:
  1. 유니버스 종목별로 직전 90봉으로 closing_bet 기술점수 계산
  2. 점수 상위 N개 픽
  3. 다음 거래일 시초가에 매도 (종베 매수→갭상승 익절 룰)
  4. 점수 버킷별 승률 / 평균수익 집계

외인/기관 데이터는 과거 일자별로 받기 어려워 0(중립)으로 둔다.
재료(catalyst) 점수도 제외 — 기술점수만으로 임계값 감을 잡는 용도.

사용:
  python scripts/backtest_closing_bet.py
  python scripts/backtest_closing_bet.py --start 2024-01-01 --end 2024-12-31
  python scripts/backtest_closing_bet.py --threshold 70 --top-n 3
  python scripts/backtest_closing_bet.py --codes 005930 000660 035420
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import FinanceDataReader as fdr

from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores

DEFAULT_UNIVERSE = [
    "005930", "000660", "035420", "035720", "005380", "051910",
    "006400", "207940", "068270", "005490", "028260", "012330",
    "066570", "096770", "017670", "030200", "055550", "105560",
    "086790", "316140", "003670", "010130", "009150", "032830",
    "015760", "034730",
]


def fetch_history(code: str, start: str, end: str) -> list[dict]:
    df = fdr.DataReader(code, start, end)
    out = []
    for date, row in df.iterrows():
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
    return out


def simulate(
    histories: dict[str, list[dict]],
    threshold: float,
    top_n: int,
) -> list[tuple[str, str, float, float]]:
    """returns: list of (date, code, score, next_open_return_pct)"""
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    results: list[tuple[str, str, float, float]] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]

        scored: list[tuple[str, float, float]] = []
        for code, h in histories.items():
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            ts = compute_technical_scores(window)
            scored.append((code, ts.composite(), window[-1]["close"]))

        scored.sort(key=lambda x: x[1], reverse=True)
        picks = [s for s in scored[:top_n] if s[1] >= threshold]

        for code, score, entry in picks:
            future = next((d for d in histories[code] if d["date"] == date_next), None)
            if future is None or entry <= 0:
                continue
            ret_pct = (future["open"] - entry) / entry * 100.0
            results.append((date_t, code, score, ret_pct))

    return results


def report(results, threshold: float, top_n: int):
    if not results:
        print(f"임계값 {threshold} / top_n {top_n} → 픽 없음")
        return

    n = len(results)
    wins = sum(1 for _, _, _, r in results if r > 0)
    avg = sum(r for _, _, _, r in results) / n
    losses = [r for _, _, _, r in results if r <= 0]
    max_loss = min(losses) if losses else 0.0
    gains = [r for _, _, _, r in results if r > 0]
    max_gain = max(gains) if gains else 0.0

    print(f"\n=== 임계값 {threshold} / top_n {top_n} ===")
    print(f"전체 픽: {n}건  승률 {wins/n*100:5.1f}%  평균수익 {avg:+.2f}%  "
          f"최대익 {max_gain:+.2f}%  최대손 {max_loss:+.2f}%")

    buckets = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
    print(f"\n{'점수구간':<12}{'건수':<8}{'승률':<10}{'평균수익':<12}")
    print("-" * 42)
    for lo, hi in buckets:
        b = [r for _, _, s, r in results if lo <= s < hi]
        if not b:
            continue
        wr = sum(1 for r in b if r > 0) / len(b) * 100
        av = sum(b) / len(b)
        print(f"{lo:>3}-{hi:<8}{len(b):<8}{wr:<10.1f}{av:+.2f}%")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--threshold", type=float, default=50.0)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--codes", nargs="+", default=DEFAULT_UNIVERSE)
    args = p.parse_args()

    print(f"백테스트 기간: {args.start} ~ {args.end}")
    print(f"유니버스: {len(args.codes)}종목, 임계값 {args.threshold}, top_n {args.top_n}")
    print(f"{'='*60}")

    histories: dict[str, list[dict]] = {}
    for code in args.codes:
        try:
            h = fetch_history(code, args.start, args.end)
            if len(h) >= 90:
                histories[code] = h
                print(f"  {code}: {len(h)}봉 로드")
            else:
                print(f"  {code}: 데이터 부족 ({len(h)}봉) — 스킵")
        except Exception as e:
            print(f"  {code}: 로드 실패 — {e}")

    if not histories:
        print("로드된 종목이 없습니다.")
        sys.exit(1)

    print(f"\n시뮬레이션 시작 ({len(histories)}종목)...")
    results = simulate(histories, args.threshold, args.top_n)
    report(results, args.threshold, args.top_n)


if __name__ == "__main__":
    main()
