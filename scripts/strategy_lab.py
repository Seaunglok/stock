"""전략 연구소 — 모든 후보 전략을 **같은 잣대·같은 체결 가정**으로 잰다 (2026-10-22).

왜 만들었나
-----------
2026-10-21 에 드러난 것: 우리 추세추종은 시점별로 재면 KODEX200 단순보유에 두 구간 모두
졌다. 그동안 '이긴다'고 판정한 근거는 ① 소급 유니버스(생존편향) ② 너무 쉬운 벤치마크(상위100
동일가중)였다. 후보마다 다른 하니스·다른 벤치마크로 재면 같은 실수가 반복된다.

잣대 — 운용자 선언(2026-10-22), **측정 전 코드 상수**
---------------------------------------------------
  ① 최대 낙폭 ≤ MAX_MDD_PCT(20%)              — 제1원칙: 회복 불가능한 손실 금지
  ② 어느 한 해도 MIN_YEAR_RET_PCT(−10%) 보다 나쁘지 않을 것
  ③ 전체 구간 CAGR ≥ KODEX200 단순보유 CAGR + MIN_EXCESS_CAGR_PP(5%p)
  ④ 박스권·강세장 **각 구간**에서 CAGR ≥ KODEX200 단순보유 CAGR
     (한 구간에서만 좋은 전략은 구간을 탄 것이다 — 10-21 추세 필터가 그랬다)
  ⑤ 강건성: 파라미터가 있는 전략은 **격자 결과의 중앙값**도 ①~④ 충족
     (가장 좋은 설정 하나가 아니라 '보통의 설정'이 통과해야 한다)
  지향 CAGR 30% 는 보고만 한다(판정 아님).

체결: 신호일 종가 → **다음 영업일 시가** 체결. 비용은 `trend_mcp.costs` 단일 소스 —
주식 매도에만 거래세, ETF·지수는 거래세 없음. 현금 이자 0(보수적).
정수 주식수: 예탁(`equity`)이 주어지면 주식수를 내림 — 소액 계좌 제약을 그대로 반영.

구간
----
  박스권 2015-07-28 ~ 2018-12-28 · 강세장 2019-01-02 ~ 2026-08-24 · 전체 = 둘을 이은 구간.
  ETF·개별종목 일봉이 2014-07-28 부터라 이 구간이 공통 최대치다.
  지수형 전략(^KS11 등 장기 시계열)은 **장기 스트레스**(1997~)에서도 ①② 를 본다.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.mcp_servers.trend_mcp import costs as C  # noqa: E402

# ── 잣대 (운용자 선언 2026-10-22 — 결과를 보기 전) ────────────────────────────
MAX_MDD_PCT = 20.0
MIN_YEAR_RET_PCT = -10.0
MIN_EXCESS_CAGR_PP = 5.0
ASPIRATION_CAGR_PCT = 30.0

BENCH_CODE = "069500"            # KODEX200 — 실제로 살 수 있는 시총가중 지수
PERIODS: dict[str, tuple[str, str]] = {
    "박스권": ("2015-07-28", "2018-12-28"),
    "강세장": ("2019-01-02", "2026-08-24"),
}
FULL = ("2015-07-28", "2026-08-24")
LONG = ("1997-01-03", "2026-08-24")     # 지수형 장기 스트레스(①② 만)

_CACHE_DIR = _ROOT / "docs_cache" / "lab"


# ── 데이터 ───────────────────────────────────────────────────────────────────
def load_bars(code: str, start: str = "1990-01-01", end: str = "2026-12-31") -> dict[str, dict]:
    """{date: {open, close}} — FDR, 디스크 캐시(같은 code·end 재호출 시 네트워크 없음).

    ⚠️ KRX 지수 심볼(KS11)은 인증 요구로 실패한다 — `^KS11`(캐럿) 을 쓸 것(backtest_dynamic 과 같음).
    시가가 0 이거나 없는 행(초기 지수 데이터)은 종가로 대체한다 — 다음 날 시가 체결이 0원이 되면
    수량이 무한대가 된다.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = code.replace("^", "IDX_").replace("/", "_")
    path = _CACHE_DIR / f"{safe}_{end}.json"
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
            rows[d.strftime("%Y-%m-%d")] = {"open": o if o == o and o > 0 else c, "close": c}
        path.write_text(json.dumps(rows), encoding="utf-8")
    return {d: v for d, v in rows.items() if start <= d <= end}


