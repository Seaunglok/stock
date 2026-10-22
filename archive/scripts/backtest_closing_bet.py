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
  python scripts/backtest_closing_bet.py --out docs/backtest_latest.md
  python scripts/backtest_closing_bet.py --csv docs/backtest_picks.csv
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


_OHLCV_CACHE_DIR = Path(__file__).parent.parent / "docs_cache" / "ohlcv"


def fetch_history(code: str, start: str, end: str) -> list[dict]:
    """디스크 캐시 우선, 없으면 FDR fetch."""
    cache_path = _OHLCV_CACHE_DIR / f"{code}_{start}_{end}.json"
    if cache_path.exists():
        import json
        return json.loads(cache_path.read_text(encoding="utf-8"))

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

    _OHLCV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    import json
    cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def simulate(
    histories: dict[str, list[dict]],
    threshold: float,
    top_n: int,
) -> list[dict]:
    """returns: list of dicts {date, code, score, ret, components: {...}}"""
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    results: list[dict] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]

        scored = []
        for code, h in histories.items():
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            ts = compute_technical_scores(window)
            scored.append((code, ts, window[-1]["close"]))

        scored.sort(key=lambda x: x[1].composite(), reverse=True)
        picks = [s for s in scored[:top_n] if s[1].composite() >= threshold]

        for code, ts, entry in picks:
            future = next((d for d in histories[code] if d["date"] == date_next), None)
            if future is None or entry <= 0:
                continue
            ret_pct = (future["open"] - entry) / entry * 100.0
            results.append({
                "date": date_t,
                "code": code,
                "score": ts.composite(),
                "ret": ret_pct,
                "components": {
                    "volume_surge": ts.volume_surge,
                    "resistance_proximity": ts.resistance_proximity,
                    "candle_shape": ts.candle_shape,
                    "consolidation": ts.consolidation,
                },
                "breakdown": {
                    k: ts.breakdown.get(k, {})
                    for k in ("volume_surge", "resistance_proximity",
                              "candle_shape", "consolidation")
                },
            })

    return results


def _legacy_tuples(results: list[dict]) -> list[tuple[str, str, float, float]]:
    """기존 report/write_csv/write_html 시그니처와 호환되도록 튜플 리스트로 변환."""
    return [(r["date"], r["code"], r["score"], r["ret"]) for r in results]


def _summarize(results, threshold: float, top_n: int) -> str:
    """report 본문을 문자열로 만들어 stdout/파일 양쪽에 동일 출력."""
    lines: list[str] = []
    if not results:
        return f"임계값 {threshold} / top_n {top_n} → 픽 없음"

    n = len(results)
    wins = sum(1 for _, _, _, r in results if r > 0)
    avg = sum(r for _, _, _, r in results) / n
    losses = [r for _, _, _, r in results if r <= 0]
    max_loss = min(losses) if losses else 0.0
    gains = [r for _, _, _, r in results if r > 0]
    max_gain = max(gains) if gains else 0.0

    lines.append(f"=== 임계값 {threshold} / top_n {top_n} ===")
    lines.append(
        f"전체 픽: {n}건  승률 {wins/n*100:5.1f}%  평균수익 {avg:+.2f}%  "
        f"최대익 {max_gain:+.2f}%  최대손 {max_loss:+.2f}%"
    )
    lines.append("")
    lines.append(f"{'점수구간':<12}{'건수':<8}{'승률':<10}{'평균수익':<12}")
    lines.append("-" * 42)
    buckets = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
    for lo, hi in buckets:
        b = [r for _, _, s, r in results if lo <= s < hi]
        if not b:
            continue
        wr = sum(1 for r in b if r > 0) / len(b) * 100
        av = sum(b) / len(b)
        lines.append(f"{lo:>3}-{hi:<8}{len(b):<8}{wr:<10.1f}{av:+.2f}%")
    return "\n".join(lines)


def report(results, threshold: float, top_n: int):
    print()
    print(_summarize(results, threshold, top_n))


