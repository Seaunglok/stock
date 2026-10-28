"""하락 예측 신호 판정대 (2026-10-28, 사전 선언) — '하락을 미리 아는 신호'가 있나.

운용자(10-28): "하락일때를 알고 인버스에 투자하고, 상승일때는 코덱스에 투자하고 이런거는 안되지?" →
"그런 신호를 맞힐 수 있는 방법이 있을거 같은데".

왜 이 판정대인가
---------------
  · 공격형 1세대 A(lab_aggr)는 **추세 신호**(Faber·TSMOM·I3 엔진)로 인버스를 들었다가 졌다 — 하락 신호 적중률이
    기저율과 같았다(Faber 47%·TSMOM 40% vs 내린 달 42%). 추세는 '이미 내린 것'을 본다.
  · 그래서 이번엔 **추세 밖의 정보원**을 잰다 — 공포(VIX), 미국 시장, 환율, 한국 단기 추세, 변동성, 그 다수결.
  · 전략을 바로 만들지 않는다. 먼저 '하락을 기저율보다 잘 맞히나'만 따로 판정한다. 통과한 신호만 다음 선언에서
    양방향 전략(lab_aggr 잣대 P1~P5)으로 간다. 롱 쪽을 섞으면 '상승장에서 KODEX200 을 들어서 번 돈'이 하락 예측
    실력처럼 보인다 — 그래서 여기선 **하락 쪽만** 떼어 잰다(하락 신호 때 인버스, 나머지는 현금).

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  자산: 숏 114800(KODEX 인버스 1배) · 현금 153130. 예탁 50만원(공격형 트랙과 같은 조건, 정수 주식수).
  체결: 하루 끝 정보로 상태를 정하고 **다음 거래일 시가** 체결(strategy_lab 공통), 편도 11.5bp.
  정보 시점: 한국 날짜 d 의 상태는 날짜 ≤ d 인 봉만 쓴다. 미국(VIX·S&P500)·환율의 d 일 봉은 한국 d+1 시가(09:00)
    전에 확정된다(미국 장 마감 = 한국 05~06시) — 그래서 이 신호들은 **아침 판단**(08:30 전후)으로 운용해야
    검증과 같다. 한국 지수 신호는 15:50 판단과 같다.
  후보(7개, 격자 3개씩 — 기본값은 격자 가운데, 흔히 쓰는 값):
    V1 VIX 레벨          VIX 종가 > L                         L ∈ {25, 30, 35}, 기본 30('공포' 관행선)
    V2 VIX 급등          VIX 5거래일 상승률 > g%               g ∈ {20, 30, 50}, 기본 30
    U1 미국 추세         S&P500 종가 < n일 이동평균             n ∈ {100, 200, 300}, 기본 200(Siegel·Faber)
    F1 원화 약세         원/달러 20거래일 상승률 > g%           g ∈ {2, 3, 4}, 기본 3
    K1 한국 단기 추세    KOSPI 종가 < n일 이동평균              n ∈ {10, 20, 40}, 기본 20
    K2 한국 변동성       KOSPI 20일 실현 변동성(연율) > v%      v ∈ {20, 25, 30}, 기본 25
    M1 다수결            V1·V2·U1·F1·K1·K2 기본값 중 k개 이상   k ∈ {2, 3, 4}, 기본 3(가중치 학습 없음)
  판정(전부, 학습 2015-07~2026-08, 구간 = strategy_lab.PERIODS 박스권·강세장):
    D1 돈   하락 신호 때 인버스·아니면 현금 전략의 연수익 > 현금(153130) 보유 연수익 — 박스권·강세장 **각각**
    D2 적중 하락 상태인 날, 다음 거래일 시가 → 그다음 시가 KODEX200 하락 비율 ≥ 그 구간 기저율 + 2%p — 각각
    D3 표본 학습 구간 인버스 진입 ≥ 20회 — 몇 번의 큰 하락에 기댄 우연을 거른다
    D4 격자 기본값이 D1~D3 통과 **그리고** 격자 3개 중 2개 이상 D1~D3 통과
  보고만: 기저율 · 하락 상태 비율 · 하락 상태 중 KODEX200 최대 상승일(인버스가 하루에 잃는 최악) · 미공개(오염) ·
    **반대로 읽기**(적중률이 두 구간 모두 기저율 −2%p 이하면 '하락 신호 뒤 오히려 오른다' — 롱 쪽 쓰임은 따로 선언).
  미공개(2026-08-25~10-21)는 이 축에선 오염(10월 하락·인버스 등락을 봤다) — 판정에 안 쓴다.
  통과 → '하락 예측 후보' 로만 기록, 다음 선언에서 양방향 전략으로 P1~P5. 탈락 → 같은 숫자로 다시 재지 않는다.
  여러 개를 한꺼번에 재므로(7 × 3) 우연 통과가 있을 수 있다 — 두 구간 각각 + 격자 2/3 + 20회를 함께 요구하는 이유.
"""
from __future__ import annotations