def calendar(bars: dict[str, dict], lo: str, hi: str) -> list[str]:
    return sorted(d for d in bars if lo <= d <= hi)


# ── 시뮬레이터 (목표 비중 기반) ────────────────────────────────────────────────
@dataclass
class Asset:
    code: str
    bars: dict[str, dict]
    taxed: bool = False          # True=주식(매도세), False=ETF·지수


@dataclass
class SimResult:
    dates: list[str] = field(default_factory=list)
    curve: list[float] = field(default_factory=list)
    trades: int = 0
    turnover: float = 0.0        # 누적 매매대금 / 평균 자산


def _side_cost(taxed: bool, sell: bool) -> float:
    bps = C.FEE_BPS + C.SLIPPAGE_BPS + (C.TAX_BPS if (taxed and sell) else 0.0)
    return bps / 10_000.0


def simulate(assets: dict[str, Asset], dates: list[str],
             target: Callable[..., dict[str, float] | None],
             equity: float = 0.0, pass_nav: bool = False) -> SimResult:
    """매일 종가 후 target(i, date) 를 부른다 → {code: 비중} 이면 **다음 날 시가**에 그 비중으로 맞춘다.

    pass_nav=True 면 target(i, date, nav) — 그날 **종가 기준 자기 자산**을 넘겨준다(낙폭 예산처럼
    전략이 자기 손익을 보고 비중을 정하는 경우). 그날까지의 값이라 미래 정보가 아니다.

    None 을 돌려주면 그대로 유지. 비중 합 < 1 이면 나머지는 현금. equity>0 이면 정수 주식수
    (소액 계좌 제약), 0 이면 소수 단위(지수형 연구용). 바가 없는 날(정지·휴장 차이)은 그 종목을
    직전 종가로 평가하고 매매하지 않는다.
    """
    cash = equity if equity > 0 else 1.0
    integer = equity > 0
    pos: dict[str, float] = {}
    last_close: dict[str, float] = {}
    pending: dict[str, float] | None = None
    res = SimResult()
    traded = 0.0
    for i, d in enumerate(dates):
        for code, a in assets.items():
            b = a.bars.get(d)
            if b:
                last_close[code] = b["close"]
        if pending is not None:
            # 평가 기준: 오늘 시가(없으면 직전 종가)
            px = {c: (assets[c].bars[d]["open"] if d in assets[c].bars else last_close.get(c, 0.0))
                  for c in set(pos) | set(pending)}
            nav = cash + sum(q * px.get(c, 0.0) for c, q in pos.items())
            want = {c: max(0.0, w) for c, w in pending.items() if w > 0}
            # 1) 매도 먼저(현금 확보)
            for c in list(pos):
                if d not in assets[c].bars:
                    continue
                goal = want.get(c, 0.0) * nav / px[c] if px[c] > 0 else 0.0
                if integer:
                    goal = math.floor(goal)
                if pos[c] > goal:
                    q = pos[c] - goal
                    cash += q * px[c] * (1 - _side_cost(assets[c].taxed, True))
                    traded += q * px[c]
                    res.trades += 1
                    pos[c] = goal
                    if pos[c] <= 0:
                        del pos[c]
            # 2) 매수
            for c, w in want.items():
                if d not in assets[c].bars or px.get(c, 0) <= 0:
                    continue
                goal = w * nav / px[c]
                if integer:
                    goal = math.floor(goal)
                have = pos.get(c, 0.0)
                if goal > have:
                    unit = px[c] * (1 + _side_cost(assets[c].taxed, False))
                    q = min(goal - have, cash / unit)
                    if integer:
                        q = math.floor(q)
                    if q > 0:
                        cash -= q * unit
                        traded += q * px[c]
                        res.trades += 1
                        pos[c] = have + q
            pending = None
        nav_close = cash + sum(q * last_close.get(c, 0.0) for c, q in pos.items())
        res.dates.append(d)
        res.curve.append(nav_close)
        if i < len(dates) - 1:
            t = target(i, d, nav_close) if pass_nav else target(i, d)
            if t is not None:
                pending = t
    avg = statistics.fmean(res.curve) if res.curve else 0.0
    res.turnover = traded / avg if avg else 0.0
    return res


