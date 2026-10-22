"""I3 장중 손절 S1 — '장 마감 뒤 판단 → 다음 날 시가' 틈을 줄일 수 있나 (2026-10-22, 사전 선언).

운용자: "장 마감 뒤에 판단하는 구조의 문제라면 해결 가능성이 있는 거 아냐?"
진단(설명용): 2026-06 초 KODEX200 이 며칠 만에 17%+ 빠지자 I3 는 종가 신호 → 다음 날 시가 체결이라 자기 고점 대비
−16.8% 까지 밀렸다(이후 8~10월 급락은 −2.7%). 설계상 최대 손실은 '1년 고점 × 18% + 갭'.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  S1 장중 손절  I3 와 모두 같고, 엔진 이탈(보유 후 최고 종가 × 0.90)만 **장중에** 실행한다:
                그날 저가 ≤ 손절선이면 그날 min(시가, 손절선)에 전량 매도(시가가 이미 아래면 시가 — 갭 하락).
                재진입(20일 고점 + KOSPI>MA120)·낙폭 예산·체결(다음 날 시가)·비용은 I3 그대로.
                손절선은 '어제까지의' 최고 종가 기준(오늘 장중 고가로 올리지 않는다 — I3 엔진과 같은 정의).
  일봉 근사: 장중 경로를 모른다 — 손절선에 닿으면 그 가격에 판 것으로(슬리피지는 하니스와 같은 편도 10bp).
  실전에선 장중 감시(폴링)로 구현해야 해 손절선보다 조금 나쁘게 체결될 수 있다.
리그 입장 조건(기본값, 전부):
  E1 제1원칙   학습 MDD ≤ 20% · 최악연도 ≥ −10%
  S2 위험 개선 학습 MDD ≤ I3 − 1.0%p  또는  장기(1998~ KOSPI) MDD ≤ I3 − 3.0%p
  S3 수익 유지 학습 연수익 ≥ I3 − 0.5%p
  S4 미공개    미공개 수익 ≥ I3 − 1%p
같이 보고만 하는 것: 2026-06 급락 구간 손실(동기가 된 사례 — 판정엔 쓰지 않는다).
"""
from __future__ import annotations

import math
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
E2_MDD_CUT_PP = 1.0
E2_LONG_MDD_CUT_PP = 3.0
E3_CAGR_TOL_PP = 0.5
E4_HO_TOL_PP = 1.0
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH = "069500", "153130"
EPISODE = ("2026-05-29", "2026-06-30")


