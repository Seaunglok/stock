"""하이브리드 점수 함수 + 고정 가중치 백테스트.

2026-05-05 §11.1 후속:
  - candle만 v2 부호 반전(+) 됐고, resistance v2는 음신호 중화에 그침.
  - 회귀로 가중치 다시 뽑지 말고 도메인 가설로 0.7/0.2/0.1 박은 뒤 비교.

세 조합을 같은 데이터(rolling universe)로 동시 평가:
  A. v1 + old weights (0.25/0.20/0.15/0.20)
  B. v1 + new weights (0.90/0/0/0.10)              ← 회귀로 뽑힌 1차 후보
  C. hybrid + fixed   (0.70/0/0.20/0.10)           ← 도메인 가설

사용:
  python scripts/backtest_hybrid.py --universe kiwoom-top --universe-top 500 \
      --daily-universe-size 200 --start 2025-01-01 --end 2026-04-30 \
      --out docs/backtest_hybrid.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.backtest_closing_bet import DEFAULT_UNIVERSE, fetch_history  # noqa: E402
from scripts import tune_weights as tw  # noqa: E402
from src.mcp_servers.closing_bet_mcp.scorer import (  # noqa: E402
    compute_technical_scores,
    compute_technical_scores_hybrid,
)

# COMPONENT_KEYS 순서: volume_surge, resistance_proximity, candle_shape, consolidation
WEIGHTS_OLD = {
    "volume_surge": 0.25,
    "resistance_proximity": 0.20,
    "candle_shape": 0.15,
    "consolidation": 0.20,
}
WEIGHTS_NEW_V1 = {
    "volume_surge": 0.90,
    "resistance_proximity": 0.0,
    "candle_shape": 0.0,
    "consolidation": 0.10,
}
WEIGHTS_HYBRID = {
    "volume_surge": 0.70,
    "resistance_proximity": 0.0,
    "candle_shape": 0.20,
    "consolidation": 0.10,
}

COMBOS = [
    ("A. v1 + old",     compute_technical_scores,        WEIGHTS_OLD),
    ("B. v1 + new",     compute_technical_scores,        WEIGHTS_NEW_V1),
    ("C. hybrid + 0.7/0.2/0.1", compute_technical_scores_hybrid, WEIGHTS_HYBRID),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--codes", nargs="+", default=None)
    p.add_argument("--universe", choices=["fixed", "kiwoom-large", "kiwoom-top"], default="kiwoom-top")
    p.add_argument("--universe-top", type=int, default=500)
    p.add_argument("--refresh-universe", action="store_true")
    p.add_argument("--threshold", type=float, default=50.0)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--daily-universe-size", type=int, default=200)
    p.add_argument("--value-window", type=int, default=5)
    p.add_argument("--fetch-workers", type=int, default=8)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    # tune_weights.py 의 COMPONENT_KEYS 는 catalyst 없이 4개 — 그대로 사용
    tw.COMPONENT_KEYS = tw.COMPONENT_KEYS_BASE

    # universe
    if args.codes:
        codes = args.codes
    elif args.universe == "fixed":
        codes = DEFAULT_UNIVERSE
    else:
        from scripts._universe_kiwoom import load_universe, select
        u = load_universe(refresh=args.refresh_universe)
        if args.universe == "kiwoom-large":
            picked = select(u, sizes=("대형주",))
        else:
            picked = select(u, sizes=("대형주", "중형주"), top_by_marketcap=args.universe_top)
        codes = [s["code"] for s in picked]
    print(f"[load] 마스터 풀 {len(codes)}종목, {args.start} ~ {args.end}")

    # fetch histories (병렬)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    histories: dict[str, list[dict]] = {}
    fail = 0
    done = 0

    def _one(code: str):
        try:
            return code, fetch_history(code, args.start, args.end), None
        except Exception as e:
            return code, None, e

    with ThreadPoolExecutor(max_workers=args.fetch_workers) as ex:
        futs = [ex.submit(_one, c) for c in codes]
        for fut in as_completed(futs):
            code, h, err = fut.result()
            done += 1
            if err is not None or h is None:
                fail += 1
            elif len(h) >= 90:
                histories[code] = h
            if done % 50 == 0:
                print(f"  [{done}/{len(codes)}] OK {len(histories)} / 실패 {fail}")
    print(f"[load] 완료 OK {len(histories)}종목 / 실패 {fail}건")

    if not histories:
        print("로드된 종목이 없습니다.")
        sys.exit(1)

    results: list[tuple[str, dict]] = []
    for label, scorer_fn, weights in COMBOS:
        print(f"\n[run] {label}  weights={weights}")
        tw.SCORER = scorer_fn
        ev = tw.evaluate_weights(
            histories, weights,
            args.threshold, args.top_n,
            args.daily_universe_size, args.value_window,
            disclosures_by_code=None,
        )
        print(f"  → 픽 {ev['n']}건, 승률 {ev['winrate']:.1f}%, 평균 {ev['avg_ret']:+.2f}%")
        results.append((label, ev))

    # 리포트
    lines: list[str] = []
    lines.append("# closing_bet 하이브리드 백테스트 비교")
    lines.append("")
    lines.append(f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 기간: {args.start} ~ {args.end}")
    lines.append(f"- 마스터 풀 {len(histories)}종목 → 매일 거래대금 상위 {args.daily_universe_size} (window {args.value_window}일)")
    lines.append(f"- 임계값 {args.threshold} / top_n {args.top_n}")
    lines.append("")
    lines.append("## 가중치")
    lines.append("")
    lines.append("| 조합 | scorer | volume | resistance | candle | consolidation |")
    lines.append("|------|--------|--------|------------|--------|---------------|")
    for label, scorer_fn, w in COMBOS:
        sname = "v1" if scorer_fn is compute_technical_scores else "hybrid"
        lines.append(
            f"| {label} | {sname} | {w['volume_surge']:.2f} | {w['resistance_proximity']:.2f} | "
            f"{w['candle_shape']:.2f} | {w['consolidation']:.2f} |"
        )
    lines.append("")
    lines.append("## 결과")
    lines.append("")
    lines.append("| 조합 | 픽 수 | 승률 | 평균수익 |")
    lines.append("|------|-------|------|----------|")
    for label, ev in results:
        lines.append(
            f"| {label} | {ev['n']} | {ev['winrate']:.1f}% | {ev['avg_ret']:+.2f}% |"
        )
    lines.append("")
    lines.append("## 점수구간별 (조합별)")
    lines.append("")
    for label, ev in results:
        lines.append(f"### {label}")
        lines.append("")
        buckets = [(50, 60), (60, 70), (70, 80), (80, 100)]
        lines.append("| 점수 | 픽 | 승률 | 평균 |")
        lines.append("|------|----|------|------|")
        for lo, hi in buckets:
            sub = [p for p in ev["picks"] if lo <= p["score"] < hi]
            if not sub:
                lines.append(f"| {lo}–{hi} | 0 | - | - |")
                continue
            n = len(sub)
            wins = sum(1 for p in sub if p["ret"] > 0)
            avg = sum(p["ret"] for p in sub) / n
            lines.append(f"| {lo}–{hi} | {n} | {wins/n*100:.1f}% | {avg:+.2f}% |")
        lines.append("")

    md = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"\n[저장] {args.out}")
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
