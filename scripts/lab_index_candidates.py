"""지수형 후보 3종 — 운용자 잣대(strategy_lab) 로 판정 (2026-10-22 선언, 측정 전).

10-21 탐색 비교(docs/2026-10-21-candidate-data-comparison.md)에서 본 세 계열을 **사전 선언한
격자와 기본값**으로 다시 잰다. 그때는 MA60·MA200 두 점만 봤다 — 한 점만 좋은 것인지,
'보통의 설정'도 좋은 것인지(⑤)를 이번에 가린다.

선언
----
A. 지수+추세필터    KODEX200 보유 ⇔ KOSPI 종가 > MA(n).  격자 n = GRID_MA, 기본 60(라이브 레짐 게이트)
B. 레버리지+추세필터 KODEX레버리지(122630) 보유 ⇔ 같은 조건. 격자·기본 동일
C. 듀얼모멘텀       월말마다 KODEX200 vs TIGER나스닥100 중 최근 m개월 수익이 큰 쪽,
                    그것이 국고채3년(114260) 보다 약하면 국고채.  격자 m = GRID_DM, 기본 12

계열 채택 조건: 기본값이 ①~④ 충족 **그리고** 격자 중앙값이 ①~④ 충족(⑤)
               **그리고** 장기 스트레스 데이터가 있는 계열은 격자 중앙값이 장기 ①② 충족.
장기 스트레스: A 는 ^KS11 자체, B 는 ^KS11 일간 2배 합성(보수 연 0.64%) — 1998-01~2026-08.
C 는 장기 데이터가 없다(국내 상장 ETF 2014-07~).

체결·비용·예탁(3,852,844원, 정수 주식수)은 strategy_lab 과 같다. 현금 이자 0.
"""
from __future__ import annotations

import bisect
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402

EQUITY = 3_852_844.0
GRID_MA = (20, 40, 60, 80, 100, 120, 150, 200, 250)
DEFAULT_MA = 60
GRID_DM = (3, 6, 9, 12)
DEFAULT_DM = 12
LONG_STRESS = ("1998-01-02", "2026-08-24")   # ^KS11 이 1996-12 부터 — MA250 워밍업 뒤


def ma_filter(signal: dict[str, dict], n: int, asset: str):
    """KOSPI 종가 > MA(n) 이면 asset 100%, 아니면 현금. 그날까지의 종가만 쓴다(미래 정보 없음)."""
    days = sorted(signal)
    pos = {d: k for k, d in enumerate(days)}
    closes = [signal[d]["close"] for d in days]

    def target(i: int, d: str) -> dict[str, float] | None:
        k = pos.get(d)
        if k is None or k + 1 < n:
            return {}
        ma = sum(closes[k + 1 - n:k + 1]) / n
        return {asset: 1.0} if closes[k] > ma else {}
    return target


def dual_momentum(bars: dict[str, dict[str, dict]], months: int,
                  risky=("069500", "133690"), safe="114260"):
    """월말 리밸런싱. 수익 비교는 그날까지의 종가로만(21×months 영업일 전 대비)."""
    look = 21 * months
    series = {c: (sorted(b), [b[d]["close"] for d in sorted(b)]) for c, b in bars.items()}
    state: dict[str, str | None] = {"cur": None}

    def ret(code: str, d: str) -> float | None:
        ds, cs = series[code]
        k = bisect.bisect_right(ds, d) - 1
        if k < look:
            return None
        return cs[k] / cs[k - look] - 1

    def target(i: int, d: str) -> dict[str, float] | None:
        nxt = calendar_next.get(d)
        month_end = nxt is None or nxt[:7] != d[:7]
        if state["cur"] is not None and not month_end:
            return None
        rs = {c: ret(c, d) for c in (*risky, safe)}
        cands = [c for c in risky if rs[c] is not None]
        if not cands:
            return {}
        best = max(cands, key=lambda c: rs[c])
        pick = best if rs[best] > (rs[safe] if rs[safe] is not None else 0.0) else safe
        state["cur"] = pick
        return {pick: 1.0}
    calendar_next: dict[str, str] = {}
    return target, calendar_next


