"""I3 규칙을 어느 자산에 쓸까 — KOSPI · S&P500 · 나스닥100 · 한미 반반 (2026-10-22, 탐색 비교).

운용자 질문: "ETF 중에 KODEX200 이 제일 좋은가? S&P500 도, 미국 탑10 도 있다."

⚠️ 탐색용이다. 여기서 1등을 골라 바로 바꾸면 '지난 20년 승자 고르기'(사후 선택)가 된다.
   채택하려면 기준을 따로 선언하고, 이후 실전 데이터로 확인한다.

조건
----
- 공정 비교를 위해 **세 자산 모두 지수로 만든다**(ETF 상장일이 제각각이라 기간이 안 맞는다):
  KOSPI(^KS11) · S&P500(^GSPC × USD/KRW) · 나스닥100(^NDX × USD/KRW), 원화·환노출, 한국 영업일 기준.
  가격지수라 배당은 빠져 있다(S&P500·KOSPI 연 1.5~2%, 나스닥 ~0.7%). 현금 이자 0.
- I3 규칙은 그대로, **재진입의 추세 확인만 각 자산 자기 지수의 120일선**으로(KOSPI 규칙을 미국 자산에 쓰지 않는다).
- 한미 반반: 각 50% 를 따로 I3 로 운용(각자 낙폭 예산), 매년 첫 영업일에 50:50 으로 되돌린다.
- 세금: 국내 상장 **해외** ETF 는 매매차익에 15.4%(배당소득세) — 시뮬레이션엔 넣지 않고 아래에 따로 추정한다.
  국내 주식형 ETF(KODEX200)는 매매차익 비과세.
- 미국테크TOP10(2021-04 상장)은 지수 이력이 없어 같은 방식으로 잴 수 없다 — 따로 적는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_holdout as H  # noqa: E402

WINDOWS = {"장기 2005~2026-08": ("2005-01-03", "2026-08-24"),
           "학습 2015-07~2026-08": ("2015-07-28", "2026-08-24"),
           "미공개 2026-08-25~10-21": ("2026-08-25", "2026-10-21")}
END = "2026-10-21"


def krw_index(code: str, ks: dict) -> dict[str, dict]:
    """미국 지수 × 원/달러 — 한국 영업일에 맞춰 직전 값으로 채움."""
    ix = L.load_bars(code, "2003-01-01", END)
    fx = L.load_bars("USD/KRW", "2003-01-01", END)
    out, li, lf = {}, None, None
    for d in sorted(ks):
        if d in ix:
            li = ix[d]["close"]
        if d in fx:
            lf = fx[d]["close"]
        if li and lf:
            out[d] = {"open": li * lf, "close": li * lf}
    return out


def run_i3(bars: dict, dates: list[str]) -> L.SimResult:
    return L.simulate({"A": L.Asset("A", bars)}, dates, H.i3(bars, bars, "A", None, *H.I3_DEFAULT), pass_nav=True)


def half_half(r1: L.SimResult, r2: L.SimResult) -> L.SimResult:
    """두 I3 곡선을 50:50 으로, 매년 첫 영업일에 재조정(각자 낙폭 예산은 그대로)."""
    out = L.SimResult()
    a = b = 0.5
    prev = None
    m1 = dict(zip(r1.dates, r1.curve))
    m2 = dict(zip(r2.dates, r2.curve))
    days = [d for d in r1.dates if d in m2]
    base1, base2, nav = m1[days[0]], m2[days[0]], 1.0
    for d in days:
        if prev and d[:4] != prev[:4]:
            base1, base2, a, b = m1[d], m2[d], nav / 2, nav / 2
        nav = a * m1[d] / base1 + b * m2[d] / base2
        out.dates.append(d)
        out.curve.append(nav)
        prev = d
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ks = L.load_bars("^KS11", "1996-01-01", END)
    spx, ndx = krw_index("^GSPC", ks), krw_index("^NDX", ks)
    start = "2004-01-02"
    dates = [d for d in sorted(ks) if start <= d <= END and d in spx and d in ndx]
    rows = {}
    for name, bars in (("KOSPI", ks), ("S&P500(원화)", spx), ("나스닥100(원화)", ndx)):
        rows[f"{name} 그냥 보유"] = L.buy_and_hold("A", dates, {d: bars[d] for d in dates})
        rows[f"{name} I3"] = run_i3({d: bars[d] for d in dates}, dates)
    rows["한미 반반 I3 (KOSPI+S&P500)"] = half_half(rows["KOSPI I3"], rows["S&P500(원화) I3"])
    rows["한미 반반 I3 (KOSPI+나스닥100)"] = half_half(rows["KOSPI I3"], rows["나스닥100(원화) I3"])

    for wname, (lo, hi) in WINDOWS.items():
        print("=" * 104)
        print(f"[{wname}]  ※ 가격지수(배당 제외)·현금 이자 0·세금 미반영")
        print(f"  {'전략':32}{'연수익':>8}{'최대낙폭':>9}{'최악연도':>9}{'구간수익':>10}")
        for name, res in rows.items():
            m = L.slice_metrics(res, lo, hi)
            print(f"  {name:32}{m['cagr']:>7.1f}%{m['mdd']:>8.1f}%{m['worst_year']:>+8.1f}%{m['total']:>+9.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
