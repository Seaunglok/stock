"""버핏식 핵심 + 위험 관리층 — 운용자 잣대(strategy_lab)로 판정 (2026-10-22 선언, 측정 전).

배경: 지수형 3종은 제1원칙(MDD ≤ 20%)에서 전부 막혔다(docs/2026-10-22-lab-criteria-declaration.md).
버핏의 수익은 '싸고·안전하고·우량한' 종목 + 레버리지로 설명된다(Frazzini-Kabiller-Pedersen).
한국에선 수익성 프리미엄이 확인됐다. 낙폭은 급락 때 오르는 자산과의 분산 + 변동성 기반 비중으로 다룬다.

선언 (격자·기본값은 측정 전 고정)
--------------------------------
D 위험관리 단독   자산 5종(KODEX200·TIGER나스닥100·KOSEF국고채10년·KODEX골드선물(H)·KOSEF미국달러선물)
                  역변동성 비중(최근 L일) → 포트폴리오 변동성이 연 σ* 를 넘으면 비례 축소, 남는 돈은
                  KODEX단기채권(현금 대용). 월말 리밸런싱. 격자 L∈{20,60,120} × σ*∈{8,12,16}%, 기본 (60, 12%).
E 버핏식 핵심     월말이 아닌 **분기말**(3·6·9·12월 마지막 영업일) 신호. 후보 = 그날 시총 상위 K(시점별)
                  − 금융·증권·보험 − 20일 평균 거래대금 5억 미만 − 적자·자본잠식 − 이력 252일 미만.
                  점수 = 평균(우량, 저평가, 저변동)의 순위.
                    우량 = 평균순위(영업이익/자산, 순이익/자본, −부채/자본)
                    저평가 = 평균순위(순이익/시총, 자본/시총)
                    저변동 = 순위(−252일 변동성)
                  상위 N 동일가중. 재무는 **공시일 다음 날부터**만 쓴다(dart_fundamentals.latest_as_of).
                  격자 N∈{5,10,15,20} × K∈{100,200,350}, 기본 (10, 200).
F 버핏식+위험관리  E 의 종목(분기 선정)을 월말마다 '그 종목들 동일가중의 60일 변동성'이 σ* 를 넘으면
                  비례 축소하고, 남는 비중은 방어 바스켓(국고채10년·금·달러, 60일 역변동성)에 둔다.
                  K=200. 격자 N∈{10,20} × σ*∈{10,15,20}%, 기본 (10, 15%).

계열 채택 = 기본값 ①~④ **그리고** 격자 중앙값 ①~④(⑤). 장기 스트레스는 데이터가 없어 해당 없음
(ETF·종목 일봉 2014-07~, DART 2014 사업연도~).

남는 편향: 종목 풀이 '현재' 시총 상위 350(그 밖으로 떨어진 종목 없음) · 상장주식수 현재값 —
수치를 부풀리는 쪽. 레버리지는 쓰지 않는다(버핏의 1.6배는 보험 플로트라 재현 불가).
"""
from __future__ import annotations

import bisect
import json
import math
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
from dart_fundamentals import OUT as FUND_PATH, latest_as_of  # noqa: E402

EQUITY = 3_852_844.0
FIN_SECTORS = frozenset({"금융", "증권", "보험"})
MIN_VALUE_KRW = 5e8

D_ASSETS = ("069500", "133690", "148070", "132030", "138230")
CASH_ETF = "153130"
DEF_ASSETS = ("148070", "132030", "138230")
D_GRID = tuple((lb, s) for lb in (20, 60, 120) for s in (8, 12, 16))
D_DEFAULT = (60, 12)
E_GRID = tuple((n, k) for n in (5, 10, 15, 20) for k in (100, 200, 350))
E_DEFAULT = (10, 200)
F_GRID = tuple((n, s) for n in (10, 20) for s in (10, 15, 20))
F_DEFAULT = (10, 15)
F_K = 200
VOL_LB = 60


