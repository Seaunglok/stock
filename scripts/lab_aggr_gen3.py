"""공격형 트랙 3세대 — 한미 반반 × 레버리지: 다른 자산으로 '줄'을 올린다 (2026-10-29, 사전 선언).

운용자(10-29): 2세대 결과 뒤 "진행해줘" — 3세대는 I3 엔진·낙폭 예산을 함께 덜 움직이는 자산 묶음에.

부모 진단
---------
  2세대(lab_aggr_gen2): 수익과 낙폭이 한 줄 위(연수익 ≈ MDD × 0.5~0.65) — 레버리지는 줄 위에서 자리만 옮긴다.
    KR 2배 G1 기본(m 3·바닥 30%): 연 17.6% · MDD 33.1%.
  한미 반반 I3(10-22 탐색, lab_asset_compare 방식 · docs/2026-10-22-etf-choice.md §2, 실제 ETF·예탁 385만원):
    연 14.0% · MDD 12.5% → 연수익÷MDD 1.12 (I3 단독 0.65) — 두 시장이 다른 때 빠져서 **줄 자체가 높다**.
    약점: 연 14% — 공격형 P2(21.75%)엔 멀다. 나스닥 I3 는 그냥 보유(21.1%)보다 7%p 낮다(엔진 비용).
  → 3세대 = 높은 줄(한미 반반) 위에서 한국 쪽만 레버리지로 올린다. 미국 2배 ETF 는 2021-12 이후 상장이라 2015~ 검증 불가
    (합성 이력은 운용 조건과 다르다) — 미국 쪽은 1배.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  자산: 한국 122630(KODEX 레버리지) · 미국 133690(TIGER 미국나스닥100, 원화·환노출) · 현금 153130(연구 공통).
  한국 절반 = 2세대 G1 그대로(lab_aggr_gen2.make_target "G1": I3 엔진은 KODEX200·KOSPI 로 판단 × 낙폭 예산 (m, f)).
  미국 절반:
    HH1  나스닥100 I3 — lab_challengers.i3x I3 기본(m 6 · 252일 · 바닥 18%), 재진입 추세 확인은 **자기 120일선**
         (KOSPI 규칙을 미국 자산에 쓰지 않는다 — 한미반반 리그 멤버·lab_asset_compare 와 같음).
    HH2  나스닥100 그냥 보유 — 미국 쪽 엔진이 값어치가 있는지 가르는 대조(엔진 비용 7%p vs MDD 31%).
  묶기: 50:50 출발, **매년 첫 거래일 종가에 50:50 재조정**(lab_asset_compare 와 같음) — 옮긴 금액 × 편도 11.5bp × 2 를 비용으로 뺀다.
  격자: 한국 절반 (m, f) = lab_aggr_gen2.GRID 9개, 기본 (3, 30). 미국 절반은 고정(선언값).
  예탁 50만원(운용 조건, 각 절반 25만원 · 정수 주식수) · 편도 11.5bp.
  입장 조건: lab_aggr P1~P5 그대로(import) — P1 MDD ≤ 30% · P2 연수익 ≥ max(KODEX200, I3) + 5%p · P3 박스권·강세장 각각 ≥
    KODEX200 · P4 롤링 3년 최솟값 > 0 · P5 격자 9개 중앙값도 P1~P4.
  보고만:
    · 세후 추정 — 국내 상장 해외 ETF(133690)는 매매차익 15.4% 과세(KODEX 레버리지는 비과세). 연수익 − 0.154 × 미국 절반 기여.
    · 예탁 365만원으로 같은 규칙(정수 주식수 영향 — 133690 은 10-21 종가 173,825원, 25만원으로 1주).
    · 장기 스트레스(1998~, ^KS11 일간 2배 합성 + ^NDX×원/달러 — 비용·괴리 없는 낙관 쪽) · 미공개(오염) · 월 +10% 달 · 최악 달.
    · 부모 줄: 한미 반반 I3(1배)를 같은 기계(50만원)로 다시 잰 값 · KR 2배 G1 단독.
  통과하면 공격형 리그(그림자)에 등록. 떨어지면 같은 숫자로 다시 재지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_aggr as A  # noqa: E402
import lab_aggr_gen2 as G2  # noqa: E402
import lab_challengers as CH  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402
from src.mcp_servers.trend_mcp import costs as C  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BASE, LEV2, CASH = A.BASE, A.LEV2, A.CASH
NDQ = "133690"
SPECS = ("HH1", "HH2")
US_MODE = {"HH1": "i3", "HH2": "hold"}
GRID, DEFAULT = G2.GRID, G2.DEFAULT
SIDE_COST = (C.FEE_BPS + C.SLIPPAGE_BPS) / 10_000.0
US_TAX = 0.154
REF_EQUITY = 3_650_000.0              # 보고만 — 계좌 전체로 잰 값(정수 주식수 영향 비교)


def combine(a: L.SimResult, b: L.SimResult, side_cost: float = SIDE_COST) -> L.SimResult:
    """두 절반의 곡선을 더한다 — 매년 첫 거래일 종가에 50:50 으로 되돌리고, 옮긴 금액 × 편도 비용 × 2 를 뺀다."""
    mb = dict(zip(b.dates, b.curve))
    out = L.SimResult(trades=a.trades + b.trades)
    ua = ub = 1.0
    prev = None
    for d, ca in zip(a.dates, a.curve):
        if d not in mb:
            continue
        va, vb = ua * ca, ub * mb[d]
        if prev is not None and d[:4] != prev[:4]:
            nav = va + vb
            moved = abs(va - nav / 2)
            nav -= 2 * side_cost * moved
            ua, ub = (nav / 2) / ca, (nav / 2) / mb[d]
            va = vb = nav / 2
        out.dates.append(d)
        out.curve.append(va + vb)
        prev = d
    return out


def us_target(mode: str, ndq: dict, asset: str, cash: str | None):
    """미국 절반 — i3: I3 기본, 재진입 추세 확인은 자기 120일선(kospi 자리에 자기 가격) · hold: 첫날 사서 보유."""
    if mode == "i3":
        m, lb = H.I3_DEFAULT
        return CH.i3x(ndq, ndq, asset, cash, m, lb, **CH.SPECS["I3"])
    if mode == "hold":
        return lambda i, d, nav: {asset: 1.0} if i == 0 else None
    raise KeyError(mode)


def run_halves(px: dict, dates: list[str], spec: str, p: tuple, equity: float = A.AG_EQUITY,
               kr_asset: str = LEV2) -> tuple[L.SimResult, L.SimResult]:
    kr_t = G2.make_target("G1", p, px[BASE], px["^KS11"], kr_asset, CASH) if kr_asset == LEV2 else \
        CH.i3x(px[BASE], px["^KS11"], BASE, CASH, *H.I3_DEFAULT, **CH.SPECS["I3"])
    kr = L.simulate({c: L.Asset(c, px[c]) for c in (kr_asset, CASH)}, dates, kr_t, equity / 2, pass_nav=True)
    us = L.simulate({c: L.Asset(c, px[c]) for c in (NDQ, CASH)}, dates, us_target(US_MODE[spec], px[NDQ], NDQ, CASH),
                    equity / 2, pass_nav=True)
    return kr, us


def after_tax_cagr(total: L.SimResult, us: L.SimResult) -> float:
    """보고만 — 미국 절반이 번 돈(연율, 절반 비중)의 15.4% 를 뺀 대략값."""
    full = L.slice_metrics(total, *L.FULL)["cagr"]
    us_c = L.slice_metrics(us, *L.FULL)["cagr"]
    return full - US_TAX * 0.5 * max(0.0, us_c)


def run_long(spec: str, p: tuple) -> dict:
    """장기 스트레스(보고만) — 한국 = ^KS11 일간 2배 합성(G1 규칙), 미국 = ^NDX × 원/달러(1배). 현금 이자 0."""
    import lab_asset_compare as AC
    ks = L.load_bars("^KS11", "1996-01-01", A.END)
    ndx = AC.krw_index("^NDX", ks)
    dates = [d for d in L.calendar(ks, *I.LONG_STRESS) if d in ndx]
    kr = L.simulate({"UP": L.Asset("UP", L.leveraged_bars(ks, 2.0))}, dates,
                    G2.make_target("G1", p, ks, ks, "UP", None), 0.0, pass_nav=True)
    us = L.simulate({"US": L.Asset("US", ndx)}, dates, us_target(US_MODE[spec], ndx, "US", None), 0.0, pass_nav=True)
    r = combine(kr, us)
    met = L.metrics(r.dates, r.curve)
    return {"mdd": met["mdd"], "events": A.dd_events(r.curve), "roll3": A.rolling_min(r.curve, A.ROLL_3Y),
            "cagr": met["cagr"]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    px = A.load()
    px[NDQ] = L.load_bars(NDQ, "2010-01-01", A.END)
    dates = [d for d in L.calendar(px[BASE], L.FULL[0], A.END) if all(d in px[c] for c in (LEV2, CASH, NDQ))]
    bench = A.spans(L.buy_and_hold(BASE, dates, px[BASE], A.AG_EQUITY))
    m, lb = H.I3_DEFAULT
    core = A.spans(L.simulate({BASE: L.Asset(BASE, px[BASE]), CASH: L.Asset(CASH, px[CASH])}, dates,
                              CH.i3x(px[BASE], px["^KS11"], BASE, CASH, m, lb, **CH.SPECS["I3"]), A.AG_EQUITY,
                              pass_nav=True))
    print("=" * 140)
    print(f"공격형 3세대(한미 반반 × 한국 레버리지) — 학습 2015-07~2026-08, 예탁 {A.AG_EQUITY:,.0f}원(절반씩) · 잣대 P1~P5(lab_aggr)")
    print(f"  {'':14}{'연수익':>8}{'MDD':>7}{'최악':>8}{'박스권':>8}{'강세장':>8}{'3년최악':>9}{'1년+비율':>9}"
          f"{'미공개*':>8}{'매매':>6}  | 월+10%달 · 최악달 · 3년 중앙값 | 장기 MDD·30%사건·3년최악")

    def row(name, r, lg=None, extra=""):
        f = r["전체"]
        tail = (f"  | {lg['mdd']:5.1f}% · {lg['events']}회 · {lg['roll3']:+6.1f}%" if lg else "")
        print(f"  {name:14}{f['cagr']:>7.2f}%{f['mdd']:>6.1f}%{f['worst_year']:>+7.1f}%{r['박스권']['cagr']:>7.1f}%"
              f"{r['강세장']['cagr']:>7.1f}%{r['roll3']:>+8.1f}%{r['roll1_pos']:>8.0%}{r['미공개']['total']:>+7.1f}%"
              f"{r['trades']:>6}  | {r['m10']:>5.0%} · {r['worst_month']:+6.1f}% · {r['roll3_med']:+7.1f}%{tail}{extra}")
    row("KODEX200", bench)
    row("I3(핵심)", core)
    row("나스닥100보유", A.spans(L.buy_and_hold(NDQ, dates, px[NDQ], A.AG_EQUITY)))
    kr1, us1 = run_halves(px, dates, "HH1", DEFAULT, kr_asset=BASE)
    row("한미반반 I3", A.spans(combine(kr1, us1)))
    row("G1(한국2배)", G2.run_spec(px, dates, "G1", DEFAULT))
    print("-" * 140)
    passed = []
    for spec in SPECS:
        rows = {}
        for p in GRID:
            kr, us = run_halves(px, dates, spec, p)
            rows[p] = A.spans(combine(kr, us))
        kr, us = run_halves(px, dates, spec, DEFAULT)
        r = rows[DEFAULT]
        row(f"{spec} 기본", r, run_long(spec, DEFAULT), f"  · 세후≈{after_tax_cagr(combine(kr, us), us):.1f}%")
        checks = A.verdict(r, bench, core)
        med = A.grid_median(list(rows.values()))
        checks.append(("P5", all(ok for _, ok in A.verdict({**med, "미공개": {}}, bench, core))))
        ok = all(x for _, x in checks)
        if ok:
            passed.append(spec)
        print(f"  {'':14}" + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks)
              + f"  (격자 중앙값 연수익 {med['전체']['cagr']:.1f}% · MDD {med['전체']['mdd']:.1f}% · 3년최악 {med['roll3']:+.1f}%)"
              + f" → {'공격형 리그 입장' if ok else '탈락'}")
        print(f"  {'':14}격자 (m, f): " + " · ".join(
            f"({p[0]:g},{p[1]}) {rows[p]['전체']['cagr']:.1f}%/{rows[p]['전체']['mdd']:.0f}%" for p in GRID))
        kr_r, us_r = run_halves(px, dates, spec, DEFAULT, equity=REF_EQUITY)
        ref = L.slice_metrics(combine(kr_r, us_r), *L.FULL)
        print(f"  {'':14}보고: 예탁 {REF_EQUITY:,.0f}원이면 연수익 {ref['cagr']:.2f}% · MDD {ref['mdd']:.1f}% (정수 주식수 영향)")
    print("=" * 140)
    print("* 미공개(2026-08-25~10-21)는 오염(10월 급락을 안다) — 판정에 쓰지 않는다. 격자 표기 = 연수익/MDD. 세후는 대략값.")
    print(f"공격형 리그 입장: {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
