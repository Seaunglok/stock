"""고전·펀드·논문·GitHub 알고리즘 1차 — 원 출처 파라미터 그대로 (2026-10-22, 사전 선언).

운용자(10-22): "추세추종·단타 등 다양한 알고리즘을 많이 가져와서 경쟁" · "펀드회사의 알고리즘, 논문이나 GitHub 에서
많이 사용되는 알고리즘도 가져와라."

원칙
----
- **파라미터는 출처의 값 그대로.** 우리 데이터로 고르면 끼워 맞추기다(추세추종의 교훈). 한국 상장 ETF 로 옮기며
  바뀌는 점(자산 대용·레버리지 불가·체결 시각)은 아래에 적는다.
- 백테스트는 **참고 표시**(strategy_lab 잣대). 리그 입장은 운용 가능성(데이터·유동성)만 본다 — 판정은 리그의
  실전 데이터(i3_shadow 승격 규칙)가 한다. 남는 돈은 현금 자리(연구=153130, 리그=머니마켓).
- 르네상스 메달리온 등 방법이 공개되지 않은 펀드는 가져올 수 없다(흉내 낸 이름표를 붙이지 않는다).

카탈로그 (선언)
---------------
  FABER10   Faber(2007) 'A Quantitative Approach to Tactical Asset Allocation' — 월말 종가 > 10개월 이동평균이면
            KODEX200 보유, 아니면 현금. 월 1회.
  TSMOM     Moskowitz·Ooi·Pedersen(2012) 'Time Series Momentum' — 5자산(KODEX200·나스닥100·국고채10년·금·달러)
            각자 12개월 수익 > 0 이면 보유(롱온리 — 원 논문의 공매도 대신 현금), 보유 자산 동일가중(원 논문의
            자산당 변동성 40% 스케일은 레버리지 없이는 전부 상한에 닿아 동일가중과 같다). 월 1회.
  VOLMGD    Moreira·Muir(2017) 'Volatility-Managed Portfolios' — 월말 KODEX200 비중 = min(1, c / 전월 실현분산),
            c = 그때까지의 월 실현분산 평균(확장 창 — 미래 정보 없음). 레버리지 불가라 상한 1.
  ALLWTHR   브리지워터 올웨더(공개된 대중판 30/40/15/7.5/7.5) — 주식 30(KODEX200) · 장기채 40(국고채10년) ·
            중기채 15(국고채3년) · 금 15(원자재 7.5 를 금에 합침 — 국내 상장 원자재 ETF 이력 부족). 분기말 재조정.
  TURTLE55  터틀 트레이딩 시스템2 — 종가가 직전 55일 최고 종가를 넘으면 진입, 직전 20일 최저 종가 밑이면 청산
            (원전은 장중 고가·저가 — 리그 데이터가 시가·종가뿐이라 종가 기준 돈치안으로 통일).
  RSI2      Connors·Alvarez(2009) — 종가 > 200일선 이고 RSI(2, Wilder) < 10 이면 **그날 종가에** 매수,
            종가 > 5일선이면 그날 종가에 청산(원전이 종가 체결).
  VBREAK    래리 윌리엄스 변동성 돌파(국내 대중판 k=0.5) — 오늘 고가가 시가 + 0.5×(전일 고가−전일 저가)를 넘으면
            그 가격(시가가 이미 위면 시가)에 매수, **다음 날 시가**에 매도. 하룻밤 보유 단타.
  BOLLMR    볼린저 역추세(GitHub 단골) — 종가 < 20일선 − 2σ 면 진입, 종가 > 20일선이면 청산(다음 날 시가 체결).
  GCROSS    골든크로스(GitHub 단골) — 50일선 > 200일선이면 보유.
대상은 별도 표기가 없으면 KODEX200, 체결은 다음 날 시가(RSI2·VBREAK 는 위 규칙). 비용은 strategy_lab 과 같다.
장기 스트레스(1998~)는 단일 자산 계열만 KOSPI 지수로.
"""
from __future__ import annotations

import contextlib
import io
import json
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402

EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH = "069500", "153130"
TSMOM_ASSETS = ("069500", "133690", "148070", "132030", "138230")
AW_WEIGHTS = {"069500": 0.30, "148070": 0.40, "114260": 0.15, "132030": 0.15}
VB_K = 0.5
LONG_STRESS = ("1998-01-02", "2026-08-24")
_OHLC_DIR = _ROOT / "docs_cache" / "lab"


