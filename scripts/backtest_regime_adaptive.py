"""레짐 연동 + 섹터 집중 복합 전략 백테스트.

전략 분기:
  weak 레짐   → 종가매매 스코어러 (volume_surge 0.90 + consolidation 0.10)
  neutral/strong → RS 모멘텀 스코어러 (RS 0.50 + volume 0.30 + consolidation 0.20)

추가 옵션:
  --sector-filter  당일 RS 상위 2개 섹터 종목에만 모멘텀 전략 적용 (PLAYBOOK E)

비교 시나리오:
  baseline       — 레짐 무관, 종가매매 v1+new (기존 기준)
  adaptive       — 레짐별 전략 분기 (PLAYBOOK D)
  sector         — 레짐 분기 + 상위 2개 섹터 집중 (PLAYBOOK D+E)

사용:
  python scripts/backtest_regime_adaptive.py
  python scripts/backtest_regime_adaptive.py --start 2025-01-01 --end 2026-04-30
  python scripts/backtest_regime_adaptive.py --html docs/backtest_regime_adaptive.html
  python scripts/backtest_regime_adaptive.py --out docs/backtest_regime_adaptive.md --csv-dir docs/adaptive_picks
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

from scripts.backtest_closing_bet import DEFAULT_UNIVERSE, fetch_history  # noqa: E402
from scripts.backtest_with_breadth_gate import (  # noqa: E402
    WEIGHTS_NEW_V1,
    classify_regime,
    compute_advance_ratio,
    fetch_kospi_returns,
    summarize,
)
from scripts import tune_weights as tw  # noqa: E402
from src.mcp_servers.closing_bet_mcp.scorer import (  # noqa: E402
    compute_technical_scores,
    score_consolidation,
    score_volume_surge,
)

# ── 섹터 매핑 (fixed universe 폴백) ──────────────────────────────────────────
SECTOR_MAP: dict[str, str] = {
    "005930": "반도체",    # 삼성전자
    "000660": "반도체",    # SK하이닉스
    "009150": "반도체",    # 삼성전기
    "035420": "인터넷",    # NAVER
    "035720": "인터넷",    # 카카오
    "005380": "자동차",    # 현대차
    "012330": "자동차",    # 현대모비스
    "051910": "배터리",    # LG화학
    "006400": "배터리",    # 삼성SDI
    "003670": "배터리",    # 포스코퓨처엠
    "207940": "바이오",    # 삼성바이오
    "068270": "바이오",    # 셀트리온
    "005490": "철강",      # POSCO홀딩스
    "010130": "비철금속",  # 고려아연
    "028260": "지주",      # 삼성물산
    "066570": "전자",      # LG전자
    "096770": "에너지",    # SK이노베이션
    "034730": "에너지",    # SK
    "017670": "통신",      # SK텔레콤
    "030200": "통신",      # KT
    "055550": "금융",      # 신한지주
    "105560": "금융",      # KB금융
    "086790": "금융",      # 하나금융
    "316140": "금융",      # 우리금융
    "032830": "금융",      # 삼성생명
    "015760": "유틸",      # 한국전력
}

MOMENTUM_W = {"rs": 0.50, "volume": 0.30, "consolidation": 0.20}


# ── RS 유틸 ─────────────────────────────────────────────────────────────────

def _rs_20d(ohlcv: list[dict]) -> float | None:
    """20일 수익률(%). 데이터 부족 시 None."""
    if len(ohlcv) < 21:
        return None
    c_now = float(ohlcv[-1].get("close", 0) or 0)
    c_past = float(ohlcv[-21].get("close", 0) or 0)
    if c_past <= 0:
        return None
    return (c_now - c_past) / c_past * 100.0


def _percentile_ranks(raw_vals: list[float]) -> list[float]:
    """값 리스트 → 백분위 순위 [0, 100]. 타이는 자연 정렬 위치 사용."""
    n = len(raw_vals)
    if n <= 1:
        return [50.0] * n
    pairs = sorted(enumerate(raw_vals), key=lambda x: x[1])
    result = [0.0] * n
    for rank, (idx, _) in enumerate(pairs):
        result[idx] = rank / (n - 1) * 100.0
    return result


def _exit_return(
    t_bar: dict, n_bar: dict, stop_loss_pct: float
) -> tuple[float, str]:
    """종가 매수 → 익일 청산 수익률 + 청산 유형.

    stop_loss_pct == 0 (기본):
      익일 시초가 청산 (기존 전략).

    stop_loss_pct > 0 (손절 활성):
      홀딩 기간을 '익일 종가' 또는 '장중 손절'로 연장.
        - 익일 시초가 ≤ 손절가 → 갭 하락, 시초가 청산 ('open')
        - 익일 저가 ≤ 손절가 → 장중 손절 (-stop_loss_pct 확정, 'stop')
        - 그 외              → 익일 종가 청산 ('close')
    """
    entry = float(t_bar.get("close", 0) or 0)
    open_p = float(n_bar.get("open", 0) or 0)
    if entry <= 0:
        return 0.0, "open"

    if stop_loss_pct > 0:
        stop_price = entry * (1.0 - stop_loss_pct / 100.0)
        low_p = float(n_bar.get("low", open_p) or open_p)
        close_p = float(n_bar.get("close", open_p) or open_p)
        if open_p <= stop_price:
            # 갭 하락 — 시초가로 즉시 청산
            return (open_p - entry) / entry * 100.0, "open"
        if low_p <= stop_price:
            # 장중 손절선 터치
            return -stop_loss_pct, "stop"
        # 손절 없이 종일 보유 → 익일 종가 청산
        return (close_p - entry) / entry * 100.0, "close"

    return (open_p - entry) / entry * 100.0, "open"


SECTOR_VOL_W = {"volume_surge": 0.70, "consolidation": 0.30}


def _sector_eligible(
    codes_today: list[str],
    histories: dict[str, list[dict]],
    date_t: str,
    sector_by_code: dict[str, str],
    sector_top: int,
) -> tuple[set[str], set[str]]:
    """당일 RS 상위 sector_top개 섹터 소속 코드 반환. (eligible_set, top_sectors)."""
    rs_raw: dict[str, float] = {}
    for code in codes_today:
        h = histories.get(code, [])
        window = [d for d in h if d["date"] <= date_t][-90:]
        rs = _rs_20d(window)
        if rs is not None:
            rs_raw[code] = rs

    if not rs_raw:
        return set(codes_today), set()

    codes_rs = list(rs_raw.keys())
    pct = _percentile_ranks([rs_raw[c] for c in codes_rs])
    rs_scores = dict(zip(codes_rs, pct))

    sec_rs: dict[str, list[float]] = {}
    for code in codes_rs:
        sec = sector_by_code.get(code, "기타")
        sec_rs.setdefault(sec, []).append(rs_scores[code])
    sec_avg = {s: sum(v) / len(v) for s, v in sec_rs.items()}
    top_sectors = {
        s for s, _ in sorted(sec_avg.items(), key=lambda x: -x[1])[:sector_top]
    }
    eligible = {c for c in codes_today if sector_by_code.get(c, "기타") in top_sectors}
    return eligible, top_sectors


# ── 핵심 시뮬레이션 ──────────────────────────────────────────────────────────

def simulate_regime_adaptive(
    histories: dict[str, list[dict]],
    kospi: dict[str, float],
    sector_by_code: dict[str, str],
    args,
    use_sector_filter: bool = False,
    use_sector_vol: bool = False,
    neutral_only_vol: bool = False,
) -> list[dict]:
    """레짐별 전략 분기 시뮬레이션.

    weak   → 종가매매 scorer (WEIGHTS_NEW_V1)
    neutral/strong, use_sector_vol=False → RS 모멘텀 scorer (+ 선택적 섹터 필터)
    neutral/strong, use_sector_vol=True  → 섹터 RS 필터 + 거래량 scorer (SECTOR_VOL_W)
    neutral_only_vol=True (use_sector_vol과 함께): strong은 종가매매로 폴백 (PLAYBOOK D+E-vol-N)
    """
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    picks: list[dict] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]

        codes_today = tw.daily_universe(
            histories, date_t, args.daily_universe_size, args.value_window
        )
        if not codes_today:
            continue

        adv, _, uni_ret = compute_advance_ratio(histories, date_t, codes_today)
        kpct = kospi.get(date_t, uni_ret)
        regime = classify_regime(kpct, adv, args.weak_kospi_pct, args.weak_adv_ratio)

        day_picks: list[tuple[str, float, str]]  # (code, score, strategy_label)

        if regime == "weak":
            # ── 종가매매 스코어러 ──────────────────────────────────────────
            scored: list[tuple[str, float]] = []
            for code in codes_today:
                h = histories.get(code, [])
                window = [d for d in h if d["date"] <= date_t][-90:]
                if len(window) < 60:
                    continue
                ts = compute_technical_scores(window)
                score = (
                    ts.volume_surge * WEIGHTS_NEW_V1["volume_surge"]
                    + ts.consolidation * WEIGHTS_NEW_V1["consolidation"]
                )
                if score >= args.threshold:
                    scored.append((code, score))
            scored.sort(key=lambda x: -x[1])
            day_picks = [(c, s, "종가매매") for c, s in scored[: args.top_n]]

        else:
            # ── neutral/strong 스코어러 ────────────────────────────────────
            # neutral_only_vol=True 이면 strong은 종가매매로 폴백 (PLAYBOOK D+E-vol-N)
            if neutral_only_vol and use_sector_vol and regime == "strong":
                scored_strong: list[tuple[str, float]] = []
                for code in codes_today:
                    h = histories.get(code, [])
                    window = [d for d in h if d["date"] <= date_t][-90:]
                    if len(window) < 60:
                        continue
                    ts = compute_technical_scores(window)
                    score = (
                        ts.volume_surge * WEIGHTS_NEW_V1["volume_surge"]
                        + ts.consolidation * WEIGHTS_NEW_V1["consolidation"]
                    )
                    if score >= args.threshold:
                        scored_strong.append((code, score))
                scored_strong.sort(key=lambda x: -x[1])
                day_picks = [(c, s, "종가매매(strong폴백)") for c, s in scored_strong[:args.top_n]]
                for code, score, strategy in day_picks:
                    h = histories.get(code, [])
                    t_bar = next((d for d in h if d["date"] == date_t), None)
                    n_bar = next((d for d in h if d["date"] == date_next), None)
                    if t_bar is None or n_bar is None or t_bar["close"] <= 0:
                        continue
                    ret, exit_type = _exit_return(t_bar, n_bar, args.stop_loss)
                    picks.append({
                        "date": date_t, "code": code, "score": score,
                        "ret": ret, "exit_type": exit_type, "regime": regime,
                        "strategy": strategy, "sector": sector_by_code.get(code, "기타"),
                    })
                continue  # 다음 날짜로

            vol_sc: dict[str, float] = {}
            con_sc: dict[str, float] = {}

            if use_sector_vol:
                # 섹터 RS 필터 → 상위 섹터 내에서 거래량 스코어 (PLAYBOOK E-vol)
                eligible, _ = _sector_eligible(
                    codes_today, histories, date_t, sector_by_code, args.sector_top
                )
                for code in eligible:
                    h = histories.get(code, [])
                    window = [d for d in h if d["date"] <= date_t][-90:]
                    if len(window) < 21:
                        continue
                    vs, _ = score_volume_surge(window)
                    cs, _ = score_consolidation(window)
                    vol_sc[code] = vs
                    con_sc[code] = cs
                m_scored: list[tuple[str, float]] = []
                for code in eligible:
                    if code not in vol_sc:
                        continue
                    mc = (
                        vol_sc[code] * SECTOR_VOL_W["volume_surge"]
                        + con_sc[code] * SECTOR_VOL_W["consolidation"]
                    )
                    if mc >= args.momentum_threshold:
                        m_scored.append((code, mc))
                m_scored.sort(key=lambda x: -x[1])
                label = "섹터RS+거래량"
                day_picks = [(c, s, label) for c, s in m_scored[: args.top_n]]

            else:
                # ── RS 모멘텀 스코어러 (기존) ──────────────────────────────
                rs_raw: dict[str, float] = {}

                for code in codes_today:
                    h = histories.get(code, [])
                    window = [d for d in h if d["date"] <= date_t][-90:]
                    if len(window) < 21:
                        continue
                    rs = _rs_20d(window)
                    if rs is None:
                        continue
                    rs_raw[code] = rs
                    vs, _ = score_volume_surge(window)
                    cs, _ = score_consolidation(window)
                    vol_sc[code] = vs
                    con_sc[code] = cs

                if not rs_raw:
                    continue

                codes_rs = list(rs_raw.keys())
                pct = _percentile_ranks([rs_raw[c] for c in codes_rs])
                rs_scores = dict(zip(codes_rs, pct))

                # 섹터 집중 필터 (PLAYBOOK E)
                eligible = set(codes_rs)
                if use_sector_filter:
                    eligible, _ = _sector_eligible(
                        codes_today, histories, date_t, sector_by_code, args.sector_top
                    )

                m_scored = []
                for code in eligible:
                    mc = (
                        rs_scores.get(code, 50.0) * MOMENTUM_W["rs"]
                        + vol_sc.get(code, 0.0) * MOMENTUM_W["volume"]
                        + con_sc.get(code, 0.0) * MOMENTUM_W["consolidation"]
                    )
                    if mc >= args.momentum_threshold:
                        m_scored.append((code, mc))
                m_scored.sort(key=lambda x: -x[1])
                label = f"모멘텀({'섹터' if use_sector_filter else ''})"
                day_picks = [(c, s, label) for c, s in m_scored[: args.top_n]]

        # 수익률 계산 (종가 매수 → 익일 청산, 손절 적용)
        for code, score, strategy in day_picks:
            h = histories.get(code, [])
            t_bar = next((d for d in h if d["date"] == date_t), None)
            n_bar = next((d for d in h if d["date"] == date_next), None)
            if t_bar is None or n_bar is None or t_bar["close"] <= 0:
                continue
            ret, exit_type = _exit_return(t_bar, n_bar, args.stop_loss)
            picks.append({
                "date": date_t,
                "code": code,
                "score": score,
                "ret": ret,
                "exit_type": exit_type,
                "regime": regime,
                "strategy": strategy,
                "sector": sector_by_code.get(code, "기타"),
            })

    return picks


def simulate_baseline(
    histories: dict[str, list[dict]],
    args,
) -> list[dict]:
    """종가매매 v1+new baseline 시뮬레이션 (stop_loss 지원)."""
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    picks: list[dict] = []
    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]
        codes_today = tw.daily_universe(
            histories, date_t, args.daily_universe_size, args.value_window
        )
        scored: list[tuple[str, float]] = []
        for code in codes_today:
            h = histories.get(code, [])
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            ts = compute_technical_scores(window)
            score = (
                ts.volume_surge * WEIGHTS_NEW_V1["volume_surge"]
                + ts.consolidation * WEIGHTS_NEW_V1["consolidation"]
            )
            if score >= args.threshold:
                scored.append((code, score))
        scored.sort(key=lambda x: -x[1])
        for code, score in scored[: args.top_n]:
            h = histories.get(code, [])
            t_bar = next((d for d in h if d["date"] == date_t), None)
            n_bar = next((d for d in h if d["date"] == date_next), None)
            if t_bar is None or n_bar is None or t_bar["close"] <= 0:
                continue
            ret, exit_type = _exit_return(t_bar, n_bar, args.stop_loss)
            picks.append({
                "date": date_t,
                "code": code,
                "score": score,
                "ret": ret,
                "exit_type": exit_type,
            })
    return picks


def simulate_sector_baseline(
    histories: dict[str, list[dict]],
    kospi: dict[str, float],
    sector_by_code: dict[str, str],
    args,
) -> list[dict]:
    """종가매매 + 섹터 집중 (레짐 분기 없음, PLAYBOOK F).

    모든 레짐에서: 당일 RS 상위 sector_top개 섹터 내 종목에만 종가매매 적용.
    """
    all_dates = sorted({d["date"] for h in histories.values() for d in h})
    picks: list[dict] = []

    for i in range(89, len(all_dates) - 1):
        date_t = all_dates[i]
        date_next = all_dates[i + 1]
        codes_today = tw.daily_universe(
            histories, date_t, args.daily_universe_size, args.value_window
        )
        if not codes_today:
            continue

        adv, _, uni_ret = compute_advance_ratio(histories, date_t, codes_today)
        kpct = kospi.get(date_t, uni_ret)
        regime = classify_regime(kpct, adv, args.weak_kospi_pct, args.weak_adv_ratio)

        eligible, _ = _sector_eligible(
            codes_today, histories, date_t, sector_by_code, args.sector_top
        )

        scored: list[tuple[str, float]] = []
        for code in eligible:
            h = histories.get(code, [])
            window = [d for d in h if d["date"] <= date_t][-90:]
            if len(window) < 60:
                continue
            ts = compute_technical_scores(window)
            score = (
                ts.volume_surge * WEIGHTS_NEW_V1["volume_surge"]
                + ts.consolidation * WEIGHTS_NEW_V1["consolidation"]
            )
            if score >= args.threshold:
                scored.append((code, score))
        scored.sort(key=lambda x: -x[1])

        for code, score in scored[: args.top_n]:
            h = histories.get(code, [])
            t_bar = next((d for d in h if d["date"] == date_t), None)
            n_bar = next((d for d in h if d["date"] == date_next), None)
            if t_bar is None or n_bar is None or t_bar["close"] <= 0:
                continue
            ret, exit_type = _exit_return(t_bar, n_bar, args.stop_loss)
            picks.append({
                "date": date_t,
                "code": code,
                "score": score,
                "ret": ret,
                "exit_type": exit_type,
                "regime": regime,
                "strategy": "종가매매+섹터",
                "sector": sector_by_code.get(code, "기타"),
            })

    return picks


# ── 통계 헬퍼 ───────────────────────────────────────────────────────────────

def regime_breakdown(picks: list[dict]) -> dict[str, dict]:
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        by_regime[p["regime"]].append(p)
    return {r: summarize(ps) for r, ps in by_regime.items()}


def sector_breakdown(picks: list[dict]) -> dict[str, dict]:
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        by_sector[p.get("sector", "기타")].append(p)
    result = {s: summarize(ps) for s, ps in by_sector.items()}
    return dict(sorted(result.items(), key=lambda x: -x[1]["n"]))


def strategy_breakdown(picks: list[dict]) -> dict[str, dict]:
    by_strat: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        by_strat[p.get("strategy", "?")].append(p)
    return {s: summarize(ps) for s, ps in by_strat.items()}


def stop_stat(picks: list[dict]) -> tuple[int, float]:
    """(손절 발동 수, 손절 비율%)."""
    n_stop = sum(1 for p in picks if p.get("exit_type") == "stop")
    return n_stop, (n_stop / len(picks) * 100.0 if picks else 0.0)


# ── HTML 렌더러 ─────────────────────────────────────────────────────────────

def render_html(
    args,
    base: dict,
    adaptive: dict,
    sector: dict,
    sector_base: dict,
    sector_vol: dict,
    sector_vol_n: dict,
    name_by_code: dict[str, str],
    base_picks: list[dict],
    adaptive_picks: list[dict],
    sector_picks: list[dict],
    sector_base_picks: list[dict],
    sector_vol_picks: list[dict],
    sector_vol_n_picks: list[dict],
) -> str:
    stop_label = f"손절 {args.stop_loss:.1f}%" if args.stop_loss > 0 else "손절 없음"

    def _stop_cell(picks: list[dict]) -> str:
        n_s, pct = stop_stat(picks)
        if args.stop_loss <= 0 or not picks:
            return "<td>-</td>"
        return f"<td>{n_s}건 ({pct:.1f}%)</td>"

    def _row(label: str, s: dict, picks: list[dict], color_class: str = "") -> str:
        d_wr = s["winrate"] - base["winrate"]
        d_avg = s["avg_ret"] - base["avg_ret"]
        d_n = s["n"] - base["n"]
        wr_cls = "pos" if d_wr > 0 else ("neg" if d_wr < 0 else "")
        avg_cls = "pos" if d_avg > 0 else ("neg" if d_avg < 0 else "")
        return (
            f"<tr class='{color_class}'>"
            f"<td>{label}</td><td>{s['n']}</td>"
            f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td>"
            f"<td>{d_n:+d}</td>"
            f"<td class='{wr_cls}'>{d_wr:+.1f}pp</td>"
            f"<td class='{avg_cls}'>{d_avg:+.2f}%</td>"
            f"{_stop_cell(picks)}</tr>"
        )

    base_stop_cell = _stop_cell(base_picks)
    summary_rows = [
        f"<tr><td>baseline (종가매매)</td><td>{base['n']}</td>"
        f"<td>{base['winrate']:.1f}%</td><td>{base['avg_ret']:+.2f}%</td>"
        f"<td colspan='3'>-</td>{base_stop_cell}</tr>",
        _row("adaptive (PLAYBOOK D)", adaptive, adaptive_picks, "highlight-blue"),
        _row("sector (PLAYBOOK D+E)", sector, sector_picks, "highlight-gold"),
        _row("sector_base (PLAYBOOK F)", sector_base, sector_base_picks, "highlight-green"),
        _row("sector_vol (D+E-vol)", sector_vol, sector_vol_picks, "highlight-purple"),
        _row("sector_vol_N (D+E-vol-N)", sector_vol_n, sector_vol_n_picks, "highlight-teal"),
    ]

    # 레짐별 분해
    def _regime_rows(picks: list[dict]) -> str:
        bd = regime_breakdown(picks)
        rows = []
        for r in ("strong", "neutral", "weak"):
            s = bd.get(r, {"n": 0, "winrate": 0.0, "avg_ret": 0.0})
            cls = "highlight" if r == "weak" else ""
            rows.append(
                f"<tr class='{cls}'><td>{r}</td><td>{s['n']}</td>"
                f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td></tr>"
            )
        return "".join(rows)

    # 전략별 분해
    def _strat_rows(picks: list[dict]) -> str:
        bd = strategy_breakdown(picks)
        rows = []
        for strat, s in bd.items():
            rows.append(
                f"<tr><td>{strat}</td><td>{s['n']}</td>"
                f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td></tr>"
            )
        return "".join(rows)

    # 섹터별 분해
    def _sector_rows(picks: list[dict]) -> str:
        bd = sector_breakdown(picks)
        rows = []
        for sec, s in bd.items():
            rows.append(
                f"<tr><td>{sec}</td><td>{s['n']}</td>"
                f"<td>{s['winrate']:.1f}%</td><td>{s['avg_ret']:+.2f}%</td></tr>"
            )
        return "".join(rows)

    # 픽 테이블 HTML
    def _picks_table(picks: list[dict], label: str) -> str:
        sorted_picks = sorted(picks, key=lambda x: (x["date"], -x["score"]), reverse=True)
        rows = []
        for p in sorted_picks:
            nm = name_by_code.get(p["code"], "")
            ret_cls = "pos" if p["ret"] > 0 else ("neg" if p["ret"] < 0 else "")
            reg_cls = "highlight" if p.get("regime") == "weak" else ""
            exit_type = p.get("exit_type", "open")
            exit_cls = "neg" if exit_type == "stop" else ""
            rows.append(
                f"<tr class='{reg_cls}'>"
                f"<td>{p['date']}</td><td>{p['code']}</td><td>{nm}</td>"
                f"<td>{p['score']:.1f}</td><td>{p.get('regime','')}</td>"
                f"<td>{p.get('strategy','')}</td><td>{p.get('sector','')}</td>"
                f"<td class='{exit_cls}'>{exit_type}</td>"
                f"<td class='{ret_cls}'>{p['ret']:+.2f}%</td></tr>"
            )
        return (
            f"<h3>{label} ({len(sorted_picks)}건)</h3>"
            f"<details><summary>펼치기/접기</summary>"
            f"<table><thead><tr>"
            f"<th>일자</th><th>코드</th><th>종목명</th><th>점수</th>"
            f"<th>레짐</th><th>전략</th><th>섹터</th><th>청산</th><th>익일 수익률</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></details>"
        )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>레짐 연동 + 섹터 집중 전략 백테스트</title>
<style>
  body {{ font-family: -apple-system,"Segoe UI",sans-serif; max-width: 1100px; margin: 32px auto; padding: 0 16px; color: #222; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ margin-top: 32px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ccc; padding: 8px 12px; text-align: right; }}
  th, td:first-child {{ text-align: left; }}
  th {{ background: #f5f5f5; }}
  tr.highlight {{ background: #fff8d6; }}
  tr.highlight-blue {{ background: #e8f4fd; }}
  tr.highlight-gold {{ background: #fef9e7; }}
  tr.highlight-green {{ background: #e8f8e8; }}
  tr.highlight-purple {{ background: #f3e8fd; }}
  tr.highlight-teal {{ background: #e0f4f4; }}
  td.pos {{ color: #117a3d; font-weight: 600; }}
  td.neg {{ color: #b3261e; font-weight: 600; }}
  .meta {{ color: #555; font-size: 14px; line-height: 1.8; }}
  code {{ background: #eee; padding: 1px 6px; border-radius: 3px; font-size: 13px; }}
  details {{ margin: 8px 0 24px; }}
  summary {{ cursor: pointer; color: #2872d4; padding: 4px 0; user-select: none; }}
  details table {{ font-size: 13px; }}
  h3 {{ margin-top: 24px; color: #444; }}
  .card {{ background:#f8f9fa; border:1px solid #dee2e6; border-radius:6px; padding:16px 20px; margin: 16px 0; }}
  .card strong {{ font-size: 15px; }}
</style>
</head><body>
<h1>레짐 연동 + 섹터 집중 전략 백테스트</h1>
<div class="meta">
  실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;·&nbsp;
  기간: {args.start} ~ {args.end} &nbsp;·&nbsp;
  daily universe 상위 {args.daily_universe_size} &nbsp;·&nbsp;
  top_n {args.top_n}<br>
  baseline threshold {args.threshold} &nbsp;·&nbsp;
  momentum threshold {args.momentum_threshold} &nbsp;·&nbsp;
  sector top {args.sector_top}<br>
  weak: KOSPI &lt; {args.weak_kospi_pct:+.1f}% OR adv &lt; {args.weak_adv_ratio:.2f} &nbsp;·&nbsp;
  <strong>{stop_label}</strong>
</div>

<h2>종합 결과</h2>
<table>
  <thead><tr><th>시나리오</th><th>픽 수</th><th>승률</th><th>평균수익</th>
  <th>Δ픽</th><th>Δ승률</th><th>Δ평균</th><th>손절 발동</th></tr></thead>
  <tbody>{''.join(summary_rows)}</tbody>
</table>

<h2>Adaptive (PLAYBOOK D) — 레짐별 분해</h2>
<table>
  <thead><tr><th>레짐</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_regime_rows(adaptive_picks)}</tbody>
</table>

<h2>Adaptive (PLAYBOOK D) — 전략별 분해</h2>
<table>
  <thead><tr><th>전략</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_strat_rows(adaptive_picks)}</tbody>
</table>

<h2>Sector (PLAYBOOK D+E) — 섹터별 분해</h2>
<table>
  <thead><tr><th>섹터</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_sector_rows(sector_picks)}</tbody>
</table>

<h2>Sector Baseline (F) — 섹터별 분해</h2>
<table>
  <thead><tr><th>섹터</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_sector_rows(sector_base_picks)}</tbody>
</table>

<h2>Sector+Vol (D+E-vol) — 레짐별 분해</h2>
<table>
  <thead><tr><th>레짐</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_regime_rows(sector_vol_picks)}</tbody>
</table>

<h2>Sector+Vol-N (D+E-vol-N) — 레짐별 분해</h2>
<table>
  <thead><tr><th>레짐</th><th>픽 수</th><th>승률</th><th>평균수익</th></tr></thead>
  <tbody>{_regime_rows(sector_vol_n_picks)}</tbody>
</table>

<h2>픽 상세</h2>
{_picks_table(base_picks, "Baseline (종가매매)")}
{_picks_table(adaptive_picks, "Adaptive (PLAYBOOK D)")}
{_picks_table(sector_picks, "Sector (PLAYBOOK D+E)")}
{_picks_table(sector_base_picks, "Sector Baseline (PLAYBOOK F)")}
{_picks_table(sector_vol_picks, "Sector+Vol (PLAYBOOK D+E-vol)")}
{_picks_table(sector_vol_n_picks, "Sector+Vol-N (PLAYBOOK D+E-vol-N)")}

<h2>전략 설명</h2>
<div class="card">
  <strong>PLAYBOOK D — 레짐 연동 전략 분기</strong><br>
  <code>weak</code> 레짐: 종가매매 스코어러 (volume_surge 0.90 + consolidation 0.10)<br>
  <code>neutral/strong</code> 레짐: RS 모멘텀 스코어러 (RS 0.50 + volume 0.30 + consolidation 0.20)<br>
  RS = 20일 수익률 백분위 순위 (universe 내 상대 강도)
</div>
<div class="card">
  <strong>PLAYBOOK E — 섹터 집중 필터</strong><br>
  neutral/strong 레짐에서 RS 평균 상위 {args.sector_top}개 섹터의 종목에만 모멘텀 전략 적용.<br>
  당일 가장 강한 섹터에 픽을 집중시켜 분산 노이즈 제거.
</div>
<div class="card">
  <strong>PLAYBOOK F — 종가매매 + 섹터 집중 (레짐 분기 없음)</strong><br>
  레짐 무관, 전 레짐에서: 당일 RS 상위 {args.sector_top}개 섹터 내 종목에만 종가매매 스코어 적용.<br>
  섹터 필터의 순수 효과를 레짐 라우팅 없이 측정.
</div>
<div class="card">
  <strong>PLAYBOOK D+E-vol — 섹터 RS 필터 + 거래량 스코어러</strong><br>
  weak → 종가매매 (기존), neutral/strong → 섹터 RS 상위 {args.sector_top}개 섹터 내에서
  거래량 급증 스코어(volume_surge 0.70 + consolidation 0.30) 적용.<br>
  RS는 섹터 선별에만 사용, 개별 종목은 거래량으로 선정.
</div>
<div class="card">
  <strong>PLAYBOOK D+E-vol-N — neutral만 섹터RS+거래량, strong은 종가매매 폴백</strong><br>
  weak → 종가매매, <strong>neutral</strong> → 섹터RS 상위 {args.sector_top}개 + 거래량 스코어,
  <strong>strong</strong> → 종가매매 폴백.<br>
  실험 근거: D+E-vol에서 strong 52.4%가 weak(53.5%)·neutral(56.0%) 대비 약함 →
  strong 레짐에서는 섹터 집중의 이점이 사라지는지 검증.
</div>
</body></html>"""


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    p.add_argument("--codes", nargs="+", default=None)
    p.add_argument("--universe", choices=["fixed", "kiwoom-large", "kiwoom-top"], default="kiwoom-top")
    p.add_argument("--universe-top", type=int, default=500)
    p.add_argument("--refresh-universe", action="store_true")
    p.add_argument("--threshold", type=float, default=50.0, help="종가매매 임계값")
    p.add_argument("--momentum-threshold", type=float, default=50.0, help="RS 모멘텀 임계값")
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--daily-universe-size", type=int, default=200)
    p.add_argument("--value-window", type=int, default=5)
    p.add_argument("--fetch-workers", type=int, default=8)
    p.add_argument("--weak-kospi-pct", type=float, default=-1.0)
    p.add_argument("--weak-adv-ratio", type=float, default=0.35)
    p.add_argument("--sector-top", type=int, default=2, help="섹터 집중 필터 상위 K개")
    p.add_argument("--sector-top-sweep", action="store_true",
                   help="sector_top 2/3/4 비교 스윕 (sector_vol 기준)")
    p.add_argument("--weak-sweep", action="store_true",
                   help="weak_kospi_pct × weak_adv_ratio 그리드 스윕")
    p.add_argument("--stop-loss", type=float, default=0.0,
                   help="손절 기준 %% (예: 2.0 → -2%% 이하 장중 손절, 0=비활성)")
    p.add_argument("--out", type=Path, default=None, help="MD 출력 경로")
    p.add_argument("--html", type=Path, default=None, help="HTML 출력 경로")
    p.add_argument("--csv-dir", type=Path, default=None, help="픽 CSV 저장 디렉터리")
    args = p.parse_args()

    tw.COMPONENT_KEYS = tw.COMPONENT_KEYS_BASE  # noqa: used by tune_weights internals
    tw.SCORER = compute_technical_scores

    # ── 유니버스 로드 ──────────────────────────────────────────────────────
    name_by_code: dict[str, str] = {}
    sector_by_code: dict[str, str] = {}

    if args.codes:
        codes = args.codes
        sector_by_code = {c: SECTOR_MAP.get(c, "기타") for c in codes}
    elif args.universe == "fixed":
        codes = DEFAULT_UNIVERSE
        sector_by_code = {c: SECTOR_MAP.get(c, "기타") for c in codes}
    else:
        from scripts._universe_kiwoom import load_universe, select
        u = load_universe(refresh=args.refresh_universe)
        if args.universe == "kiwoom-large":
            picked = select(u, sizes=("대형주",))
        else:
            picked = select(u, sizes=("대형주", "중형주"), top_by_marketcap=args.universe_top)
        codes = [s["code"] for s in picked]
        name_by_code = {s["code"]: s.get("name", "") for s in picked}
        # Kiwoom API가 제공하는 업종명 사용, 폴백은 SECTOR_MAP
        sector_by_code = {
            s["code"]: (s.get("sector") or SECTOR_MAP.get(s["code"], "기타"))
            for s in picked
        }

    print(f"[load] 마스터 풀 {len(codes)}종목, {args.start} ~ {args.end}")

    # ── OHLCV 로드 (병렬) ─────────────────────────────────────────────────
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

    # ── KOSPI 로드 ────────────────────────────────────────────────────────
    print("[load] KOSPI 일별 등락 로드")
    kospi = fetch_kospi_returns(args.start, args.end)
    print(f"  KOSPI 거래일 {len(kospi)}일")

    # ── Baseline (종가매매 v1+new) ─────────────────────────────────────────
    stop_info = f"  손절 {args.stop_loss:.1f}%" if args.stop_loss > 0 else "  손절 없음"
    print(f"\n[run] baseline (종가매매 v1+new){stop_info}")
    base_picks = simulate_baseline(histories, args)
    base = summarize(base_picks)
    n_bs, pct_bs = stop_stat(base_picks)
    stop_msg = f", 손절 발동 {n_bs}건 ({pct_bs:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  baseline → 픽 {base['n']}, 승률 {base['winrate']:.1f}%, 평균 {base['avg_ret']:+.2f}%{stop_msg}")

    # ── Adaptive (PLAYBOOK D) ─────────────────────────────────────────────
    print(f"\n[run] adaptive (PLAYBOOK D: 레짐 연동){stop_info}")
    adaptive_picks = simulate_regime_adaptive(
        histories, kospi, sector_by_code, args, use_sector_filter=False
    )
    adaptive = summarize(adaptive_picks)
    n_ad, pct_ad = stop_stat(adaptive_picks)
    stop_msg_ad = f", 손절 발동 {n_ad}건 ({pct_ad:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  adaptive → 픽 {adaptive['n']}, 승률 {adaptive['winrate']:.1f}%, 평균 {adaptive['avg_ret']:+.2f}%{stop_msg_ad}")

    # ── Sector (PLAYBOOK D+E) ─────────────────────────────────────────────
    print(f"\n[run] sector (PLAYBOOK D+E: 레짐 연동 + 섹터 집중){stop_info}")
    sector_picks = simulate_regime_adaptive(
        histories, kospi, sector_by_code, args, use_sector_filter=True
    )
    sector_stat_dict = summarize(sector_picks)
    n_sec, pct_sec = stop_stat(sector_picks)
    stop_msg_sec = f", 손절 발동 {n_sec}건 ({pct_sec:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  sector   → 픽 {sector_stat_dict['n']}, 승률 {sector_stat_dict['winrate']:.1f}%, 평균 {sector_stat_dict['avg_ret']:+.2f}%{stop_msg_sec}")

    # ── Sector Baseline (PLAYBOOK F: 종가매매+섹터, 레짐 무관) ───────────────
    print(f"\n[run] sector_base (PLAYBOOK F: 종가매매 + 섹터 집중, 레짐 분기 없음){stop_info}")
    sector_base_picks = simulate_sector_baseline(histories, kospi, sector_by_code, args)
    sector_base = summarize(sector_base_picks)
    n_sb, pct_sb = stop_stat(sector_base_picks)
    stop_msg_sb = f", 손절 발동 {n_sb}건 ({pct_sb:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  sector_base → 픽 {sector_base['n']}, 승률 {sector_base['winrate']:.1f}%, 평균 {sector_base['avg_ret']:+.2f}%{stop_msg_sb}")

    # ── Sector+Vol (PLAYBOOK D+E-vol: 섹터RS필터 + 거래량 스코어러) ───────────
    print(f"\n[run] sector_vol (PLAYBOOK D+E-vol: 섹터RS+거래량 스코어러){stop_info}")
    sector_vol_picks = simulate_regime_adaptive(
        histories, kospi, sector_by_code, args,
        use_sector_filter=True, use_sector_vol=True
    )
    sector_vol = summarize(sector_vol_picks)
    n_sv, pct_sv = stop_stat(sector_vol_picks)
    stop_msg_sv = f", 손절 발동 {n_sv}건 ({pct_sv:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  sector_vol  → 픽 {sector_vol['n']}, 승률 {sector_vol['winrate']:.1f}%, 평균 {sector_vol['avg_ret']:+.2f}%{stop_msg_sv}")

    # ── Sector+Vol-N (PLAYBOOK D+E-vol-N: neutral만 섹터RS+거래량, strong→종가매매 폴백)
    print(f"\n[run] sector_vol_N (D+E-vol-N: neutral만 섹터RS+거래량, strong 종가매매 폴백){stop_info}")
    sector_vol_n_picks = simulate_regime_adaptive(
        histories, kospi, sector_by_code, args,
        use_sector_filter=True, use_sector_vol=True, neutral_only_vol=True,
    )
    sector_vol_n = summarize(sector_vol_n_picks)
    n_svn, pct_svn = stop_stat(sector_vol_n_picks)
    stop_msg_svn = f", 손절 발동 {n_svn}건 ({pct_svn:.1f}%)" if args.stop_loss > 0 else ""
    print(f"  sector_vol_N → 픽 {sector_vol_n['n']}, 승률 {sector_vol_n['winrate']:.1f}%, 평균 {sector_vol_n['avg_ret']:+.2f}%{stop_msg_svn}")

    # ── sector_top 파라미터 sweep ─────────────────────────────────────────
    if args.sector_top_sweep:
        print("\n[sweep] sector_top 파라미터 비교 (sector_vol 기준)")
        print(f"  {'top':>5} | {'픽 수':>6} | {'승률':>7} | {'평균수익':>8} | {'Δ승률':>7} | {'Δ평균':>8}")
        for k in (2, 3, 4):
            orig = args.sector_top
            args.sector_top = k
            _p = simulate_regime_adaptive(
                histories, kospi, sector_by_code, args,
                use_sector_filter=True, use_sector_vol=True,
            )
            _s = summarize(_p)
            d_wr = _s["winrate"] - base["winrate"]
            d_avg = _s["avg_ret"] - base["avg_ret"]
            print(
                f"  top={k}: 픽 {_s['n']:4d}, 승률 {_s['winrate']:.1f}%,"
                f"  평균 {_s['avg_ret']:+.2f}%,"
                f"  Δ승률 {d_wr:+.1f}pp, Δ평균 {d_avg:+.2f}%"
            )
            args.sector_top = orig

    # ── weak sensitivity sweep ────────────────────────────────────────────
    if args.weak_sweep:
        print("\n[sweep] weak 파라미터 sensitivity (sector_vol, neutral leaning)")
        kospi_grid = [-0.3, -0.5, -0.7, -1.0, -1.5]
        adv_grid   = [0.30, 0.35, 0.40, 0.45]
        hdr = "  KOSPI\\adv |" + "".join(f" {a:.2f}  " for a in adv_grid)
        print(hdr)
        orig_kp = args.weak_kospi_pct
        orig_ar = args.weak_adv_ratio
        for kp in kospi_grid:
            row_parts = []
            for ar in adv_grid:
                args.weak_kospi_pct = kp
                args.weak_adv_ratio = ar
                _p = simulate_regime_adaptive(
                    histories, kospi, sector_by_code, args,
                    use_sector_filter=True, use_sector_vol=True,
                )
                _s = summarize(_p)
                row_parts.append(f"{_s['winrate']:5.1f}%({_s['n']:3d})")
            print(f"  {kp:+.1f}%      | " + " | ".join(row_parts))
        args.weak_kospi_pct = orig_kp
        args.weak_adv_ratio = orig_ar

    # ── 분해 통계 출력 ────────────────────────────────────────────────────
    print("\n[breakdown] Adaptive 레짐별")
    for r in ("strong", "neutral", "weak"):
        sub = [p for p in adaptive_picks if p["regime"] == r]
        s = summarize(sub)
        print(f"  {r:8s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Adaptive 전략별")
    for strat, s in strategy_breakdown(adaptive_picks).items():
        print(f"  {strat}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Sector D+E 섹터별")
    for sec, s in sector_breakdown(sector_picks).items():
        print(f"  {sec:10s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Sector Baseline (F) 레짐별")
    for r in ("strong", "neutral", "weak"):
        sub = [p for p in sector_base_picks if p.get("regime") == r]
        s = summarize(sub)
        print(f"  {r:8s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Sector Baseline (F) 섹터별")
    for sec, s in sector_breakdown(sector_base_picks).items():
        print(f"  {sec:10s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Sector+Vol (D+E-vol) 레짐별")
    for r in ("strong", "neutral", "weak"):
        sub = [p for p in sector_vol_picks if p.get("regime") == r]
        s = summarize(sub)
        print(f"  {r:8s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    print("\n[breakdown] Sector+Vol-N (D+E-vol-N) 레짐별")
    for r in ("strong", "neutral", "weak"):
        sub = [p for p in sector_vol_n_picks if p.get("regime") == r]
        s = summarize(sub)
        print(f"  {r:8s}: 픽 {s['n']:4d}, 승률 {s['winrate']:.1f}%, 평균 {s['avg_ret']:+.2f}%")

    # ── MD 리포트 ─────────────────────────────────────────────────────────
    lines: list[str] = [
        "# 레짐 연동 + 섹터 집중 전략 백테스트",
        "",
        f"- 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 기간: {args.start} ~ {args.end}",
        f"- 마스터 풀 {len(histories)}종목 / daily universe 상위 {args.daily_universe_size} / top_n {args.top_n}",
        f"- baseline threshold {args.threshold} / momentum threshold {args.momentum_threshold}",
        f"- weak 조건: KOSPI < {args.weak_kospi_pct:+.1f}% OR adv < {args.weak_adv_ratio:.2f}",
        f"- 손절 기준: {args.stop_loss:.1f}% (0=비활성)" if args.stop_loss > 0 else "- 손절: 비활성",
        "",
        "## 종합 결과",
        "",
        "| 시나리오 | 픽 수 | 승률 | 평균수익 | Δ픽 | Δ승률 | Δ평균 | 손절 발동 |",
        "|---|---|---|---|---|---|---|---|",
        f"| baseline (종가매매) | {base['n']} | {base['winrate']:.1f}% | {base['avg_ret']:+.2f}% | - | - | - | {n_bs}건 ({pct_bs:.1f}%) |",
    ]

    for label, s, picks_list, n_stop, pct_stop in [
        ("adaptive (D)", adaptive, adaptive_picks, n_ad, pct_ad),
        ("sector (D+E)", sector_stat_dict, sector_picks, n_sec, pct_sec),
        ("sector_base (F)", sector_base, sector_base_picks, n_sb, pct_sb),
        ("sector_vol (D+E-vol)", sector_vol, sector_vol_picks, n_sv, pct_sv),
        ("sector_vol_N (D+E-vol-N)", sector_vol_n, sector_vol_n_picks, n_svn, pct_svn),
    ]:
        d_wr = s["winrate"] - base["winrate"]
        d_avg = s["avg_ret"] - base["avg_ret"]
        d_n = s["n"] - base["n"]
        stop_col = f"{n_stop}건 ({pct_stop:.1f}%)" if args.stop_loss > 0 else "-"
        lines.append(
            f"| {label} | {s['n']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% | "
            f"{d_n:+d} | {d_wr:+.1f}pp | {d_avg:+.2f}% | {stop_col} |"
        )

    lines += [
        "",
        "## Adaptive 레짐별",
        "",
        "| 레짐 | 픽 수 | 승률 | 평균수익 |",
        "|---|---|---|---|",
    ]
    for r in ("strong", "neutral", "weak"):
        sub = [p for p in adaptive_picks if p["regime"] == r]
        s = summarize(sub)
        lines.append(f"| {r} | {s['n']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% |")

    lines += [
        "",
        "## Adaptive 전략별",
        "",
        "| 전략 | 픽 수 | 승률 | 평균수익 |",
        "|---|---|---|---|",
    ]
    for strat, s in strategy_breakdown(adaptive_picks).items():
        lines.append(f"| {strat} | {s['n']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% |")

    lines += [
        "",
        "## Sector D+E 섹터별",
        "",
        "| 섹터 | 픽 수 | 승률 | 평균수익 |",
        "|---|---|---|---|",
    ]
    for sec, s in sector_breakdown(sector_picks).items():
        lines.append(f"| {sec} | {s['n']} | {s['winrate']:.1f}% | {s['avg_ret']:+.2f}% |")

    md = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"\n[저장] {args.out}")
    else:
        print("\n" + md)

    # ── CSV ────────────────────────────────────────────────────────────────
    if args.csv_dir:
        import csv
        args.csv_dir.mkdir(parents=True, exist_ok=True)
        for label, picks in [
            ("adaptive", adaptive_picks),
            ("sector", sector_picks),
            ("sector_base", sector_base_picks),
            ("sector_vol", sector_vol_picks),
            ("sector_vol_N", sector_vol_n_picks),
        ]:
            path = args.csv_dir / f"picks_{label}.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "code", "name", "score", "regime", "strategy", "sector", "exit_type", "ret_pct"])
                for pk in sorted(picks, key=lambda x: (x["date"], -x["score"])):
                    w.writerow([
                        pk["date"], pk["code"], name_by_code.get(pk["code"], ""),
                        f"{pk['score']:.2f}", pk["regime"], pk.get("strategy", ""),
                        pk.get("sector", ""), pk.get("exit_type", "open"), f"{pk['ret']:.4f}",
                    ])
            print(f"[저장] {path} ({len(picks)}건)")

    # ── HTML ───────────────────────────────────────────────────────────────
    if args.html:
        html = render_html(
            args, base, adaptive, sector_stat_dict,
            sector_base, sector_vol, sector_vol_n,
            name_by_code,
            base_picks, adaptive_picks, sector_picks,
            sector_base_picks, sector_vol_picks, sector_vol_n_picks,
        )
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(html, encoding="utf-8")
        print(f"[저장] {args.html}")


if __name__ == "__main__":
    main()
