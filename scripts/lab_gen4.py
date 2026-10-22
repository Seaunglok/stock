"""리그 4세대·기초지수 — 개선 백로그 P2 ④⑤ (2026-10-22, 사전 선언).

운용자(10-22): "남은 일 중 P2 도 진행해줘."

④ I3 × TSMOM — 강점 결합. I3 의 수익(학습 12.6%)과 TSMOM 의 분산(MDD 13.4%, 제1원칙 통과). 근거: 갭 위험은 매도 시각으로
   못 막고 분산으로만 줄었다(S1), I3 는 평균 39% 를 현금(머니마켓)으로 둔다.
   G4a  KODEX200 비중 = I3 그대로(엔진 × 낙폭 예산 — 예산은 **계좌 전체** 자산으로). 남는 (1−w) 는 머니마켓 대신
        **TSMOM 4자산**(나스닥100·국고채10년·금·달러, 각자 12개월 수익 > 0 이면 1/4, 아니면 현금). KODEX200 은 I3 가
        이미 판단하므로 바스켓에서 뺀다(I3 이탈 때 다시 사지 않게). TSMOM 은 월말, I3 는 자기 규칙대로 바뀐다.
   G4b  I3 절반 + TSMOM(5자산, lab_classics 그대로) 절반 — 각자 운용, 재조정 없음(한미반반과 같은 방식).
   입장 조건(전부): E1 학습 MDD ≤ 20% · 최악연도 ≥ −10%
                    G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p)
                    G3 미공개 ≥ I3 − 1%p
⑤ R6 × KRX300 — ETF 스크린 2군(강세장 +0.5~2.8%p)의 관찰 후보. KODEX KRX300(292190, 2018-09 상장 — 규모 최대,
   **거래대금은 하루 1천만원대로 작다**). 재진입 추세 확인은 KOSPI>MA120 그대로. 박스권 이력이 없어 **강세장 구간만**.
   I3·R6 를 KODEX200·KRX300 각각에(2×2) — 기초지수 효과와 R6 효과를 나눠 본다.
   입장 조건(전부): E1 강세장 구간 MDD ≤ 20% · 최악연도 ≥ −10% · K2 강세장 연수익 ≥ I3(KODEX200) + 1%p · G3 미공개.
   (구간이 짧아 통과해도 리그 입장까지만 — 판정은 실전 데이터.)
공통: 예탁 364만원, 현금 153130(이력), 비용은 하니스 그대로. 통과한 후보는 2026-10-23 등록(10월 신규 상한 3).
같이 보고만 하는 것: 2026-06 급락 구간 손실.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_classics as C  # noqa: E402
import lab_challengers as CH  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH, KRX300 = "069500", "153130", "292190"
TS4 = ("133690", "148070", "132030", "138230")
EPISODE = ("2026-05-29", "2026-06-30")
G2_MDD_CUT, G2_CAGR_TOL, G2_CAGR_UP, G2_MDD_TOL = 2.0, 0.5, 1.0, 0.5
K2_BULL_UP = 1.0
HO_TOL = 1.0


def g4a_target(kodex, ks, px_ts: dict, ends: set[str]):
    """I3(KODEX200) × TSMOM 4자산 현금 자리. target(i, d, nav)."""
    i3 = H.i3(kodex, ks, BASE, CASH, *H.I3_DEFAULT)
    ts = C.tsmom(px_ts, ends)
    st = {"w": None, "ts": {}}

    def target(i, d, nav):
        r1 = i3(i, d, nav)
        r2 = ts(i, d)
        if r1 is not None:
            st["w"] = r1.get(BASE, 0.0)
        if r2 is not None:
            st["ts"] = r2
        if (r1 is None and r2 is None) or st["w"] is None:
            return None
        w = st["w"]
        out = {BASE: w} if w > 0 else {}
        for a, x in st["ts"].items():
            out[a] = out.get(a, 0.0) + (1 - w) * x
        rest = 1.0 - sum(out.values())
        if rest > 1e-9:
            out[CASH] = rest
        return out
    return target


def spans(r: L.SimResult) -> dict:
    return {"전체": L.slice_metrics(r, *L.FULL), "박스권": L.slice_metrics(r, *L.PERIODS["박스권"]),
            "강세장": L.slice_metrics(r, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(r, *L.HOLDOUT),
            "사례": L.slice_metrics(r, *EPISODE)}


def add_curves(a: L.SimResult, b: L.SimResult) -> L.SimResult:
    bm = dict(zip(b.dates, b.curve))
    out = L.SimResult()
    for d, v in zip(a.dates, a.curve):
        if d in bm:
            out.dates.append(d)
            out.curve.append(v + bm[d])
    out.trades = a.trades + b.trades
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = L.load_bars(BASE, "2014-01-01", END)
    c = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    ts_px = {a: L.load_bars(a, "2010-01-01", END) for a in (BASE, *TS4)}
    x3 = L.load_bars(KRX300, "2014-01-01", END)
    dates = [d for d in L.calendar(k, L.FULL[0], END) if d in c]
    ends = C.month_ends(sorted(k))
    sim = lambda assets, t, eq=EQUITY: L.simulate(assets, dates, t, eq, pass_nav=True)  # noqa: E731

    i3 = sim({BASE: L.Asset(BASE, k), CASH: L.Asset(CASH, c)}, H.i3(k, ks, BASE, CASH, *H.I3_DEFAULT))
    g4a = sim({BASE: L.Asset(BASE, k), CASH: L.Asset(CASH, c), **{a: L.Asset(a, ts_px[a]) for a in TS4}},
              g4a_target(k, ks, {a: ts_px[a] for a in TS4}, ends))
    half_i3 = sim({BASE: L.Asset(BASE, k), CASH: L.Asset(CASH, c)}, H.i3(k, ks, BASE, CASH, *H.I3_DEFAULT), EQUITY / 2)
    ts5 = C.tsmom({a: ts_px[a] for a in (BASE, *TS4)}, ends)

    def ts5_t(i, d, nav):
        r = ts5(i, d)
        if r is None:
            return None
        out = dict(r)
        rest = 1.0 - sum(out.values())
        if rest > 1e-9:
            out[CASH] = rest
        return out
    half_ts = sim({**{a: L.Asset(a, ts_px[a]) for a in (BASE, *TS4)}, CASH: L.Asset(CASH, c)}, ts5_t, EQUITY / 2)
    g4b = add_curves(half_i3, half_ts)
    R = {"I3": spans(i3), "G4a": spans(g4a), "G4b": spans(g4b)}
    T = {"I3": i3.trades, "G4a": g4a.trades, "G4b": g4b.trades}

    # ⑤ 2×2 — 강세장 구간(KRX300 이력: 2018-09~)
    xdates = [d for d in L.calendar(k, "2018-10-01", END) if d in c and d in x3]
    def run_on(bars, code, spec):
        return L.simulate({code: L.Asset(code, bars), CASH: L.Asset(CASH, c)}, xdates,
                          CH.i3x(bars, ks, code, CASH, *H.I3_DEFAULT, **spec), EQUITY, pass_nav=True)
    X = {f"{nm}·{lbl}": spans(run_on(b, code, CH.SPECS[nm]))
         for nm in ("I3", "R6") for lbl, b, code in (("KODEX200", k, BASE), ("KRX300", x3, KRX300))}

    print("=" * 112)
    print(f"④ I3 × TSMOM — 2015-07~2026-08, 예탁 {EQUITY:,.0f}원")
    print(f"  {'':6}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}{'매매':>6}")
    for n, r in R.items():
        print(f"  {n:6}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['사례']['total']:>+8.1f}%{T[n]:>6}")
    ref = R["I3"]
    for n in ("G4a", "G4b"):
        r = R[n]
        e1 = r["전체"]["mdd"] <= L.MAX_MDD_PCT and r["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT
        g2 = ((r["전체"]["mdd"] <= ref["전체"]["mdd"] - G2_MDD_CUT and r["전체"]["cagr"] >= ref["전체"]["cagr"] - G2_CAGR_TOL)
              or (r["전체"]["cagr"] >= ref["전체"]["cagr"] + G2_CAGR_UP and r["전체"]["mdd"] <= ref["전체"]["mdd"] + G2_MDD_TOL))
        g3 = r["미공개"]["total"] >= ref["미공개"]["total"] - HO_TOL
        print(f"  {n}: E1{'O' if e1 else 'X'} · G2{'O' if g2 else 'X'} · G3{'O' if g3 else 'X'} → "
              f"{'리그 입장' if e1 and g2 and g3 else '탈락'}")
    print("=" * 112)
    print("⑤ 기초지수 × 재진입 — 강세장 2019-01~2026-08 (KRX300 2018-09 상장)")
    print(f"  {'':16}{'강세장':>8}{'MDD':>7}{'최악':>7}{'미공개':>8}{'6월 사례':>9}")
    for n, r in X.items():
        print(f"  {n:16}{r['강세장']['cagr']:>7.2f}%{r['강세장']['mdd']:>6.1f}%{r['강세장']['worst_year']:>+6.1f}%"
              f"{r['미공개']['total']:>+7.1f}%{r['사례']['total']:>+8.1f}%")
    xref = X["I3·KODEX200"]
    for n in ("I3·KRX300", "R6·KRX300"):
        r = X[n]
        e1 = r["강세장"]["mdd"] <= L.MAX_MDD_PCT and r["강세장"]["worst_year"] >= L.MIN_YEAR_RET_PCT
        k2 = r["강세장"]["cagr"] >= xref["강세장"]["cagr"] + K2_BULL_UP
        g3 = r["미공개"]["total"] >= xref["미공개"]["total"] - HO_TOL
        print(f"  {n}: E1{'O' if e1 else 'X'} · K2{'O' if k2 else 'X'} · G3{'O' if g3 else 'X'} → "
              f"{'리그 입장' if e1 and k2 and g3 else '탈락'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