# ── 공통 ─────────────────────────────────────────────────────────────────────
class Prices:
    """종목별 정렬 날짜·종가 — 그날까지의 값만 꺼낸다(미래 정보 차단)."""

    def __init__(self, bars: dict[str, dict[str, dict]]):
        self.bars = bars
        self.days = {c: sorted(b) for c, b in bars.items()}
        self.closes = {c: [b[d]["close"] for d in self.days[c]] for c, b in bars.items()}

    def upto(self, code: str, d: str) -> int:
        """d 이하 마지막 인덱스(없으면 -1)."""
        return bisect.bisect_right(self.days.get(code, []), d) - 1

    def vol(self, code: str, d: str, n: int) -> float | None:
        k = self.upto(code, d)
        if k < n:
            return None
        cs = self.closes[code][k - n:k + 1]
        rets = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs)) if cs[i - 1] > 0 and cs[i] > 0]
        return statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 5 else None

    def rets(self, code: str, d: str, n: int) -> list[float] | None:
        k = self.upto(code, d)
        if k < n:
            return None
        cs = self.closes[code][k - n:k + 1]
        return [cs[i] / cs[i - 1] - 1 for i in range(1, len(cs))]


def period_ends(dates: list[str], months: tuple[int, ...] | None = None) -> set[str]:
    """그 달 마지막 영업일(months 가 주어지면 그 달들만)."""
    out = set()
    for i, d in enumerate(dates):
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        if (nxt is None or nxt[:7] != d[:7]) and (months is None or int(d[5:7]) in months):
            out.add(d)
    return out


def inv_vol_weights(px: Prices, codes: tuple[str, ...], d: str, n: int) -> dict[str, float]:
    vs = {c: px.vol(c, d, n) for c in codes}
    inv = {c: 1.0 / v for c, v in vs.items() if v and v > 0}
    tot = sum(inv.values())
    return {c: x / tot for c, x in inv.items()} if tot else {}


def port_vol(px: Prices, w: dict[str, float], d: str, n: int) -> float | None:
    series = {c: px.rets(c, d, n) for c in w}
    if any(s is None for s in series.values()) or not series:
        return None
    m = min(len(s) for s in series.values())
    daily = [sum(w[c] * series[c][-m + i] for c in w) for i in range(m)]
    return statistics.pstdev(daily) * math.sqrt(252) if m > 5 else None


def pct_rank(vals: dict[str, float]) -> dict[str, float]:
    """값이 클수록 1 에 가까운 백분위 순위(동률은 평균)."""
    items = sorted(vals.items(), key=lambda x: x[1])
    n = len(items)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = ((i + j) / 2) / (n - 1) if n > 1 else 1.0
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


# ── D ────────────────────────────────────────────────────────────────────────
def strat_d(px: Prices, dates: list[str], lookback: int, sigma: float):
    ends = period_ends(dates)

    def target(i: int, d: str):
        if d not in ends and i != 0:
            return None
        w = inv_vol_weights(px, D_ASSETS, d, lookback)
        if not w:
            return {CASH_ETF: 1.0}
        pv = port_vol(px, w, d, lookback)
        s = min(1.0, sigma / 100.0 / pv) if pv else 1.0
        out = {c: x * s for c, x in w.items()}
        out[CASH_ETF] = 1.0 - s
        return out
    return target


# ── E ────────────────────────────────────────────────────────────────────────
_RANK_MEMO: dict = {}


def buffett_pick(px: Prices, fund: dict, shares: dict[str, int], sectors: dict[str, str],
                 d: str, n: int, k: int) -> list[str]:
    """그날 정보만으로 상위 n 종목. 재무는 공시일 다음 날부터(latest_as_of 는 avail < d).

    순위는 n 과 무관하므로 (풀 id, d, k) 로 메모한다 — 격자 N 4개가 같은 순위를 다시 계산하지 않게.
    """
    mk = (id(px), id(fund), d, k)
    if mk not in _RANK_MEMO:
        _RANK_MEMO[mk] = _rank(px, fund, shares, sectors, d, k)
    return _RANK_MEMO[mk][:n]


