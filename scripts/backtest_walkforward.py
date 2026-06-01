"""비용 포함 워크포워드 백테스트 — 과적합 없는 OOS 성과 추정.

기존 backtest_dynamic.py 의 한계 3가지를 보완한다:
  1. 거래비용 미반영        → 매도세 + 수수료 + 슬리피지(시장가 2회) 차감
  2. 단순 시초가 청산        → 라이브(P1)와 동일한 모델:
                              09:00 시초 부분청산(녹색이면 33%) + 15:10 잔량 강제청산,
                              장중 -STOP% 손절(저가가 손절가 이탈 시)
  3. 인샘플 그리드서치(과적합) → 워크포워드: train 구간에서 파라미터 선택 →
                              바로 다음 test 구간에서만 평가. 모든 fold 의 test(OOS)
                              결과를 풀링해 "본 적 없는 구간"의 순(net) 성과를 보고.

데이터 파이프라인(유니버스/OHLCV/거래대금 top50/MA20·갭 필터)은 backtest_dynamic 재사용.

사용법:
  python scripts/backtest_walkforward.py --start 2025-11-01 --end 2026-05-09
  python scripts/backtest_walkforward.py --gap-mode live --train-days 60 --test-days 20
  python scripts/backtest_walkforward.py --slippage-bps 15   # 슬리피지 가정 상향

비용 가정(편도, bps; 1bp=0.01%):
  --tax-bps       매도세 (기본 18 = 0.18%, 매도 1회만)
  --fee-bps       위탁수수료 (기본 1.5, 매수+매도 각 1회)
  --slippage-bps  시장가 슬리피지 (기본 10, 매수+매도 각 1회)
  기본 왕복 ≈ 0.18 + 1.5*2/100 + 10*2/100 = 약 0.41%
"""
from __future__ import annotations

import argparse
import statistics
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))   # backtest_dynamic 동일 디렉터리 import
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    import FinanceDataReader as fdr

# 데이터 로더 재사용 (동적 유니버스·OHLCV 캐시·필터)
from backtest_dynamic import (  # noqa: E402
    get_broad_universe,
    get_ohlcv,
    get_top50_by_date,
    _above_ma20,
    _gap_pct,
)
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores  # noqa: E402


# ─── 비용 모델 ──────────────────────────────────────────────────────────────

class Costs:
    """왕복 거래비용(%) — 매수 1회 + 매도(부분/강제 포함) 1회로 근사."""

    def __init__(self, tax_bps: float, fee_bps: float, slippage_bps: float):
        self.tax = tax_bps / 100.0          # 매도세 (매도 측만)
        self.fee = fee_bps / 100.0          # 편도 수수료
        self.slip = slippage_bps / 100.0    # 편도 슬리피지

    @property
    def roundtrip_pct(self) -> float:
        # 매수(수수료+슬리피지) + 매도(매도세+수수료+슬리피지)
        return self.tax + 2 * self.fee + 2 * self.slip

    def __repr__(self) -> str:
        return (f"Costs(왕복≈{self.roundtrip_pct:.3f}%  "
                f"tax={self.tax:.3f} fee={self.fee:.3f}x2 slip={self.slip:.3f}x2)")


# ─── 청산 모델 (라이브 P1과 동일) ──────────────────────────────────────────────

def realized_gross_pct(
    entry: float,
    nxt: dict,
    stop_pct: float,
) -> float:
    """익일 OHLC 로 라이브(P1) 청산을 재현한 총(gross) 수익률 %.

    09:00 ≈ 익일 open, 15:10 ≈ 익일 close 로 근사.
      - 시초가가 손절가 이하  → 전량 시초가 청산 (갭다운 손절)
      - 시초가 > 평단(녹색)   → 33% 시초가 익절, 잔여 67% 종가까지 보유
      - 그 외(0 ~ -stop%)     → 09:00 HOLD, 잔여 100% 종가까지 보유
      - 보유분은 장중 저가가 손절가 이탈 시 손절가에 청산(장중 -STOP% 손절)
    """
    o, h, l, c = nxt["open"], nxt["high"], nxt["low"], nxt["close"]
    if entry <= 0:
        return 0.0
    stop_price = entry * (1.0 + stop_pct / 100.0)
    open_ret = (o - entry) / entry * 100.0

    # 갭다운 손절: 시초가가 이미 손절가 이하 → 전량 시초가 청산
    if o <= stop_price:
        return open_ret

    if o > entry:           # 시초 녹색 → 33% 익절
        realized = 0.33 * open_ret
        rem = 0.67
    else:                   # 시초 약보합 → HOLD
        realized = 0.0
        rem = 1.0

    # 잔여분: 장중 손절 이탈 시 손절가, 아니면 종가(15:10 강제청산)
    if l <= stop_price:
        rem_ret = (stop_price - entry) / entry * 100.0
    else:
        rem_ret = (c - entry) / entry * 100.0
    return realized + rem * rem_ret


