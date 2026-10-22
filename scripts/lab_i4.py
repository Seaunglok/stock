"""I4 — I3 의 강세장 부진 보완 (2026-10-22 선언, 측정 전).

진단(학습 구간, 판정 아님): I3 가 강세장에서 덜 버는 이유는 ① 조정 뒤 재진입이 늦고 ② 낙폭 예산이
비중을 줄인 채 오래 둔다(2025: 엔진 보유일 83% 인데 평균 비중 63% → 69.1% 가 51.1% 로).

선언 (엔진은 I1a 기본값 그대로 — KODEX200 가격·KOSPI MA120 으로 보유/이탈 결정)
--------------------------------------------------------------------------------
I4a 레버리지 보강  위험 비중 e = min(2.0, m × 쿠션). e ≤ 1 이면 KODEX200 e, e > 1 이면
                   KODEX레버리지 (e−1) + KODEX200 (2−e) — 실효 노출 e, 비중 합 ≤ 1(차입 없음).
                   계좌가 최고점 근처일 때만 1배를 넘는다. 격자 m ∈ {8, 11, 14} × L ∈ {126, 252, 504},
                   기본 (11, 252) — m=11 이면 최고점(쿠션 18%)에서 2배.
I4b 한·미 교체     보유 신호일 때 월말마다 KODEX200 vs TIGER나스닥100 중 최근 252영업일 수익이 큰 쪽을 산다.
                   낙폭 예산은 I3 와 같다(상한 1). 격자 m ∈ {4, 6, 8} × L, 기본 (6, 252).
I4c 둘 다          I4b 의 선택이 KODEX200 일 때만 I4a 레버리지 허용(나스닥 레버리지 ETF 는 2022 상장이라
                   검증 이력이 없다). 격자·기본값은 I4a 와 같다.
매매: 실효 비중이 10%p 이상 바뀌거나, 엔진 신호·보유 자산이 바뀔 때만.

판정: strategy_lab 잣대(학습 2015-07~2026-08) + 장기 스트레스(격자 중앙값 ①②).
  장기: I4a = ^KS11 + 2배 합성(1998~), I4b·I4c = ^KS11 + 원화 환산 나스닥100(^NDX × USD/KRW, 2005~).
미공개(2026-08-25~10-21): 기본값 3종을 HO①②③ 로 본다. ⚠️ 이 구간은 I3 판정에 이미 한 번 썼다 —
  그 결과를 알고 I4 를 설계했으므로 **약한 증거**다. 최종 확인은 실전 운용에서 새로 쌓이는 데이터.
"""
from __future__ import annotations

import bisect
import statistics
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
BASE, LEV, ALT = "069500", "122630", "133690"
LEV_GRID = tuple((m, lb) for m in (8, 11, 14) for lb in (126, 252, 504))
LEV_DEFAULT = (11, 252)
ROT_GRID = tuple((m, lb) for m in (4, 6, 8) for lb in (126, 252, 504))
ROT_DEFAULT = (6, 252)
LEV_CAP = 2.0
FLOOR_DD = 18.0
BAND = 0.10
MOM_DAYS = 252
LONG_A = ("1998-01-02", "2026-08-24")
LONG_BC = ("2005-01-03", "2026-08-24")
EXT_END = L.HOLDOUT[1]


def i4(base_bars: dict, kospi: dict, m: float, lookback: int, *, lev: bool, rotate: bool,
       alt_bars: dict | None = None, base: str = BASE, lev_code: str = LEV, alt: str = ALT,
       cash: str | None = CASH_ETF):
    """target(i, d, nav). 엔진은 base 가격·KOSPI 로, 낙폭 예산은 최근 lookback 일 자기 자산 최고치로."""
    engine = I.reentry_confirmed(base_bars, kospi, base, 10, 20, cash)
    cap = LEV_CAP if lev else 1.0
    series = {base: (sorted(base_bars), [base_bars[d]["close"] for d in sorted(base_bars)])}
    if rotate and alt_bars is not None:
        series[alt] = (sorted(alt_bars), [alt_bars[d]["close"] for d in sorted(alt_bars)])
    st: dict = {"in": True, "navs": [], "w": None, "asset": base, "month": None}

    def mom(code: str, d: str) -> float | None:
        ds, cs = series[code]
        k = bisect.bisect_right(ds, d) - 1
        return cs[k] / cs[k - MOM_DAYS] - 1 if k >= MOM_DAYS and cs[k - MOM_DAYS] > 0 else None

    def target(i: int, d: str, nav: float):
        sig = engine(i, d)
        if sig is not None:
            st["in"] = base in sig
        prev_asset = st["asset"]
        if rotate and d[:7] != st["month"]:          # 월이 바뀐 첫 호출 = 직전 달 말 기준 선택
            st["month"] = d[:7]
            ma, mb = mom(base, d), mom(alt, d)
            if ma is not None and mb is not None:
                st["asset"] = alt if mb > ma else base
        st["navs"].append(nav)
        peak = max(st["navs"][-lookback:])
        floor = (1 - FLOOR_DD / 100.0) * peak
        e = min(cap, max(0.0, m * (nav - floor) / nav)) if nav > 0 else 0.0
        if not st["in"]:
            e = 0.0
        asset = st["asset"]
        if asset != base:
            e = min(e, 1.0)                           # 나스닥 레버리지 없음
        if (st["w"] is not None and sig is None and asset == prev_asset
                and abs(e - st["w"]) < BAND and not (e == 0.0 and st["w"] > 0)):
            return None
        st["w"] = e
        out: dict[str, float] = {}
        if e > 1.0:
            out[lev_code], out[asset] = e - 1.0, 2.0 - e
        elif e > 0:
            out[asset] = e
        invested = sum(out.values())
        if cash and invested < 1.0:
            out[cash] = 1.0 - invested
        return out
    return target


