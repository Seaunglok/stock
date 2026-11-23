"""11세대 — 세 시장 I3: KODEX200 · 미국 S&P500(환헤지) · 금(환헤지)을 1/3씩, 각자 I3 엔진 (2026-11-23, 사전 선언 · 측정 전).

운용자(11-23) "3자리를 다 채우지말고 1자리 채우자" → 방향 질문에 「세 시장 I3」 선택.

진단 (부모 I3 의 강점·약점 — 우리 진단, 결과표에서 고른 게 아니다)
  · 강점: 낙폭 축소는 타이밍 덕(㉘ `lab_i3_overfit` — 같은 노출 무작위 대비 p_MDD 0.0004·0.009). 이 엔진을 그대로 쓴다.
  · 약점: **한 시장 · 사실상 두 종목** — KODEX200 은 삼성전자·SK하이닉스 약 58~62%(11-19 구성 평가), I3 는 반도체 두 종목의 타이밍이다.
    집중이 낮은 한국 지수 ETF 는 없다(㉖ `lab_lowconc_etf` — 대상 없음) → 집중을 줄이는 길은 **다른 시장과 나누기**뿐(㉖ 결론).
    리그의 한미반반은 나스닥100 이라 반도체와 같이 움직여(같은 AI·반도체 국면) 나누는 효과가 약하다 → 넓은 미국 지수 + 금.
  · 문헌: 여러 자산군에 추세 타이밍을 각각 걸면 낙폭이 준다(Faber 2007 'A Quantitative Approach to Tactical Asset Allocation' ·
    Hurst·Ooi·Pedersen 2017 'A Century of Evidence on Trend-Following'). 리그의 Faber10·TSMOM 은 월말 규칙 — 여기선 I3 엔진(일간)을
    각 시장에 그대로.

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  몫     KR = KODEX200(069500), 재진입 시장 확인 KOSPI(^KS11)>120일선 — I3 그대로.
         US = KODEX 미국S&P500선물(H)(219480), 재진입 확인 자기 120일선(한미반반·HH1 의 미국 몫과 같은 방식).
         GOLD = KODEX 골드선물(H)(132030), 재진입 확인 자기 120일선.
         엔진·낙폭 예산은 몫마다 `lab_challengers.i3x(**SPECS['I3'])`(m 6 · 252일 · 바닥 82% · 밴드 10% — 숫자를 새로 고르지 않는다).
  합치기 1/3 씩 출발, **매년 첫 거래일 종가에 1/3 로 되돌린다**(옮긴 금액 × 편도 비용 × 2 를 뺀다 — `lab_aggr_gen3.combine` 의 세 몫판).
         몫의 낙폭 예산은 자기 자산 곡선으로 재므로 되돌려도 몫의 판단은 같다(비례).
  체결   종가 판단 → 다음 날 시가(strategy_lab.simulate), 정수 주식, 몫마다 예탁 364만원 ÷ 3, 현금 153130(검증 — I3 와 같다), 비용 가정 그대로.
         미국 ETF 는 2015-05-29 부터라 출발(2015-07-28) 뒤 처음 몇 달은 엔진 이력이 짧다(엔진은 첫날 보유로 시작 — I3 와 같은 규칙).
  구간   학습 FULL 2015-07-28~2026-08-24 · 미공개 HOLDOUT 2026-08-25~10-21 · 박스권·강세장·6월 사례(lab_gen4.spans 그대로).
         장기 LONG 2001-09-03~2026-08-24 — 대용 지수 ^KS11 · ^GSPC(달러 값 = 환헤지와 같은 셈) · GC=F(금 선물 연속, 2000-08~ — 그래서
         1998 이 아니라 2001-09 부터). **I3 기준값도 같은 구간으로 다시 잰다**(G6 를 같은 창에서 비교).
  입장 조건(전부, I3 대비 — 6~9세대와 같은 `lab_gen6.verdict`): E1 학습 MDD ≤ 20% · 최악연도 ≥ −10% ·
         G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p) · G3 미공개 ≥ I3 − 1%p ·
         G6 장기 MDD ≤ I3 + 3%p.
  보고만 몫별 평균 위험 비중 · I3 와 일간 수익 상관 · 박스권·강세장·6월 사례 · 매매 수.
  통과하면 I3 리그 등록 REGISTER_ON 2026-12-01(12월 신규 1 — 운용자 "1자리") · 실전 현금 자리 488770(리그 공통) · 승격 판정은 등록일부터
         (㉔ 통계 조건 포함). 시험 장부 +1.

결과 (6476629 선언대로 1회, 기준 수정 없음) — **G2 미달로 탈락**
            연수익    MDD    최악    박스권   강세장   미공개   6월 사례  장기MDD  매매
  I3        12.61%  19.8%  −6.1%    6.2%   15.6%   −2.7%   −10.5%    28.4%   355
  M11a       8.48%  10.5%  −5.4%    1.7%   11.7%   −1.8%    −4.7%    13.5%   877     E1 O · G2 X · G3 O · G6 O
  보고만  몫별: KR 11.81%·MDD 19.2% · US(219480) 5.24%·16.7% · 금(132030) 6.01%·18.0% · I3 와 일간 수익 상관 0.77
읽는 법
  · 나누기는 낙폭을 반으로 줄였다(학습 19.8 → 10.5% · 장기 28.4 → 13.5% · 6월 급락 −10.5 → −4.7%) — 진단(한 시장 집중)은 맞았다.
  · 그러나 연 −4.1%p. 미국 몫이 5.2% 에 그쳤다 — 환헤지 비용(원화 금리 < 달러 금리)과 I3 엔진의 휩쏘(미국 몫 매매 247번)가 S&P500 의
    상승을 깎았다. 금 몫도 6.0%. 한국 몫만 I3 에 가깝다(11.8%). G2 는 '낙폭을 줄이면 수익은 0.5%p 까지만 내준다'라 탈락.
  · 연수익 ÷ MDD 는 0.81(I3 0.64)로 더 효율적이다 — 운용자 제1원칙이 MDD 라 의미가 있지만, 선언 기준은 G2 그대로다(규칙 1).
    넣으려면 R6·D5a 처럼 **운용자 예외**로만. 다시 재지 않는다(몫·비중·재조정을 바꾼 변형도 이 결과를 보고 만든 것이 된다).
"""
from __future__ import annotations