def i3_sim(ohlc: dict, kospi: dict, dates: list[str], equity: float, cash_bars: dict | None,
           intraday: bool = False, m: float = H.I3_DEFAULT[0], lookback: int = H.I3_DEFAULT[1],
           x_pct: float = 10, n: int = 20, regime_ma: int = I.I1_REGIME_MA,
           floor_dd: float = H.I3_FLOOR_DD, band: float = H.I3_BAND, start: str | None = None,
           asset: str = BASE, cash: str = CASH) -> tuple[L.SimResult, list[tuple[str, str]]]:
    """I3 를 한 루프로 — intraday=False 면 strategy_lab.simulate(lab_holdout.i3) 와 **같은 결과**(테스트로 잠금).
    intraday=True 면 엔진 이탈만 장중(저가 ≤ 손절선 → min(시가, 손절선) 매도).
    start: 리그용 — 이 날 전에는 매매하지 않고 낙폭 예산 자산을 equity 로 고정(실전 시작일 출발과 같다).
    반환: (자산곡선, [(날짜, 사건)])."""
    days = sorted(ohlc)
    pos = {d: k for k, d in enumerate(days)}
    closes = [ohlc[d]["close"] for d in days]
    kdays = sorted(kospi)
    kpos = {d: k for k, d in enumerate(kdays)}
    kcl = [kospi[d]["close"] for d in kdays]

    def regime_up(d):
        k = kpos.get(d)
        if k is None or k + 1 < regime_ma:
            return False
        return kcl[k] > sum(kcl[k + 1 - regime_ma:k + 1]) / regime_ma

    eng = {"in": True, "peak": None, "started": False}
    bud = {"navs": [], "w": None}
    events: list[tuple[str, str]] = []
    assets = {asset: L.Asset(asset, ohlc)}
    if cash_bars is not None:
        assets[cash] = L.Asset(cash, cash_bars)
    cash_amt = equity if equity > 0 else 1.0
    integer = equity > 0
    hold: dict[str, float] = {}
    last_close: dict[str, float] = {}
    pending = None
    res = L.SimResult()
    traded = 0.0

    def engine_close(d):
        """종가 기준 엔진(lab_dd_control.reentry_confirmed 와 같은 규칙) — sig 반환."""
        k = pos.get(d)
        if k is None:
            return None
        c = closes[k]
        if not eng["started"]:
            eng["started"], eng["peak"] = True, c
            return {asset: 1.0}
        if eng["in"]:
            eng["peak"] = max(eng["peak"], c)
            if c <= eng["peak"] * (1 - x_pct / 100.0):
                eng["in"] = False
                return {cash: 1.0} if cash_bars is not None else {}
            return None
        if k >= n and c > max(closes[k - n:k]) and regime_up(d):
            eng["in"], eng["peak"] = True, c
            return {asset: 1.0}
        return None

    for i, d in enumerate(dates):
        trading = start is None or d > start
        for code, a in assets.items():
            b = a.bars.get(d)
            if b:
                last_close[code] = b["close"]
        if pending is not None:                         # 어제 종가 판단 → 오늘 시가 (strategy_lab.simulate 와 같은 코드)
            px = {c: (assets[c].bars[d]["open"] if d in assets[c].bars else last_close.get(c, 0.0))
                  for c in set(hold) | set(pending)}
            nav = cash_amt + sum(q * px.get(c, 0.0) for c, q in hold.items())
            want = {c: max(0.0, w) for c, w in pending.items() if w > 0}
            for c in list(hold):
                if d not in assets[c].bars:
                    continue
                goal = want.get(c, 0.0) * nav / px[c] if px[c] > 0 else 0.0
                if integer:
                    goal = math.floor(goal)
                if hold[c] > goal:
                    q = hold[c] - goal
                    cash_amt += q * px[c] * (1 - L._side_cost(assets[c].taxed, True))
                    traded += q * px[c]
                    res.trades += 1
                    hold[c] = goal
                    if hold[c] <= 0:
                        del hold[c]
            for c, w in want.items():
                if d not in assets[c].bars or px.get(c, 0) <= 0:
                    continue
                goal = w * nav / px[c]
                if integer:
                    goal = math.floor(goal)
                have = hold.get(c, 0.0)
                if goal > have:
                    unit = px[c] * (1 + L._side_cost(assets[c].taxed, False))
                    q = min(goal - have, cash_amt / unit)
                    if integer:
                        q = math.floor(q)
                    if q > 0:
                        cash_amt -= q * unit
                        traded += q * px[c]
                        res.trades += 1
                        hold[c] = have + q
            pending = None
        intraday_exit = False
        b = ohlc.get(d)
        if intraday and eng["in"] and eng["peak"] is not None and b and d in pos:
            level = eng["peak"] * (1 - x_pct / 100.0)       # 어제까지의 최고 종가 기준
            if b["low"] <= level:
                fill = min(b["open"], level)
                if trading and hold.get(asset, 0) > 0:
                    q = hold.pop(asset)
                    cash_amt += q * fill * (1 - L._side_cost(False, True))
                    traded += q * fill
                    res.trades += 1
                eng["in"] = False
                intraday_exit = True
                events.append((d, f"장중 손절 {fill:,.0f}" + ("" if b["open"] > level else " (갭 — 시가)")))
        nav_close = cash_amt + sum(q * last_close.get(c, 0.0) for c, q in hold.items())
        if not trading:
            nav_close = equity
        res.dates.append(d)
        res.curve.append(nav_close)
        if i < len(dates) - 1:
            sig = ({cash: 1.0} if cash_bars is not None else {}) if intraday_exit else engine_close(d)
            bud["navs"].append(nav_close)
            peak = max(bud["navs"][-lookback:])
            floor = (1 - floor_dd / 100.0) * peak
            e = min(1.0, max(0.0, m * (nav_close - floor) / nav_close)) if nav_close > 0 else 0.0
            w = e if eng["in"] else 0.0
            emit = not (bud["w"] is not None and sig is None and abs(w - bud["w"]) < band
                        and not (w == 0.0 and bud["w"] > 0))
            if emit:
                bud["w"] = w
            if start is not None and d < start:
                continue                                # 출발 전 — 판단만 따라가고 매매 안 함
            if not emit and not (start is not None and d == start):
                continue                                # 출발일엔 그날 목표를 강제로 낸다(실전 첫 판단과 같다)
            wv = bud["w"]
            out = {asset: wv} if wv > 0 else {}
            if cash_bars is not None and wv < 1.0:
                out[cash] = 1.0 - wv
            pending = out
    avg = sum(res.curve) / len(res.curve) if res.curve else 0.0
    res.turnover = traded / avg if avg else 0.0
    return res, events