# ── 데이터: 고가·저가까지 ──────────────────────────────────────────────────────
def load_ohlc(code: str, start: str = "1990-01-01", end: str = END) -> dict[str, dict]:
    """{date: {open, high, low, close}} — strategy_lab.load_bars 는 시가·종가만 남겨 변동성 돌파를 못 잰다."""
    safe = code.replace("^", "IDX_").replace("/", "_")
    path = _OHLC_DIR / f"ohlc_{safe}_{end}.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        with contextlib.redirect_stdout(io.StringIO()):
            import FinanceDataReader as fdr
            df = fdr.DataReader(code, start, end)
        rows = {}
        for d, r in df.iterrows():
            c = float(r["Close"])
            if not c == c or c <= 0:
                continue
            o = float(r.get("Open", c) or c)
            o = o if o == o and o > 0 else c
            h = float(r.get("High", max(o, c)) or max(o, c))
            lo = float(r.get("Low", min(o, c)) or min(o, c))
            rows[d.strftime("%Y-%m-%d")] = {"open": o, "high": max(h, o, c) if h == h else max(o, c),
                                            "low": min(lo, o, c) if lo == lo and lo > 0 else min(o, c), "close": c}
        _OHLC_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    return {d: v for d, v in rows.items() if start <= d <= end}


def _closes(bars):
    days = sorted(bars)
    return days, {d: k for k, d in enumerate(days)}, [bars[d]["close"] for d in days]


def month_ends(days: list[str]) -> set[str]:
    return {d for a, d in zip(days[1:] + [None], days) if a is None or a[:7] != d[:7]}


# ── 알고리즘 (target(i, d) → {code: 비중} | None, 비중 합 < 1 이면 나머지 현금) ─────────────────
def faber10(bars, asset, ends: set[str]):
    days, pos, cl = _closes(bars)
    me = [d for d in days if d in ends]
    mpos = {d: k for k, d in enumerate(me)}

    def t(i, d):
        if d not in mpos:
            return None
        k = mpos[d]
        if k < 9:
            return {}
        sma = statistics.fmean(bars[x]["close"] for x in me[k - 9:k + 1])
        return {asset: 1.0} if bars[d]["close"] > sma else {}
    return t


def tsmom(bars_by: dict, ends: set[str], look: int = 252):
    series = {c: _closes(b) for c, b in bars_by.items()}

    def t(i, d):
        if d not in ends:
            return None
        on = []
        for c, (days, pos, cl) in series.items():
            k = pos.get(d)
            if k is not None and k >= look and cl[k] / cl[k - look] - 1 > 0:
                on.append(c)
        n = len(bars_by)
        return {c: 1.0 / n for c in on}               # 꺼진 자산 몫은 현금
    return t


def volmgd(bars, asset, ends: set[str]):
    days, pos, cl = _closes(bars)
    hist: list[float] = []

    def t(i, d):
        if d not in ends:
            return None
        k = pos.get(d)
        if k is None or k < 22:
            return {}
        rets = [cl[j] / cl[j - 1] - 1 for j in range(k - 20, k + 1)]
        var = statistics.pvariance(rets) * 252
        hist.append(var)
        c = statistics.fmean(hist)
        return {asset: min(1.0, c / var) if var > 0 else 1.0}
    return t


def all_weather(qends: set[str], weights: dict[str, float] = AW_WEIGHTS):
    def t(i, d):
        return dict(weights) if (d in qends or i == 0) else None
    return t


def turtle(bars, asset, entry: int = 55, exit_: int = 20):
    """종가 기준 돈치안(원전은 장중 고가·저가 — 리그 데이터가 시가·종가뿐이라 연구·리그를 같은 계산으로)."""
    days, pos, cl = _closes(bars)
    st = {"in": False}

    def t(i, d):
        k = pos.get(d)
        if k is None or k < entry:
            return {} if i == 0 else None
        if not st["in"] and cl[k] > max(cl[k - entry:k]):
            st["in"] = True
            return {asset: 1.0}
        if st["in"] and cl[k] < min(cl[k - exit_:k]):
            st["in"] = False
            return {}
        return {} if i == 0 else None
    return t