import bisect
import math
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_aggr as A  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BASE, INV1, CASH = A.BASE, A.INV1, A.CASH
EQUITY = A.AG_EQUITY
END = L.HOLDOUT[1]
EXTERNAL = ("^VIX", "^GSPC", "USD/KRW", "^KS11")
CANDIDATES: dict[str, tuple[str, tuple, float]] = {
    "V1": ("VIX 레벨 > {}", (25, 30, 35), 30),
    "V2": ("VIX 5일 급등 > {}%", (20, 30, 50), 30),
    "U1": ("S&P500 < {}일선", (100, 200, 300), 200),
    "F1": ("원/달러 20일 상승 > {}%", (2, 3, 4), 3),
    "K1": ("KOSPI < {}일선", (10, 20, 40), 20),
    "K2": ("KOSPI 20일 변동성 > {}%", (20, 25, 30), 25),
    "M1": ("위 6개 기본값 중 {}개 이상", (2, 3, 4), 3),
}
VOTERS = ("V1", "V2", "U1", "F1", "K1", "K2")
VIX_JUMP_LAG = 5
FX_WINDOW = 20
VOL_WINDOW = 20
HIT_EDGE_PP = 2.0
MIN_ENTRIES = 20
GRID_PASS = 2


# ── 신호 — d 의 상태는 날짜 ≤ d 인 봉만 ────────────────────────────────────────
def _ser(bars: dict[str, dict]) -> tuple[list[str], list[float]]:
    ds = sorted(bars)
    return ds, [bars[x]["close"] for x in ds]


def _at(ds: list[str], d: str) -> int:
    """날짜 ≤ d 인 마지막 봉의 위치(없으면 -1)."""
    return bisect.bisect_right(ds, d) - 1


def _level_above(bars, thr: float):
    ds, c = _ser(bars)

    def f(d):
        k = _at(ds, d)
        return None if k < 0 else c[k] > thr
    return f


def _change_above(bars, lag: int, pct: float):
    ds, c = _ser(bars)

    def f(d):
        k = _at(ds, d)
        return None if k < lag else c[k] / c[k - lag] - 1 > pct / 100.0
    return f


def _below_ma(bars, n: int):
    ds, c = _ser(bars)

    def f(d):
        k = _at(ds, d)
        return None if k < n - 1 else c[k] < statistics.fmean(c[k - n + 1:k + 1])
    return f


def _vol_above(bars, n: int, pct: float):
    ds, c = _ser(bars)

    def f(d):
        k = _at(ds, d)
        if k < n:
            return None
        r = [c[j] / c[j - 1] - 1 for j in range(k - n + 1, k + 1)]
        return statistics.stdev(r) * math.sqrt(252) * 100 > pct
    return f


