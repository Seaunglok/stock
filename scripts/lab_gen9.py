"""리그 9세대 — 재진입을 외국인 수급으로 확인한다 (2026-11-10, 사전 선언).

운용자(11-10): "혹시 더 추가할 후보가 새로 있을까?" → '외국인 수급 9세대' 선택. 시장 일지(11-06~)로 모으기 시작한
키움 수급 이력(`data/market_flows/daily.csv`, ka10051 KRX 확정치, 2010-01-04~)을 처음 쓰는 세대.

근거 — 어디서 왔나 (부모 I3 진단, 수급 자료를 보기 **전** — 판정에 쓰지 않는다)
-------------------------------------------------------------------------------
  · 6~8세대는 낙폭 예산 배수 축이었고 8세대에서 멈췄다(리그 실전 기록을 기다린다). 9세대는 **다른 축 — 엔진의 재진입**.
  · 부모 I3 의 재진입(20일 고점 + KOSPI > 120일선), 2015-07-28~2026-10-21 학습+미공개: 10회.
      실패(재진입 후 60영업일 안에 재진입 가격보다 낮게 다시 이탈) 3회 — 2025-02-13 −7.7% · 2026-06-17 −6.5%(4일) ·
      2026-09-07 −8.3%(미공개 구간). 큰 수익은 3회 — 2020-05-26 +50.8% · 2025-04-29 +124.9% · 2026-04-14 +32.8%.
      **박스권(2015-07~2018)에는 재진입이 한 번도 없었다** → 이 세대는 박스권 약점을 바꾸지 못한다(보고만).
  · 가설: 20일 고점 돌파가 진짜 회복인지 외국인 매매가 알려 준다(실패한 재진입을 거른다 / 회복을 더 일찍 알아본다).
    문헌은 외국인 매매가 한국·아시아 시장 주가와 **같이 움직이고 가격 충격이 크다**는 데까지 — Choe·Kho·Stulz(1999,
    JFE) 1997 한국 · Richards(2005, JFQA) 아시아 신흥시장. **앞날 예측력의 근거는 약하다 — 이 설계는 우리 가설이다.**

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  수급 확인  KOSPI 외국인 순매수(억원)의 최근 FLOW_N(20)거래일 합 > 0. 창은 판단일 d 의 **전 거래일까지**(FLOW_LAG 1) —
             KRX 확정치는 다음 날 아침에 나오므로(시장 일지) 15:50 판단엔 전날까지만 있다. 검증 = 운용.
             20 = 엔진의 20일 고점 n 그대로, 부호만 본다(2010 → 2026 시가총액이 몇 배라 금액 기준선은 시대마다 다르다).
  F9a  확인 추가   재진입 = 20일 고점 + KOSPI > 120일선 **그리고** 수급 확인 — 실패한 재진입을 거른다.
  F9b  확인 대안   재진입 = 20일 고점 + (KOSPI > 120일선 **또는** 수급 확인) — 120일선이 늦을 때 수급으로 먼저 들어간다.
  자료가 없으면  창 안에 확정치(check=='ok')가 없는 날이 하나라도 있으면 그날은 I3 확인(120일선) 그대로 —
                 2010 전(장기 스트레스 1998~)·빠진 날. 이탈(−10%)·낙폭 예산·m·바닥·밴드·현금 자리는 I3 그대로.
  측정 가드  학습 시작 FLOW_WARMUP(40)거래일 전 ~ 미공개 끝까지 KOSPI 거래일에 확정치가 FLOW_GAP_MAX(0)개 넘게 비면
             **측정하지 않는다**(채우기 미완료 — 빈 날은 조용히 I3 로 돌아가 결과가 I3 처럼 보인다).
  입장 조건(전부): I3 대비 E1·G2·G3·G6(6~8세대와 같다)
                   E9 겨눈 약점 — F9a: 실패 재진입 < I3 **그리고** 강세장 연수익 ≥ I3 − 1.0%p(큰 재진입을 잃지 않는다)
                                  F9b: 강세장 연수익 ≥ I3 + 1.0%p(E2 크기) **그리고** 실패 재진입 ≤ I3 + 1
                   실패 재진입 = 재진입 후 FAIL_DAYS(60 = 2세대 TIGHT_DAYS)영업일 안에 재진입 때보다 낮은 KODEX200 가격으로 이탈,
                   학습+미공개 전체에서 센다.
  통과하면 REGISTER_ON(2026-11-16) 등록(11월 신규 3 중 V7a 1 — 남은 2, 정원 25 중 23). 떨어지면 기록만, 같은 숫자로
  다시 재지 않는다. 20·1 을 바꿔 다시 재지 않는다(선언).
같이 보고만 하는 것: 박스권, 미공개, 6월 사례, 장기 MDD(2010 전은 I3 와 같다), 재진입 목록, 수급이 판단을 바꾼 재진입.
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
import lab_holdout as H  # noqa: E402
import market_flows as MF  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
FLOW_N = 20                                      # 엔진 재진입의 20일 고점과 같은 n
FLOW_LAG = 1                                     # 확정치는 다음 날 아침 → 판단일 전날까지
SPECS9: dict[str, dict] = {
    "F9a": {"reset": "none", "reentry_flow": "and", "flow_n": FLOW_N, "flow_lag": FLOW_LAG},
    "F9b": {"reset": "none", "reentry_flow": "or", "flow_n": FLOW_N, "flow_lag": FLOW_LAG},
}
FAIL_DAYS = CH.TIGHT_DAYS                        # 60 — 2세대 '재진입은 대개 60일 안에 실패하거나 자리 잡는다'
E9A_BULL_TOL_PP = 1.0
E9B_BULL_GAIN_PP = CH.E2_BULL_GAIN_PP            # 1.0
E9B_FAIL_TOL = 1
FLOW_WARMUP = 40
FLOW_GAP_MAX = 0
REGISTER_ON = "2026-11-16"
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH


def load_flows(path: Path = MF.FLOWS_FILE) -> dict[str, float]:
    """{날짜: KOSPI 외국인 순매수 억원} — check=='ok' 이고 값이 있는 줄만(bad·dup·unchecked 는 빈 날)."""
    out: dict[str, float] = {}
    for d, r in MF.load_rows(path).items():
        v = r.get("kospi_foreign_eok")
        if r.get("check") == "ok" and v not in (None, ""):
            out[d] = float(v)
    return out


def flow_gaps(flows: dict[str, float], ks: dict, start: str, end: str, warmup: int = FLOW_WARMUP) -> list[str]:
    """start 의 warmup 거래일 전 ~ end 사이 KOSPI 거래일 중 확정치가 없는 날."""
    days = sorted(ks)
    first = next((k for k, d in enumerate(days) if d >= start), len(days))
    return [d for d in days[max(0, first - warmup):] if d <= end and d not in flows]


def stints(spec: dict, kodex, cash, ks, dates) -> list[tuple[str, str | None]]:
    """(재진입일, 다음 이탈일) — 시작 보유는 재진입이 아니다. 판단은 바꾸지 않는다(진단)."""
    m, lb = H.I3_DEFAULT
    t = CH.i3x(kodex, ks, BASE, CASH, m, lb, **spec)
    log: list[tuple[str, float]] = []

    def wrap(i, d, nav):
        r = t(i, d, nav)
        if r is not None:
            log.append((d, r.get(BASE, 0.0)))
        return r
    L.simulate({BASE: L.Asset(BASE, kodex), CASH: L.Asset(CASH, cash)}, dates, wrap, EQUITY, pass_nav=True)
    out, prev, ent = [], None, None
    for d, w in log:
        if prev is not None and prev == 0 and w > 0:
            ent = d
        elif prev is not None and prev > 0 and w == 0 and ent:
            out.append((ent, d))
            ent = None
        prev = w
    if ent:
        out.append((ent, None))
    return out


def failures(st: list[tuple[str, str | None]], kodex: dict, dates: list[str], days: int = FAIL_DAYS) -> int:
    pos = {d: k for k, d in enumerate(dates)}
    return sum(1 for a, b in st if b is not None and pos[b] - pos[a] <= days
               and kodex[b]["close"] < kodex[a]["close"])


def verdict(name: str, r: dict, ref: dict) -> list[tuple[str, bool]]:
    checks = G6.verdict(r, ref)
    bull, bull0 = r["강세장"]["cagr"], ref["강세장"]["cagr"]
    if name == "F9a":
        ok = r["fails"] < ref["fails"] and bull >= bull0 - E9A_BULL_TOL_PP
    else:
        ok = bull >= bull0 + E9B_BULL_GAIN_PP and r["fails"] <= ref["fails"] + E9B_FAIL_TOL
    checks.append(("E9", ok))
    return checks


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    flows = load_flows()
    gaps = flow_gaps(flows, ks, L.FULL[0], END)
    if len(gaps) > FLOW_GAP_MAX:
        print(f"측정 안 함 — 수급 확정치 빈 날 {len(gaps)}개 > {FLOW_GAP_MAX}: {gaps[:5]}{' …' if len(gaps) > 5 else ''}"
              f" (채우기 미완료 · market_flows.py 로 채운 뒤 다시)")
        return 2
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    specs = {"I3": CH.SPECS["I3"], **{n: {**s, "flows": flows} for n, s in SPECS9.items()}}
    M = {}
    for n, s in specs.items():
        r = G6.measure(s, kodex, cash, ks, dates, long_dates)
        r["stints"] = stints(s, kodex, cash, ks, dates)
        r["fails"] = failures(r["stints"], kodex, dates)
        M[n] = r
    print("=" * 112)
    print(f"9세대 외국인 수급 재진입 확인 — {dates[0]}~{dates[-1]}, 예탁 {EQUITY:,.0f}원 · 수급 {FLOW_N}일 합 > 0 "
          f"(판단 전날까지) · 확정치 {len(flows)}일")
    print(f"  {'':5}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}"
          f"{'장기MDD':>9}{'재진입':>7}{'실패':>5}{'매매':>6}")
    for n, r in M.items():
        print(f"  {n:5}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['사례']['total']:>+8.1f}%{r['장기']['mdd']:>8.1f}%{len(r['stints']):>6}{r['fails']:>5}{r['trades']:>6}")
    print("=" * 112)
    base = {a for a, _ in M["I3"]["stints"]}
    for n in SPECS9:
        mine = {a for a, _ in M[n]["stints"]}
        print(f"  {n} 재진입: I3 에만 {sorted(base - mine)} · {n} 에만 {sorted(mine - base)}")
    passed = []
    for n in SPECS9:
        checks = verdict(n, M[n], M["I3"])
        ok = all(x for _, x in checks)
        if ok:
            passed.append(n)
        print(f"  {n}: " + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"\n리그 입장({REGISTER_ON} 등록): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