def spans(res: L.SimResult) -> dict:
    return {"전체": L.slice_metrics(res, *L.FULL), "박스권": L.slice_metrics(res, *L.PERIODS["박스권"]),
            "강세장": L.slice_metrics(res, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(res, *L.HOLDOUT),
            "사례": L.slice_metrics(res, *EPISODE)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import lab_classics as C
    k = C.load_ohlc(BASE, "2014-01-01", END)
    c = L.load_bars(CASH, "2014-01-01", END)
    ks = C.load_ohlc("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(k, L.FULL[0], END) if d in c]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    out = {}
    for name, intra in (("I3", False), ("S1", True)):
        r, ev = i3_sim(k, ks, dates, EQUITY, c, intraday=intra)
        lr, _ = i3_sim(ks, ks, long_dates, 0.0, None, intraday=intra, asset="IDX")
        out[name] = {**spans(r), "장기": L.metrics(lr.dates, lr.curve), "trades": r.trades, "events": ev}
    print("=" * 110)
    print(f"I3 vs S1(장중 손절) — 기본값 {H.I3_DEFAULT}, 예탁 {EQUITY:,.0f}원")
    print(f"  {'':4}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'장기MDD':>9}{'장기최악':>9}"
          f"{'6월 사례':>9}{'매매':>6}")
    for n, r in out.items():
        print(f"  {n:4}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['장기']['mdd']:>8.1f}%{r['장기']['worst_year']:>+8.1f}%{r['사례']['total']:>+8.1f}%{r['trades']:>6}")
    a, b = out["I3"], out["S1"]
    checks = [
        ("E1 제1원칙", b["전체"]["mdd"] <= L.MAX_MDD_PCT and b["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT),
        ("S2 위험 개선", b["전체"]["mdd"] <= a["전체"]["mdd"] - E2_MDD_CUT_PP
         or b["장기"]["mdd"] <= a["장기"]["mdd"] - E2_LONG_MDD_CUT_PP),
        ("S3 수익 유지", b["전체"]["cagr"] >= a["전체"]["cagr"] - E3_CAGR_TOL_PP),
        ("S4 미공개", b["미공개"]["total"] >= a["미공개"]["total"] - E4_HO_TOL_PP),
    ]
    ok = all(x for _, x in checks)
    print("=" * 110)
    print("  S1: " + " · ".join(f"{n}{'O' if x else 'X'}" for n, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"  장중 손절 발생 {sum(1 for _, e in b['events'] if '장중' in e)}회 (그중 갭 {sum(1 for _, e in b['events'] if '갭' in e)}회)")
    for d, e in b["events"]:
        if d >= "2026-01-01":
            print(f"    {d} {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