# ─── 일자별 후보 생성 (한 번만, 이후 파라미터 평가는 슬라이싱) ───────────────────

_GAP_CUT = {"strict": 4.0, "current": 8.0, "live": 2.0, "none": None}


def build_daily_candidates(
    start: str,
    end: str,
    gap_mode: str,
    stop_pct: float,
    costs: Costs,
) -> tuple[list[str], dict[str, list[dict]]]:
    """모든 영업일에 대해 (threshold/top_n 무관) 전체 채점 후보 + 순수익을 미리 계산.

    반환:
      dates_fmt: 평가 가능한 영업일(YYYY-MM-DD) 리스트 (익일 데이터 있는 날만)
      daily:     date_fmt → [{code, score, gap, gross, net}, ...]  (score 내림차순)
    """
    kospi = fdr.DataReader("^KS11", start, end)
    dates = [d.strftime("%Y%m%d") for d in kospi.index]
    print(f"기간 {start}~{end}: {len(dates)} 영업일 | gap={gap_mode} stop={stop_pct}% | {costs}")

    universe = get_broad_universe()
    broad: dict[str, list[dict]] = {}
    for idx, code in enumerate(universe, 1):
        h = get_ohlcv(code, dates[-1] if dates else end.replace("-", ""), days=200)
        if h:
            broad[code] = h
        if idx % 50 == 0:
            print(f"  유니버스 로드 {idx}/{len(universe)}")
    print(f"  → {len(broad)}종목 로드 완료")

    gap_cut = _GAP_CUT.get(gap_mode)
    daily: dict[str, list[dict]] = {}
    dates_fmt: list[str] = []

    for i, date_str in enumerate(dates[:-1]):
        if i < 1:
            continue
        date_next = dates[i + 1]
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        next_fmt = f"{date_next[:4]}-{date_next[4:6]}-{date_next[6:]}"

        top50 = get_top50_by_date(date_str, broad)
        if not top50:
            continue

        cands: list[dict] = []
        for code, _value in top50:
            full = broad.get(code, [])
            ohlcv = [c for c in full if c["date"] <= date_fmt][-95:]
            if len(ohlcv) < 21 or ohlcv[-1]["date"] != date_fmt:
                continue
            if not _above_ma20(ohlcv):
                continue
            gap = _gap_pct(ohlcv)
            if gap_cut is not None and gap >= gap_cut:
                continue

            entry = ohlcv[-1]["close"]
            nxt = next((c for c in full if c["date"] == next_fmt), None)
            if nxt is None or entry <= 0:
                continue

            score = compute_technical_scores(ohlcv).composite()
            gross = realized_gross_pct(entry, nxt, stop_pct)
            net = gross - costs.roundtrip_pct
            cands.append({"code": code, "score": score, "gap": gap,
                          "gross": gross, "net": net})

        if cands:
            cands.sort(key=lambda x: -x["score"])
            daily[date_fmt] = cands
            dates_fmt.append(date_fmt)

    print(f"  평가 가능 영업일 {len(dates_fmt)}일")
    return dates_fmt, daily


# ─── 파라미터 평가 ────────────────────────────────────────────────────────────

def pick_returns(
    daily: dict[str, list[dict]],
    dates_subset: list[str],
    threshold: float,
    top_n: int,
) -> list[float]:
    """주어진 (threshold, top_n)로 dates_subset 구간의 픽별 net 수익률 리스트."""
    out: list[float] = []
    for d in dates_subset:
        qualified = [c for c in daily.get(d, []) if c["score"] >= threshold]
        for p in qualified[:top_n]:
            out.append(p["net"])
    return out


def metrics(nets: list[float]) -> dict:
    n = len(nets)
    if n == 0:
        return {"n": 0, "win": 0.0, "avg": 0.0, "median": 0.0, "std": 0.0, "total": 0.0}
    wins = sum(1 for r in nets if r > 0)
    avg = sum(nets) / n
    return {
        "n": n,
        "win": wins / n * 100.0,
        "avg": avg,
        "median": statistics.median(nets),
        "std": statistics.pstdev(nets) if n > 1 else 0.0,
        "total": sum(nets),
    }


# ─── 워크포워드 ───────────────────────────────────────────────────────────────

THRESHOLD_GRID = [50.0, 55.0, 60.0, 65.0]
TOPN_GRID = [3, 5]
MIN_TRAIN_PICKS = 10          # train 구간 최소 픽 수 (degenerate 셀 방지)
BASELINE = (55.0, 3)          # 현 운영 기본값


