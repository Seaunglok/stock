"""I3 매매 시각 — 다음 날 시가(현행·검증값) vs 장 시작 직후를 피하는 대안 (2026-10-22, 사전 선언).

운용자: "9시 매매는 가장 비싼 거 아냐? 주식은 9~10시 변동성이 커서 단타가 아니면 피했으면 한다."
실측(키움 5분봉, 10-06~10-21 11일): KODEX200 5분 고저폭 — 첫 5분 89bp · 09:05~10시 54bp · 10~15시 36bp.
또 09:00~09:05·15:20~15:30 은 ETF 유동성공급자(LP) 호가 의무가 없는 시간(삼성자산운용 안내).
흔들림이 크다는 것 자체는 '평균적으로 비싸다'가 아니다 — 11년 일봉으로 체결 시각만 바꿔 잰다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
변형(판단 규칙·파라미터는 그대로, 체결가만 바뀐다):
  NEXT_OPEN  다음 날 시가          — 현행·검증값
  NEXT_CLOSE 다음 날 종가          — '10시 이후 매매'의 끝점(장중 어느 시각이든 시가와 이 값 사이)
  SAME_CLOSE 판단한 날 종가        — '15:10 판단 → 15:15 매매'의 근사(종가로 판단·체결 → 낙관 쪽 근사)
판정 = 비열위(non-inferiority). 동기는 운용자 선호(장 초반 회피)라 '더 낫다'가 아니라 '나빠지지 않는다'를 본다:
  학습 FULL 에서 현행 대비  연수익 ≥ −TOL_CAGR_PP · MDD ≤ +TOL_MDD_PP · 최악연도 ≥ −TOL_WORST_PP
  그리고 격자(I3_GRID 9개) 중앙값에서도 같은 조건, 미공개 HOLDOUT 수익 ≥ 현행 − TOL_HO_PP.
채택 순서(선언): SAME_CLOSE 가 비열위면 그것(신호 당일 반영·LP 의무 시간대), 아니면 NEXT_CLOSE 가
비열위면 '다음 날 10시 이후', 둘 다 아니면 시가 유지 + 매수만 LP 의무 시간(09:05) 이후로.
한계: 일봉이라 장중 특정 시각(10:00·15:15)을 직접 못 잰다 — 끝점 두 개로 사이를 가둔다.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
TOL_CAGR_PP = 0.5
TOL_MDD_PP = 1.0
TOL_WORST_PP = 1.0
TOL_HO_PP = 1.0
VARIANTS = ("NEXT_OPEN", "NEXT_CLOSE", "SAME_CLOSE")
PREFERENCE = ("SAME_CLOSE", "NEXT_CLOSE")
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH = "069500", "153130"     # 검증 현금(이력 있는 쪽) — 시각 비교라 현금 종목은 결과에 영향 거의 없음


def fill_bars(bars: dict[str, dict], variant: str) -> dict[str, dict]:
    """체결가만 바꾼 일봉. simulate 는 '다음 날 open' 에 체결하므로 open 자리에 원하는 가격을 넣는다."""
    if variant == "NEXT_OPEN":
        return bars
    days = sorted(bars)
    if variant == "NEXT_CLOSE":
        return {d: {"open": bars[d]["close"], "close": bars[d]["close"]} for d in days}
    if variant == "SAME_CLOSE":          # d 의 open = 전날 종가 → '다음 날 open 체결' = 판단한 날 종가 체결
        out = {days[0]: dict(bars[days[0]])}
        for a, b in zip(days, days[1:]):
            out[b] = {"open": bars[a]["close"], "close": bars[b]["close"]}
        return out
    raise ValueError(variant)


def run(variant: str, m: float, lookback: int, kodex, cash, ks, dates) -> L.SimResult:
    fk, fc = fill_bars(kodex, variant), fill_bars(cash, variant)
    return L.simulate({BASE: L.Asset(BASE, fk), CASH: L.Asset(CASH, fc)}, dates,
                      H.i3(kodex, ks, BASE, CASH, m, lookback), EQUITY, pass_nav=True)


def spans(res: L.SimResult) -> dict:
    return {"전체": L.slice_metrics(res, *L.FULL), "박스권": L.slice_metrics(res, *L.PERIODS["박스권"]),
            "강세장": L.slice_metrics(res, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(res, *L.HOLDOUT)}


def non_inferior(s: dict, ref: dict) -> list[tuple[str, bool]]:
    return [("연수익", s["cagr"] >= ref["cagr"] - TOL_CAGR_PP),
            ("MDD", s["mdd"] <= ref["mdd"] + TOL_MDD_PP),
            ("최악연도", s["worst_year"] >= ref["worst_year"] - TOL_WORST_PP)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]

    dflt, grid = {}, {}
    for v in VARIANTS:
        dflt[v] = spans(run(v, *H.I3_DEFAULT, kodex, cash, ks, dates))
        rows = [spans(run(v, m, lb, kodex, cash, ks, dates))["전체"] for m, lb in H.I3_GRID]
        grid[v] = {k: statistics.median(r[k] for r in rows) for k in ("cagr", "mdd", "worst_year")}

    print("=" * 100)
    print(f"I3 체결 시각 비교 — 기본값 {H.I3_DEFAULT}, 예탁 {EQUITY:,.0f}원, 2015-07~2026-08 (+미공개 08-25~10-21)")
    print(f"  {'변형':12}{'연수익':>8}{'MDD':>7}{'최악연도':>9}{'박스권':>8}{'강세장':>8}{'미공개':>8}  | 격자 중앙값 연수익·MDD·최악")
    for v in VARIANTS:
        s, g = dflt[v], grid[v]
        print(f"  {v:12}{s['전체']['cagr']:>7.2f}%{s['전체']['mdd']:>6.1f}%{s['전체']['worst_year']:>+8.1f}%"
              f"{s['박스권']['cagr']:>7.1f}%{s['강세장']['cagr']:>7.1f}%{s['미공개']['total']:>+7.1f}%"
              f"  | {g['cagr']:.2f}% · {g['mdd']:.1f}% · {g['worst_year']:+.1f}%")

    print("=" * 100)
    ref, gref = dflt["NEXT_OPEN"], grid["NEXT_OPEN"]
    verdict = {}
    for v in VARIANTS[1:]:
        a = non_inferior(dflt[v]["전체"], ref["전체"])
        b = non_inferior(grid[v], gref)
        ho = dflt[v]["미공개"]["total"] >= ref["미공개"]["total"] - TOL_HO_PP
        ok = all(x for _, x in a) and all(x for _, x in b) and ho
        verdict[v] = ok
        print(f"  {v}: 기본값 {' '.join(n + ('O' if x else 'x') for n, x in a)} · 격자 "
              f"{' '.join(n + ('O' if x else 'x') for n, x in b)} · 미공개 {'O' if ho else 'x'} → {'비열위' if ok else '열위'}")
    pick = next((v for v in PREFERENCE if verdict.get(v)), None)
    print(f"\n선언된 채택 순서에 따른 결론: {pick or '시가 유지 + 매수만 09:05 이후'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
