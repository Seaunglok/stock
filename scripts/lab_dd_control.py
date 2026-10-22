"""낙폭 통제 2종 — 재진입 확인 강화(I1) · 낙폭 예산(I2) (2026-10-22 선언, 측정 전).

H1·H2 결과(docs/2026-10-22-lab-criteria-declaration.md 4차): −5% 에서 빠져도 MDD 40.3% 였다.
이탈은 됐지만 하락장 반등마다 재진입했다가 또 잘려 손실이 쌓였다(왕복 21회 중 손실 14회).
그래서 두 갈래로 고친다.

I1 재진입 확인 강화
  H 와 같은 이탈(진입 후 최고 대비 −X%) + 재진입은 '직전 n일 최고 돌파' **그리고 KOSPI 종가 >
  KOSPI MA120**(장기 상승 추세가 살아 있을 때만). 하락장 반등에 다시 들어가는 것을 막는다.
  격자 X ∈ {5, 10, 15}% × n ∈ {10, 20, 40}, 기본 (10, 20).  I1a KODEX200 · I1b 레버리지.

I2 낙폭 예산 (Grossman-Zhou 1993 낙폭 통제 / TIPP)
  전략 자기 자산의 최고치 대비 바닥선 F = (1 − D)·최고치, D = 18%(제1원칙 20% 에 갭 여유 2%p).
  위험자산 비중 e = min(1, m × (자산 − F) / 자산). 낙폭이 커질수록 비중이 자동으로 줄고, 바닥에
  닿으면 0 — **구조적으로** 최대 낙폭이 D 근처에서 멈춘다(갭 하락만큼 넘을 수 있음). 나머지는
  단기채권 ETF. 목표 비중과 현재 비중이 10%p 이상 벌어질 때만 매매(잦은 매매 방지).
  알려진 약점: 바닥에 닿으면 비중이 0 근처라 회복이 매우 느리다(현금 고착) — 측정한다.
  격자 m ∈ {2, 3, 5, 8}, 기본 5.  I2a KODEX200 · I2b 레버리지.

판정: strategy_lab 잣대(기본값 ①~④ + 격자 중앙값 ①~④) + 장기 스트레스(1998~, 격자 중앙값 ①②).
장기는 KODEX200 → ^KS11, 레버리지 → ^KS11 2배 합성(보수 연 0.64%), 현금 이자 0.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402

EQUITY = 3_852_844.0
CASH_ETF = "153130"
I1_GRID = tuple((x, n) for x in (5, 10, 15) for n in (10, 20, 40))
I1_DEFAULT = (10, 20)
I1_REGIME_MA = 120
I2_GRID = (2, 3, 5, 8)
I2_DEFAULT = 5
I2_FLOOR_DD = 18.0
I2_BAND = 0.10
LONG_STRESS = ("1998-01-02", "2026-08-24")


def reentry_confirmed(bars: dict[str, dict], kospi: dict[str, dict], asset: str,
                      x_pct: float, n: int, cash: str | None, regime_ma: int = I1_REGIME_MA):
    """I1 — 이탈은 H 와 같고, 재진입은 n일 고점 돌파 **그리고** KOSPI > MA(regime_ma). 그날까지의 값만."""
    days = sorted(bars)
    pos = {d: k for k, d in enumerate(days)}
    closes = [bars[d]["close"] for d in days]
    kdays = sorted(kospi)
    kpos = {d: k for k, d in enumerate(kdays)}
    kcl = [kospi[d]["close"] for d in kdays]
    out_w = {cash: 1.0} if cash else {}
    st = {"in": True, "peak": None, "started": False}

    def regime_up(d: str) -> bool:
        k = kpos.get(d)
        if k is None or k + 1 < regime_ma:
            return False
        return kcl[k] > sum(kcl[k + 1 - regime_ma:k + 1]) / regime_ma

    def target(i: int, d: str):
        k = pos.get(d)
        if k is None:
            return None
        c = closes[k]
        if not st["started"]:
            st["started"], st["peak"] = True, c
            return {asset: 1.0}
        if st["in"]:
            st["peak"] = max(st["peak"], c)
            if c <= st["peak"] * (1 - x_pct / 100.0):
                st["in"] = False
                return out_w
            return None
        if k >= n and c > max(closes[k - n:k]) and regime_up(d):
            st["in"], st["peak"] = True, c
            return {asset: 1.0}
        return None
    return target


def drawdown_budget(asset: str, m: float, cash: str | None,
                    floor_dd: float = I2_FLOOR_DD, band: float = I2_BAND):
    """I2 — target(i, d, nav). 자기 자산 최고치 대비 바닥선까지의 쿠션 × m 이 위험자산 비중."""
    st = {"peak": 0.0, "e": None}

    def target(i: int, d: str, nav: float):
        st["peak"] = max(st["peak"], nav)
        floor = (1 - floor_dd / 100.0) * st["peak"]
        e = min(1.0, max(0.0, m * (nav - floor) / nav)) if nav > 0 else 0.0
        if st["e"] is not None and abs(e - st["e"]) < band and not (e == 0.0 and st["e"] > 0):
            return None
        st["e"] = e
        w = {asset: e} if e > 0 else {}
        if cash and e < 1.0:
            w[cash] = 1.0 - e
        return w
    return target


def _run_family(name, grid, default, label_fn, make_main, make_long, pass_nav, dates, assets_fn,
                long_dates, long_assets_fn, bench) -> bool:
    print("=" * 100)
    print(f"[{name}]")
    print(L.HEADER + "   판정  (매매횟수)")
    evals, default_ok, res = [], False, None
    for p in grid:
        res = L.simulate(assets_fn(), dates, make_main(p), EQUITY, pass_nav=pass_nav)
        s, _, rows = L.evaluate(res, bench)
        evals.append(s)
        ok = L.passed(rows)
        if p == default:
            default_ok = ok
        print(L.fmt_row(("◆" if p == default else " ") + label_fn(p), s) + f"   {'통과' if ok else '미달'}  ({res.trades})")
    _, b, _ = L.evaluate(res, bench)
    med = L.robustness(evals)
    med_rows = L.judge(med, b)
    print(L.fmt_row(" 격자 중앙값", med) + f"   {'통과' if L.passed(med_rows) else '미달'}")
    for nm, ok, txt in med_rows:
        print(f"      [{'O' if ok else 'X'}] {nm}: {txt}")
    lm = []
    for p in grid:
        r = L.simulate(long_assets_fn(), long_dates, make_long(p), 0.0, pass_nav=pass_nav)
        lm.append((p, L.metrics(r.dates, r.curve)))
    med_long = {"mdd": statistics.median(m_["mdd"] for _, m_ in lm),
                "worst_year": statistics.median(m_["worst_year"] for _, m_ in lm)}
    long_rows = L.judge_long(med_long)
    print(f"  장기 스트레스 {long_dates[0]}~{long_dates[-1]} (CAGR / MDD / 최악연도):  "
          + " · ".join(f"{label_fn(p)} {m_['cagr']:+.1f}%/{m_['mdd']:.0f}%/{m_['worst_year']:+.0f}%" for p, m_ in lm))
    for nm, ok, txt in long_rows:
        print(f"      [{'O' if ok else 'X'}] 중앙값 {nm}: {txt}")
    verdict = default_ok and L.passed(med_rows) and L.passed(long_rows)
    print(f"  → {name}: {'채택 가능' if verdict else '기각'} (기본값 {'O' if default_ok else 'X'} · "
          f"격자 중앙값 {'O' if L.passed(med_rows) else 'X'} · 장기 {'O' if L.passed(long_rows) else 'X'})")
    return verdict


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars("069500", "2014-01-01", L.FULL[1])
    lev = L.load_bars("122630", "2014-01-01", L.FULL[1])
    cash = L.load_bars(CASH_ETF, "2014-01-01", L.FULL[1])
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    ks2 = L.leveraged_bars(ks)
    dates = L.calendar(kodex, *L.FULL)
    long_dates = L.calendar(ks, *LONG_STRESS)
    bench = L.buy_and_hold("069500", dates, kodex, EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    print(f"잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% ③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p "
          f"④박스권·강세장 각각 ≥벤치 ⑤격자 중앙값 · 장기 ①② · 예탁 {EQUITY:,.0f}원")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))
    verdicts = {}
    for tag, code, bars, long_bars in (("a KODEX200", "069500", kodex, ks), ("b 레버리지", "122630", lev, ks2)):
        def assets(code=code, bars=bars):
            return {code: L.Asset(code, bars), CASH_ETF: L.Asset(CASH_ETF, cash)}

        def long_assets(long_bars=long_bars):
            return {"IDX": L.Asset("IDX", long_bars)}
        verdicts[f"I1{tag}"] = _run_family(
            f"I1{tag} 재진입 확인 강화", I1_GRID, I1_DEFAULT, lambda p: f"X{p[0]}%·n{p[1]}",
            lambda p, code=code, bars=bars: reentry_confirmed(bars, ks, code, p[0], p[1], CASH_ETF),
            lambda p, long_bars=long_bars: reentry_confirmed(long_bars, ks, "IDX", p[0], p[1], None),
            False, dates, assets, long_dates, long_assets, bench)
        verdicts[f"I2{tag}"] = _run_family(
            f"I2{tag} 낙폭 예산", I2_GRID, I2_DEFAULT, lambda p: f"m{p}",
            lambda p, code=code: drawdown_budget(code, p, CASH_ETF),
            lambda p: drawdown_budget("IDX", p, None),
            True, dates, assets, long_dates, long_assets, bench)
    print("=" * 100)
    print("최종: " + " · ".join(f"{k} {'채택 가능' if v else '기각'}" for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