import contextlib
import io
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_challengers as CH  # noqa: E402
import lab_gen4 as G4  # noqa: E402
import lab_gen6 as G6  # noqa: E402
import lab_holdout as H  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
NAME = "M11a"
DECLARED_ON = "2026-11-23"
REGISTER_ON = "2026-12-01"
KR, US, GOLD = "069500", "219480", "132030"
KOSPI = "^KS11"
SLEEVES = {KR: KOSPI, US: US, GOLD: GOLD}              # 몫 → 재진입 시장 확인에 쓰는 가격
LONG = ("2001-09-03", "2026-08-24")
LONG_PROXY = {KR: "^KS11", US: "^GSPC", GOLD: "GC=F"}
EQUITY, END, CASH = G4.EQUITY, G4.END, G4.CASH
SIDE_COST = L.side_cost(False, False)


def combine_n(curves: list[tuple[list[str], list[float]]], side_cost: float = SIDE_COST) -> L.SimResult:
    """몫 곡선들을 더한다 — 첫 몫의 날짜 중 모든 몫에 값이 있는 날만, 매년 첫 거래일 종가에 같은 비중으로 되돌리고
    옮긴 금액 합 × 편도 비용 × 2 를 뺀다(`lab_aggr_gen3.combine` 의 n 몫판)."""
    maps = [dict(zip(ds, cs)) for ds, cs in curves]
    n = len(maps)
    units = [1.0] * n
    out = L.SimResult()
    prev = None
    for d in curves[0][0]:
        if any(d not in m for m in maps):
            continue
        vals = [u * m[d] for u, m in zip(units, maps)]
        if prev is not None and d[:4] != prev[:4]:
            nav = sum(vals)
            moved = sum(abs(v - nav / n) for v in vals) / 2
            nav -= 2 * side_cost * moved
            units = [(nav / n) / m[d] for m in maps]
            vals = [nav / n] * n
        out.dates.append(d)
        out.curve.append(sum(vals))
        prev = d
    return out


def sleeve_target(bars: dict, regime: dict, asset: str, cash: str | None):
    m, lb = H.I3_DEFAULT
    return CH.i3x(bars, regime, asset, cash, m, lb, **CH.SPECS["I3"])


def run_full(px: dict, dates: list[str], equity: float = EQUITY, cash: str = CASH) -> tuple[L.SimResult, dict]:
    """학습·미공개 재생 — 몫마다 정수 주식 시뮬레이션 → combine_n. (합친 결과, 몫별 SimResult)"""
    sims = {}
    for asset, reg in SLEEVES.items():
        t = sleeve_target(px[asset], px[reg], asset, cash)
        sims[asset] = L.simulate({asset: L.Asset(asset, px[asset]), cash: L.Asset(cash, px[cash])},
                                 [d for d in dates if d in px[cash]], t, equity / len(SLEEVES), pass_nav=True)
    comb = combine_n([(s.dates, s.curve) for s in sims.values()])
    comb.trades = sum(s.trades for s in sims.values())
    return comb, sims