def select_params(daily, train_dates) -> tuple[float, int, dict]:
    """train 구간에서 net avg 최대 (픽 수 가드) 파라미터 선택. 없으면 baseline."""
    best = None
    for thr in THRESHOLD_GRID:
        for tn in TOPN_GRID:
            m = metrics(pick_returns(daily, train_dates, thr, tn))
            if m["n"] < MIN_TRAIN_PICKS:
                continue
            key = (m["avg"], m["n"])   # net avg 우선, 동률 시 표본 많은 쪽
            if best is None or key > best[0]:
                best = (key, thr, tn, m)
    if best is None:
        return BASELINE[0], BASELINE[1], {"n": 0}
    return best[1], best[2], best[3]


def walk_forward(daily, dates_fmt, train_days, test_days):
    """rolling train→test. 각 fold 의 OOS(test) 픽을 풀링해 반환."""
    folds = []
    oos_nets: list[float] = []
    base_oos_nets: list[float] = []   # 고정 baseline 비교군

    t = train_days
    while t + test_days <= len(dates_fmt):
        train_dates = dates_fmt[t - train_days:t]
        test_dates = dates_fmt[t:t + test_days]

        thr, tn, train_m = select_params(daily, train_dates)
        test_nets = pick_returns(daily, test_dates, thr, tn)
        base_nets = pick_returns(daily, test_dates, BASELINE[0], BASELINE[1])

        oos_nets.extend(test_nets)
        base_oos_nets.extend(base_nets)
        folds.append({
            "train": (train_dates[0], train_dates[-1]),
            "test": (test_dates[0], test_dates[-1]),
            "params": (thr, tn),
            "train_m": train_m,
            "test_m": metrics(test_nets),
        })
        t += test_days

    return folds, oos_nets, base_oos_nets


# ─── 리포트 ───────────────────────────────────────────────────────────────────

def _fmt_m(m: dict) -> str:
    if m["n"] == 0:
        return "픽 0"
    return (f"{m['n']:>4}건  승률 {m['win']:>5.1f}%  net평균 {m['avg']:>+5.2f}%  "
            f"중앙 {m['median']:>+5.2f}%  표준편차 {m['std']:>4.2f}  누적 {m['total']:>+6.1f}%")


def report(folds, oos_nets, base_oos_nets) -> None:
    print("\n" + "=" * 78)
    print("워크포워드 fold별 결과 (train 구간 선택 파라미터 → test 구간 OOS 성과)")
    print("=" * 78)
    for f in folds:
        thr, tn = f["params"]
        print(f"\n[{f['test'][0]} ~ {f['test'][1]}]  선택 thr={thr:.0f} top_n={tn} "
              f"(train {f['train'][0]}~{f['train'][1]})")
        print(f"   train: {_fmt_m(f['train_m'])}")
        print(f"   test : {_fmt_m(f['test_m'])}")

    print("\n" + "=" * 78)
    print("풀링 OOS (모든 fold test 구간 합산) — 비용 차감 후 정직한 추정")
    print("=" * 78)
    print(f"  워크포워드(적응형 파라미터): {_fmt_m(metrics(oos_nets))}")
    print(f"  고정 baseline thr=55 top_n=3 : {_fmt_m(metrics(base_oos_nets))}")
    wf, bs = metrics(oos_nets), metrics(base_oos_nets)
    if wf["n"] and bs["n"]:
        print(f"\n  → 적응형이 baseline 대비 net평균 {wf['avg'] - bs['avg']:+.2f}%p, "
              f"승률 {wf['win'] - bs['win']:+.1f}%p")
    print("\n주의: 단일 시초/종가 청산을 일봉으로 근사 — 실거래 슬리피지/체결은 다를 수 있음.")


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--start", default="2025-11-01")
    p.add_argument("--end", default="2026-05-09")
    p.add_argument("--gap-mode", choices=["strict", "current", "live", "none"], default="live")
    p.add_argument("--stop-pct", type=float, default=-2.0)
    p.add_argument("--train-days", type=int, default=60)
    p.add_argument("--test-days", type=int, default=20)
    p.add_argument("--tax-bps", type=float, default=18.0)
    p.add_argument("--fee-bps", type=float, default=1.5)
    p.add_argument("--slippage-bps", type=float, default=10.0)
    args = p.parse_args()

    costs = Costs(args.tax_bps, args.fee_bps, args.slippage_bps)
    dates_fmt, daily = build_daily_candidates(
        args.start, args.end, args.gap_mode, args.stop_pct, costs,
    )
    if len(dates_fmt) < args.train_days + args.test_days:
        print(f"\n영업일 부족: {len(dates_fmt)}일 < train({args.train_days})+test({args.test_days}). "
              f"--train-days/--test-days 를 줄이거나 기간을 늘리세요.")
        return
    folds, oos, base = walk_forward(daily, dates_fmt, args.train_days, args.test_days)
    report(folds, oos, base)


if __name__ == "__main__":
    main()