def buy_and_hold(code: str, dates: list[str], bars: dict[str, dict], equity: float = 0.0,
                 taxed: bool = False) -> SimResult:
    """첫날 종가 신호 → 다음 날 시가 전액 매수 후 보유. 벤치마크도 같은 체결·비용을 쓴다."""
    return simulate({code: Asset(code, bars, taxed)}, dates,
                    lambda i, d: {code: 1.0} if i == 0 else None, equity)


# ── 지표 ─────────────────────────────────────────────────────────────────────
def metrics(dates: list[str], curve: list[float]) -> dict:
    """CAGR·MDD·MAR·연도별 수익·최악 연도. 연도 수익은 그 해 첫 값 대비 마지막 값(첫 해는 시작일부터)."""
    if len(curve) < 2 or curve[0] <= 0:
        return {"cagr": 0.0, "mdd": 0.0, "mar": 0.0, "total": 0.0, "years": {}, "worst_year": 0.0}
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100.0)
    n = len(curve)
    cagr = ((curve[-1] / curve[0]) ** (252.0 / n) - 1) * 100.0
    years: dict[str, float] = {}
    prev_end, cur_year = curve[0], dates[0][:4]
    for k in range(1, n):
        y = dates[k][:4]
        if y != cur_year:
            years[cur_year] = (curve[k - 1] / prev_end - 1) * 100.0
            prev_end, cur_year = curve[k - 1], y
    years[cur_year] = (curve[-1] / prev_end - 1) * 100.0
    return {"cagr": cagr, "mdd": mdd, "mar": (cagr / mdd) if mdd > 0 else float("inf"),
            "total": (curve[-1] / curve[0] - 1) * 100.0, "years": years,
            "worst_year": min(years.values()) if years else 0.0}


def slice_metrics(res: SimResult, lo: str, hi: str) -> dict:
    """한 번 돌린 결과에서 구간만 잘라 잰다(구간마다 다시 돌리면 진입 시점이 달라진다)."""
    pts = [(d, v) for d, v in zip(res.dates, res.curve) if lo <= d <= hi]
    return metrics([d for d, _ in pts], [v for _, v in pts])


# ── 판정 ─────────────────────────────────────────────────────────────────────
def judge(strat: dict[str, dict], bench: dict[str, dict]) -> list[tuple[str, bool, str]]:
    """strat/bench: {'전체': metrics, '박스권': metrics, '강세장': metrics} → [(기준, 통과, 설명)]."""
    s, b = strat["전체"], bench["전체"]
    rows = [
        ("① 최대낙폭", s["mdd"] <= MAX_MDD_PCT, f"{s['mdd']:.1f}% ≤ {MAX_MDD_PCT:g}%"),
        ("② 최악 연도", s["worst_year"] >= MIN_YEAR_RET_PCT,
         f"{s['worst_year']:+.1f}% ≥ {MIN_YEAR_RET_PCT:+g}%"),
        ("③ 초과 수익", s["cagr"] >= b["cagr"] + MIN_EXCESS_CAGR_PP,
         f"CAGR {s['cagr']:.1f}% ≥ 벤치 {b['cagr']:.1f}% + {MIN_EXCESS_CAGR_PP:g}%p"),
    ]
    for name in PERIODS:
        ss, bb = strat.get(name), bench.get(name)
        ok = bool(ss and bb) and ss["cagr"] >= bb["cagr"]
        txt = (f"{ss['cagr']:.1f}% ≥ 벤치 {bb['cagr']:.1f}%" if ss and bb else "구간 데이터 없음")
        rows.append((f"④ {name}", ok, txt))
    return rows


def passed(rows: list[tuple[str, bool, str]]) -> bool:
    return bool(rows) and all(ok for _, ok, _ in rows)


def judge_long(m: dict) -> list[tuple[str, bool, str]]:
    """장기 스트레스(1997~, 외환위기·닷컴·금융위기 포함) — 제1원칙 ①② 만 본다.

    벤치마크 대비 ③④ 는 보지 않는다: KODEX200 이 2014-07 부터라 장기 벤치가 없고, 이 구간의
    목적은 '역사상 최악의 장에서도 회복 불가능한 손실을 피했나'다.
    """
    return [
        ("장기 ① 최대낙폭", m["mdd"] <= MAX_MDD_PCT, f"{m['mdd']:.1f}% ≤ {MAX_MDD_PCT:g}%"),
        ("장기 ② 최악 연도", m["worst_year"] >= MIN_YEAR_RET_PCT,
         f"{m['worst_year']:+.1f}% ≥ {MIN_YEAR_RET_PCT:+g}%"),
    ]


