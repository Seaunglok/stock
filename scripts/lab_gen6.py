"""리그 6세대 — 낙폭 예산 배수를 장기 추세에 따라 바꾼다 (2026-10-23, 사전 선언).

운용자(10-23): 6세대 제안에 "진행해줘" · "6세대 연구는 어디서 참고한 거야?"

근거 — 어디서 왔나
------------------
  · 우리 진단(8차, lab_reentry): 강세장 부진 28.3%p 중 27.8%p 가 재진입 후 60영업일 안이고, 재진입 9회의 진입 비중
    평균이 54% 였다. 비중을 깎는 것은 낙폭 예산 비중 = min(1, m × 쿠션) 의 배수 m(=6) — 재진입할 땐 계좌가 1년 최고치보다
    ~10% 아래라 쿠션이 작다(6 × 0.089 ≈ 0.53).
  · 부모 R6(3세대): 리셋을 'KOSPI 250일선이 오를 때만'으로 막아 위험은 I3 와 같고 연 +0.5%p. 다만 강세장 +1%p(E2)에
    0.2%p 모자랐다. 리그 문서 '다음 세대 후보'(10-22): "새 축이 필요하다(예: 예산 m 을 장기 추세에 따라 다르게)".
  · 이론: 낙폭 예산은 Grossman·Zhou(1993, Mathematical Finance 3(3)) — 위험자산 비중을 '바닥선 위 여유'에 비례시킨다.
    m 은 그 비례 상수(포트폴리오 보험 CPPI 의 배수). 배수를 시장 상황에 따라 바꾸는 연구(변동성·VaR 연동, 국면 전환)는
    있지만 **장기 추세로 바꾸는 근거는 찾지 못했다 — 이 설계는 우리 가설이다**. 배수가 클수록 갭 하락 손실이 커진다는
    지적이 있어 m 은 I3 격자(4·6·8) 밖으로 키우지 않는다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  T6a  I3 + 배수 추세 연동   KOSPI 250일선이 20영업일 전보다 높으면 m = 8, 아니면 m = 6(I3 그대로).
  T6b  R6 + 배수 추세 연동   부모 R6(1년 1회 리셋·250일선 상승 때만) + T6a 의 배수.
  T6c  비대칭               상승 8 · 그 외 4 — 장기 하락장에선 I3 보다 더 방어.
  숫자: 4·6·8 = 6차 I3 격자, 250·20 = 3세대 R6 장기 추세. 새 숫자 없음, 격자 탐색 없음. 엔진·L·바닥·밴드는 I3 그대로.
  입장 조건(전부, I3 대비): E1 학습 MDD ≤ 20% · 최악연도 ≥ −10%
                    G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p)
                    G3 미공개 ≥ I3 − 1%p
                    G6 장기(1998~ KOSPI) MDD ≤ I3 + 3%p — 배수를 키우는 설계라 닷컴·금융위기 스트레스를 본다
  통과하면 2026-11-02 등록(10월 신규 상한 3 소진, 정원 25 중 21). 떨어지면 기록만 하고 같은 숫자로 다시 재지 않는다.
같이 보고만 하는 것: 박스권·강세장, 재진입한 날의 목표 비중 평균(가설: I3 ~54% → 더 높게), 2026-06 급락(갭) 사례.

6세대 결과 (1406001 선언대로, 기준 수정 없음)
-------------------------------------------
        연수익   MDD   최악   박스권  강세장  미공개  6월 갭  장기MDD  재진입 비중
  I3    12.61%  19.8%  −6.1%   6.2%  15.6%  −2.7%  −10.5%  31.2%   51%
  T6a   13.59%  20.8%  −6.0%   5.9%  17.2%  −2.1%  −11.5%  32.0%   55%   → E1·G2 탈락
  T6b   13.10%  20.8%  −6.0%   5.9%  16.5%  −2.2%  −11.5%  32.0%   65%   → E1·G2 탈락
  T6c   13.76%  18.6%  −6.7%   5.0%  17.9%  −2.1%  −11.5%  30.0%   47%   → 전부 통과, 2026-11-02 등록
가설한 경로(재진입 비중↑)는 틀렸다 — 재진입은 대개 장기선이 내려가는 중이라 T6c 는 오히려 배수 4. 이득은 상승장 눌림과
장기 하락장의 조기 축소에서. 대가: 박스권 −1.2%p · 갭 급락 −1%p(문헌 지적대로). 다음 후보: 배수 × 변동성(7세대).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_challengers as CH  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_gen4 as G4  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
M_UP, M_DOWN_C = 8, 4                          # I3 격자(4·6·8)의 끝값 — 기본 m 6 은 H.I3_DEFAULT
TREND = {"m_trend_ma": 250, "m_trend_lag": 20}  # R6 의 장기 추세 정의 그대로
SPECS6: dict[str, dict] = {
    "T6a": {"reset": "none", "m_up": M_UP, **TREND},
    "T6b": {**CH.SPECS["R6"], "m_up": M_UP, **TREND},
    "T6c": {"reset": "none", "m_up": M_UP, "m_down": M_DOWN_C, **TREND},
}
G6_LONG_MDD_TOL = 3.0
REGISTER_ON = "2026-11-02"
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH


def reentry_tracker(t, asset: str = BASE):
    """target 을 감싸 '재진입한 날의 목표 비중'을 모은다(진단용 — 판단은 바꾸지 않는다)."""
    st = {"w": None, "seen0": False}
    weights: list[float] = []

    def target(i, d, nav):
        r = t(i, d, nav)
        if r is not None:
            w = r.get(asset, 0.0)
            if st["seen0"] and st["w"] == 0.0 and w > 0:
                weights.append(w)
            st["seen0"] = st["seen0"] or w == 0.0
            st["w"] = w
        return r
    target.weights = weights
    return target


def measure(spec: dict, kodex, cash, ks, dates, long_dates) -> dict:
    m, lb = H.I3_DEFAULT
    t = reentry_tracker(CH.i3x(kodex, ks, BASE, CASH, m, lb, **spec))
    res = L.simulate({BASE: L.Asset(BASE, kodex), CASH: L.Asset(CASH, cash)}, dates, t, EQUITY, pass_nav=True)
    lr = L.simulate({"IDX": L.Asset("IDX", ks)}, long_dates, CH.i3x(ks, ks, "IDX", None, m, lb, **spec),
                    0.0, pass_nav=True)
    out = G4.spans(res)
    out["장기"] = L.metrics(lr.dates, lr.curve)
    out["trades"] = res.trades
    out["reentry_w"] = list(t.weights)
    return out


def verdict(r: dict, ref: dict) -> list[tuple[str, bool]]:
    """선언한 입장 조건 그대로 — (이름, 통과)."""
    full, rf = r["전체"], ref["전체"]
    return [
        ("E1", full["mdd"] <= L.MAX_MDD_PCT and full["worst_year"] >= L.MIN_YEAR_RET_PCT),
        ("G2", (full["mdd"] <= rf["mdd"] - G4.G2_MDD_CUT and full["cagr"] >= rf["cagr"] - G4.G2_CAGR_TOL)
         or (full["cagr"] >= rf["cagr"] + G4.G2_CAGR_UP and full["mdd"] <= rf["mdd"] + G4.G2_MDD_TOL)),
        ("G3", r["미공개"]["total"] >= ref["미공개"]["total"] - G4.HO_TOL),
        ("G6", r["장기"]["mdd"] <= ref["장기"]["mdd"] + G6_LONG_MDD_TOL),
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    specs = {"I3": CH.SPECS["I3"], "R6": CH.SPECS["R6"], **SPECS6}
    M = {n: measure(s, kodex, cash, ks, dates, long_dates) for n, s in specs.items()}
    print("=" * 118)
    print(f"6세대 배수 추세 연동 — 2015-07~2026-08, 예탁 {EQUITY:,.0f}원 · 기본 m {H.I3_DEFAULT[0]} → 상승 {M_UP}"
          f" (T6c 하락 {M_DOWN_C})")
    print(f"  {'':5}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}"
          f"{'장기MDD':>9}{'재진입 비중':>11}{'매매':>6}")
    for n, r in M.items():
        rw = r["reentry_w"]
        avg = sum(rw) / len(rw) if rw else float("nan")
        print(f"  {n:5}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['사례']['total']:>+8.1f}%{r['장기']['mdd']:>8.1f}%{avg:>9.0%}({len(rw)}){r['trades']:>5}")
    print("=" * 118)
    passed = []
    for n in SPECS6:
        checks = verdict(M[n], M["I3"])
        ok = all(x for _, x in checks)
        if ok:
            passed.append(n)
        print(f"  {n}: " + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"\n리그 입장({REGISTER_ON} 등록): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