def krw_ndx(ks: dict) -> dict[str, dict]:
    """^NDX × USD/KRW — KOSPI 영업일에 맞춰 직전 값으로 채운 원화 환산 나스닥100(장기 스트레스용)."""
    ndx = L.load_bars("^NDX", "2003-01-01", L.FULL[1])
    fx = L.load_bars("USD/KRW", "2003-01-01", L.FULL[1])
    out, ln, lf = {}, None, None
    for d in sorted(ks):
        if d in ndx:
            ln = ndx[d]["close"]
        if d in fx:
            lf = fx[d]["close"]
        if ln and lf:
            v = ln * lf
            out[d] = {"open": v, "close": v}
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bars = {c: L.load_bars(c, "2014-01-01", EXT_END) for c in (BASE, LEV, ALT, CASH_ETF)}
    ks = L.load_bars("^KS11", "1996-01-01", EXT_END)
    ks2 = L.leveraged_bars(ks)
    ndx_krw = krw_ndx(ks)
    dates = L.calendar(bars[BASE], *L.FULL)
    bench = L.buy_and_hold(BASE, dates, bars[BASE], EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    print(f"[학습 {L.FULL[0]}~{L.FULL[1]}] 잣대: ①MDD≤20% ②최악연도≥-10% ③CAGR≥벤치+5%p ④구간별≥벤치 ⑤격자 중앙값 · 장기 ①②")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))

    def assets():
        return {c: L.Asset(c, b) for c, b in bars.items()}

    fams = (
        ("I4a 레버리지 보강", LEV_GRID, LEV_DEFAULT, dict(lev=True, rotate=False), LONG_A),
        ("I4b 한·미 교체", ROT_GRID, ROT_DEFAULT, dict(lev=False, rotate=True), LONG_BC),
        ("I4c 둘 다", LEV_GRID, LEV_DEFAULT, dict(lev=True, rotate=True), LONG_BC),
    )
    verdicts, defaults = {}, {}
    for name, grid, default, kw, long_span in fams:
        long_dates = L.calendar(ks, *long_span)
        if kw["rotate"]:
            long_assets = lambda: {"IDX": L.Asset("IDX", ks), "LEVX": L.Asset("LEVX", ks2),  # noqa: E731
                                   "ALTX": L.Asset("ALTX", ndx_krw)}
        else:
            long_assets = lambda: {"IDX": L.Asset("IDX", ks), "LEVX": L.Asset("LEVX", ks2)}  # noqa: E731
        verdicts[name] = I._run_family(
            name, grid, default, lambda p: f"m{p[0]}·L{p[1]}",
            lambda p, kw=kw: i4(bars[BASE], ks, p[0], p[1], alt_bars=bars[ALT], **kw),
            lambda p, kw=kw: i4(ks, ks, p[0], p[1], alt_bars=ndx_krw, base="IDX", lev_code="LEVX",
                                alt="ALTX", cash=None, **kw),
            True, dates, assets, long_dates, long_assets, bench)
        defaults[name] = (default, kw)

    ext = L.calendar(bars[BASE], L.FULL[0], EXT_END)
    print("=" * 100)
    print(f"[미공개 {L.HOLDOUT[0]} ~ {L.HOLDOUT[1]}] ⚠️ I3 판정에 이미 쓴 구간 — 약한 증거")
    bm = L.slice_metrics(L.buy_and_hold(BASE, ext, bars[BASE], EQUITY), *L.HOLDOUT)
    print(f"  {'전략':26}{'구간수익':>9}{'구간MDD':>9}   판정")
    print(f"  {'KODEX200 단순보유':26}{bm['total']:>+8.1f}%{bm['mdd']:>8.1f}%")
    for name, (p, kw) in defaults.items():
        res = L.simulate(assets(), ext, i4(bars[BASE], ks, p[0], p[1], alt_bars=bars[ALT], **kw), EQUITY,
                         pass_nav=True)
        sm = L.slice_metrics(res, *L.HOLDOUT)
        rows = L.judge_holdout(sm, bm)
        print(f"  {name:26}{sm['total']:>+8.1f}%{sm['mdd']:>8.1f}%   {'통과' if L.passed(rows) else '미달'}")
        for nm, ok, txt in rows:
            print(f"      [{'O' if ok else 'X'}] {nm}: {txt}")
    print("=" * 100)
    print("최종(학습 잣대): " + " · ".join(f"{k} {'통과' if v else '기각'}" for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