def down_fn(code: str, p, px: dict):
    """d → True(하락 상태)·False·None(자료 부족)."""
    if code == "V1":
        return _level_above(px["^VIX"], p)
    if code == "V2":
        return _change_above(px["^VIX"], VIX_JUMP_LAG, p)
    if code == "U1":
        return _below_ma(px["^GSPC"], p)
    if code == "F1":
        return _change_above(px["USD/KRW"], FX_WINDOW, p)
    if code == "K1":
        return _below_ma(px["^KS11"], p)
    if code == "K2":
        return _vol_above(px["^KS11"], VOL_WINDOW, p)
    if code == "M1":
        fs = [down_fn(c, CANDIDATES[c][2], px) for c in VOTERS]

        def f(d):
            v = [g(d) for g in fs]
            return None if any(x is None for x in v) else sum(v) >= p
        return f
    raise KeyError(code)


# ── 전략·측정 ────────────────────────────────────────────────────────────────
def short_timing(states: dict[str, bool | None]):
    """하락 상태면 인버스, 아니면(자료 부족 포함) 현금. 상태가 바뀐 날만 목표를 낸다."""
    st = {"w": None}

    def target(i, d):
        w = {INV1: 1.0} if states.get(d) else {CASH: 1.0}
        if w == st["w"]:
            return None
        st["w"] = w
        return w
    return target


def entries(states: dict[str, bool | None], dates: list[str]) -> int:
    n, prev = 0, False
    for d in dates:
        s = bool(states.get(d))
        n += s and not prev
        prev = s
    return n


def hit_rates(states: dict[str, bool | None], base: dict[str, dict], dates: list[str], lo: str, hi: str) -> dict:
    """구간의 날 d: 다음 거래일 시가 → 그다음 시가 KODEX200 이 내렸나. 기저율·하락 상태 적중률·최대 상승일."""
    n = dn = sn = sdn = 0
    worst = (0.0, "")
    for k, d in enumerate(dates[:-2]):
        if not lo <= d <= hi:
            continue
        r = base[dates[k + 2]]["open"] / base[dates[k + 1]]["open"] - 1
        n += 1
        dn += r < 0
        if states.get(d):
            sn += 1
            sdn += r < 0
            if r > worst[0]:
                worst = (r, dates[k + 1])
    return {"base": dn / n if n else 0.0, "hit": sdn / sn if sn else 0.0, "days": sn, "share": sn / n if n else 0.0,
            "worst_up": worst}


def judge(r: dict, cash: dict) -> list[tuple[str, bool]]:
    """D1~D3 — r = measure() 결과, cash = 현금 보유의 구간별 metrics."""
    return [("D1", all(r["seg"][p]["cagr"] > cash[p]["cagr"] for p in L.PERIODS)),
            ("D2", all(r["hit"][p]["hit"] >= r["hit"][p]["base"] + HIT_EDGE_PP / 100 for p in L.PERIODS)),
            ("D3", r["entries"] >= MIN_ENTRIES)]


def contrarian(r: dict) -> bool:
    """보고만 — 두 구간 모두 적중률이 기저율 −2%p 이하(하락 신호 뒤 오히려 오른다)."""
    return all(r["hit"][p]["days"] and r["hit"][p]["hit"] <= r["hit"][p]["base"] - HIT_EDGE_PP / 100
               for p in L.PERIODS)


def measure(px: dict, dates: list[str], code: str, p) -> dict:
    f = down_fn(code, p, px)
    states = {d: f(d) for d in dates}
    res = L.simulate({c: L.Asset(c, px[c]) for c in (INV1, CASH)}, dates, short_timing(states), EQUITY)
    seg = {p_: L.slice_metrics(res, *L.PERIODS[p_]) for p_ in L.PERIODS}
    seg["전체"] = L.slice_metrics(res, *L.FULL)
    seg["미공개"] = L.slice_metrics(res, *L.HOLDOUT)
    hit = {p_: hit_rates(states, px[BASE], dates, *L.PERIODS[p_]) for p_ in L.PERIODS}
    hit["전체"] = hit_rates(states, px[BASE], dates, *L.FULL)
    learn = [d for d in dates if d <= L.FULL[1]]
    return {"seg": seg, "hit": hit, "entries": entries(states, learn)}


