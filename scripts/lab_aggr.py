"""공격형 트랙 1세대 A — 양방향(상승은 KODEX200·레버리지, 하락은 인버스) (2026-10-28, 사전 선언).

운용자(10-28): "우리 너무 갇혀있는거 같어 … 이번달에도 10프로씩 버는 사람들이 있어 … 너무 안정적으로 하나"
→ 결정: 핵심(I3)은 그대로 두고 **공격형 트랙**을 따로 — 리그 그림자 기록 2주 → 실계좌 50만원, 트랙 자금 −30% 에서
  자동 정지 후 운용자 판단. 연구 방향 A(양방향)·B(단타, lab_orb). 그리고 목표: **"3년 동안 계속 돈을 버는 것"**.

진단 — 왜 이 축인가 (우리 리그의 빈 곳)
-------------------------------------
  · 리그 23개 전부 롱 온리 — 하락에서 버는 멤버가 0. 10월 KODEX200 −13.5% 동안 KODEX 인버스 +13.7%.
    (이 숫자를 이미 봤다 → 미공개 구간(2026-08-25~10-21)은 이 축에선 **오염** — 보고만, 판정에 안 쓴다.)
  · 레버리지는 I1b·I2b·I4 에서 '최대 낙폭 20%' 잣대로 탈락 — 전략이 나빠서가 아니라 잣대 때문. 공격형 잣대로 다시 잰다.
  · 근거: 시계열 모멘텀(Moskowitz·Ooi·Pedersen 2012, JFE 104(2) — 지난 12개월 수익 부호로 롱/숏, 58개 선물),
    Faber(2007) 10개월 이동평균. 원 출처는 롱/숏(TSMOM) 또는 롱/현금(Faber) — 개인 계좌는 공매도가 안 되니
    **숏 = 인버스 ETF 매수**. MOP 의 '초과수익(무위험 대비)' 부호는 단순 수익 부호로 대신한다(현금 이자 0 가정과 같은 쪽).

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  자산: 롱 1배 069500(KODEX200) · 롱 2배 122630(KODEX 레버리지) · 숏 114800(KODEX 인버스) · 현금 153130.
        200선물인버스2X(252670)는 **제외** — 10-27 가격 104원, 1틱(1원)이 0.96% 라 비용 가정(편도 11.5bp)과 안 맞는다.
  신호(종가 판단 → 다음 날 시가 체결, strategy_lab 공통):
    A1  Faber 양방향   월말 종가 > 최근 N개 월말 종가 평균 → 롱, 아니면 인버스.  N ∈ {6, 8, 10, 12}, 기본 10(원 출처)
    A2  TSMOM 양방향   월말에 지난 N개월(N×21영업일) 수익 > 0 → 롱, 아니면 인버스.  N ∈ {3, 6, 9, 12}, 기본 12(원 출처)
    A3  I3 엔진 양방향  엔진 보유 → 롱 · 엔진 이탈 & KOSPI < 120일선 → 인버스 · 이탈 & KOSPI ≥ 120일선 → 현금.
                       엔진 = lab_dd_control.reentry_confirmed 그대로(이탈 −X% · 재진입 n일 고점 + KOSPI>MA120).
                       격자 = I1_GRID(X 5·10·15 × n 10·20·40), 기본 (10, 20). 부모 I3 의 약점 '이탈 중 놀고 있음'을 겨눈다.
    롱 배수: 'a' = 1배(069500), 'b' = 2배(122630). 숏은 언제나 인버스 1배.  → A1a·A1b·A2a·A2b·A3a·A3b (6개)
  예탁: AG_EQUITY 50만원(운용 조건 = 검증 조건, 정수 주식수).
  입장 조건(전부, 2015-07~2026-08 학습 구간):
    P1 최대 낙폭 ≤ 30%            — 운용자 정지선(트랙 −30%)과 같은 숫자: 과거 어느 날 시작했어도 정지선에 안 닿았다
    P2 연수익 ≥ max(KODEX200 보유, I3) + 5%p — 위험을 더 지는 만큼 핵심과 지수를 분명히 이겨야 한다
    P3 박스권·강세장 **각각** 연수익 ≥ KODEX200 보유 — 한 구간만 탄 전략 금지(strategy_lab ④ 그대로)
    P4 롤링 3년(756영업일) 수익 최솟값 > 0 — 운용자 목표 "3년 동안 계속 돈을 번다": 어느 날 시작했든 3년 뒤엔 플러스
    P5 격자 중앙값도 P1~P4 — 가장 좋은 설정 하나가 아니라 '보통의 설정'이 통과
  보고만(판정 아님): 최악 연도 · 장기(1998~, ^KS11 합성 — 2배·인버스는 일간 배수 합성, 낙관 쪽) 최대 낙폭·30% 낙폭 횟수·
    롤링 3년 최솟값 · 미공개(오염) · 매매 수 · 롤링 1년 플러스 비율.
  운용자 지향(10-28) "월 10% 수익을 3년 동안" = 36개월 1.1^36 ≈ 30.9배(연 ≈ 214%) — strategy_lab 의 지향 CAGR 처럼
    **보고만**: 월 +10% 이상인 달 비율 · 최악의 달 · 롤링 3년 수익 중앙값(배수). 판정 기준으로 쓰면 아무것도 통과하지
    못해 비교가 안 되고, 기준을 결과에 맞춰 낮추는 유혹만 생긴다.
  참고로 KODEX 레버리지(122630) 단순 보유도 같은 표에 둔다(신호 없는 '공격'의 기준선).
  통과하면 공격형 리그(그림자, 주문 없음)에 등록 → 2주 기록 → 운용자 승인 시 실계좌 50만원. 떨어지면 기록만 —
  같은 숫자로 다시 재지 않는다. 잣대 상수는 결과를 본 뒤 고치지 않는다.

1세대 A 결과 (be1839c 선언대로, 기준 수정 없음) — **6개 전부 탈락**
              연수익   MDD   박스권  강세장  3년최악  월+10%달  최악달
  KODEX200    16.75%  40.8%   4.1%  23.1%  −20.8%     7%   −21.3%
  레버리지보유  23.82%  68.3%   3.2%  34.8%  −46.5%    22%   −45.2%
  I3(핵심)    12.10%  18.5%   5.9%  15.0%   −9.3%     4%   −10.6%
  A1a 14.9%·40.8% · A1b 25.4%·68.4% · A2a 10.1%·40.1% · A2b 18.2%·68.3% · A3a 12.5%·38.9%
  A3b         24.88%  50.8%  16.3%  28.7%  −30.6%    19%   −26.1%   → P2·P3 통과, P1·P4·P5 탈락
진단(탐색 — 판정에 안 씀):
  ① 인버스는 돈을 잃었다 — A3 의 인버스 보유 685일 누적 −33%. A1a(14.9%) < KODEX200 보유(16.8%), A3a 는 I3 와 수익이
    같고 MDD 2배. 2015~2026 은 장기 상승장이라 하락 신호의 대부분이 곧 되돌아왔다.
  ② 수익은 레버리지가 만든다(A3b 연 24.9%·박스권 16.3%) — 모든 후보의 최대 낙폭은 2026-06~08 급락. 엔진 이탈(−10%)이
    2배 상품에는 늦다. I3 가 이 구간을 18.5% 로 막은 건 낙폭 예산 덕(엔진만으론 못 막는다).
  ③ P4 '어느 날 시작했든 3년 뒤 플러스'는 I3(−9.3%)·KODEX200(−20.8%)도 못 넘는다 — 2015~2026 에서 이 기준을 넘은
    전략은 아직 없다.
  ④ 월 +10% 인 달은 레버리지 보유 22%·A3b 19% 로 '자주' 오지만 최악 달이 −45%·−26% — 꾸준하지 않다.
  떨어진 6개는 같은 숫자로 다시 재지 않는다. 다음은 ②의 진단에서: 레버리지 × 낙폭 예산(인버스 없이).
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
import lab_challengers as CH  # noqa: E402
import lab_classics as C  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BASE, LEV2, INV1, CASH = "069500", "122630", "114800", "153130"
EXCLUDED = {"252670": "200선물인버스2X — 10-27 가격 104원, 1틱 0.96%(비용 가정 11.5bp 와 안 맞음)"}
LONG = {"a": BASE, "b": LEV2}
AG_EQUITY = 500_000.0                 # 운용자 결정(10-28) 실계좌 50만원
AG_MAX_MDD_PCT = 30.0                 # 운용자 정지선 −30%
AG_EXCESS_PP = 5.0
ROLL_3Y = 756                         # 3년 = 252 × 3 영업일
ROLL_1Y = 252
ASPIRATION_MONTHLY_PCT = 10.0         # 운용자 지향(10-28) 월 10% × 36개월 — 보고만
ASPIRATION_MONTHS = 36
A1_GRID, A1_DEFAULT = (6, 8, 10, 12), 10
A2_GRID, A2_DEFAULT = (3, 6, 9, 12), 12
A3_GRID, A3_DEFAULT = I.I1_GRID, I.I1_DEFAULT
FAMILIES = {"A1": (A1_GRID, A1_DEFAULT), "A2": (A2_GRID, A2_DEFAULT), "A3": (A3_GRID, A3_DEFAULT)}
SPECS = tuple(f"{f}{lv}" for f in FAMILIES for lv in LONG)          # A1a A1b A2a A2b A3a A3b
END = L.HOLDOUT[1]


# ── 신호 → 목표 비중 ─────────────────────────────────────────────────────────
def _changed_only(state_fn, long_code: str, inv: str, cash: str | None):
    """state_fn(i, d) → 'up'|'down'|'flat'|None(판단 없음). 상태가 바뀐 날만 목표를 낸다(매달 같은 비중 재조정 없음)."""
    st = {"w": None}

    def target(i, d):
        s = state_fn(i, d)
        if s is None:
            return None
        w = {long_code: 1.0} if s == "up" else {inv: 1.0} if s == "down" else ({cash: 1.0} if cash else {})
        if w == st["w"]:
            return None
        st["w"] = w
        return w
    return target


def faber_ls(bars, months: int, ends: set[str]):
    """A1 — 월말 종가가 최근 months 개 월말 종가 평균보다 높으면 'up', 아니면 'down'. 자료 부족이면 'flat'."""
    me = [d for d in sorted(bars) if d in ends]
    mpos = {d: k for k, d in enumerate(me)}

    def state(i, d):
        k = mpos.get(d)
        if k is None:
            return None
        if k < months - 1:
            return "flat"
        sma = statistics.fmean(bars[x]["close"] for x in me[k - months + 1:k + 1])
        return "up" if bars[d]["close"] > sma else "down"
    return state


def tsmom_ls(bars, months: int, ends: set[str]):
    """A2 — 월말에 지난 months×21 영업일 수익 > 0 이면 'up', 아니면 'down'."""
    days, pos, cl = C._closes(bars)
    look = months * 21

    def state(i, d):
        if d not in ends:
            return None
        k = pos.get(d)
        if k is None:
            return None
        if k < look:
            return "flat"
        return "up" if cl[k] / cl[k - look] - 1 > 0 else "down"
    return state


def engine_ls(bars, kospi, x_pct: float, n: int):
    """A3 — 검증된 I3 엔진(reentry_confirmed)을 그대로 쓰고, 이탈 중엔 KOSPI 가 120일선 아래면 'down'(인버스)."""
    eng = I.reentry_confirmed(bars, kospi, "__IN__", x_pct, n, "__OUT__")
    kdays = sorted(kospi)
    kpos = {d: k for k, d in enumerate(kdays)}
    kcl = [kospi[d]["close"] for d in kdays]
    ma = I.I1_REGIME_MA
    st = {"in": None}

    def below(d: str) -> bool:
        k = kpos.get(d)
        if k is None or k + 1 < ma:
            return False
        return kcl[k] < sum(kcl[k + 1 - ma:k + 1]) / ma

    def state(i, d):
        r = eng(i, d)
        if r is not None:
            st["in"] = "__IN__" in r
        if st["in"] is None:
            return None
        if st["in"]:
            return "up"
        return "down" if below(d) else "flat"
    return state


def make_state(family: str, param, bars, kospi, ends: set[str]):
    if family == "A1":
        return faber_ls(bars, param, ends)
    if family == "A2":
        return tsmom_ls(bars, param, ends)
    return engine_ls(bars, kospi, *param)


# ── 지표 ─────────────────────────────────────────────────────────────────────
def rolling_min(curve: list[float], window: int) -> float:
    """롤링 창 수익(%)의 최솟값 — '어느 날 시작했든 window 뒤의 최악'. 창보다 짧으면 nan."""
    if len(curve) <= window:
        return float("nan")
    return min((curve[k] / curve[k - window] - 1) * 100 for k in range(window, len(curve)))


def rolling_pos_share(curve: list[float], window: int) -> float:
    rs = [curve[k] / curve[k - window] - 1 for k in range(window, len(curve))]
    return sum(1 for r in rs if r > 0) / len(rs) if rs else float("nan")


def rolling_median(curve: list[float], window: int) -> float:
    rs = [(curve[k] / curve[k - window] - 1) * 100 for k in range(window, len(curve))]
    return statistics.median(rs) if rs else float("nan")


def monthly_returns(dates: list[str], curve: list[float]) -> list[float]:
    """월말 값 대비 월말 값(%) — 첫 달은 시작값 대비."""
    ends: dict[str, float] = {}
    for d, v in zip(dates, curve):
        ends[d[:7]] = v
    vals = [curve[0]] + list(ends.values()) if curve else []
    return [(b / a - 1) * 100 for a, b in zip(vals, vals[1:])]


def dd_events(curve: list[float], cut_pct: float = AG_MAX_MDD_PCT) -> int:
    """최고점 대비 cut_pct 이상 빠진 '사건' 수(새 최고점을 찍어야 다음 사건으로 센다)."""
    peak, inside, n = curve[0] if curve else 0.0, False, 0
    for v in curve:
        if v > peak:
            peak, inside = v, False
        if peak > 0 and (peak - v) / peak * 100 >= cut_pct and not inside:
            n, inside = n + 1, True
    return n


def spans(res: L.SimResult) -> dict:
    full = [(d, v) for d, v in zip(res.dates, res.curve) if L.FULL[0] <= d <= L.FULL[1]]
    fc = [v for _, v in full]
    mr = monthly_returns([d for d, _ in full], fc)
    return {"전체": L.slice_metrics(res, *L.FULL), "박스권": L.slice_metrics(res, *L.PERIODS["박스권"]),
            "강세장": L.slice_metrics(res, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(res, *L.HOLDOUT),
            "roll3": rolling_min(fc, ROLL_3Y), "roll1_pos": rolling_pos_share(fc, ROLL_1Y), "trades": res.trades,
            "roll3_med": rolling_median(fc, ROLL_3Y),
            "m10": sum(1 for x in mr if x >= ASPIRATION_MONTHLY_PCT) / len(mr) if mr else float("nan"),
            "worst_month": min(mr) if mr else float("nan")}


def verdict(r: dict, bench: dict, core: dict) -> list[tuple[str, bool]]:
    """선언한 입장 조건 그대로(P1~P4) — r/bench/core 는 spans() 결과(core = I3)."""
    f = r["전체"]
    return [
        ("P1", f["mdd"] <= AG_MAX_MDD_PCT),
        ("P2", f["cagr"] >= max(bench["전체"]["cagr"], core["전체"]["cagr"]) + AG_EXCESS_PP),
        ("P3", all(r[p]["cagr"] >= bench[p]["cagr"] for p in L.PERIODS)),
        ("P4", r["roll3"] > 0),
    ]


def grid_median(rows: list[dict]) -> dict:
    """격자 결과들의 지표별 중앙값 — P5 는 이 dict 로 verdict 를 다시 돌린다."""
    out = {}
    for span in ("전체", *L.PERIODS):
        out[span] = {k: statistics.median(r[span][k] for r in rows) for k in ("cagr", "mdd")}
    out["roll3"] = statistics.median(r["roll3"] for r in rows)
    return out


# ── 실행 ─────────────────────────────────────────────────────────────────────
def load() -> dict:
    px = {c: L.load_bars(c, "2009-01-01", END) for c in (LEV2, INV1)}
    px[BASE] = L.load_bars(BASE, "2014-01-01", END)
    px[CASH] = L.load_bars(CASH, "2014-01-01", END)
    px["^KS11"] = L.load_bars("^KS11", "1996-01-01", END)
    return px


def run_spec(px: dict, dates: list[str], family: str, lv: str, param) -> dict:
    ends = C.month_ends(sorted(px[BASE]))
    t = _changed_only(make_state(family, param, px[BASE], px["^KS11"], ends), LONG[lv], INV1, CASH)
    assets = {c: L.Asset(c, px[c]) for c in (LONG[lv], INV1, CASH)}
    return spans(L.simulate(assets, dates, t, AG_EQUITY))


def run_long(ks: dict, family: str, lv: str, param) -> dict:
    """장기 스트레스(보고만) — ^KS11 과 그 일간 2배·−1배 합성. 현금 이자 0."""
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    up = ks if lv == "a" else L.leveraged_bars(ks, 2.0)
    assets = {"UP": L.Asset("UP", up), "INV": L.Asset("INV", L.leveraged_bars(ks, -1.0))}
    ends = C.month_ends(sorted(ks))
    t = _changed_only(make_state(family, param, ks, ks, ends), "UP", "INV", None)
    r = L.simulate(assets, long_dates, t, 0.0)
    return {"mdd": L.metrics(r.dates, r.curve)["mdd"], "events": dd_events(r.curve),
            "roll3": rolling_min(r.curve, ROLL_3Y), "cagr": L.metrics(r.dates, r.curve)["cagr"]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    px = load()
    dates = [d for d in L.calendar(px[BASE], L.FULL[0], END) if all(d in px[c] for c in (LEV2, INV1, CASH))]
    bench = spans(L.buy_and_hold(BASE, dates, px[BASE], AG_EQUITY))
    m, lb = H.I3_DEFAULT
    core = spans(L.simulate({BASE: L.Asset(BASE, px[BASE]), CASH: L.Asset(CASH, px[CASH])}, dates,
                            CH.i3x(px[BASE], px["^KS11"], BASE, CASH, m, lb, **CH.SPECS["I3"]), AG_EQUITY,
                            pass_nav=True))
    print("=" * 128)
    print(f"공격형 1세대 A(양방향) — 학습 2015-07~2026-08, 예탁 {AG_EQUITY:,.0f}원 · 숏 = 인버스 1배 · 잣대 P1~P5(선언)")
    print(f"  {'':10}{'연수익':>8}{'MDD':>7}{'최악':>8}{'박스권':>8}{'강세장':>8}{'3년최악':>9}{'1년+비율':>9}"
          f"{'미공개*':>8}{'매매':>6}  | 월+10%달 · 최악달 · 3년 중앙값 | 장기 MDD·30%사건·3년최악")

    def row(name, r, lg=None):
        f = r["전체"]
        tail = (f"  | {lg['mdd']:5.1f}% · {lg['events']}회 · {lg['roll3']:+6.1f}%" if lg else "")
        print(f"  {name:10}{f['cagr']:>7.2f}%{f['mdd']:>6.1f}%{f['worst_year']:>+7.1f}%{r['박스권']['cagr']:>7.1f}%"
              f"{r['강세장']['cagr']:>7.1f}%{r['roll3']:>+8.1f}%{r['roll1_pos']:>8.0%}{r['미공개']['total']:>+7.1f}%"
              f"{r['trades']:>6}  | {r['m10']:>5.0%} · {r['worst_month']:+6.1f}% · {r['roll3_med']:+7.1f}%{tail}")
    row("KODEX200", bench)
    row("레버리지보유", spans(L.buy_and_hold(LEV2, dates, px[LEV2], AG_EQUITY)))
    row("I3(핵심)", core)
    goal = ((1 + ASPIRATION_MONTHLY_PCT / 100) ** ASPIRATION_MONTHS - 1) * 100
    print(f"  지향(운용자): 월 +{ASPIRATION_MONTHLY_PCT:g}% × {ASPIRATION_MONTHS}개월 = 3년 {goal:+,.0f}% "
          f"(연 {((1 + ASPIRATION_MONTHLY_PCT / 100) ** 12 - 1) * 100:.0f}%) — 보고만")
    print("-" * 128)
    passed = []
    for fam, (grid, default) in FAMILIES.items():
        for lv in LONG:
            name = f"{fam}{lv}"
            rows = {p: run_spec(px, dates, fam, lv, p) for p in grid}
            r = rows[default]
            row(name, r, run_long(px["^KS11"], fam, lv, default))
            checks = verdict(r, bench, core)
            med = grid_median(list(rows.values()))
            p5 = all(ok for _, ok in verdict({**med, "미공개": {}}, bench, core))
            checks.append(("P5", p5))
            ok = all(x for _, x in checks)
            if ok:
                passed.append(name)
            print(f"  {'':10}" + " · ".join(f"{c}{'O' if x else 'X'}" for c, x in checks)
                  + f"  (격자 중앙값 연수익 {med['전체']['cagr']:.1f}% · MDD {med['전체']['mdd']:.1f}% · 3년최악 {med['roll3']:+.1f}%)"
                  + f" → {'공격형 리그 입장' if ok else '탈락'}")
    print("=" * 128)
    print("* 미공개(2026-08-25~10-21)는 이 축에선 오염(10월 인버스 등락을 선언 전에 봤다) — 판정에 쓰지 않는다.")
    print(f"공격형 리그 입장: {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
