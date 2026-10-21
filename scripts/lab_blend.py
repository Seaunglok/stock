"""전략 조합 — 서로 다르게 움직이는 수익원을 섞는다 (2026-10-22 선언, 측정 전).

지금까지 7개 계열이 전부 기각됐다. 제1원칙(MDD ≤ 20%)을 지킨 것은 D(위험관리, MAR 0.88)뿐이었고,
수익 목표(CAGR ≥ 21.8%)를 넘은 것은 B(레버리지+추세필터)·C(듀얼모멘텀)였지만 낙폭이 40~60% 였다.
상관이 낮은 수익원을 섞으면 위험 대비 수익이 각 구성요소보다 좋아질 수 있다(메달리온식 분산).

선언 (구성요소는 이미 선언·측정된 기본값을 그대로 쓴다 — 여기서 다시 고르지 않는다)
----------------------------------------------------------------------------------
G1  α·C + (1−α)·D     C = 듀얼모멘텀 12개월, D = 위험관리 (L60, σ12%)
                      격자 α ∈ {0.3, 0.4, 0.5, 0.6, 0.7}, 기본 0.5
G2  α·B + (1−α)·D     B = 레버리지(122630) + KOSPI>MA60
                      격자 α ∈ {0.2, 0.3, 0.4, 0.5}, 기본 0.3

조합 방식: 각 구성요소가 자기 일정대로 목표 비중을 내면(C·D 월말, B 신호 변화 시), 그 시점의
구성요소별 최신 비중을 α 로 가중합해 전체를 다시 맞춘다. 레버리지(비중 합 > 1)는 쓰지 않는다.

판정: strategy_lab 잣대 그대로 — 기본값 ①~④ + 격자 중앙값 ①~④.
장기 스트레스: 채권·금·달러 ETF 가 2014-07 부터라 조합의 장기 데이터가 없다 — 해당 없음.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_buffett as LB  # noqa: E402
import lab_index_candidates as LI  # noqa: E402

EQUITY = 3_852_844.0
G1_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)
G1_DEFAULT = 0.5
G2_GRID = (0.2, 0.3, 0.4, 0.5)
G2_DEFAULT = 0.3


def blend(parts: list[tuple[float, object]]):
    """parts = [(α, target_fn)] → 조합 target_fn. 구성요소 중 하나라도 새 비중을 내면 전체를 재조합."""
    latest: list[dict[str, float]] = [{} for _ in parts]

    def target(i: int, d: str):
        changed = False
        for k, (_, fn) in enumerate(parts):
            w = fn(i, d)
            if w is not None:
                latest[k] = w
                changed = True
        if not changed:
            return None
        out: dict[str, float] = {}
        for k, (a, _) in enumerate(parts):
            for c, x in latest[k].items():
                out[c] = out.get(c, 0.0) + a * x
        return out
    return target


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    codes = sorted(set(LB.D_ASSETS) | {LB.CASH_ETF, "114260", "122630"})
    bars = {c: L.load_bars(c, "2014-01-01", L.FULL[1]) for c in codes}
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    dates = L.calendar(bars["069500"], *L.FULL)
    nxt_map = {d: dates[k + 1] for k, d in enumerate(dates[:-1])}
    bench = L.buy_and_hold("069500", dates, bars["069500"], EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    px = LB.Prices(bars)
    print(f"잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% ③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p "
          f"④박스권·강세장 각각 ≥벤치 ⑤격자 중앙값 · 예탁 {EQUITY:,.0f}원")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))

    def assets():
        return {c: L.Asset(c, b) for c, b in bars.items()}

    def comp_c():
        t, nxt = LI.dual_momentum({c: bars[c] for c in ("069500", "133690", "114260")}, LI.DEFAULT_DM)
        nxt.update(nxt_map)
        return t

    def comp_d():
        return LB.strat_d(px, dates, *LB.D_DEFAULT)

    def comp_b():
        return LI.ma_filter(ks, LI.DEFAULT_MA, "122630")

    # 구성요소 단독 성적(참고 — 이미 측정된 기본값과 같아야 한다)
    for label, fn in (("[참고] C 듀얼모멘텀 12개월", comp_c()), ("[참고] D 위험관리 L60·σ12%", comp_d()),
                      ("[참고] B 레버리지+MA60", comp_b())):
        s, _, _ = L.evaluate(L.simulate(assets(), dates, fn, EQUITY), bench)
        print(L.fmt_row(label, s))

    verdicts = {}
    for fam, grid, default, make in (
            ("G1 C+D", G1_GRID, G1_DEFAULT, lambda a: blend([(a, comp_c()), (1 - a, comp_d())])),
            ("G2 B+D", G2_GRID, G2_DEFAULT, lambda a: blend([(a, comp_b()), (1 - a, comp_d())]))):
        runs = [(f"α{a:.1f}", L.simulate(assets(), dates, make(a), EQUITY)) for a in grid]
        verdicts[fam] = LB._family(fam, runs, f"α{default:.1f}", bench)
    print("=" * 100)
    print("최종: " + " · ".join(f"{k} {'채택 가능' if v else '기각'}" for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
