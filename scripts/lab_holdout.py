"""I3(I1 수익 엔진 + 낙폭 예산 + 회복 장치) 선언 · 미공개 2개월 검증 (2026-10-22 선언, 측정 전).

5차 결과: I1a(재진입 확인)는 지수 수익에 낙폭 절반이지만 장기 MDD 48.9%(누적 손실), I2a(낙폭 예산)는
제1원칙을 구조적으로 지켰지만 바닥에 닿은 뒤 28년 중 99% 의 날 현금 고착. 둘을 합치고 회복 장치를 단다.

I3 선언 (설계·격자는 2026-08-24 까지의 데이터로만 판정한다)
----------------------------------------------------------
엔진: I1a 기본값 그대로(진입 후 최고 대비 −10% 이탈 · 직전 20일 고점 돌파 + KOSPI>MA120 재진입).
낙폭 예산: 바닥선 F = (1 − 18%) × **최근 L영업일** 자기 자산 최고치, 비중 e = min(1, m × (자산−F)/자산).
  '최근 L일 최고치' 가 회복 장치다 — 전체 최고치를 쓰면(I2) 한 번 바닥에 닿은 뒤 영원히 현금이다.
  L일이 지나면 기준 최고치가 내려와 다시 위험을 질 수 있다(대가: L일보다 긴 하락에선 낙폭이 18% 를 넘을 수 있다).
최종 비중 = 엔진이 보유 신호일 때 e, 아니면 0. 나머지 단기채권 ETF. 10%p 이상 벌어지거나 엔진 신호가
바뀔 때만 매매. 격자 m ∈ {4, 6, 8} × L ∈ {126, 252, 504}, 기본 (6, 252).
판정(학습 구간): strategy_lab 잣대 + 장기 스트레스(1998~).

미공개 구간 검증 (strategy_lab.HOLDOUT = 2026-08-25 ~ 10-21)
-----------------------------------------------------------
대상(측정 전 고정): **I1a 기본값, I3 기본값.** 참고로 I2a 기본값·KODEX200 도 같이 적는다.
각 전략은 2015-07-28 부터 끊김 없이 돌려(포지션을 들고 들어간다) 미공개 구간만 잘라 잰다.
  HO① 구간 수익 ≥ KODEX200 구간 수익
  HO② 구간 MDD ≤ KODEX200 구간 MDD 의 절반
  HO③ 구간 수익 ≥ −10%
채택 경로: 학습 구간 잣대 **그리고** 미공개 HO①~③ 를 모두 통과해야 실전 후보. 학습 잣대는 못 넘고
미공개만 통과하면 '참고' 로만 보고한다(운용자 판단).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_dd_control as I  # noqa: E402

EQUITY = 3_852_844.0
CASH_ETF = "153130"
I3_GRID = tuple((m, lb) for m in (4, 6, 8) for lb in (126, 252, 504))
I3_DEFAULT = (6, 252)
I3_FLOOR_DD = 18.0
I3_BAND = 0.10
EXT_END = L.HOLDOUT[1]


def i3(bars: dict, kospi: dict, asset: str, cash: str | None, m: float, lookback: int,
       x_pct: float = 10, n: int = 20, floor_dd: float = I3_FLOOR_DD, band: float = I3_BAND):
    """target(i, d, nav) — I1a 엔진 신호 × 최근 lookback 일 최고치 기준 낙폭 예산."""
    engine = I.reentry_confirmed(bars, kospi, asset, x_pct, n, cash)
    st: dict = {"in": True, "navs": [], "w": None}

    def target(i: int, d: str, nav: float):
        sig = engine(i, d)
        if sig is not None:
            st["in"] = asset in sig
        st["navs"].append(nav)
        peak = max(st["navs"][-lookback:])
        floor = (1 - floor_dd / 100.0) * peak
        e = min(1.0, max(0.0, m * (nav - floor) / nav)) if nav > 0 else 0.0
        w = e if st["in"] else 0.0
        if (st["w"] is not None and sig is None and abs(w - st["w"]) < band
                and not (w == 0.0 and st["w"] > 0)):
            return None
        st["w"] = w
        out = {asset: w} if w > 0 else {}
        if cash and w < 1.0:
            out[cash] = 1.0 - w
        return out
    return target


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars("069500", "2014-01-01", EXT_END)
    cash = L.load_bars(CASH_ETF, "2014-01-01", EXT_END)
    ks = L.load_bars("^KS11", "1996-01-01", EXT_END)
    dates = L.calendar(kodex, *L.FULL)
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    bench = L.buy_and_hold("069500", dates, kodex, EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    print(f"[학습 구간 {L.FULL[0]}~{L.FULL[1]}] 잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% "
          f"③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p ④구간별≥벤치 ⑤격자 중앙값 · 장기 ①②")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))

    def assets():
        return {"069500": L.Asset("069500", kodex), CASH_ETF: L.Asset(CASH_ETF, cash)}

    def long_assets():
        return {"IDX": L.Asset("IDX", ks)}
    train_ok = I._run_family(
        "I3 재진입 확인 + 낙폭 예산(최근 L일)", I3_GRID, I3_DEFAULT, lambda p: f"m{p[0]}·L{p[1]}",
        lambda p: i3(kodex, ks, "069500", CASH_ETF, p[0], p[1]),
        lambda p: i3(ks, ks, "IDX", None, p[0], p[1]),
        True, dates, assets, long_dates, long_assets, bench)

    # ── 미공개 구간 ──
    ext = L.calendar(kodex, L.FULL[0], EXT_END)
    ho = L.calendar(kodex, *L.HOLDOUT)
    print("=" * 100)
    print(f"[미공개 구간 {ho[0]} ~ {ho[-1]} · {len(ho)}영업일] — 2015-07-28 부터 끊김 없이 돌려 이 구간만 잘라 잼")
    bres = L.buy_and_hold("069500", ext, kodex, EQUITY)
    bm = L.slice_metrics(bres, *L.HOLDOUT)
    print(f"  {'전략':30}{'구간수익':>9}{'구간MDD':>9}   판정")
    print(f"  {'KODEX200 단순보유':30}{bm['total']:>+8.1f}%{bm['mdd']:>8.1f}%")
    runs = {
        "I1a 재진입 확인(기본)": (L.simulate(assets(), ext, I.reentry_confirmed(kodex, ks, "069500", 10, 20, CASH_ETF),
                                         EQUITY), True),
        "I3 기본(m6·L252)": (L.simulate(assets(), ext, i3(kodex, ks, "069500", CASH_ETF, *I3_DEFAULT), EQUITY,
                                       pass_nav=True), True),
        "[참고] I2a 낙폭 예산(m5)": (L.simulate(assets(), ext, I.drawdown_budget("069500", 5, CASH_ETF), EQUITY,
                                            pass_nav=True), False),
    }
    ho_ok = {}
    for label, (res, declared) in runs.items():
        sm = L.slice_metrics(res, *L.HOLDOUT)
        rows = L.judge_holdout(sm, bm)
        ok = L.passed(rows)
        if declared:
            ho_ok[label] = ok
        print(f"  {label:30}{sm['total']:>+8.1f}%{sm['mdd']:>8.1f}%   {'통과' if ok else '미달'}")
        for nm, good, txt in rows:
            print(f"      [{'O' if good else 'X'}] {nm}: {txt}")
    print("=" * 100)
    print(f"최종: I3 학습 잣대 {'통과' if train_ok else '기각'} · 미공개 " +
          " · ".join(f"{k} {'통과' if v else '미달'}" for k, v in ho_ok.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