def load() -> dict:
    px = {c: L.load_bars(c, "2009-01-01", END) for c in (INV1, *EXTERNAL)}
    px[BASE] = L.load_bars(BASE, "2014-01-01", END)
    px[CASH] = L.load_bars(CASH, "2014-01-01", END)
    return px


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    px = load()
    dates = [d for d in L.calendar(px[BASE], L.FULL[0], END) if all(d in px[c] for c in (INV1, CASH))]
    cres = L.buy_and_hold(CASH, dates, px[CASH], EQUITY)
    cash = {p: L.slice_metrics(cres, *L.PERIODS[p]) for p in L.PERIODS}
    ires = L.buy_and_hold(INV1, dates, px[INV1], EQUITY)
    print("=" * 132)
    print(f"하락 예측 신호 판정대 — 학습 2015-07~2026-08 · 하락 신호 때 인버스(114800)·아니면 현금(153130) · 예탁 "
          f"{EQUITY:,.0f}원 · 잣대 D1~D4(선언)")
    print(f"  현금 보유 연수익: 박스권 {cash['박스권']['cagr']:.2f}% · 강세장 {cash['강세장']['cagr']:.2f}%  |  인버스 계속 보유: "
          f"박스권 {L.slice_metrics(ires, *L.PERIODS['박스권'])['cagr']:+.1f}% · "
          f"강세장 {L.slice_metrics(ires, *L.PERIODS['강세장'])['cagr']:+.1f}%")
    print(f"  {'':4}{'':26}{'박스권':>8}{'강세장':>8}{'기저율':>8}{'적중 박/강':>13}{'하락상태':>8}{'진입':>6}"
          f"{'미공개*':>8}  최대 상승일(인버스 최악)")
    print("-" * 132)
    passed, contra = [], []
    for code, (label, grid, default) in CANDIDATES.items():
        rows = {p: measure(px, dates, code, p) for p in grid}
        ok_grid = sum(all(x for _, x in judge(rows[p], cash)) for p in grid)
        for p in grid:
            r = rows[p]
            h = r["hit"]
            w = h["전체"]["worst_up"]
            mark = "*" if p == default else " "
            print(f"  {code}{mark} {label.format(p):26}"
                  f"{r['seg']['박스권']['cagr']:>+7.1f}%{r['seg']['강세장']['cagr']:>+7.1f}%{h['전체']['base']:>7.0%}"
                  f"{h['박스권']['hit']:>7.0%}/{h['강세장']['hit']:<4.0%}{h['전체']['share']:>8.0%}{r['entries']:>6}"
                  f"{r['seg']['미공개']['total']:>+7.1f}%  {w[0] * 100:+.1f}% {w[1]}")
        checks = judge(rows[default], cash)
        checks.append(("D4", all(x for _, x in checks) and ok_grid >= GRID_PASS))
        ok = all(x for _, x in checks)
        if ok:
            passed.append(code)
        if contrarian(rows[default]):
            contra.append(code)
        print(f"  {'':4}" + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks)
              + f"  (격자 통과 {ok_grid}/3) → {'하락 예측 후보' if ok else '탈락'}"
              + ("  · 반대로 읽기: 하락 신호 뒤 오히려 올랐다(보고만)" if contrarian(rows[default]) else ""))
    print("=" * 132)
    print("* 미공개(2026-08-25~10-21)는 이 축에선 오염 — 판정에 쓰지 않는다. 적중 = 다음 거래일 시가 → 그다음 시가 KODEX200 하락.")
    print(f"하락 예측 후보: {', '.join(passed) if passed else '없음'} · 반대 신호(보고만): {', '.join(contra) if contra else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