def rsi_wilder(cl: list[float], n: int = 2) -> list[float | None]:
    out: list[float | None] = [None] * len(cl)
    ag = al = None
    for k in range(1, len(cl)):
        ch = cl[k] - cl[k - 1]
        g, lo = max(ch, 0.0), max(-ch, 0.0)
        if k <= n:
            ag = (ag or 0.0) + g / n
            al = (al or 0.0) + lo / n
            if k == n:
                out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
            continue
        ag = (ag * (n - 1) + g) / n
        al = (al * (n - 1) + lo) / n
        out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def rsi2(bars, asset):
    days, pos, cl = _closes(bars)
    r = rsi_wilder(cl, 2)
    st = {"in": False}

    def t(i, d):
        k = pos.get(d)
        if k is None or k < 200 or r[k] is None:
            return None
        ma200 = sum(cl[k - 199:k + 1]) / 200
        ma5 = sum(cl[k - 4:k + 1]) / 5
        if not st["in"] and cl[k] > ma200 and r[k] < 10:
            st["in"] = True
            return {asset: 1.0}
        if st["in"] and cl[k] > ma5:
            st["in"] = False
            return {}
        return None
    return t


def bollinger_mr(bars, asset, n: int = 20, z: float = 2.0):
    days, pos, cl = _closes(bars)
    st = {"in": False}

    def t(i, d):
        k = pos.get(d)
        if k is None or k < n:
            return None
        win = cl[k - n + 1:k + 1]
        m, s = statistics.fmean(win), statistics.pstdev(win)
        if not st["in"] and cl[k] < m - z * s:
            st["in"] = True
            return {asset: 1.0}
        if st["in"] and cl[k] > m:
            st["in"] = False
            return {}
        return None
    return t


def golden_cross(bars, asset, fast: int = 50, slow: int = 200):
    days, pos, cl = _closes(bars)

    def t(i, d):
        k = pos.get(d)
        if k is None or k < slow:
            return {}
        return {asset: 1.0} if sum(cl[k - fast + 1:k + 1]) / fast > sum(cl[k - slow + 1:k + 1]) / slow else {}
    return t


def vbreak_curve(ohlc: dict, cash: dict | None, dates: list[str], equity: float, k: float = VB_K,
                 start: str | None = None) -> tuple[list[str], list[float], int]:
    """변동성 돌파 자산곡선 — 돌파한 날 그 가격에 사서 다음 날 시가에 판다. 안 산 날은 현금 자리 수익.
    비용: 매수·매도 각각 수수료+슬리피지(ETF 매도세 없음, strategy_lab._side_cost 와 같은 값)."""
    buy_c, sell_c = L._side_cost(False, False), L._side_cost(False, True)
    nav, out_d, out_v, trades = equity, [], [], 0
    held = None                                         # 전날 돌파 매수가
    prev = None
    for d in dates:
        if start and d < start:
            prev = d
            continue
        b = ohlc.get(d)
        if held is not None:                            # 1) 전날 산 것 — 오늘 시가에 판다
            if b:
                nav *= b["open"] * (1 - sell_c) / (held * (1 + buy_c))
                held = None
        elif cash is not None and prev in cash and d in cash and out_d:
            nav *= cash[d]["close"] / cash[prev]["close"]   # 안 산 날은 현금 자리 수익
        mark = nav
        if b and held is None and prev in ohlc:          # 2) 오늘 돌파하면 그 가격에 산다
            p = ohlc[prev]
            level = b["open"] + k * (p["high"] - p["low"])
            if b["high"] >= level:
                held = max(b["open"], level)
                trades += 1
                mark = nav * b["close"] * (1 - sell_c) / (held * (1 + buy_c))   # 장부는 종가 평가
        out_d.append(d)
        out_v.append(mark)
        prev = d
    return out_d, out_v, trades


# ── 측정 ─────────────────────────────────────────────────────────────────────
def _sim(codes_bars: dict, dates, target, fill_same_close: bool = False) -> L.SimResult:
    import lab_exec_timing as T
    assets = {c: L.Asset(c, T.fill_bars(b, "SAME_CLOSE") if fill_same_close else b) for c, b in codes_bars.items()}

    def tt(i, d):
        r = target(i, d)
        if r is None:
            return None
        out = dict(r)
        rest = 1.0 - sum(out.values())
        if rest > 1e-9 and CASH in codes_bars:
            out[CASH] = out.get(CASH, 0.0) + rest
        return out
    return L.simulate(assets, dates, tt, EQUITY)


