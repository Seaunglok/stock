"""리그 5세대 — '방어 자산 현금 자리' (2026-10-22, 사전 선언).

부모 G4a(4세대): I3 의 남는 돈을 TSMOM 4자산에 → 강세장 15.6→21.0%·연 16.0% (강점) 이지만 MDD 22% (약점: 현금 자리에
나스닥 = 주식 위험이 들어가 I3 의 이탈이 무의미해짐). → 강점(현금 자리 활용)은 잇고, 약점(주식)만 뺀다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  D5a 방어 추세  KODEX200 비중 = I3 그대로(예산은 계좌 전체). 남는 (1−w) 는 **국고채10년·금·달러** 중 12개월 수익 > 0 인
                 것에 1/3 씩(lab_classics.tsmom 그대로, 나머지는 현금). 월말 갱신.
  D5b 방어 고정  남는 (1−w) 를 국고채10년·금·달러에 **항상 1/3 씩**(월말 재조정) — 추세 필터가 의미 있는지 대조.
  입장 조건(4세대와 같다, 전부): E1 학습 MDD ≤ 20% · 최악연도 ≥ −10%
                    G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p)
                    G3 미공개 ≥ I3 − 1%p
  통과하면 2026-10-23 등록(10월 신규 상한 3, 정원 20).
같이 보고만 하는 것: 강세장·2026-06 급락 구간.
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
import lab_gen4 as G4  # noqa: E402
import lab_holdout as H  # noqa: E402

DEF3 = ("148070", "132030", "138230")          # 국고채10년 · 금 · 달러
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH


def static_defensive(ends: set[str], assets: tuple[str, ...] = DEF3):
    """월말마다 방어 자산 동일가중(1/3) — tsmom 과 같은 모양의 target(i, d)."""
    def t(i, d):
        if d not in ends and i != 0:
            return None
        return {a: 1.0 / len(assets) for a in assets}
    return t


def combine(kodex, ks, sleeve):
    """I3(KODEX200) × 현금 자리 슬리브 — lab_gen4.g4a_target 과 같은 결합(슬리브만 바꿀 수 있게)."""
    i3 = H.i3(kodex, ks, BASE, CASH, *H.I3_DEFAULT)
    st = {"w": None, "sl": {}}

    def target(i, d, nav):
        r1, r2 = i3(i, d, nav), sleeve(i, d)
        if r1 is not None:
            st["w"] = r1.get(BASE, 0.0)
        if r2 is not None:
            st["sl"] = r2
        if (r1 is None and r2 is None) or st["w"] is None:
            return None
        w = st["w"]
        out = {BASE: w} if w > 0 else {}
        for a, x in st["sl"].items():
            out[a] = out.get(a, 0.0) + (1 - w) * x
        rest = 1.0 - sum(out.values())
        if rest > 1e-9:
            out[CASH] = rest
        return out
    return target


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = L.load_bars(BASE, "2014-01-01", END)
    c = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    px = {a: L.load_bars(a, "2010-01-01", END) for a in DEF3}
    dates = [d for d in L.calendar(k, L.FULL[0], END) if d in c]
    ends = C.month_ends(sorted(k))
    assets = {BASE: L.Asset(BASE, k), CASH: L.Asset(CASH, c), **{a: L.Asset(a, px[a]) for a in DEF3}}
    runs = {
        "I3": L.simulate({BASE: L.Asset(BASE, k), CASH: L.Asset(CASH, c)}, dates,
                         H.i3(k, ks, BASE, CASH, *H.I3_DEFAULT), EQUITY, pass_nav=True),
        "D5a": L.simulate(assets, dates, combine(k, ks, C.tsmom(px, ends)), EQUITY, pass_nav=True),
        "D5b": L.simulate(assets, dates, combine(k, ks, static_defensive(ends)), EQUITY, pass_nav=True),
    }
    R = {n: G4.spans(r) for n, r in runs.items()}
    print("=" * 104)
    print(f"5세대 방어 현금 자리 — 2015-07~2026-08, 예탁 {EQUITY:,.0f}원 (부모 G4a: 15.99%·MDD 22.0%·강세장 21.0%)")
    print(f"  {'':6}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}{'매매':>6}")
    for n, r in R.items():
        print(f"  {n:6}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['사례']['total']:>+8.1f}%{runs[n].trades:>6}")
    ref = R["I3"]
    for n in ("D5a", "D5b"):
        r = R[n]
        e1 = r["전체"]["mdd"] <= L.MAX_MDD_PCT and r["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT
        g2 = ((r["전체"]["mdd"] <= ref["전체"]["mdd"] - G4.G2_MDD_CUT and r["전체"]["cagr"] >= ref["전체"]["cagr"] - G4.G2_CAGR_TOL)
              or (r["전체"]["cagr"] >= ref["전체"]["cagr"] + G4.G2_CAGR_UP and r["전체"]["mdd"] <= ref["전체"]["mdd"] + G4.G2_MDD_TOL))
        g3 = r["미공개"]["total"] >= ref["미공개"]["total"] - G4.HO_TOL
        print(f"  {n}: E1{'O' if e1 else 'X'} · G2{'O' if g2 else 'X'} · G3{'O' if g3 else 'X'} → "
              f"{'리그 입장' if e1 and g2 and g3 else '탈락'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