def write_markdown(path: Path, results, threshold: float, top_n: int,
                   start: str, end: str, universe_size: int) -> None:
    body = _summarize(results, threshold, top_n)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# closing_bet 백테스트 결과\n\n")
        f.write(f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- 기간: {start} ~ {end}\n")
        f.write(f"- 유니버스: {universe_size}종목, 임계값 {threshold}, top_n {top_n}\n\n")
        f.write("```\n")
        f.write(body)
        f.write("\n```\n")


def write_html(path: Path, rich_results: list[dict],
               histories: dict[str, list[dict]],
               threshold: float, top_n: int,
               start: str, end: str,
               code_to_name: dict[str, str] | None = None) -> None:
    """종목별로 묶인 캔들차트 + 요약 + 픽 상세를 단일 HTML로 저장.

    - 상단: 전체 요약 (승률, 평균수익, 점수구간 분포)
    - 본문: 픽이 있었던 종목마다 카드 1개
        · 캔들차트(픽 기간 + 좌우 여유) + 모든 BUY/SELL 마커
        · 픽별 점수/수익/sub-component 테이블
    """
    import html as html_mod

    import plotly.graph_objects as go
    import plotly.io as pio

    code_to_name = code_to_name or {}

    path.parent.mkdir(parents=True, exist_ok=True)

    if not rich_results:
        path.write_text("<html><body><p>픽 없음</p></body></html>",
                        encoding="utf-8")
        return

    # ── 종목별 그룹핑 ────────────────────────────────
    from collections import defaultdict
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rich_results:
        by_code[r["code"]].append(r)

    # 평균수익 내림차순 정렬
    code_order = sorted(
        by_code.keys(),
        key=lambda c: -sum(p["ret"] for p in by_code[c]) / len(by_code[c]),
    )

    # ── 전체 요약 통계 ────────────────────────────────
    n = len(rich_results)
    wins = sum(1 for r in rich_results if r["ret"] > 0)
    avg = sum(r["ret"] for r in rich_results) / n
    max_gain = max(r["ret"] for r in rich_results)
    max_loss = min(r["ret"] for r in rich_results)

    bucket_rows = []
    for lo, hi in [(50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]:
        b = [r for r in rich_results if lo <= r["score"] < hi]
        if not b:
            continue
        wr = sum(1 for r in b if r["ret"] > 0) / len(b) * 100
        av = sum(r["ret"] for r in b) / len(b)
        bucket_rows.append((f"{lo}-{hi}", len(b), wr, av))

    # ── 종목별 차트 figure 빌드 ──────────────────────
    chart_blocks: list[str] = []
    for code in code_order:
        picks = sorted(by_code[code], key=lambda x: x["date"])
        h = histories.get(code, [])
        if not h:
            continue

        first_pick_idx = next(
            (i for i, d in enumerate(h) if d["date"] == picks[0]["date"]), 0)
        last_pick_idx = next(
            (i for i, d in enumerate(h) if d["date"] == picks[-1]["date"]),
            len(h) - 1)
        win_start = max(0, first_pick_idx - 30)
        win_end = min(len(h), last_pick_idx + 6)
        window = h[win_start:win_end]
        if not window:
            continue

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=[d["date"] for d in window],
            open=[d["open"] for d in window],
            high=[d["high"] for d in window],
            low=[d["low"] for d in window],
            close=[d["close"] for d in window],
            increasing_line_color="#d24",
            decreasing_line_color="#26d",
            name="OHLC",
            showlegend=False,
        ))

        buy_x, buy_y, sell_x, sell_y, sell_text = [], [], [], [], []
        for p in picks:
            idx = next((j for j, d in enumerate(h) if d["date"] == p["date"]),
                       None)
            if idx is None:
                continue
            buy_x.append(p["date"])
            buy_y.append(h[idx]["close"])
            if idx + 1 < len(h):
                sell_x.append(h[idx + 1]["date"])
                sell_y.append(h[idx + 1]["open"])
                sell_text.append(f"{p['ret']:+.2f}%")

        fig.add_trace(go.Scatter(
            x=buy_x, y=buy_y, mode="markers+text",
            marker=dict(symbol="triangle-up", size=14, color="#0a0"),
            text=["BUY"] * len(buy_x), textposition="bottom center",
            name="BUY", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=sell_x, y=sell_y, mode="markers+text",
            marker=dict(symbol="triangle-down", size=14, color="#a00"),
            text=sell_text, textposition="top center",
            name="SELL", showlegend=False,
        ))

        fig.update_layout(
            height=420,
            margin=dict(l=40, r=20, t=20, b=30),
            xaxis=dict(type="category", rangeslider=dict(visible=False)),
            plot_bgcolor="#fafafa",
        )

        avg_ret = sum(p["ret"] for p in picks) / len(picks)
        winrate = sum(1 for p in picks if p["ret"] > 0) / len(picks) * 100
        name = code_to_name.get(code, "")
        title = (f"{code} {name} — 픽 {len(picks)}회 · 승률 {winrate:.0f}% "
                 f"· 평균수익 {avg_ret:+.2f}%")

        # 픽 상세 테이블
        rows_html = []
        for p in picks:
            bd = p.get("breakdown", {})
            ratio = bd.get("volume_surge", {}).get("ratio", "-")
            gap = bd.get("resistance_proximity", {}).get("gap_pct", "-")
            wick = bd.get("candle_shape", {}).get("upper_wick_ratio", "-")
            ret_color = "#0a7" if p["ret"] > 0 else "#c33"
            rows_html.append(
                f"<tr><td>{p['date']}</td>"
                f"<td>{p['score']:.0f}</td>"
                f"<td style='color:{ret_color};font-weight:600'>"
                f"{p['ret']:+.2f}%</td>"
                f"<td>{ratio}</td><td>{gap}</td><td>{wick}</td>"
                f"<td>{p['components']['volume_surge']:.0f}</td>"
                f"<td>{p['components']['resistance_proximity']:.0f}</td>"
                f"<td>{p['components']['candle_shape']:.0f}</td>"
                f"<td>{p['components']['consolidation']:.0f}</td></tr>"
            )

        chart_html = pio.to_html(
            fig, include_plotlyjs=False, full_html=False,
            div_id=f"chart_{code}",
        )

        chart_blocks.append(f"""
<section class="card">
  <h2>{html_mod.escape(title)}</h2>
  {chart_html}
  <details open>
    <summary>픽 상세 ({len(picks)}건)</summary>
    <table>
      <thead><tr>
        <th>날짜</th><th>점수</th><th>수익</th>
        <th>거래대금배율</th><th>저항이격%</th><th>위꼬리</th>
        <th>거래대금</th><th>저항이격</th><th>캔들</th><th>조정회복</th>
      </tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
  </details>
</section>""")

    # ── 요약 HTML ────────────────────────────────────
    bucket_html = "".join(
        f"<tr><td>{label}</td><td>{cnt}</td>"
        f"<td>{wr:.1f}%</td><td>{av:+.2f}%</td></tr>"
        for label, cnt, wr, av in bucket_rows
    )

    summary_html = f"""
<section class="summary">
  <h1>closing_bet 백테스트 결과</h1>
  <p class="meta">
    기간 <b>{start} ~ {end}</b> ·
    임계값 <b>{threshold}</b> ·
    top_n <b>{top_n}</b> ·
    유니버스 <b>{len(histories)}종목</b> ·
    실행 {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </p>
  <div class="stats">
    <div><span>전체 픽</span><b>{n}건</b></div>
    <div><span>승률</span><b>{wins/n*100:.1f}%</b></div>
    <div><span>평균수익</span><b>{avg:+.2f}%</b></div>
    <div><span>최대익</span><b style="color:#0a7">{max_gain:+.2f}%</b></div>
    <div><span>최대손</span><b style="color:#c33">{max_loss:+.2f}%</b></div>
  </div>
  <h3>점수구간 분포</h3>
  <table class="bucket">
    <thead><tr><th>구간</th><th>건수</th><th>승률</th><th>평균수익</th></tr></thead>
    <tbody>{bucket_html}</tbody>
  </table>
</section>"""

    css = """
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif;
         max-width: 1100px; margin: 24px auto; padding: 0 16px;
         color: #222; background: #fff; }
  h1 { margin: 0 0 8px; font-size: 22px; }
  h2 { margin: 0 0 12px; font-size: 16px; color: #333; }
  h3 { margin: 18px 0 8px; font-size: 14px; color: #555; }
  .meta { color: #666; font-size: 13px; margin: 0 0 16px; }
  .summary, .card { border: 1px solid #e3e3e3; border-radius: 8px;
                    padding: 16px 20px; margin-bottom: 20px;
                    background: #fff; }
  .stats { display: flex; flex-wrap: wrap; gap: 18px;
           padding: 12px 0; border-top: 1px solid #eee;
           border-bottom: 1px solid #eee; }
  .stats div { display: flex; flex-direction: column; }
  .stats span { font-size: 12px; color: #888; }
  .stats b { font-size: 18px; }
  table { border-collapse: collapse; width: 100%;
          font-size: 13px; margin-top: 8px; }
  th, td { border: 1px solid #eee; padding: 6px 8px;
           text-align: center; }
  th { background: #f7f7f7; font-weight: 600; }
  table.bucket { max-width: 480px; }
  details summary { cursor: pointer; font-size: 13px;
                    color: #555; padding: 6px 0; }
</style>"""

    html_doc = f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<title>closing_bet backtest {start} ~ {end}</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
{css}
</head><body>
{summary_html}
{''.join(chart_blocks)}
</body></html>"""

    path.write_text(html_doc, encoding="utf-8")


def analyze_top_stocks(rich_results: list[dict], top_k: int = 5,
                       min_picks: int = 2) -> str:
    """기간 내 종가배팅 수익률 상위 종목 + 공통 조건 분석.

    1. 종목별 픽을 모아 평균수익률 상위 top_k 추출 (min_picks 미만은 제외)
    2. 승자(ret > 0) vs 패자 픽의 sub-component 점수 평균 비교 → 어떤 조건이
       수익을 만들었는지 데이터 기반으로 추정
    """
    from collections import defaultdict

    if not rich_results:
        return "분석할 데이터가 없습니다."

    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rich_results:
        by_code[r["code"]].append(r)

    rows = []
    for code, picks in by_code.items():
        if len(picks) < min_picks:
            continue
        avg_ret = sum(p["ret"] for p in picks) / len(picks)
        wins = sum(1 for p in picks if p["ret"] > 0)
        rows.append({
            "code": code,
            "n": len(picks),
            "avg_ret": avg_ret,
            "winrate": wins / len(picks) * 100.0,
            "max_ret": max(p["ret"] for p in picks),
            "picks": picks,
        })

    rows.sort(key=lambda x: -x["avg_ret"])
    top = rows[:top_k]

    out: list[str] = []
    out.append(f"# 종가배팅 수익률 상위 {len(top)}종목 (min_picks={min_picks})")
    out.append("")
    out.append(f"| 순위 | 종목 | 픽 횟수 | 승률 | 평균수익 | 최대수익 |")
    out.append(f"|------|------|---------|------|----------|----------|")
    for i, r in enumerate(top, 1):
        out.append(
            f"| {i} | {r['code']} | {r['n']} | {r['winrate']:.0f}% | "
            f"{r['avg_ret']:+.2f}% | {r['max_ret']:+.2f}% |"
        )
    out.append("")

    # 공통 조건 분석: 전체 winners vs losers
    winners = [p for p in rich_results if p["ret"] > 0]
    losers = [p for p in rich_results if p["ret"] <= 0]
    if winners and losers:
        out.append("## 승자 vs 패자 sub-component 평균 비교")
        out.append("")
        out.append("| 조건 | 승자 평균 | 패자 평균 | 차이 |")
        out.append("|------|-----------|-----------|------|")
        for key, label in [
            ("volume_surge", "거래대금 surge (기준2)"),
            ("resistance_proximity", "저항선 이격 (기준3)"),
            ("candle_shape", "캔들 모양 (기준4)"),
            ("consolidation", "조정 후 회복 (기준5)"),
        ]:
            w_avg = sum(p["components"][key] for p in winners) / len(winners)
            l_avg = sum(p["components"][key] for p in losers) / len(losers)
            diff = w_avg - l_avg
            mark = "**↑**" if diff > 5 else ("↓" if diff < -5 else "·")
            out.append(f"| {label} | {w_avg:.1f} | {l_avg:.1f} | {diff:+.1f} {mark} |")
        out.append("")
        out.append("> **↑**: 승자에서 5점 이상 높음 → 수익 픽의 핵심 조건 후보")
        out.append("")

    # 상위 종목별 평균 sub-component (어떤 종목이 어떤 조건으로 뽑혔나)
    out.append("## 상위 종목별 평균 점수 분포")
    out.append("")
    out.append("| 종목 | 거래대금 | 저항이격 | 캔들 | 조정회복 |")
    out.append("|------|----------|----------|------|----------|")
    for r in top:
        comps = [p["components"] for p in r["picks"]]
        avg = {k: sum(c[k] for c in comps) / len(comps) for k in comps[0]}
        out.append(
            f"| {r['code']} | {avg['volume_surge']:.0f} | "
            f"{avg['resistance_proximity']:.0f} | {avg['candle_shape']:.0f} | "
            f"{avg['consolidation']:.0f} |"
        )
    out.append("")

    # 픽 상세 (날짜·점수·실제 지표값)
    out.append("## 상위 종목 픽 상세")
    out.append("")
    for r in top:
        out.append(f"### {r['code']}")
        out.append("")
        out.append("| 날짜 | 점수 | 수익 | 거래대금배율 | 저항이격% | 위꼬리 |")
        out.append("|------|------|------|--------------|-----------|--------|")
        for p in sorted(r["picks"], key=lambda x: x["date"]):
            bd = p["breakdown"]
            ratio = bd.get("volume_surge", {}).get("ratio", "-")
            gap = bd.get("resistance_proximity", {}).get("gap_pct", "-")
            wick = bd.get("candle_shape", {}).get("upper_wick_ratio", "-")
            out.append(
                f"| {p['date']} | {p['score']:.0f} | {p['ret']:+.2f}% | "
                f"{ratio} | {gap} | {wick} |"
            )
        out.append("")

    return "\n".join(out)


def write_csv(path: Path, results) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "score", "next_open_return_pct"])
        for date, code, score, ret in results:
            w.writerow([date, code, f"{score:.2f}", f"{ret:.4f}"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--threshold", type=float, default=50.0)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--codes", nargs="+", default=None,
                   help="유니버스를 종목코드 리스트로 직접 지정")
    p.add_argument("--universe", choices=["fixed", "kiwoom-large", "kiwoom-top"],
                   default="fixed",
                   help="유니버스 소스: fixed=하드코딩 26종목, "
                        "kiwoom-large=키움 ka10099 대형주, "
                        "kiwoom-top=시총 상위 N (--universe-top 사용)")
    p.add_argument("--universe-top", type=int, default=100,
                   help="--universe kiwoom-top 사용 시 상위 N 종목")
    p.add_argument("--refresh-universe", action="store_true",
                   help="universe 캐시를 무시하고 키움 API 재호출")
    p.add_argument("--out", type=Path, default=None,
                   help="결과 요약을 마크다운으로 저장할 경로 (예: docs/backtest_latest.md)")
    p.add_argument("--csv", type=Path, default=None,
                   help="픽별 raw 데이터를 CSV로 저장할 경로")
    p.add_argument("--html", type=Path, default=None,
                   help="종목별 캔들차트 + 요약을 단일 HTML로 저장할 경로")
    p.add_argument("--last-days", type=int, default=None,
                   help="픽 결과를 최근 N일로 필터 (데이터는 --start부터 받아 점수 계산용 충분히 확보)")
    p.add_argument("--top-stocks", action="store_true",
                   help="기간 내 종가배팅 수익률 상위 종목 + 공통조건 분석 출력")
    p.add_argument("--top-stocks-k", type=int, default=5,
                   help="--top-stocks 가 추출할 종목 수")
    p.add_argument("--min-picks", type=int, default=2,
                   help="--top-stocks 분석에서 최소 픽 횟수 (적은 표본 제외)")
    p.add_argument("--top-stocks-out", type=Path, default=None,
                   help="상위 종목 분석을 마크다운으로 저장할 경로")
    args = p.parse_args()

    # universe 결정
    code_to_name: dict[str, str] = {}
    if args.codes:
        codes = args.codes
        universe_label = f"명시적 {len(codes)}종목"
    elif args.universe == "fixed":
        codes = DEFAULT_UNIVERSE
        universe_label = f"고정 {len(codes)}종목"
    else:
        from scripts._universe_kiwoom import load_universe, select
        u = load_universe(refresh=args.refresh_universe)
        if args.universe == "kiwoom-large":
            picked = select(u, sizes=("대형주",))
            universe_label = f"키움 대형주 {len(picked)}종목"
        else:
            picked = select(u, sizes=("대형주", "중형주"),
                            top_by_marketcap=args.universe_top)
            universe_label = f"키움 시총상위 {len(picked)}종목"
        codes = [s["code"] for s in picked]
        code_to_name = {s["code"]: s["name"] for s in picked}

    print(f"백테스트 기간: {args.start} ~ {args.end}")
    print(f"유니버스: {universe_label}, 임계값 {args.threshold}, top_n {args.top_n}")
    print(f"{'='*60}")

    histories: dict[str, list[dict]] = {}
    fail_count = 0
    for i, code in enumerate(codes, 1):
        try:
            h = fetch_history(code, args.start, args.end)
            if len(h) >= 90:
                histories[code] = h
                if i % 25 == 0 or len(codes) <= 30:
                    name = code_to_name.get(code, "")
                    print(f"  [{i}/{len(codes)}] {code} {name}: {len(h)}봉 로드")
        except Exception as e:
            fail_count += 1
    if fail_count:
        print(f"  로드 실패 {fail_count}건 (조용히 스킵)")

    if not histories:
        print("로드된 종목이 없습니다.")
        sys.exit(1)

    print(f"\n시뮬레이션 시작 ({len(histories)}종목)...")
    rich_results = simulate(histories, args.threshold, args.top_n)

    if args.last_days:
        cutoff = (datetime.now() - timedelta(days=args.last_days)).strftime("%Y-%m-%d")
        rich_results = [r for r in rich_results if r["date"] >= cutoff]
        print(f"  최근 {args.last_days}일 필터 적용 → {len(rich_results)}건")

    results = _legacy_tuples(rich_results)
    report(results, args.threshold, args.top_n)

    if args.out:
        write_markdown(args.out, results, args.threshold, args.top_n,
                       args.start, args.end, len(histories))
        print(f"\n[저장] 마크다운 → {args.out}")
    if args.csv:
        write_csv(args.csv, results)
        print(f"[저장] CSV → {args.csv}")
    if args.html:
        write_html(args.html, rich_results, histories,
                   args.threshold, args.top_n,
                   args.start, args.end, code_to_name)
        print(f"[저장] HTML → {args.html}")
    if args.top_stocks:
        top_md = analyze_top_stocks(rich_results, top_k=args.top_stocks_k,
                                    min_picks=args.min_picks)
        if args.top_stocks_out:
            args.top_stocks_out.parent.mkdir(parents=True, exist_ok=True)
            args.top_stocks_out.write_text(top_md, encoding="utf-8")
            print(f"[저장] 상위종목 분석 → {args.top_stocks_out}")
        else:
            print("\n" + top_md)


if __name__ == "__main__":
    main()