def specs(px: dict, dates: list[str]) -> dict[str, tuple]:
    """이름 → (자산 dict, target, 종가체결 여부, 장기 스트레스용 builder(ks) 또는 None)."""
    k, c = px[BASE], px[CASH]
    ends = month_ends(sorted(k))                       # 자산 전체 달력 — 10개월선·12개월 워밍업이 비지 않게
    qends = {d for d in ends if int(d[5:7]) in (3, 6, 9, 12)}
    one = lambda b: {BASE: b, CASH: c}  # noqa: E731
    return {
        "FABER10": (one(k), faber10(k, BASE, ends), False, lambda ks, e: faber10(ks, "IDX", e)),
        "TSMOM": ({**{a: px[a] for a in TSMOM_ASSETS}, CASH: c}, tsmom({a: px[a] for a in TSMOM_ASSETS}, ends), False, None),
        "VOLMGD": (one(k), volmgd(k, BASE, ends), False, lambda ks, e: volmgd(ks, "IDX", e)),
        "ALLWTHR": ({**{a: px[a] for a in AW_WEIGHTS}, CASH: c}, all_weather(qends), False, None),
        "TURTLE55": (one(k), turtle(k, BASE), False, lambda ks, e: turtle(ks, "IDX")),
        "RSI2": (one(k), rsi2(k, BASE), True, lambda ks, e: rsi2(ks, "IDX")),
        "BOLLMR": (one(k), bollinger_mr(k, BASE), False, lambda ks, e: bollinger_mr(ks, "IDX")),
        "GCROSS": (one(k), golden_cross(k, BASE), False, lambda ks, e: golden_cross(ks, "IDX")),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    codes = {BASE, CASH, *TSMOM_ASSETS, *AW_WEIGHTS}
    px = {cd: load_ohlc(cd, "2010-01-01", END) for cd in codes}
    ks = load_ohlc("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(px[BASE], L.FULL[0], END) if d in px[CASH]]
    long_dates = L.calendar(ks, *LONG_STRESS)
    bench = L.buy_and_hold(BASE, dates, px[BASE], EQUITY)
    rows = {}

    def record(name, res_d, res_v, trades, long_m):
        r = L.SimResult(dates=res_d, curve=res_v, trades=trades)
        rows[name] = {"전체": L.slice_metrics(r, *L.FULL), "박스권": L.slice_metrics(r, *L.PERIODS["박스권"]),
                      "강세장": L.slice_metrics(r, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(r, *L.HOLDOUT),
                      "장기": long_m, "trades": trades}

    record("KODEX200 보유", bench.dates, bench.curve, bench.trades, None)
    for name, (assets, target, same_close, long_b) in specs(px, dates).items():
        res = _sim(assets, dates, target, same_close)
        long_m = None
        if long_b:
            le = month_ends(sorted(ks))
            lr = _sim({"IDX": ks}, long_dates, long_b(ks, le), same_close)
            long_m = L.metrics(lr.dates, lr.curve)
        record(name, res.dates, res.curve, res.trades, long_m)
    vd, vv, vt = vbreak_curve(px[BASE], px[CASH], dates, EQUITY)
    ld, lv, _ = vbreak_curve(ks, None, long_dates, EQUITY)
    record("VBREAK", vd, vv, vt, L.metrics(ld, lv))

    print("=" * 118)
    print(f"고전·펀드·논문·GitHub 1차 — 원 출처 파라미터, 예탁 {EQUITY:,.0f}원, 2015-07~2026-08 (+미공개 08-25~10-21)")
    print(f"  {'':14}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'장기MDD':>9}{'장기최악':>9}{'매매':>6}  제1원칙")
    for name, r in rows.items():
        lm = r["장기"]
        p12 = r["전체"]["mdd"] <= L.MAX_MDD_PCT and r["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT
        print(f"  {name:14}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              + (f"{lm['mdd']:>8.1f}%{lm['worst_year']:>+8.1f}%" if lm else f"{'—':>9}{'—':>9}")
              + f"{r['trades']:>6}  {'O' if p12 else 'x'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
