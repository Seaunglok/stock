"""공격형 트랙 2세대 — 레버리지 × 낙폭 예산, 인버스 없이 (2026-10-29, 사전 선언).

부모 진단 (1세대 A 결과, lab_aggr — 판정에 안 쓴 진단을 설계의 출발점으로)
-----------------------------------------------------------------------
  강점  A3b(I3 엔진 + 레버리지 + 인버스): 연 24.9% · 박스권 16.3% — 수익은 레버리지가 만든다.
  약점  ① 인버스가 돈을 잃었다(A3 인버스 보유 685일 누적 −33%).
        ② 최대 낙폭 50.8% — 엔진 이탈(최고 대비 −10%)이 2배 상품엔 늦다(2026-06~08 급락).
  다른 부모 I3: 같은 급락을 18.5% 로 막은 건 **낙폭 예산**이다(엔진만으론 못 막는다).
  C 판정대(lab_downside)도 같은 말을 했다 — 하락 '방향'은 못 맞히고, 남는 건 '비중을 줄이는' 쪽.
  → 2세대 = 인버스를 빼고(①) 레버리지에 낙폭 예산을 씌운다(②).

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  자산: 위험 122630(KODEX 레버리지) · 현금 153130(연구 공통). 인버스 없음.
  G1  I3 엔진 × 낙폭 예산, 드는 것만 레버리지 — lab_challengers.i3x 그대로(엔진은 KODEX200·KOSPI 로 판단: 이탈 −10% ·
      재진입 20일 고점 + KOSPI>120일선). 레버리지 비중 = min(1, m × 쿠션), 쿠션 = (자산 − 바닥)/자산,
      바닥 = 최근 252일 자기 자산 최고치 × (1 − f).
  G2  낙폭 예산만(엔진 없음) — 엔진이 필요한지 가르는 대조군. 예산 식은 i3_core.budget_exposure 그대로.
  격자  m ∈ {2, 3, 4.5} × f ∈ {25, 30, 35}% (9개). 기본 (3, 30) — 둘 다 격자 가운데:
        f 30 = 운용자 정지선 −30% — 예산이 정지선에 닿기 전에 스스로 비중을 줄이게.
        m 3 = I3 의 m 6 을 2배 상품으로 환산(기초지수 노출 기준 같은 배수). 최고점에서 레버리지 90% = 기초 1.8배.
  매매 밴드 10%p(I3 와 같음) · 예탁 50만원(운용 조건) · 정수 주식수 · 편도 11.5bp.
  입장 조건: lab_aggr 의 P1~P5 그대로(import, 숫자 안 바꿈) —
    P1 최대 낙폭 ≤ 30% · P2 연수익 ≥ max(KODEX200 보유, I3) + 5%p · P3 박스권·강세장 각각 ≥ KODEX200 ·
    P4 롤링 3년 수익 최솟값 > 0(1세대에서 I3·KODEX200 도 못 넘은 것을 알고도 그대로 둔다 — 운용자 목표 "3년 동안 계속 번다") ·
    P5 격자 9개 중앙값도 P1~P4.
  보고만: 장기 스트레스(1998~, ^KS11 일간 2배 합성 — 비용·괴리 없는 낙관 쪽) 최대 낙폭·30% 사건·3년 최악 ·
    미공개(오염 — 10월 급락을 안다) · 월 +10% 달 비율 · 최악 달 · 부모(KODEX200·레버리지 보유·I3·A3b) 같은 표.
  통과하면 공격형 리그(그림자)에 등록 → 2주 기록 → 운용자 승인 시 실계좌 50만원. 떨어지면 같은 숫자로 다시 재지 않는다.

결과 (edc6989 선언대로, 기준 수정 없음) — **G1·G2 둘 다 탈락**
                연수익   MDD   박스권  강세장  3년최악   장기 MDD
  KODEX200     16.75%  40.8%   4.1%  23.1%  −20.8%
  I3(핵심)     12.10%  18.5%   5.9%  15.0%   −9.3%
  A3b(1세대)   24.88%  50.8%  16.3%  28.7%  −30.6%
  G1 기본      17.64%  33.1%   7.6%  22.4%  −19.9%    49.2%   P1~P5 전부 X(강세장이 KODEX200 에 0.7%p 모자람)
  G2 기본      10.28%  54.8%   4.3%  13.2%  −42.3%    60.8%
  G1 격자(연수익/MDD): (2,25) 13.2/21 · (2,30) 15.0/24 · (2,35) 18.3/27 · (3,25) 15.6/26 · (3,30) 17.6/33 · (3,35) 21.7/38
                       (4.5,25) 16.6/35 · (4.5,30) 22.0/42 · (4.5,35) 24.9/43
진단(판정에 안 씀):
  ① **수익과 낙폭이 한 줄 위에 있다** — G1 격자 9개가 연수익 ≈ MDD × 0.5~0.65 의 직선. P2(연 21.75% 이상)를 넘는 설정은
    MDD 38~43%. 레버리지는 같은 줄 위에서 위치만 옮긴다(연수익÷MDD: I3 0.65 · G1 0.53 · A3b 0.49 · KODEX200 0.41 ·
    레버리지 보유 0.35 — I3 가 오히려 가장 효율적).
  ② **엔진이 필요하다** — 낙폭 예산만(G2)은 MDD 54.8%. 바닥선이 '최근 252일 최고치' 기준이라 긴 하락에선 1년마다 바닥이
    내려가 다시 사들인다. G1 도 같은 이유로 바닥(30%)보다 깊이(33%) 빠졌다.
  ③ 수익을 올리려면 레버리지가 아니라 **새 수익원**(다른 자산·다른 시간대)이 필요하다 — 같은 줄을 위로 옮기는 것.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import i3_core as K  # noqa: E402
import lab_aggr as A  # noqa: E402
import lab_challengers as CH  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BASE, LEV2, CASH = A.BASE, A.LEV2, A.CASH
SPECS = ("G1", "G2")
M_GRID = (2, 3, 4.5)
F_GRID = (25, 30, 35)
GRID = tuple((m, f) for m in M_GRID for f in F_GRID)
DEFAULT = (3, 30)
LOOKBACK = 252
BAND = 0.10


def budget_only(asset: str, cash: str | None, m: float, f: float, lookback: int = LOOKBACK, band: float = BAND):
    """G2 — 엔진 없이 낙폭 예산만. target(i, d, nav). 예산 식은 실전 I3 와 같은 i3_core.budget_exposure."""
    st: dict = {"navs": [], "w": None}

    def target(i: int, d: str, nav: float):
        st["navs"].append(nav)
        w = K.budget_exposure(st["navs"], m, lookback, f)
        if st["w"] is not None and abs(w - st["w"]) < band and not (w == 0.0 and st["w"] > 0):
            return None
        st["w"] = w
        out = {asset: w} if w > 0 else {}
        if cash and w < 1.0:
            out[cash] = 1.0 - w
        return out
    return target


def make_target(spec: str, p: tuple, sig_bars: dict, kospi: dict, asset: str, cash: str | None):
    """sig_bars·kospi 로 판단하고 asset 을 든다(G1 엔진은 KODEX200 으로 판단 — 레버리지 가격으로 판단하지 않는다)."""
    m, f = p
    if spec == "G1":
        return CH.i3x(sig_bars, kospi, asset, cash, m, LOOKBACK, floor_dd=f, band=BAND)
    if spec == "G2":
        return budget_only(asset, cash, m, f)
    raise KeyError(spec)


def run_spec(px: dict, dates: list[str], spec: str, p: tuple) -> dict:
    t = make_target(spec, p, px[BASE], px["^KS11"], LEV2, CASH)
    res = L.simulate({c: L.Asset(c, px[c]) for c in (LEV2, CASH)}, dates, t, A.AG_EQUITY, pass_nav=True)
    return A.spans(res)


def run_long(ks: dict, spec: str, p: tuple) -> dict:
    """장기 스트레스(보고만) — ^KS11 로 판단, ^KS11 일간 2배 합성을 든다. 현금 이자 0."""
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    t = make_target(spec, p, ks, ks, "UP", None)
    r = L.simulate({"UP": L.Asset("UP", L.leveraged_bars(ks, 2.0))}, long_dates, t, 0.0, pass_nav=True)
    met = L.metrics(r.dates, r.curve)
    return {"mdd": met["mdd"], "events": A.dd_events(r.curve), "roll3": A.rolling_min(r.curve, A.ROLL_3Y),
            "cagr": met["cagr"]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    px = A.load()
    dates = [d for d in L.calendar(px[BASE], L.FULL[0], A.END) if all(d in px[c] for c in (LEV2, CASH))]
    bench = A.spans(L.buy_and_hold(BASE, dates, px[BASE], A.AG_EQUITY))
    m, lb = H.I3_DEFAULT
    core = A.spans(L.simulate({BASE: L.Asset(BASE, px[BASE]), CASH: L.Asset(CASH, px[CASH])}, dates,
                              CH.i3x(px[BASE], px["^KS11"], BASE, CASH, m, lb, **CH.SPECS["I3"]), A.AG_EQUITY,
                              pass_nav=True))
    a_dates = [d for d in dates if d in px[A.INV1]]
    print("=" * 132)
    print(f"공격형 2세대(레버리지 × 낙폭 예산, 인버스 없음) — 학습 2015-07~2026-08, 예탁 {A.AG_EQUITY:,.0f}원 · 잣대 P1~P5(lab_aggr)")
    print(f"  {'':12}{'연수익':>8}{'MDD':>7}{'최악':>8}{'박스권':>8}{'강세장':>8}{'3년최악':>9}{'1년+비율':>9}"
          f"{'미공개*':>8}{'매매':>6}  | 월+10%달 · 최악달 · 3년 중앙값 | 장기 MDD·30%사건·3년최악")

    def row(name, r, lg=None):
        f = r["전체"]
        tail = (f"  | {lg['mdd']:5.1f}% · {lg['events']}회 · {lg['roll3']:+6.1f}%" if lg else "")
        print(f"  {name:12}{f['cagr']:>7.2f}%{f['mdd']:>6.1f}%{f['worst_year']:>+7.1f}%{r['박스권']['cagr']:>7.1f}%"
              f"{r['강세장']['cagr']:>7.1f}%{r['roll3']:>+8.1f}%{r['roll1_pos']:>8.0%}{r['미공개']['total']:>+7.1f}%"
              f"{r['trades']:>6}  | {r['m10']:>5.0%} · {r['worst_month']:+6.1f}% · {r['roll3_med']:+7.1f}%{tail}")
    row("KODEX200", bench)
    row("레버리지보유", A.spans(L.buy_and_hold(LEV2, dates, px[LEV2], A.AG_EQUITY)))
    row("I3(핵심)", core)
    row("A3b(1세대)", A.run_spec(px, a_dates, "A3", "b", A.A3_DEFAULT))
    print("-" * 132)
    passed = []
    for spec in SPECS:
        rows = {p: run_spec(px, dates, spec, p) for p in GRID}
        r = rows[DEFAULT]
        row(f"{spec} 기본", r, run_long(px["^KS11"], spec, DEFAULT))
        checks = A.verdict(r, bench, core)
        med = A.grid_median(list(rows.values()))
        checks.append(("P5", all(ok for _, ok in A.verdict({**med, "미공개": {}}, bench, core))))
        ok = all(x for _, x in checks)
        if ok:
            passed.append(spec)
        print(f"  {'':12}" + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks)
              + f"  (격자 중앙값 연수익 {med['전체']['cagr']:.1f}% · MDD {med['전체']['mdd']:.1f}% · 3년최악 {med['roll3']:+.1f}%)"
              + f" → {'공격형 리그 입장' if ok else '탈락'}")
        print(f"  {'':12}격자 (m, f): " + " · ".join(
            f"({p[0]:g},{p[1]}) {rows[p]['전체']['cagr']:.1f}%/{rows[p]['전체']['mdd']:.0f}%" for p in GRID))
    print("=" * 132)
    print("* 미공개(2026-08-25~10-21)는 오염(10월 급락을 안다) — 판정에 쓰지 않는다. 격자 표기 = 연수익/MDD.")
    print(f"공격형 리그 입장: {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