def _rank(px: Prices, fund: dict, shares: dict[str, int], sectors: dict[str, str],
          d: str, k: int) -> list[str]:
    caps = []
    for code in px.bars:
        b = px.bars[code].get(d)
        sh = shares.get(code, 0)
        if b and sh > 0 and b["close"] > 0:
            caps.append((b["close"] * sh, code))
    caps.sort(reverse=True)
    cand: dict[str, dict] = {}
    for mcap, code in caps[:k]:
        if sectors.get(code, "") in FIN_SECTORS:
            continue
        j = px.upto(code, d)
        if j < 252:
            continue
        vals = [px.bars[code][px.days[code][t]].get("value", 0) or 0 for t in range(j - 19, j + 1)]
        if statistics.fmean(vals) < MIN_VALUE_KRW:
            continue
        f = latest_as_of(fund.get(code, {}), d)
        if not f:
            continue
        eq, ni, assets = f.get("equity"), f.get("net_income"), f.get("assets")
        op, liab = f.get("op_income"), f.get("liabilities")
        if not all(x is not None for x in (eq, ni, assets, op, liab)) or eq <= 0 or ni <= 0 or assets <= 0:
            continue
        v = px.vol(code, d, 252)
        if v is None:
            continue
        cand[code] = {"opa": op / assets, "roe": ni / eq, "lev": -liab / eq,
                      "ep": ni / mcap, "bp": eq / mcap, "lv": -v}
    if not cand:
        return []
    r = {m: pct_rank({c: x[m] for c, x in cand.items()}) for m in ("opa", "roe", "lev", "ep", "bp", "lv")}
    score = {c: (statistics.fmean([r["opa"][c], r["roe"][c], r["lev"][c]])
                 + statistics.fmean([r["ep"][c], r["bp"][c]])
                 + r["lv"][c]) / 3.0 for c in cand}
    return [c for c, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))]


def strat_e(px: Prices, fund, shares, sectors, dates: list[str], n: int, k: int):
    ends = period_ends(dates, (3, 6, 9, 12))

    def target(i: int, d: str):
        if d not in ends and i != 0:
            return None
        picks = buffett_pick(px, fund, shares, sectors, d, n, k)
        return {c: 1.0 / n for c in picks}
    return target


# ── F ────────────────────────────────────────────────────────────────────────
def strat_f(px: Prices, fund, shares, sectors, dates: list[str], n: int, sigma: float):
    q_ends = period_ends(dates, (3, 6, 9, 12))
    m_ends = period_ends(dates)
    state: dict[str, list[str]] = {"picks": []}

    def target(i: int, d: str):
        if d in q_ends or i == 0:
            state["picks"] = buffett_pick(px, fund, shares, sectors, d, n, F_K)
        elif d not in m_ends:
            return None
        picks = state["picks"]
        if not picks:
            return inv_vol_weights(px, DEF_ASSETS, d, VOL_LB)
        ew = {c: 1.0 / len(picks) for c in picks}
        pv = port_vol(px, ew, d, VOL_LB)
        s = min(1.0, sigma / 100.0 / pv) if pv else 1.0
        out = {c: s / n for c in picks}
        for c, x in inv_vol_weights(px, DEF_ASSETS, d, VOL_LB).items():
            out[c] = out.get(c, 0.0) + (1.0 - s * len(picks) / n) * x
        return out
    return target


