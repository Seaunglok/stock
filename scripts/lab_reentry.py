"""I3 강세장 재진입 개선 — 재진입 때 낙폭 예산의 기준점을 다시 잡는다 (2026-10-22, 사전 선언).

운용자: "강세장 재진입 개선 한번 봐줘."

진단(측정 전, 설명용 — scratchpad bull_diag)
-------------------------------------------
강세장(2019~2026-08) 엔진 보유일의 93% 에서 낙폭 예산이 비중을 깎았고, 그로 놓친 수익(단순합)
28.3%p 중 **27.8%p 가 재진입 후 60영업일 안**이다. 재진입 9회의 진입 비중 평균 54%(2025-04 32%,
2026-06 33%). 이유: 엔진이 −10% 로 이탈한 뒤 다시 들어올 때 자산은 1년 최고치보다 ~10% 아래 →
비중 = 6 × (0.90 − 0.82)/0.90 ≈ 53%. 새 상승 추세를 확인하고도 절반만 들고 들어간다.
엔진만(I1a) 강세장 21.3% vs I3 15.6% vs 보유 23.2% — 차이의 대부분이 예산이다.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
후보(엔진·m·L·바닥 18%·10%p 밴드는 I3 그대로, 재진입 때 기준점만 바뀐다):
  R1 재진입 리셋     재진입한 날의 자산을 새 기준점으로 — 바닥 = 82% × (재진입 이후 최고치). 진입 비중 100%.
                     약점: 재진입이 연달아 실패하면(닷컴 휩쏘) 누적 손실 상한이 없다.
  R2 리셋 + 누적 상한 바닥 = max(82% × 재진입 이후 최고치, (1 − CAP_DD) × 1년 최고치). CAP_DD = 20% 는
                     운용자 ① MDD 한도 그대로 — 기준점을 다시 잡아도 1년 최고치 대비 20% 아래로는 위험을 안 진다.
채택 조건(전부):
  ① 학습 MDD ≤ 20% · ② 최악연도 ≥ −10% — 기본값과 격자(I3_GRID) 중앙값 둘 다 (I3 가 지키는 선)
  ③ 강세장 연수익 ≥ I3 + MIN_BULL_GAIN_PP — 기본값과 격자 중앙값 둘 다
  ④ 전반(2015-07~2020)·후반(2021~2026-08) 각각 연수익 ≥ I3 — 한 국면(2025~26)에만 기대지 않는다
  ⑤ 박스권 연수익 ≥ I3 − 0.5%p
  ⑥ 장기 스트레스(1998~, KOSPI 지수) 격자 중앙값 MDD ≤ I3 + 2%p · 최악연도 ≥ I3 − 2%p
  ⑦ 미공개(08-25~10-21) 수익 ≥ I3 − 1%p (이미 본 구간이라 약한 증거)
둘 다 통과하면 R2(위험 상한이 있는 쪽). 통과해도 실전 반영은 운용자 결정 + 실전==검증 대조 테스트 후.
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
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
CAP_DD = 20.0
MIN_BULL_GAIN_PP = 1.0
BOX_TOL_PP = 0.5
LONG_MDD_TOL_PP = 2.0
LONG_WORST_TOL_PP = 2.0
HO_TOL_PP = 1.0
HALVES = {"전반": ("2015-07-28", "2020-12-30"), "후반": ("2021-01-04", "2026-08-24")}
MODES = ("I3", "R1", "R2")
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH = "069500", "153130"


def i3r(bars: dict, kospi: dict, asset: str, cash: str | None, m: float, lookback: int, mode: str = "I3",
        cap_dd: float = CAP_DD, x_pct: float = 10, n: int = 20,
        floor_dd: float = H.I3_FLOOR_DD, band: float = H.I3_BAND):
    """lab_holdout.i3 와 같고, mode R1/R2 면 엔진이 이탈→보유로 바뀐 날 예산 기준점을 다시 잡는다."""
    engine = I.reentry_confirmed(bars, kospi, asset, x_pct, n, cash)
    st: dict = {"in": True, "navs": [], "w": None, "ref": None}

    def target(i: int, d: str, nav: float):
        sig = engine(i, d)
        st["navs"].append(nav)
        if sig is not None:
            now_in = asset in sig
            if now_in and not st["in"] and mode != "I3":
                st["ref"] = len(st["navs"]) - 1           # 재진입한 날(오늘 종가 자산)부터
            st["in"] = now_in
        peak = max(st["navs"][-lookback:])
        floor = (1 - floor_dd / 100.0) * peak
        if st["ref"] is not None:
            since = st["navs"][st["ref"]:][-lookback:]
            floor = (1 - floor_dd / 100.0) * max(since)
            if mode == "R2":
                floor = max(floor, (1 - cap_dd / 100.0) * peak)
        e = min(1.0, max(0.0, m * (nav - floor) / nav)) if nav > 0 else 0.0
        w = e if st["in"] else 0.0
        if (st["w"] is not None and sig is None and abs(w - st["w"]) < band
                and not (w == 0.0 and st["w"] > 0)):
            return None
        st["w"] = w
        out = {asset: w} if w > 0 else {}
        if cash and w < 1.0:
            out[cash] = 1.0 - w
        return out
    return target


def measure(mode: str, p, kodex, cash, ks, dates, long_dates) -> dict:
    res = L.simulate({BASE: L.Asset(BASE, kodex), CASH: L.Asset(CASH, cash)}, dates,
                     i3r(kodex, ks, BASE, CASH, p[0], p[1], mode), EQUITY, pass_nav=True)
    lr = L.simulate({"IDX": L.Asset("IDX", ks)}, long_dates, i3r(ks, ks, "IDX", None, p[0], p[1], mode),
                    0.0, pass_nav=True)
    out = {"전체": L.slice_metrics(res, *L.FULL), "박스권": L.slice_metrics(res, *L.PERIODS["박스권"]),
           "강세장": L.slice_metrics(res, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(res, *L.HOLDOUT),
           "장기": L.metrics(lr.dates, lr.curve), "trades": res.trades}
    for k, span in HALVES.items():
        out[k] = L.slice_metrics(res, *span)
    return out


def med(rows: list[dict], span: str, key: str) -> float:
    return statistics.median(r[span][key] for r in rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    D, G = {}, {}
    for mode in MODES:
        D[mode] = measure(mode, H.I3_DEFAULT, kodex, cash, ks, dates, long_dates)
        G[mode] = [measure(mode, p, kodex, cash, ks, dates, long_dates) for p in H.I3_GRID]

    print("=" * 112)
    print(f"재진입 개선 — 기본값 {H.I3_DEFAULT} / 격자 중앙값, 예탁 {EQUITY:,.0f}원")
    print(f"  {'':10}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'전반':>7}{'후반':>7}{'미공개':>8}"
          f"{'장기MDD':>9}{'장기최악':>9}{'매매':>6}")
    for mode in MODES:
        for tag, src in (("기본", D[mode]), ("중앙", None)):
            if src is not None:
                v = {s: src[s] for s in ("전체", "박스권", "강세장", "전반", "후반", "미공개", "장기")}
                f = lambda s, k: v[s][k]  # noqa: E731
                tr = f"{src['trades']:>6}"
            else:
                f = lambda s, k, mode=mode: med(G[mode], s, k)  # noqa: E731
                tr = ""
            print(f"  {mode + ' ' + tag:10}{f('전체', 'cagr'):>7.2f}%{f('전체', 'mdd'):>6.1f}%{f('전체', 'worst_year'):>+6.1f}%"
                  f"{f('박스권', 'cagr'):>7.1f}%{f('강세장', 'cagr'):>7.1f}%{f('전반', 'cagr'):>6.1f}%{f('후반', 'cagr'):>6.1f}%"
                  f"{f('미공개', 'total'):>+7.1f}%{f('장기', 'mdd'):>8.1f}%{f('장기', 'worst_year'):>+8.1f}%{tr}")

    print("=" * 112)
    ref_d, ref_g = D["I3"], G["I3"]
    verdict = {}
    for mode in ("R1", "R2"):
        d, g = D[mode], G[mode]
        checks = [
            ("① MDD≤20 기본·중앙", d["전체"]["mdd"] <= L.MAX_MDD_PCT and med(g, "전체", "mdd") <= L.MAX_MDD_PCT),
            ("② 최악≥−10 기본·중앙", d["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT
             and med(g, "전체", "worst_year") >= L.MIN_YEAR_RET_PCT),
            ("③ 강세장 +1%p 기본·중앙", d["강세장"]["cagr"] >= ref_d["강세장"]["cagr"] + MIN_BULL_GAIN_PP
             and med(g, "강세장", "cagr") >= med(ref_g, "강세장", "cagr") + MIN_BULL_GAIN_PP),
            ("④ 전반·후반 ≥ I3", all(d[h]["cagr"] >= ref_d[h]["cagr"] for h in HALVES)),
            ("⑤ 박스권 ≥ I3−0.5", d["박스권"]["cagr"] >= ref_d["박스권"]["cagr"] - BOX_TOL_PP),
            ("⑥ 장기 MDD·최악 중앙", med(g, "장기", "mdd") <= med(ref_g, "장기", "mdd") + LONG_MDD_TOL_PP
             and med(g, "장기", "worst_year") >= med(ref_g, "장기", "worst_year") - LONG_WORST_TOL_PP),
            ("⑦ 미공개 ≥ I3−1", d["미공개"]["total"] >= ref_d["미공개"]["total"] - HO_TOL_PP),
        ]
        verdict[mode] = all(ok for _, ok in checks)
        print(f"  {mode}: " + " · ".join(f"{n}{'O' if ok else 'X'}" for n, ok in checks)
              + f"  → {'통과' if verdict[mode] else '기각'}")
    pick = "R2" if verdict["R2"] else ("R1" if verdict["R1"] else None)
    print(f"\n선언된 결론: {pick + ' 채택 후보(운용자 결정)' if pick else '둘 다 기각 — I3 유지'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
