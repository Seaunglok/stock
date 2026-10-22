"""closing_bet composite() 가중치 회귀 재산정.

04-30 백테스트에서 `점수 ↑ ≠ 수익률 ↑` 가 확인됐다.
현재 가중치(volume 0.25 / resistance 0.20 / candle 0.15 / consolidation 0.20 / inst 0.20)는
경험치이고, 실제 수익률과 정렬되어 있지 않다.

이 스크립트는:
  1. 유니버스 모든 종목·모든 거래일에 대해 4개 sub-component 점수와 익일 시초가 수익률을 수집
     (top_n / threshold 필터 없음 → 회귀용 풀 샘플)
  2. OLS 회귀: ret ~ a*volume + b*resistance + c*candle + d*consolidation + intercept
  3. 음수 계수는 0으로 클리핑 후 합=1로 정규화 → 신규 가중치 제안
  4. 신규 가중치로 백테스트 재실행하여 기존 vs 신규 성능 비교

institutional 점수는 백테스트에서 None(=0)으로 고정돼 회귀 대상 제외.

사용:
  python scripts/tune_weights.py                       # 고정 26종목, 직전 400일
  python scripts/tune_weights.py --universe kiwoom-top --universe-top 100
  python scripts/tune_weights.py --start 2025-01-01 --end 2026-04-30
  python scripts/tune_weights.py --out docs/tune_weights.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.backtest_closing_bet import (  # noqa: E402
    DEFAULT_UNIVERSE,
    fetch_history,
    simulate,
)
from src.mcp_servers.closing_bet_mcp.scorer import (  # noqa: E402
    compute_technical_scores,
    compute_technical_scores_v2,
)

SCORERS = {
    "v1": compute_technical_scores,
    "v2": compute_technical_scores_v2,
}
SCORER = compute_technical_scores  # CLI에서 교체

COMPONENT_KEYS_BASE = ("volume_surge", "resistance_proximity", "candle_shape", "consolidation")
COMPONENT_KEYS = COMPONENT_KEYS_BASE  # main()에서 catalyst 켜지면 확장
CURRENT_WEIGHTS_BASE = {
    "volume_surge": 0.25,
    "resistance_proximity": 0.20,
    "candle_shape": 0.15,
    "consolidation": 0.20,
    # institutional 0.20 은 백테스트에서 0이라 제외
}
CURRENT_WEIGHTS = dict(CURRENT_WEIGHTS_BASE)


def daily_universe(
    histories: dict[str, list[dict]],
    date_t: str,
    size: int,
    value_window: int,
) -> list[str]:
    """date_t 기준 직전 value_window일 평균 거래대금 상위 size 종목코드 반환.

    종베의 현실 — 매일 다른 종목이 후보로 올라온다. 마스터 풀 안에서
    '오늘 가장 핫한 N개'를 골라 그날의 universe로 쓴다.
    """
    ranks: list[tuple[str, float]] = []
    for code, h in histories.items():
        window = [d for d in h if d["date"] <= date_t][-value_window:]
        if len(window) < value_window:
            continue
        avg_value = sum(d.get("value", 0.0) for d in window) / len(window)
        if avg_value > 0:
            ranks.append((code, avg_value))
    ranks.sort(key=lambda x: -x[1])
    return [c for c, _ in ranks[:size]]


def _score_with_optional_catalyst(
    window: list[dict],
    disclosures_by_code: dict[str, list[dict]] | None,
    code: str,
    date_t: str,
):
    if disclosures_by_code is not None:
        return SCORER(window, disclosures=disclosures_by_code.get(code, []),
                      target_date=date_t)
    return SCORER(window)


def collect_samples(
    histories: dict[str, list[dict]],
    daily_size: int,
    value_window: int,
    disclosures_by_code: dict[str, list[dict]] | None = None,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """매일의 universe(거래대금 상위 daily_size)에 대해서만 sub-component + 익일 수익률 수집.

    Returns:
        X: (N, 4) — 4개 sub-component 점수
        y: (N,)   — 익일 시초가 수익률 (%)
        rows:     — 디버깅용 dict 리스트
    """
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    X_list: list[list[float]] = []
    y_list: list[float] = []
    rows: list[dict] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]
        codes_today = daily_universe(histories, date_t, daily_size, value_window)
        for code in codes_today:
            h = histories[code]
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            future = next((d for d in h if d["date"] == date_next), None)
            if future is None:
                continue
            entry = window[-1]["close"]
            if entry <= 0:
                continue
            ret_pct = (future["open"] - entry) / entry * 100.0

            ts = _score_with_optional_catalyst(window, disclosures_by_code, code, date_t)
            x = [getattr(ts, k) for k in COMPONENT_KEYS]
            X_list.append(x)
            y_list.append(ret_pct)
            rows.append({
                "date": date_t, "code": code, "ret": ret_pct,
                **{k: v for k, v in zip(COMPONENT_KEYS, x)},
            })

    return np.array(X_list), np.array(y_list), rows


def fit_ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    """절편 포함 OLS. returns (coefs[4], intercept, r_squared)."""
    n = X.shape[0]
    X1 = np.hstack([X, np.ones((n, 1))])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    coefs = beta[:-1]
    intercept = float(beta[-1])
    y_pred = X1 @ beta
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return coefs, intercept, r2


def normalize_weights(coefs: np.ndarray) -> dict[str, float]:
    """음수 → 0 클리핑 후 합=1 정규화. 모두 0이면 균등 분배."""
    clipped = np.maximum(coefs, 0.0)
    total = clipped.sum()
    if total <= 0:
        clipped = np.ones_like(coefs)
        total = clipped.sum()
    weights = clipped / total
    return {k: float(round(weights[i], 3)) for i, k in enumerate(COMPONENT_KEYS)}


def composite_with_weights(components: dict[str, float], weights: dict[str, float]) -> float:
    return sum(components[k] * weights[k] for k in COMPONENT_KEYS)


def evaluate_weights(
    histories: dict[str, list[dict]],
    weights: dict[str, float],
    threshold: float,
    top_n: int,
    daily_size: int,
    value_window: int,
    disclosures_by_code: dict[str, list[dict]] | None = None,
) -> dict:
    """신규 가중치로 rolling-universe simulate."""
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    picks: list[dict] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]
        codes_today = daily_universe(histories, date_t, daily_size, value_window)
        scored = []
        for code in codes_today:
            h = histories[code]
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            ts = _score_with_optional_catalyst(window, disclosures_by_code, code, date_t)
            comps = {k: getattr(ts, k) for k in COMPONENT_KEYS}
            score = composite_with_weights(comps, weights)
            scored.append((code, score, window[-1]["close"]))

        scored.sort(key=lambda x: -x[1])
        day_picks = [s for s in scored[:top_n] if s[1] >= threshold]
        for code, score, entry in day_picks:
            future = next((d for d in histories[code] if d["date"] == date_next), None)
            if future is None or entry <= 0:
                continue
            ret_pct = (future["open"] - entry) / entry * 100.0
            picks.append({"date": date_t, "code": code, "score": score, "ret": ret_pct})

    if not picks:
        return {"n": 0, "winrate": 0.0, "avg_ret": 0.0, "picks": []}
    n = len(picks)
    wins = sum(1 for p in picks if p["ret"] > 0)
    avg = sum(p["ret"] for p in picks) / n
    return {"n": n, "winrate": wins / n * 100.0, "avg_ret": avg, "picks": picks}


def render_report(
    coefs: np.ndarray,
    intercept: float,
    r2: float,
    n_samples: int,
    new_weights: dict[str, float],
    eval_old: dict,
    eval_new: dict,
    threshold: float,
    top_n: int,
    start: str,
    end: str,
    universe_size: int,
    daily_size: int,
    value_window: int,
) -> str:
    lines: list[str] = []
    lines.append("# closing_bet 가중치 재산정 결과 (rolling universe)")
    lines.append("")
    lines.append(f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 기간: {start} ~ {end}")
    lines.append(f"- 마스터 풀 {universe_size}종목 → 매일 거래대금 상위 {daily_size} (window {value_window}일)")
    lines.append(f"- 회귀 샘플 {n_samples}건")
    lines.append(f"- 백테스트 비교 조건: 임계값 {threshold} / top_n {top_n}")
    lines.append("")
    lines.append("## 1. OLS 회귀 결과 (ret% ~ 4 sub-components)")
    lines.append("")
    lines.append(f"- R² = {r2:.4f}")
    lines.append(f"- 절편 = {intercept:+.4f}")
    lines.append("")
    lines.append("| sub-component | 회귀계수 | 부호 |")
    lines.append("|---------------|----------|------|")
    for k, c in zip(COMPONENT_KEYS, coefs):
        sign = "+" if c > 0 else ("-" if c < 0 else "0")
        lines.append(f"| {k} | {c:+.5f} | {sign} |")
    lines.append("")
    lines.append("> 음수 계수는 \"점수가 높을수록 수익이 낮다\" — 현재 합산식의 노이즈/역신호.")
    lines.append("")
    lines.append("## 2. 신규 가중치 제안 (음수 클리핑 → 합=1 정규화)")
    lines.append("")
    lines.append("| sub-component | 기존 | 신규 | 변화 |")
    lines.append("|---------------|------|------|------|")
    for k in COMPONENT_KEYS:
        old = CURRENT_WEIGHTS[k]
        new = new_weights[k]
        diff = new - old
        lines.append(f"| {k} | {old:.3f} | {new:.3f} | {diff:+.3f} |")
    lines.append("")
    lines.append("## 3. 백테스트 비교")
    lines.append("")
    lines.append("| 가중치 | 픽 수 | 승률 | 평균수익 |")
    lines.append("|--------|-------|------|----------|")
    lines.append(
        f"| 기존 | {eval_old['n']} | {eval_old['winrate']:.1f}% | {eval_old['avg_ret']:+.2f}% |"
    )
    lines.append(
        f"| 신규 | {eval_new['n']} | {eval_new['winrate']:.1f}% | {eval_new['avg_ret']:+.2f}% |"
    )
    lines.append("")
    lines.append("## 4. 적용 방법")
    lines.append("")
    lines.append("`src/mcp_servers/closing_bet_mcp/scorer.py` `TechnicalScores.composite()`:")
    lines.append("```python")
    lines.append("def composite(self) -> float:")
    lines.append("    return (")
    for i, k in enumerate(COMPONENT_KEYS):
        prefix = "  " if i == 0 else "+ "
        lines.append(f"        {prefix}self.{k} * {new_weights[k]:.3f}")
    lines.append("        + self.institutional * 0.0  # 백테스트 데이터 없음, 운영시 별도 가중")
    lines.append("    )")
    lines.append("```")
    lines.append("")
    lines.append("> institutional은 백테스트에 없어 회귀에서 빠졌다. 운영(실시간) 단계에서는")
    lines.append("> 외인/기관 데이터가 들어오므로 별도 가중(예: 0.15)을 추가하거나, 4개 컴포넌트")
    lines.append("> 합산 후 institutional 가산점 형태로 분리하는 것을 권한다.")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--codes", nargs="+", default=None)
    p.add_argument("--universe", choices=["fixed", "kiwoom-large", "kiwoom-top"], default="fixed")
    p.add_argument("--universe-top", type=int, default=100)
    p.add_argument("--refresh-universe", action="store_true")
    p.add_argument("--threshold", type=float, default=50.0,
                   help="비교 백테스트 임계값")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--daily-universe-size", type=int, default=200,
                   help="매일 거래대금 상위 N개를 그날 후보군으로 (rolling universe)")
    p.add_argument("--value-window", type=int, default=5,
                   help="거래대금 평균 산출 일수")
    p.add_argument("--fetch-workers", type=int, default=8,
                   help="OHLCV 병렬 fetch worker 수")
    p.add_argument("--scorer", choices=list(SCORERS.keys()), default="v1",
                   help="점수 함수 버전: v1=기존, v2=resistance/candle 재설계")
    p.add_argument("--catalyst", action="store_true",
                   help="DART 공시 기반 catalyst 점수를 회귀 5번째 변수로 추가")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    global SCORER, COMPONENT_KEYS, CURRENT_WEIGHTS
    SCORER = SCORERS[args.scorer]
    if args.catalyst:
        COMPONENT_KEYS = COMPONENT_KEYS_BASE + ("catalyst",)
        CURRENT_WEIGHTS = dict(CURRENT_WEIGHTS_BASE)
        CURRENT_WEIGHTS["catalyst"] = 0.0  # 기존 composite()에는 catalyst 가중 없음
    print(f"[scorer] {args.scorer}  catalyst={'on' if args.catalyst else 'off'}")

    # universe — 마스터 풀 (이 안에서 매일 rolling 선정)
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
    print(f"[load] 매일 universe = 이 풀에서 {args.value_window}일 평균 거래대금 상위 {args.daily_universe_size}")

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

    disclosures_by_code: dict[str, list[dict]] | None = None
    if args.catalyst:
        from scripts._dart_cache import load_disclosures
        print(f"[catalyst] DART 공시 fetch ({len(histories)}종목)...")
        disclosures_by_code = {}
        n_disc = 0
        fail_disc = 0
        for i, code in enumerate(histories.keys(), 1):
            try:
                disclosures_by_code[code] = load_disclosures(code, args.start, args.end)
                n_disc += len(disclosures_by_code[code])
            except Exception as e:
                disclosures_by_code[code] = []
                fail_disc += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(histories)}] 누적 공시 {n_disc}건 / 실패 {fail_disc}")
        print(f"[catalyst] 완료 — 공시 총 {n_disc}건, fetch 실패 {fail_disc}종목")

    print("[1/3] 회귀 샘플 수집 (rolling universe)...")
    X, y, rows = collect_samples(histories, args.daily_universe_size, args.value_window,
                                 disclosures_by_code=disclosures_by_code)
    print(f"  샘플 {len(y)}건, X shape={X.shape}")

    print("[2/3] OLS 회귀...")
    coefs, intercept, r2 = fit_ols(X, y)
    new_weights = normalize_weights(coefs)
    print(f"  R²={r2:.4f}, intercept={intercept:+.4f}")
    for k, c in zip(COMPONENT_KEYS, coefs):
        print(f"  {k}: coef={c:+.5f}  → weight={new_weights[k]:.3f}")

    print("[3/3] 백테스트 비교 (기존 가중치 vs 신규 가중치, rolling)...")
    eval_old = evaluate_weights(histories, CURRENT_WEIGHTS, args.threshold,
                                args.top_n, args.daily_universe_size, args.value_window,
                                disclosures_by_code=disclosures_by_code)
    eval_new = evaluate_weights(histories, new_weights, args.threshold,
                                args.top_n, args.daily_universe_size, args.value_window,
                                disclosures_by_code=disclosures_by_code)
    print(f"  기존: {eval_old['n']}건 승률 {eval_old['winrate']:.1f}% 평균 {eval_old['avg_ret']:+.2f}%")
    print(f"  신규: {eval_new['n']}건 승률 {eval_new['winrate']:.1f}% 평균 {eval_new['avg_ret']:+.2f}%")

    md = render_report(
        coefs, intercept, r2, len(y), new_weights,
        eval_old, eval_new, args.threshold, args.top_n,
        args.start, args.end, len(histories),
        args.daily_universe_size, args.value_window,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"\n[저장] {args.out}")
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
