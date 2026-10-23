"""리그 7세대 — 낙폭 예산 배수에 변동성 브레이크 (2026-10-23, 사전 선언).

운용자(10-23): "7세대 진행하고, 6세대는 다음주에 바로 추가하자"

근거 — 어디서 왔나
------------------
  · 부모 T6c(6세대, 배수 상승 8·그 외 4): 강점 연 +1.2%p · MDD −1.2%p · 장기 MDD −1.2%p(I3 대비).
    약점 ① 2026-06 밤사이 갭 급락 −10.5 → −11.5%(배수 8 상태에서 갭을 맞았다) ② 박스권 6.2 → 5.0%.
  · 문헌(포트폴리오 보험 CPPI): **위험·변동성이 클수록 배수를 낮춘다**가 주류다 — 조건부 배수(VaR 연동 DARQ-VaR,
    halshs-01015390), 운용사 실무 노트(AXA IM: 주식 배수 4~6, 변동성이 오르면 낮춘다). 배수가 클수록 갭 손실이 커진다
    (점프가 있는 CPPI 연구) — T6c 의 약점 ①과 같은 지적이다. 단 국면 전환 비교에선 고정 배수가 더 나은 경우가 많았다는
    결과도 있다(halshs-00389789) — 브레이크가 이긴다는 보장은 없다.
  · 반대 증거도 적는다: 변동성 관리 포트폴리오(Moreira·Muir 2017, 1/전월분산)는 우리 리그 '변동성관리' 멤버로 KOSPI 에서
    MDD 35.2%·최악 −25.1% 였다 — 노출 전체를 변동성으로 조절하는 것은 여기서 방어가 되지 않았다. 그래서 이번엔 **배수에만
    브레이크**(줄이기만, 늘리지 않음)를 걸고 엔진·바닥선은 그대로 둔다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  V7a  T6c + 변동성 브레이크  배수 × min(1, σ252 / σ20), 하한 2. σ = KOSPI 일간 수익률(종가→종가, 밤사이 갭 포함) 표준편차.
                             최근 20일이 1년 평균보다 흔들리면 그 비율만큼 배수를 줄인다. 조용한 장에선 T6c 그대로.
  V7b  I3 + 같은 브레이크    기본 배수 6 에 같은 브레이크 — 브레이크만의 효과를 T6c 와 떼어 본다.
  숫자: 20 = 엔진의 20일 고점, 252 = 예산 기간 L, 하한 2 = I2 격자(2·3·5·8) 최솟값, 8·4 = T6c 그대로. 새 숫자 없음.
  입장 조건(전부, I3 대비 — 6세대와 같다): E1 학습 MDD ≤ 20% · 최악연도 ≥ −10%
                    G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p)
                    G3 미공개 ≥ I3 − 1%p · G6 장기(1998~ KOSPI) MDD ≤ I3 + 3%p
                    V7a 는 추가로 E7(부모 약점): 2026-06 급락 사례 손실이 T6c 보다 0.5%p 이상 작고 학습 MDD ≤ T6c
                    — 부모가 이미 리그에 있으니 그 약점을 줄여야 자리를 받는다.
  통과하면 2026-11-02 등록(11월 신규 3 남음, 정원 25 중 22). 떨어지면 기록만 하고 같은 숫자로 다시 재지 않는다.
같이 보고만 하는 것: 박스권·강세장, 매매 수, 재진입 비중, 브레이크가 걸린 날 비율(σ20 > σ252).

7세대 결과 (ef2d207 선언대로, 기준 수정 없음) — 브레이크가 걸린 날: 학습 38% · 6월 사례 100% · 미공개 11%
        연수익   MDD   최악   박스권  강세장  미공개  6월 갭  장기MDD  재진입 비중  매매
  I3    12.61%  19.8%  −6.1%   6.2%  15.6%  −2.7%  −10.5%  31.2%   51%   355
  T6c   13.76%  18.6%  −6.7%   5.0%  17.9%  −2.1%  −11.5%  30.0%   47%   225
  V7a   13.20%  16.5%  −6.6%   4.2%  17.5%  −3.6%  −10.3%  29.8%   42%   265   → 전부 통과(G3 여유 0.1%p), 2026-11-02 등록
  V7b   12.46%  18.3%  −5.9%   5.3%  15.8%  −5.6%   −7.9%  31.2%   52%   380   → G2·G3 탈락
브레이크는 급락 국면(6월)엔 들었지만 미공개 구간의 반등에선 비중을 늦게 돌려놓아 손해였다. I3 에 단독으로는 수지가 안 맞고,
T6c 의 상승기 배수 8 과 짝일 때만 통과. 아슬아슬한 통과라 리그 실전 기록을 특히 본다.
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
import lab_gen6 as G6  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BRAKE = {"vol_short": 20, "vol_long": 252, "m_min": 2}
SPECS7: dict[str, dict] = {
    "V7a": {**G6.SPECS6["T6c"], **BRAKE},
    "V7b": {"reset": "none", **BRAKE},
}
E7_EPISODE_GAIN_PP = 0.5
REGISTER_ON = "2026-11-02"
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH


def brake_share(ks: dict, start: str, end: str, short: int = 20, long: int = 252) -> float:
    """기간 중 σ_short > σ_long 인 날 비율(브레이크가 걸린 날) — 진단용."""
    days = sorted(ks)
    cl = [ks[d]["close"] for d in days]
    ret = [0.0] + [cl[j] / cl[j - 1] - 1 for j in range(1, len(cl))]

    def sd(k, w):
        xs = ret[k + 1 - w:k + 1]
        mu = sum(xs) / w
        return (sum((x - mu) ** 2 for x in xs) / w) ** 0.5
    hit = tot = 0
    for k, d in enumerate(days):
        if start <= d <= end and k >= long:
            tot += 1
            hit += sd(k, short) > sd(k, long)
    return hit / tot if tot else float("nan")


def verdict(name: str, r: dict, ref: dict, parent: dict) -> list[tuple[str, bool]]:
    checks = G6.verdict(r, ref)
    if name == "V7a":
        checks.append(("E7", r["사례"]["total"] >= parent["사례"]["total"] + E7_EPISODE_GAIN_PP
                       and r["전체"]["mdd"] <= parent["전체"]["mdd"]))
    return checks


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    specs = {"I3": CH.SPECS["I3"], "T6c": G6.SPECS6["T6c"], **SPECS7}
    M = {n: G6.measure(s, kodex, cash, ks, dates, long_dates) for n, s in specs.items()}
    print("=" * 118)
    print(f"7세대 변동성 브레이크 — 2015-07~2026-08, 예탁 {EQUITY:,.0f}원 · 배수 × min(1, σ252/σ20), 하한 {BRAKE['m_min']}")
    print(f"  브레이크가 걸린 날: 학습 {brake_share(ks, L.FULL[0], L.FULL[1]):.0%} · 6월 사례 "
          f"{brake_share(ks, *G4.EPISODE):.0%} · 미공개 {brake_share(ks, *L.HOLDOUT):.0%}")
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
    for n in SPECS7:
        checks = verdict(n, M[n], M["I3"], M["T6c"])
        ok = all(x for _, x in checks)
        if ok:
            passed.append(n)
        print(f"  {n}: " + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"\n리그 입장({REGISTER_ON} 등록): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