def run_long(px: dict, long_dates: dict[str, list[str]]) -> L.SimResult:
    """장기 스트레스 — 대용 지수에 소수 단위, 현금 0. 몫마다 자기 달력 → KOSPI 달력에 마지막 값으로 맞춘 뒤 합친다."""
    curves = []
    kd = long_dates[KR]
    for asset, proxy in LONG_PROXY.items():
        b = px[proxy]
        r = L.simulate({"IDX": L.Asset("IDX", b)}, long_dates[asset], sleeve_target(b, b, "IDX", None), 0.0,
                       pass_nav=True)
        m = dict(zip(r.dates, r.curve))
        first = r.curve[0]
        last, filled = None, []
        for d in kd:
            last = m.get(d, last)
            filled.append((last if last is not None else first) / first)
        curves.append((kd, filled))
    return combine_n(curves)


def i3_ref(px: dict, dates: list[str], long_kd: list[str]) -> dict:
    """I3 기준값 — 같은 자료·같은 구간(학습은 lab_gen6.measure 와 같은 길, 장기는 LONG 창)."""
    m, lb = H.I3_DEFAULT
    t = CH.i3x(px[KR], px[KOSPI], KR, CASH, m, lb, **CH.SPECS["I3"])
    res = L.simulate({KR: L.Asset(KR, px[KR]), CASH: L.Asset(CASH, px[CASH])}, dates, t, EQUITY, pass_nav=True)
    ks = px["^KS11"]
    lr = L.simulate({"IDX": L.Asset("IDX", ks)}, long_kd, CH.i3x(ks, ks, "IDX", None, m, lb, **CH.SPECS["I3"]), 0.0,
                    pass_nav=True)
    out = G4.spans(res)
    out["장기"] = L.metrics(lr.dates, lr.curve)
    out["trades"] = res.trades
    out["_res"] = res
    return out


def load() -> dict:
    px = {}
    with contextlib.redirect_stdout(io.StringIO()):
        for c in (KR, US, GOLD, CASH):
            px[c] = L.load_bars(c, "2014-01-01", END)
        for c in ("^KS11", "^GSPC", "GC=F"):
            px[c] = L.load_bars(c, "1996-01-01", END)
    return px


def daily(r: L.SimResult) -> dict[str, float]:
    return {b: y / x - 1 for a, b, x, y in zip(r.dates, r.dates[1:], r.curve, r.curve[1:]) if x > 0}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    px = load()
    dates = [d for d in L.calendar(px[KR], L.FULL[0], END) if d in px[CASH]]
    long_dates = {a: L.calendar(px[p], *LONG) for a, p in LONG_PROXY.items()}
    ref = i3_ref(px, dates, long_dates[KR])
    comb, sims = run_full(px, dates)
    r = G4.spans(comb)
    r["장기"] = L.metrics(*(lambda x: (x.dates, x.curve))(run_long(px, long_dates)))
    r["trades"] = comb.trades
    a, b = daily(comb), daily(ref["_res"])
    common = sorted(set(a) & set(b))
    corr = statistics.correlation([a[d] for d in common], [b[d] for d in common])
    print("=" * 112)
    print(f"11세대 세 시장 I3 — 학습 {L.FULL[0]}~{L.FULL[1]} · 예탁 {EQUITY:,.0f}원(몫마다 1/3) · 장기 {LONG[0]}~{LONG[1]}")
    print(f"  {'':6}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}{'장기MDD':>9}{'매매':>6}")
    for n, x in (("I3", ref), (NAME, r)):
        print(f"  {n:6}{x['전체']['cagr']:>7.2f}%{x['전체']['mdd']:>6.1f}%{x['전체']['worst_year']:>+6.1f}%"
              f"{x['박스권']['cagr']:>7.1f}%{x['강세장']['cagr']:>7.1f}%{x['미공개']['total']:>+7.1f}%"
              f"{x['사례']['total']:>+8.1f}%{x['장기']['mdd']:>8.1f}%{x['trades']:>6}")
    for asset, s in sims.items():
        m = L.metrics(s.dates, s.curve)
        print(f"    보고만 몫 {asset}: 연수익 {m['cagr']:.2f}% · MDD {m['mdd']:.1f}% · 매매 {s.trades}")
    print(f"    보고만 I3 와 일간 수익 상관 {corr:.2f} ({len(common)}일)")
    checks = G6.verdict(r, ref)
    ok = all(x for _, x in checks)
    print("=" * 112)
    print(f"  {NAME}: " + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks)
          + f" → {'리그 입장(' + REGISTER_ON + ' 등록)' if ok else '탈락'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
