"""리그 8세대 — 회복이 확인되면 변동성 브레이크를 푼다 (2026-10-26, 사전 선언).

운용자(10-26): 8세대 '브레이크를 푸는 속도' 제안에 "1번은 진행"

근거 — 어디서 왔나 (부모 V7a 진단, 탐색 — 판정에 쓰지 않는다)
-----------------------------------------------------------
  · 부모 V7a(7세대, T6c + 변동성 브레이크): 강점 학습 MDD 16.5% · 6월 갭 −10.3%. 약점 박스권 4.2% · 미공개 −3.6%.
  · 박스권(2015-07~2018) T6c +17.7% vs V7a +14.6%: V7a 가 진 날은 대부분 **상승일에 비중이 낮았던 날**(예: 2018-02-23
    98% vs 63%) — 흔들린 뒤 곧 반등하는 박스권에서 브레이크가 비중을 늦게 돌려놓았다. 브레이크로 비중이 5%p 넘게 낮았던
    498일 중 85일은 **KOSPI 가 이미 20일 고점**이었다(회복이 확인됐는데도 브레이크가 걸려 있었다).
  · 미공개(2026-08-25~10-21) T6c −2.1% vs V7a −3.6%: V7a 가 진 날은 오히려 **V7a 비중이 더 높았던 하락일**(예: 10-08
    14% vs 30%) — 앞선 급락에서 덜 잃어 예산 쿠션이 남았고 이어진 하락에서 더 들고 있었다. 이건 해제 속도 문제가 아니라
    낙폭 예산의 구조다 — **이번 세대는 이 약점을 겨누지 않는다**(같은 데이터로 하나씩만 고친다).
  · 문헌: 포트폴리오 보험의 조건부 배수 연구는 '위험이 클 때 낮춘다'까지만 — 언제 되돌리는지는 정하지 않는다. 그래서
    되돌리는 시점은 우리 엔진의 정의(20일 고점 = 재진입 신호)를 그대로 빌린다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  V8a  V7a + 해제(20일 고점)   KOSPI 종가가 직전 20일 최고 종가보다 높은 날엔 브레이크를 걸지 않는다(배수 = T6c 그대로).
  V8b  V7a + 해제(20일선 위)   KOSPI 종가가 20일 이동평균보다 높은 날엔 브레이크 없음 — 더 일찍·자주 푼다(속도 대조).
  숫자: 20 = 엔진의 20일 고점 그대로, 나머지는 V7a 그대로. 새 숫자 없음.
  입장 조건(전부): I3 대비 E1·G2·G3·G6(6·7세대와 같다)
                    E8 부모 대비 — ① 박스권 연수익 ≥ V7a + 0.5%p(약점 감소) ② 6월 사례 손실 ≤ V7a + 0.5%p(갭 방어 유지)
                    ③ 학습 MDD ≤ V7a + 1.0%p(낙폭 방어를 크게 잃지 않는다)
  통과하면 2026-11-02 등록(11월 신규 3 중 V7a 1 — 남은 2, 정원 25 중 23). 떨어지면 기록만, 같은 숫자로 다시 재지 않는다.
같이 보고만 하는 것: 강세장, 미공개(겨누지 않는 약점), 매매 수, 브레이크가 풀린 날 비율.

8세대 결과 (db8b117 선언대로, 기준 수정 없음) — 브레이크가 걸렸을 날 중 풀린 비율: V8a 13% · V8b 49%
        연수익   MDD   최악   박스권  강세장  미공개  6월 갭  장기MDD  매매
  V7a   13.20%  16.5%  −6.6%   4.2%  17.5%  −3.6%  −10.3%  29.8%   265
  V8a   13.26%  17.1%  −6.8%   4.1%  17.6%  −1.8%  −12.4%  29.7%   297   → E8 탈락(박스권 그대로 · 갭 방어 −2.1%p)
  V8b   13.87%  18.6%  −6.2%   4.4%  18.4%  −2.1%  −11.5%  30.0%   269   → E8 탈락(박스권 +0.2%p · MDD +2.1%p)
겨눈 약점(박스권)은 줄지 않았고, 반등에서 풀자 이어진 급락에 다시 맞아 부모의 강점(갭 방어)을 잃었다. V8b 는 절반이 풀려
사실상 T6c. V8a 의 미공개 −1.8%(가장 좋음)는 겨누지 않은 지표라 관찰로만 — 결과를 보고 채택하면 사후 선택이다.
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
import lab_gen7 as G7  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
RELEASE_N = 20                                   # 엔진 재진입의 20일 고점과 같은 n
SPECS8: dict[str, dict] = {
    "V8a": {**G7.SPECS7["V7a"], "brake_off_high": RELEASE_N},
    "V8b": {**G7.SPECS7["V7a"], "brake_off_ma": RELEASE_N},
}
E8_BOX_GAIN_PP = 0.5
E8_EPISODE_TOL_PP = 0.5
E8_MDD_TOL_PP = 1.0
REGISTER_ON = "2026-11-02"
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH


def verdict(r: dict, ref: dict, parent: dict) -> list[tuple[str, bool]]:
    checks = G6.verdict(r, ref)
    checks.append(("E8", r["박스권"]["cagr"] >= parent["박스권"]["cagr"] + E8_BOX_GAIN_PP
                   and r["사례"]["total"] >= parent["사례"]["total"] - E8_EPISODE_TOL_PP
                   and r["전체"]["mdd"] <= parent["전체"]["mdd"] + E8_MDD_TOL_PP))
    return checks


def release_share(ks: dict, start: str, end: str, spec: dict) -> float:
    """브레이크가 걸렸을 날(σ20 > σ252) 중 회복 확인으로 풀린 날 비율 — 진단용."""
    days = sorted(ks)
    cl = [ks[d]["close"] for d in days]
    ret = [0.0] + [cl[j] / cl[j - 1] - 1 for j in range(1, len(cl))]

    def sd(k, w):
        xs = ret[k + 1 - w:k + 1]
        mu = sum(xs) / w
        return (sum((x - mu) ** 2 for x in xs) / w) ** 0.5
    hit = rel = 0
    for k, d in enumerate(days):
        if not (start <= d <= end) or k < 252:
            continue
        if sd(k, 20) <= sd(k, 252):
            continue
        hit += 1
        n = spec.get("brake_off_high")
        ma = spec.get("brake_off_ma")
        if (n and cl[k] > max(cl[k - n:k])) or (ma and cl[k] > sum(cl[k + 1 - ma:k + 1]) / ma):
            rel += 1
    return rel / hit if hit else float("nan")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    specs = {"I3": CH.SPECS["I3"], "T6c": G6.SPECS6["T6c"], "V7a": G7.SPECS7["V7a"], **SPECS8}
    M = {n: G6.measure(s, kodex, cash, ks, dates, long_dates) for n, s in specs.items()}
    print("=" * 118)
    print(f"8세대 브레이크 해제 — 2015-07~2026-08, 예탁 {EQUITY:,.0f}원 · 회복 확인(KOSPI {RELEASE_N}일 고점 / {RELEASE_N}일선 위)")
    for n in SPECS8:
        print(f"  {n}: 브레이크가 걸렸을 날 중 풀린 비율 — 학습 {release_share(ks, *L.FULL, SPECS8[n]):.0%}")
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
    for n in SPECS8:
        checks = verdict(M[n], M["I3"], M["V7a"])
        ok = all(x for _, x in checks)
        if ok:
            passed.append(n)
        print(f"  {n}: " + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"\n리그 입장({REGISTER_ON} 등록): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
