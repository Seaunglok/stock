"""Breadth-Regime Gate ex-post 검증.

2026-05-06 §6 #1 (룰 기반 게이트) 의 첫 실험. claude-trading-skills 의
`market-breadth-analyzer` 를 한국 시장 + 우리 백테스트 인프라에 맞춰 이식.

가설:
  v1+new (volume 0.90 / consolidation 0.10) 의 1,143픽 / 52.8% 승률 / +0.86%
  중 약세 레짐 일자의 픽은 평균 미만 → 차단하면 픽 수↓ 승률↑ EV↑.

레짐 판정 (PLAYBOOK A 와 동일):
  - KOSPI(KS11) 당일 등락률
  - 그날 daily_universe 내 양봉 비율(advance_ratio)
  → strong/neutral/weak

게이트 적용:
  - strong: 픽 그대로
  - neutral: composite ≥ 65 만 채택
  - weak: 그날 픽 전체 차단

사용:
  python scripts/backtest_with_breadth_gate.py \
      --universe kiwoom-top --universe-top 500 --daily-universe-size 200 \
      --start 2025-01-01 --end 2026-04-30 \
      --out docs/backtest_breadth_gate.md
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import FinanceDataReader as fdr

from scripts.backtest_closing_bet import DEFAULT_UNIVERSE, fetch_history
from scripts import tune_weights as tw
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores

WEIGHTS_NEW_V1 = {
    "volume_surge": 0.90,
    "resistance_proximity": 0.0,
    "candle_shape": 0.0,
    "consolidation": 0.10,
}


_KOSPI_CACHE_DIR = PROJECT_ROOT / "docs_cache" / "ohlcv"


def fetch_kospi_returns(start: str, end: str) -> dict[str, float]:
    """date → KOSPI 당일 등락률(%). 디스크 캐시 우선."""
    import json as _json
    cache_path = _KOSPI_CACHE_DIR / f"KS11_{start}_{end}.json"
    if cache_path.exists():
        return _json.loads(cache_path.read_text(encoding="utf-8"))

    import time
    last_err: Exception | None = None
    df = None
    for attempt in range(3):
        try:
            df = fdr.DataReader("KS11", start, end)
            break
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))

    out: dict[str, float] = {}
    if df is not None:
        for date, row in df.iterrows():
            o, c = float(row["Open"]), float(row["Close"])
            if o <= 0:
                continue
            out[date.strftime("%Y-%m-%d")] = (c - o) / o * 100.0
    else:
        # FDR 실패 → pykrx 폴백
        print(f"  FDR 실패 ({last_err}), pykrx 폴백 시도")
        try:
            from pykrx import stock
            s_compact = start.replace("-", "")
            e_compact = end.replace("-", "")
            pdf = stock.get_index_ohlcv(s_compact, e_compact, "1001")  # 1001 = KOSPI
            for date, row in pdf.iterrows():
                o, c = float(row["시가"]), float(row["종가"])
                if o <= 0:
                    continue
                out[date.strftime("%Y-%m-%d")] = (c - o) / o * 100.0
        except Exception as e2:
            print(f"  pykrx 도 실패 ({e2}). 005930+000660 프록시로 대체 [proxy]")
            try:
                proxy_codes = ["005930", "000660"]
                proxy_data: dict[str, list[float]] = {}
                for pc in proxy_codes:
                    h = fetch_history(pc, start, end)
                    for bar in h:
                        d, o, c = bar["date"], bar["open"], bar["close"]
                        if o <= 0:
                            continue
                        proxy_data.setdefault(d, []).append((c - o) / o * 100.0)
                out = {d: sum(vs) / len(vs) for d, vs in proxy_data.items()}
                print(f"  [proxy] 005930+000660 평균 {len(out)}일 로드")
            except Exception as e3:
                print(f"  프록시도 실패 ({e3}). KOSPI 신호 비활성")
                return {}

    _KOSPI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(_json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def compute_advance_ratio(
    histories: dict[str, list[dict]],
    date_t: str,
    universe_codes: list[str],
) -> tuple[float, int, float]:
    """date_t 기준 universe 내 양봉 비율 + 표본수 + 평균 일중수익(%)."""
    n_total = 0
    n_up = 0
    sum_ret = 0.0
    for code in universe_codes:
        h = histories.get(code, [])
        bar = next((d for d in h if d["date"] == date_t), None)
        if bar is None or bar["open"] <= 0:
            continue
        n_total += 1
        if bar["close"] > bar["open"]:
            n_up += 1
        sum_ret += (bar["close"] - bar["open"]) / bar["open"] * 100.0
    if n_total == 0:
        return 0.0, 0, 0.0
    return n_up / n_total, n_total, sum_ret / n_total


def classify_regime(
    kospi_pct: float,
    advance_ratio: float,
    weak_kospi_pct: float = -1.0,
    weak_adv_ratio: float = 0.35,
) -> str:
    if kospi_pct > 0.5 and advance_ratio >= 0.55:
        return "strong"
    if kospi_pct < weak_kospi_pct or advance_ratio < weak_adv_ratio:
        return "weak"
    return "neutral"


def gate_pick(score: float, regime: str, mode: str, neutral_cut: float, strong_cut: float) -> bool:
    """게이트 통과 여부.

    mode:
      standard  — 약세 차단(weak), 중립은 score≥neutral_cut, 강세 그대로
      inverted  — 강세/중립은 score≥cut으로 컷, 약세는 그대로 (2026-05-06 검증 후 채택)
      weak-only — 약세 픽만 채택, 그 외 전부 차단
    """
    if mode == "standard":
        if regime == "weak":
            return False
        if regime == "neutral":
            return score >= neutral_cut
        return True
    if mode == "inverted":
        if regime == "weak":
            return True
        if regime == "neutral":
            return score >= neutral_cut
        return score >= strong_cut
    if mode == "weak-only":
        return regime == "weak"
    if mode == "weak-filtered":
        # 약세 레짐 + composite 최소 컷 (caller가 weak_score_cut 으로 전달)
        if regime != "weak":
            return False
        return score >= neutral_cut  # neutral_cut을 weak_score_cut으로 재활용
    raise ValueError(f"unknown gate mode: {mode}")


def summarize(picks: list[dict]) -> dict:
    if not picks:
        return {"n": 0, "winrate": 0.0, "avg_ret": 0.0}
    n = len(picks)
    wins = sum(1 for p in picks if p["ret"] > 0)
    avg = sum(p["ret"] for p in picks) / n
    return {"n": n, "winrate": wins / n * 100.0, "avg_ret": avg}


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
    p.add_argument("--html", type=Path, default=None, help="HTML 리포트 저장 경로")
    p.add_argument(
        "--gate-mode",
        choices=["standard", "inverted", "weak-only", "weak-filtered", "all"],
        default="all",
        help="all = standard/inverted/weak-only/weak-filtered 4모드 비교",
    )
    p.add_argument("--neutral-cut", type=float, default=65.0)
    p.add_argument("--strong-cut", type=float, default=65.0)
    p.add_argument("--weak-kospi-pct", type=float, default=-1.0,
                   help="KOSPI 등락률이 이 값 미만이면 weak (단독으로 트리거)")
    p.add_argument("--weak-adv-ratio", type=float, default=0.35,
                   help="universe 양봉 비율이 이 값 미만이면 weak")
    p.add_argument("--csv", type=Path, default=None,
                   help="모드별 픽 CSV 저장 디렉터리 (mode 별 파일 생성)")
    args = p.parse_args()

    tw.COMPONENT_KEYS = tw.COMPONENT_KEYS_BASE
    tw.SCORER = compute_technical_scores

    # universe + 종목명 매핑
    name_by_code: dict[str, str] = {}
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
        name_by_code = {s["code"]: s.get("name", "") for s in picked}
    print(f"[load] 마스터 풀 {len(codes)}종목, {args.start} ~ {args.end}")

    # OHLCV 로드 (병렬)
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

    # KOSPI returns
    print("[load] KOSPI(KS11) 일별 등락 로드")
    kospi = fetch_kospi_returns(args.start, args.end)
    print(f"  KOSPI 거래일 {len(kospi)}일")

    # baseline 백테스트 (v1 + new)
    print("\n[run] baseline (v1 + new weights)")
    ev = tw.evaluate_weights(
        histories, WEIGHTS_NEW_V1,
        args.threshold, args.top_n,
        args.daily_universe_size, args.value_window,
        disclosures_by_code=None,
    )
    print(f"  baseline → 픽 {ev['n']}, 승률 {ev['winrate']:.1f}%, 평균 {ev['avg_ret']:+.2f}%")

    # 각 픽의 date_t 별 레짐 계산 (universe 캐싱)
    print("\n[gate] 레짐 분류 + 게이트 적용")
    regime_cache: dict[str, tuple[str, float, float, int]] = {}
    # date_t → (regime, kospi_pct, adv_ratio, n_universe)

    # date_t 별 daily_universe (tune_weights 와 동일 산식)
    dates_in_picks = sorted({p["date"] for p in ev["picks"]})
    use_proxy = not kospi  # KOSPI 못 가져왔으면 universe 평균 수익을 프록시로 사용
    if use_proxy:
        print("  KOSPI 신호 없음 → universe 평균 일중수익을 프록시로 사용")
    for date_t in dates_in_picks:
        uni = tw.daily_universe(histories, date_t, args.daily_universe_size, args.value_window)
        adv, n_uni, uni_ret = compute_advance_ratio(histories, date_t, uni)
        kpct = kospi.get(date_t, uni_ret if use_proxy else 0.0)
        regime = classify_regime(kpct, adv, args.weak_kospi_pct, args.weak_adv_ratio)
        regime_cache[date_t] = (regime, kpct, adv, n_uni)

    # 레짐 분포
    regime_days: dict[str, int] = defaultdict(int)
    for r, _, _, _ in regime_cache.values():
        regime_days[r] += 1

    # 픽에 레짐 부여
    enriched: list[dict] = []
    for pk in ev["picks"]:
        info = regime_cache.get(pk["date"])
        if info is None:
            continue
        enriched.append({**pk, "regime": info[0]})

    # 모드별 게이트 적용
    modes = ["standard", "inverted", "weak-only", "weak-filtered"] if args.gate_mode == "all" else [args.gate_mode]
    gated_by_mode: dict[str, list[dict]] = {}
    for m in modes:
        gated_by_mode[m] = [
            pk for pk in enriched
            if gate_pick(pk["score"], pk["regime"], m, args.neutral_cut, args.strong_cut)
        ]

    # 레짐별 픽 분해 (게이트 적용 전)
    by_regime_pre: dict[str, list[dict]] = defaultdict(list)
    for pk in enriched:
        by_regime_pre[pk["regime"]].append(pk)

    base_summary = summarize(ev["picks"])
    mode_summaries = {m: summarize(pl) for m, pl in gated_by_mode.items()}

    # 콘솔 / 마크다운 리포트
    lines: list[str] = []
    lines.append("# Breadth-Regime Gate 백테스트")
    lines.append("")
    lines.append(f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 기간: {args.start} ~ {args.end}")
    lines.append(f"- 마스터 풀 {len(histories)}종목 → 매일 거래대금 상위 {args.daily_universe_size}")
    lines.append(f"- 임계값(baseline) {args.threshold} / top_n {args.top_n}")
    lines.append("- 가중치: v1 + new (0.90 / 0 / 0 / 0.10)")
    lines.append(f"- 게이트 모드: {', '.join(modes)} (neutral_cut={args.neutral_cut}, strong_cut={args.strong_cut})")
    lines.append("")
    lines.append(f"- 분석 일자 수: {len(regime_cache)} (강세 {regime_days['strong']} / 중립 {regime_days['neutral']} / 약세 {regime_days['weak']})")
    lines.append("")
    lines.append("## 결과")
    lines.append("")
    lines.append("| 시나리오 | 픽 수 | 승률 | 평균수익 | Δ픽 | Δ승률 | Δ평균 |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(
        f"| baseline | {base_summary['n']} | {base_summary['winrate']:.1f}% | "
        f"{base_summary['avg_ret']:+.2f}% | - | - | - |"
    )
    for m in modes:
        s = mode_summaries[m]
        d_n = s["n"] - base_summary["n"]
        d_wr = s["winrate"] - base_summary["winrate"]
        d_avg = s["avg_ret"] - base_summary["avg_ret"]
        lines.append(
            f"| {m} | {s['n']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% | "
            f"{d_n:+d} | {d_wr:+.1f}pp | {d_avg:+.2f}% |"
        )
    lines.append("")
    lines.append("## 레짐별 baseline 분해 (게이트 적용 전)")
    lines.append("")
    lines.append("| 레짐 | 일수 | 픽 수 | 승률 | 평균수익 |")
    lines.append("|---|---|---|---|---|")
    regime_breakdown: list[tuple[str, int, dict]] = []
    for r in ("strong", "neutral", "weak"):
        sub = by_regime_pre.get(r, [])
        s = summarize(sub)
        regime_breakdown.append((r, regime_days[r], s))
        lines.append(
            f"| {r} | {regime_days[r]} | {s['n']} | "
            f"{s['winrate']:.1f}% | {s['avg_ret']:+.2f}% |"
        )

    # 픽 마크다운 표 (모드별 — 날짜 desc, 점수 desc 정렬)
    for m in modes:
        mp = sorted(gated_by_mode[m], key=lambda r: (r["date"], -r["score"]), reverse=True)
        if not mp:
            continue
        lines.append("")
        lines.append(f"## 픽 — {m} (총 {len(mp)}건, 최신 50건)")
        lines.append("")
        lines.append("| 일자 | 코드 | 종목명 | composite | 레짐 | 익일 수익률 |")
        lines.append("|---|---|---|---|---|---|")
        for r in mp[:50]:
            nm = name_by_code.get(r["code"], "")
            lines.append(
                f"| {r['date']} | {r['code']} | {nm} | {r['score']:.1f} | "
                f"{r['regime']} | {r['ret']:+.2f}% |"
            )

    md = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"\n[저장] {args.out}")
    else:
        print("\n" + md)

    # 픽 CSV (모드별)
    if args.csv:
        import csv
        args.csv.mkdir(parents=True, exist_ok=True)
        for m in modes:
            mp = sorted(gated_by_mode[m], key=lambda r: (r["date"], -r["score"]))
            path = args.csv / f"picks_{m}.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "code", "name", "score", "regime", "ret_pct"])
                for r in mp:
                    w.writerow([
                        r["date"], r["code"], name_by_code.get(r["code"], ""),
                        f"{r['score']:.2f}", r["regime"], f"{r['ret']:.4f}"
                    ])
            print(f"[저장] {path} ({len(mp)}건)")

    # HTML 리포트
    if args.html:
        html = render_html(
            args, base_summary, modes, mode_summaries, regime_days, regime_breakdown,
            gated_by_mode, name_by_code,
        )
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(html, encoding="utf-8")
        print(f"[저장] {args.html}")


def render_html(args, base, modes, mode_summaries, regime_days, regime_breakdown,
                gated_by_mode=None, name_by_code=None) -> str:
    gated_by_mode = gated_by_mode or {}
    name_by_code = name_by_code or {}
    def row(label, s, base):
        d_n = s["n"] - base["n"] if base["n"] else 0
        d_wr = s["winrate"] - base["winrate"]
        d_avg = s["avg_ret"] - base["avg_ret"]
        wr_cls = "pos" if d_wr > 0 else ("neg" if d_wr < 0 else "")
        avg_cls = "pos" if d_avg > 0 else ("neg" if d_avg < 0 else "")
        return (
            f"<tr><td>{label}</td><td>{s['n']}</td>"
            f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td>"
            f"<td>{d_n:+d}</td><td class='{wr_cls}'>{d_wr:+.1f}pp</td>"
            f"<td class='{avg_cls}'>{d_avg:+.2f}%</td></tr>"
        )

    rows = [f"<tr><td>baseline</td><td>{base['n']}</td><td>{base['winrate']:.1f}%</td>"
            f"<td>{base['avg_ret']:+.2f}%</td><td colspan='3'>-</td></tr>"]
    for m in modes:
        rows.append(row(m, mode_summaries[m], base))

    regime_rows = []
    for r, days, s in regime_breakdown:
        cls = "highlight" if r == "weak" else ""
        regime_rows.append(
            f"<tr class='{cls}'><td>{r}</td><td>{days}</td><td>{s['n']}</td>"
            f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td></tr>"
        )

    # 픽 테이블 (모드별, 날짜 desc)
    picks_sections = []
    for m in modes:
        mp = sorted(gated_by_mode.get(m, []), key=lambda r: (r["date"], -r["score"]), reverse=True)
        if not mp:
            continue
        rows_html = []
        for r in mp:
            nm = name_by_code.get(r["code"], "")
            ret_cls = "pos" if r["ret"] > 0 else ("neg" if r["ret"] < 0 else "")
            reg_cls = "highlight" if r["regime"] == "weak" else ""
            rows_html.append(
                f"<tr class='{reg_cls}'><td>{r['date']}</td>"
                f"<td>{r['code']}</td><td>{nm}</td>"
                f"<td>{r['score']:.1f}</td><td>{r['regime']}</td>"
                f"<td class='{ret_cls}'>{r['ret']:+.2f}%</td></tr>"
            )
        picks_sections.append(
            f"<h3>{m} ({len(mp)}건)</h3>"
            f"<details open><summary>펼치기/접기</summary>"
            f"<table><thead><tr><th>일자</th><th>코드</th><th>종목명</th>"
            f"<th>composite</th><th>레짐</th><th>익일 수익률</th></tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table></details>"
        )
    picks_html = (
        "<h2>픽 상세 (날짜 내림차순)</h2>" + "".join(picks_sections)
    ) if picks_sections else ""

    # 모드별 권장 결론 산출
    best_mode = max(modes, key=lambda m: mode_summaries[m]["avg_ret"]) if modes else None
    verdict = ""
    if best_mode:
        bs = mode_summaries[best_mode]
        verdict = (
            f"<p><strong>최우수 모드:</strong> <code>{best_mode}</code> — "
            f"픽 {bs['n']} / 승률 {bs['winrate']:.1f}% / 평균 {bs['avg_ret']:+.2f}% "
            f"(baseline 대비 승률 {bs['winrate']-base['winrate']:+.1f}pp, "
            f"평균 {bs['avg_ret']-base['avg_ret']:+.2f}%)</p>"
        )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>Breadth-Regime Gate 백테스트</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 960px; margin: 32px auto; padding: 0 16px; color: #222; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ margin-top: 32px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ccc; padding: 8px 12px; text-align: right; }}
  th, td:first-child {{ text-align: left; }}
  th {{ background: #f5f5f5; }}
  tr.highlight {{ background: #fff8d6; }}
  td.pos {{ color: #117a3d; font-weight: 600; }}
  td.neg {{ color: #b3261e; font-weight: 600; }}
  .meta {{ color: #555; font-size: 14px; }}
  code {{ background: #eee; padding: 1px 6px; border-radius: 3px; }}
  .verdict {{ background: #eef7ff; border-left: 4px solid #2872d4; padding: 12px 16px; margin: 16px 0; }}
  details {{ margin: 8px 0 24px; }}
  summary {{ cursor: pointer; color: #2872d4; padding: 4px 0; }}
  details table {{ font-size: 13px; }}
  h3 {{ margin-top: 24px; color: #444; }}
</style>
</head><body>
<h1>Breadth-Regime Gate 백테스트</h1>
<div class="meta">
  실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 기간: {args.start} ~ {args.end} ·
  마스터 풀 거래대금 상위 {args.daily_universe_size} · top_n {args.top_n} ·
  가중치 v1+new (0.90/0/0/0.10) · neutral_cut {args.neutral_cut} · strong_cut {args.strong_cut} ·
  weak: KOSPI&lt;{args.weak_kospi_pct:+.1f}% OR adv&lt;{args.weak_adv_ratio:.2f}
</div>
<p class="meta">분석 일자 {sum(regime_days.values())}일 — 강세 {regime_days['strong']} / 중립 {regime_days['neutral']} / 약세 {regime_days['weak']}</p>

<h2>모드별 결과</h2>
<table>
  <thead><tr><th>시나리오</th><th>픽 수</th><th>승률</th><th>평균수익</th><th>Δ픽</th><th>Δ승률</th><th>Δ평균</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
<div class="verdict">{verdict}</div>

<h2>레짐별 baseline 분해 (게이트 적용 전)</h2>
<table>
  <thead><tr><th>레짐</th><th>일수</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{''.join(regime_rows)}</tbody>
</table>

{picks_html}

<h2>게이트 모드 정의</h2>
<ul>
  <li><code>standard</code> — weak 차단, neutral은 score ≥ neutral_cut, strong 그대로</li>
  <li><code>inverted</code> — weak 그대로, neutral은 score ≥ neutral_cut, strong은 score ≥ strong_cut</li>
  <li><code>weak-only</code> — weak 픽만 채택</li>
</ul>
</body></html>
"""


if __name__ == "__main__":
    main()