# ── 실행 ─────────────────────────────────────────────────────────────────────
def _family(name: str, runs: list[tuple[str, L.SimResult]], default_label: str, bench: L.SimResult) -> bool:
    print("=" * 100)
    print(f"[{name}]")
    print(L.HEADER + "   판정  (매매횟수)")
    evals, default_ok = [], False
    _, b, _ = L.evaluate(runs[0][1], bench)
    for label, res in runs:
        s, _, rows = L.evaluate(res, bench)
        evals.append(s)
        ok = L.passed(rows)
        if label == default_label:
            default_ok = ok
        print(L.fmt_row(("◆" if label == default_label else " ") + label, s)
              + f"   {'통과' if ok else '미달'}  ({res.trades})")
    med = L.robustness(evals)
    med_rows = L.judge(med, b)
    print(L.fmt_row(" 격자 중앙값", med) + f"   {'통과' if L.passed(med_rows) else '미달'}")
    for n_, ok, txt in med_rows:
        print(f"      [{'O' if ok else 'X'}] {n_}: {txt}")
    verdict = default_ok and L.passed(med_rows)
    print(f"  → {name}: {'채택 가능' if verdict else '기각'} "
          f"(기본값 {'O' if default_ok else 'X'} · 격자 중앙값 {'O' if L.passed(med_rows) else 'X'})")
    return verdict


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import backtest_trend_portfolio as P
    etf_codes = sorted(set(D_ASSETS) | {CASH_ETF})
    etf_bars = {c: L.load_bars(c, "2014-01-01", L.FULL[1]) for c in etf_codes}
    dates = L.calendar(etf_bars["069500"], *L.FULL)
    bench = L.buy_and_hold("069500", dates, etf_bars["069500"], EQUITY)
    bs, _, _ = L.evaluate(bench, bench)
    print(f"잣대: ①MDD≤{L.MAX_MDD_PCT:g}% ②최악연도≥{L.MIN_YEAR_RET_PCT:+g}% ③CAGR≥벤치+{L.MIN_EXCESS_CAGR_PP:g}%p "
          f"④박스권·강세장 각각 ≥벤치 ⑤격자 중앙값 · 예탁 {EQUITY:,.0f}원")
    print(L.HEADER)
    print(L.fmt_row("KODEX200 단순보유(벤치)", bs))
    verdicts = {}

    epx = Prices(etf_bars)
    runs = []
    for lb, sg in D_GRID:
        assets = {c: L.Asset(c, etf_bars[c]) for c in etf_codes}
        runs.append((f"L{lb}·σ{sg}%", L.simulate(assets, dates, strat_d(epx, dates, lb, sg), EQUITY)))
    verdicts["D 위험관리 단독"] = _family("D 위험관리 단독", runs, f"L{D_DEFAULT[0]}·σ{D_DEFAULT[1]}%", bench)

    key = ("2015-01-01", "2026-08-25", 100, 350, "")
    _d, sbars, _c, _o = P._load(*key)
    shares = P._SHARES[key]
    sectors = P._sector_map()
    fund = json.loads(FUND_PATH.read_text(encoding="utf-8"))
    stock_bars = {c: {d: {"open": b["open"], "close": b["close"], "value": b.get("value", 0)}
                      for d, b in bm.items()} for c, bm in sbars.items()}
    spx = Prices(stock_bars)
    print(f"  종목 {len(stock_bars)} · 재무 {len(fund)}종목 · 금융 제외 업종 {sorted(FIN_SECTORS)}")
    runs = []
    for n, k in E_GRID:
        assets = {c: L.Asset(c, b, taxed=True) for c, b in stock_bars.items()}
        runs.append((f"N{n}·K{k}", L.simulate(assets, dates, strat_e(spx, fund, shares, sectors, dates, n, k), EQUITY)))
    verdicts["E 버핏식 핵심"] = _family("E 버핏식 핵심", runs, f"N{E_DEFAULT[0]}·K{E_DEFAULT[1]}", bench)

    allpx = Prices({**stock_bars, **{c: etf_bars[c] for c in DEF_ASSETS}})
    runs = []
    for n, sg in F_GRID:
        assets = {**{c: L.Asset(c, b, taxed=True) for c, b in stock_bars.items()},
                  **{c: L.Asset(c, etf_bars[c]) for c in DEF_ASSETS}}
        runs.append((f"N{n}·σ{sg}%", L.simulate(assets, dates, strat_f(allpx, fund, shares, sectors, dates, n, sg), EQUITY)))
    verdicts["F 버핏식+위험관리"] = _family("F 버핏식+위험관리", runs, f"N{F_DEFAULT[0]}·σ{F_DEFAULT[1]}%", bench)

    print("=" * 100)
    print("최종: " + " · ".join(f"{k} {'채택 가능' if v else '기각'}" for k, v in verdicts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
