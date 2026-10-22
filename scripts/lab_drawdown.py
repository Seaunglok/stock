"""낙폭 감지 이탈 — 고점 대비 X% 빠지면 빠지고, 회복이 확인되면 다시 들어간다 (2026-10-22 선언, 측정 전).

운용자 지적(10-22): "낙폭을 감지하고 빼면 최대 낙폭을 막을 수 있다. 그런 전략을 만드는 게 우리 몫."
지금까지의 A·B 는 '이동평균 위/아래' 로만 들락거렸다. 이번엔 **낙폭 자체**를 직접 감지한다.
2026-06-22 → 07-30 KODEX200 −40.8%(5주) 같은 급락에서 −X% 지점에 빠지면 나머지를 피한다.
문제는 두 가지다 — ① 갭 하락은 X% 보다 더 빠진 뒤에야 체결된다(다음 날 시가) ② 다시 들어가는
시점이 늦으면 반등을 놓치고, 박스권에선 들락거리다 비용·휩쏘로 깎인다. 그래서 측정한다.

선언 (격자·기본값 측정 전 고정)
--------------------------------
규칙: 보유 중 종가가 '진입 후 최고 종가' 대비 X% 이상 하락 → 다음 날 시가에 전량 매도, 현금 대용
      ETF(KODEX단기채권 153130). 현금 상태에서 종가가 **직전 n일 최고 종가를 넘으면**(회복 확인)
      → 다음 날 시가에 재진입하고 최고 종가를 새로 잰다. 시작일엔 보유로 출발.
H1  KODEX200(069500)      격자 X ∈ {5, 8, 10, 12, 15}% × n ∈ {10, 20, 40}일, 기본 (10%, 20일)
H2  KODEX레버리지(122630)  같은 격자·기본값

판정: strategy_lab 잣대(기본값 ①~④ + 격자 중앙값 ①~④) **그리고** 장기 스트레스(1998~2026,
외환위기 직후·닷컴·금융위기) 격자 중앙값 ①②. 장기는 H1 = ^KS11 자체, H2 = ^KS11 일간 2배 합성
(보수 연 0.64%, 낙관 쪽), 현금 이자 0(보수적).
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

EQUITY = 3_852_844.0
CASH_ETF = "153130"
GRID = tuple((x, n) for x in (5, 8, 10, 12, 15) for n in (10, 20, 40))
DEFAULT = (10, 20)
LONG_STRESS = ("1998-01-02", "2026-08-24")


def drawdown_exit(bars: dict[str, dict], asset: str, x_pct: float, n: int, cash: str | None):
    """그날까지의 종가만 쓴다. 보유 → 진입 후 최고 대비 −x% 면 이탈, 현금 → 직전 n일 최고 돌파 시 재진입."""
    days = sorted(bars)
    pos = {d: k for k, d in enumerate(days)}
    closes = [bars[d]["close"] for d in days]
    out_w = {cash: 1.0} if cash else {}
    st = {"in": True, "peak": None, "started": False}

    def target(i: int, d: str):
        k = pos.get(d)
        if k is None:
            return None
        c = closes[k]
        if not st["started"]:
            st["started"] = True
            st["peak"] = c
            return {asset: 1.0}
        if st["in"]:
            st["peak"] = max(st["peak"], c)
            if c <= st["peak"] * (1 - x_pct / 100.0):
                st["in"] = False
                return out_w
            return None
        if k >= n and c > max(closes[k - n:k]):
            st["in"] = True
            st["peak"] = c
            return {asset: 1.0}
        return None
    return target


def _family(name: str, asset: str, asset_bars: dict, long_bars: dict, dates: list[str],
            cash_bars: dict, bench: L.SimResult) -> bool:
    print("=" * 100)
    print(f"[{name}]")
    print(L.HEADER + "   판정  (매매횟수)")
    evals, default_ok = [], False
    for x, n in GRID:
        assets = {asset: L.Asset(asset, asset_bars), CASH_ETF: L.Asset(CASH_ETF, cash_bars)}
        res = L.simulate(assets, dates, drawdown_exit(asset_bars, asset, x, n, CASH_ETF), EQUITY)
        s, b, rows = L.evaluate(res, bench)
        evals.append(s)
        ok = L.passed(rows)
        label = f"X{x}%·n{n}"
        if (x, n) == DEFAULT:
            default_ok = ok
        print(L.fmt_row(("◆" if (x, n) == DEFAULT else " ") + label, s)
              + f"   {'통과' if ok else '미달'}  ({res.trades})")
    _, b, _ = L.evaluate(res, bench)
    med = L.robustness(evals)
    med_rows = L.judge(med, b)
    print(L.fmt_row(" 격자 중앙값", med) + f"   {'통과' if L.passed(med_rows) else '미달'}")
    for nm, ok, txt in med_rows:
        print(f"      [{'O' if ok else 'X'}] {nm}: {txt}")
    long_dates = L.calendar(long_bars, *LONG_STRESS)
    lm = []
    for x, n in GRID:
        r = L.simulate({"IDX": L.Asset("IDX", long_bars)}, long_dates, drawdown_exit(long_bars, "IDX", x, n, None))
        lm.append(((x, n), L.metrics(r.dates, r.curve)))
    med_long = {"mdd": statistics.median(m["mdd"] for _, m in lm),
                "worst_year": statistics.median(m["worst_year"] for _, m in lm)}
    long_rows = L.judge_long(med_long)
    print(f"  장기 스트레스 {LONG_STRESS[0]}~{LONG_STRESS[1]} (X·n: CAGR / MDD / 최악연도):")
    for (x, n), m in lm:
        mark = "◆" if (x, n) == DEFAULT else " "
        print(f"    {mark}X{x}%·n{n}: {m['cagr']:+.1f}% / {m['mdd']:.0f}% / {m['worst_year']:+.0f}%")
    for nm, ok, txt in long_rows:
        print(f"      [{'O' if ok else 'X'}] 중앙값 {nm}: {txt}")
    verdict = default_ok and L.passed(med_rows) and L.passed(long_rows)
    print(f"  → {name}: {'채택 가능' if verdict else '기각'} (기본값 {'O' if default_ok else 'X'} · "
          f"격자 중앙값 {'O' if L.passed(med_rows) else 'X'} · 장기 {'O' if L.passed(long_rows) else 'X'})")
    return verdict


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars("069500", "2014-01-01", L.FULL[1])
    lev = L.load_bars("122630", "2014-01-01", L.FULL[1])
    cash = L.load_bars(CASH_ETF, "2014-01-01", L.FULL[1])
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    dates = L.calendar(kodex, *L.FULL)
    bench = L.buy_and_hold("069500", dates, kodex, EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    print(f"잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% ③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p "
          f"④박스권·강세장 각각 ≥벤치 ⑤격자 중앙값 · 장기 ①② · 예탁 {EQUITY:,.0f}원")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))
    v1 = _family("H1 KODEX200 낙폭 이탈", "069500", kodex, ks, dates, cash, bench)
    v2 = _family("H2 레버리지 낙폭 이탈", "122630", lev, L.leveraged_bars(ks), dates, cash, bench)
    print("=" * 100)
    print(f"최종: H1 {'채택 가능' if v1 else '기각'} · H2 {'채택 가능' if v2 else '기각'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