def _evaluate_family(name: str, runs: list[tuple[str, L.SimResult]], default_label: str,
                     bench: L.SimResult, long_runs: list[tuple[str, L.SimResult]] | None) -> bool:
    print("=" * 96)
    print(f"[{name}]")
    print(L.HEADER + "   판정")
    evals = []
    default_ok = False
    for label, res in runs:
        s, b, rows = L.evaluate(res, bench)
        evals.append(s)
        ok = L.passed(rows)
        mark = "◆" if label == default_label else " "
        if label == default_label:
            default_ok = ok
        print(L.fmt_row(f"{mark}{label}", s) + f"   {'통과' if ok else '미달'}")
    med = L.robustness(evals)
    _, b, _ = L.evaluate(runs[0][1], bench)
    med_rows = L.judge(med, b)
    print(L.fmt_row(" 격자 중앙값", med) + f"   {'통과' if L.passed(med_rows) else '미달'}")
    for n_, ok, txt in med_rows:
        print(f"      [{'O' if ok else 'X'}] {n_}: {txt}")
    long_ok = True
    if long_runs:
        lm = [L.metrics(r.dates, r.curve) for _, r in long_runs]
        med_long = {"mdd": statistics.median(m["mdd"] for m in lm),
                    "worst_year": statistics.median(m["worst_year"] for m in lm)}
        rows = L.judge_long(med_long)
        long_ok = L.passed(rows)
        print(f"  장기 스트레스 {LONG_STRESS[0]}~{LONG_STRESS[1]} (격자별 MDD / 최악연도):")
        print("    " + " · ".join(f"{lb} {m['mdd']:.0f}%/{m['worst_year']:+.0f}%" for (lb, _), m in zip(long_runs, lm)))
        for n_, ok, txt in rows:
            print(f"      [{'O' if ok else 'X'}] 중앙값 {n_}: {txt}")
    verdict = default_ok and L.passed(med_rows) and long_ok
    print(f"  → {name}: {'채택 가능' if verdict else '기각'} "
          f"(기본값 {'O' if default_ok else 'X'} · 격자 중앙값 {'O' if L.passed(med_rows) else 'X'}"
          + (f" · 장기 {'O' if long_ok else 'X'}" if long_runs else "") + ")")
    return verdict


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    kodex = L.load_bars("069500", "2014-01-01", L.FULL[1])
    lev = L.load_bars("122630", "2014-01-01", L.FULL[1])
    ndx = L.load_bars("133690", "2014-01-01", L.FULL[1])
    bond = L.load_bars("114260", "2014-01-01", L.FULL[1])
    dates = L.calendar(kodex, *L.FULL)
    bench = L.buy_and_hold("069500", dates, kodex, EQUITY)
    bs, _, brows = L.evaluate(bench, bench)
    print(f"잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% ③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p "
          f"④박스권·강세장 각각 ≥벤치 ⑤격자 중앙값도 충족 · 예탁 {EQUITY:,.0f}원")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))

    verdicts = {}
    for fam, asset_code, asset_bars, long_bars in (
            ("A 지수+추세필터", "069500", kodex, ks),
            ("B 레버리지+추세필터", "122630", lev, L.leveraged_bars(ks))):
        runs = []
        for n in GRID_MA:
            res = L.simulate({asset_code: L.Asset(asset_code, asset_bars)}, dates,
                             ma_filter(ks, n, asset_code), EQUITY)
            runs.append((f"MA{n}", res))
        long_dates = L.calendar(long_bars, *LONG_STRESS)
        long_runs = [(f"MA{n}", L.simulate({"IDX": L.Asset("IDX", long_bars)}, long_dates,
                                           ma_filter(ks, n, "IDX")))
                     for n in GRID_MA]
        verdicts[fam] = _evaluate_family(fam, runs, f"MA{DEFAULT_MA}", bench, long_runs)

    runs = []
    assets = {c: L.Asset(c, b) for c, b in (("069500", kodex), ("133690", ndx), ("114260", bond))}
    for m in GRID_DM:
        tgt, nxt = dual_momentum({c: a.bars for c, a in assets.items()}, m)
        nxt.update({d: dates[k + 1] for k, d in enumerate(dates[:-1])})
        runs.append((f"{m}개월", L.simulate(assets, dates, tgt, EQUITY)))
    verdicts["C 듀얼모멘텀"] = _evaluate_family("C 듀얼모멘텀", runs, f"{DEFAULT_DM}개월", bench, None)

    print("=" * 96)
    print("최종: " + " · ".join(f"{k} {'채택 가능' if v else '기각'}" for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