def leveraged_bars(bars: dict[str, dict], mult: float = 2.0, fee_pa: float = 0.0064) -> dict[str, dict]:
    """지수 일봉 → 일간 mult 배 레버리지 합성 시계열(일일 재조정, 연 보수 차감).

    레버리지 ETF 상장(2010) 이전 구간의 장기 스트레스용. 실제 ETF 의 추적오차·차입비용은 반영
    못 하므로 결과는 낙관 쪽이다. 시가는 전일 합성 종가 × (1 + mult × 갭).
    """
    out: dict[str, dict] = {}
    prev_c = prev_s = None
    daily_fee = fee_pa / 252.0
    for d in sorted(bars):
        b = bars[d]
        if prev_c is None:
            prev_c, prev_s = b["close"], 100.0
            out[d] = {"open": 100.0, "close": 100.0}
            continue
        s_close = max(prev_s * (1 + mult * (b["close"] / prev_c - 1) - daily_fee), 1e-9)
        s_open = max(prev_s * (1 + mult * (b["open"] / prev_c - 1)), 1e-9)
        out[d] = {"open": s_open, "close": s_close}
        prev_c, prev_s = b["close"], s_close
    return out


def evaluate(res: SimResult, bench_res: SimResult) -> tuple[dict, dict, list]:
    """전체·구간별 지표와 판정 행."""
    spans = {"전체": FULL, **PERIODS}
    s = {k: slice_metrics(res, *v) for k, v in spans.items()}
    b = {k: slice_metrics(bench_res, *v) for k, v in spans.items()}
    return s, b, judge(s, b)


def robustness(results: list[dict]) -> dict:
    """격자 결과(각 원소 = evaluate 의 strat dict) → 지표별 **중앙값** strat dict.

    ⑤ 판정은 이 중앙값 dict 를 judge 에 넣어 한다 — '보통의 설정'이 통과해야 한다.
    """
    out: dict[str, dict] = {}
    for span in ("전체", *PERIODS):
        rows = [r[span] for r in results if span in r]
        if not rows:
            continue
        out[span] = {k: statistics.median(r[k] for r in rows)
                     for k in ("cagr", "mdd", "total", "worst_year")}
        out[span]["mar"] = (out[span]["cagr"] / out[span]["mdd"]) if out[span]["mdd"] > 0 else float("inf")
        out[span]["years"] = {}
    return out


def fmt_row(label: str, s: dict) -> str:
    f = s["전체"]
    box = s.get("박스권", {}).get("cagr", float("nan"))
    bull = s.get("강세장", {}).get("cagr", float("nan"))
    return (f"{label:30}{f['cagr']:>7.1f}%{f['mdd']:>7.1f}%{f['mar']:>6.2f}"
            f"{f['worst_year']:>+8.1f}%{box:>+8.1f}%{bull:>+8.1f}%")


HEADER = f"{'전략':30}{'CAGR':>8}{'MDD':>8}{'MAR':>6}{'최악연도':>9}{'박스권':>8}{'강세장':>8}"


def bench_result(equity: float = 0.0) -> SimResult:
    bars = load_bars(BENCH_CODE, "2014-01-01", FULL[1])
    return buy_and_hold(BENCH_CODE, calendar(bars, *FULL), bars, equity)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    b = bench_result()
    s, bb, rows = evaluate(b, b)
    print(f"잣대: ①MDD≤{MAX_MDD_PCT:g}% ②최악연도≥{MIN_YEAR_RET_PCT:+g}% "
          f"③CAGR≥벤치+{MIN_EXCESS_CAGR_PP:g}%p ④구간별≥벤치 ⑤격자 중앙값")
    print(HEADER)
    print(fmt_row("KODEX200 단순보유(벤치)", s))
    for name, ok, txt in rows:
        print(f"  [{'O' if ok else 'X'}] {name}: {txt}")
