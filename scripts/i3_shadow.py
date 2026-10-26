"""I3 리그 — 챔피언(실전 I3)과 여러 계열의 도전자를 매일 같은 조건으로 기록하고, 선언된 승격 규칙으로 판정한다.

운용자(10-22): "매일매일 발전해야 한다" · "도전자를 계속 만들어 발전 — 약점은 줄이고 강점은 살려라" ·
"기본은 I3 로 꾸준히 벌면서 더 나은 알고리즘을 검증하며 보완" · "추세추종·단타 등 다양한 알고리즘을 가져와 경쟁".

    연구(사전선언·백테스트) ──▶ 리그 입장(주문 없음) ──매일 15:50 판단 뒤 기록──▶ 승격 규칙 충족
        ──▶ 텔레그램 '승격 후보' ──운용자 승인──▶ 실전(i3_core 교체 + 실전==검증 대조 테스트)

- **주문과 무관하다.** 별도 프로세스(i3_decide.cmd 가 판단 뒤 실행) — 실패해도 실전 판단·매매에 영향 없다.
  멤버 하나가 실패해도 나머지는 기록한다.
- 모든 멤버가 같은 조건: **실전 시작일**(state navs[0])에 같은 자산으로 출발, 신호는 과거부터 재생(워밍업),
  체결은 각 엔진의 검증 가정, 남는 돈은 i3_core.CASH(머니마켓). 챔피언 모델은 실계좌의 기준선이기도 하다.
- 결과: `data/i3/shadow.json`(최신·순위·승격 판정) · `data/i3/shadow_history.csv`(일별 1행).
  텔레그램: 매일 리그 순위 한 통 · 승격 조건을 처음 충족한 날(critical).

입장 규칙: ① 연구에서 사전선언으로 측정한 계열의 **선언 기본값**은 운용 가능하면 들어온다(운용자 결정 10-22).
② 결과를 보고 만든 새 설계(세대)는 `lab_challengers` 입장 조건(E1·E2·E3)을 통과해야 한다.
등록일을 남긴다 — 승격 판정은 등록일 이후 실전 데이터만 쓴다.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import lab_reentry as R  # noqa: E402
import strategy_lab as L  # noqa: E402

DATA_DIR = _ROOT / "data" / "i3"
SHADOW_FILE = DATA_DIR / "shadow.json"
HISTORY_FILE = DATA_DIR / "shadow_history.csv"
AFTER_CLOSE = dtime(15, 35)
DIVERGE_PP = 0.10                # 위험 비중이 이만큼 다르면 '다르게 행동한 날'(I3 매매 밴드와 같은 값)
KOSPI = "^KS11"
NDQ = "133690"                   # TIGER 미국나스닥100

# ── 승격 규칙 (2026-10-22 선언 — 실전 데이터를 보기 전. 결과를 보고 고치면 무효) ──────────────
PROMO_MIN_DAYS = 120             # 실전 기록 최소 영업일(약 6개월)
PROMO_MIN_DIVERGE_DAYS = 20      # 챔피언과 다르게 행동한 날이 이만큼은 있어야 비교가 된다
PROMO_MARGIN_PP = 2.0            # 등록 이후 누적 수익 ≥ 챔피언 + 2%p
PROMO_MAX_MDD = 20.0             # 운용자 ① 그대로
PROMO_MDD_TOL_PP = 3.0           # 그리고 MDD ≤ 챔피언 MDD + 3%p
PROMO_CONSECUTIVE = 2            # 월간 점검에서 연속 충족 횟수(멤버가 많을수록 '운 좋은 1등'이 나온다)

# ── 리그 운영 규칙 (2026-10-22 운용자 확정 — 첫 실전 기록 전. 바꾸는 건 매년 1월 점검 때만) ──────────
RELEGATE_MDD = 25.0              # 등록 후 MDD 초과 → 즉시 탈락(위험)
RELEGATE_MIN_DAYS = 60           # 부진·중복 탈락은 등록 후 이만큼 지난 뒤(약 3개월)
RELEGATE_LAG_PP = 10.0           # 월간 점검: 등록 후 누적이 챔피언보다 이만큼 낮으면 탈락(부진)
DUP_CORR = 0.98                  # 월간 점검: 최근 DUP_WINDOW 일 일간 수익 상관 ≥ 이면 '중복 의심' **알림만**
DUP_WINDOW = 60                  # (10-22 구현 중 수정 — 첫 기록 전): 자동 탈락으로 하면 R1·R6(재진입 때만 다름)과
#                                  같은 시기에 둘 다 100% 보유인 계열(Faber·골든크로스)이 차이가 드러나기 전에 잘린다.
DOWN_RUNS = 5                    # 연속 실패(데이터 중단·상장폐지 등) 이만큼이면 탈락(운용 불가)
CAPACITY = 25                    # 정원(활성 멤버, 챔피언 포함). 10-22 운용자 결정으로 20→25 — 1월 점검 밖의 예외
#                                  (D5a 를 넣을 자리: "25개 늘리자 그럼")
MAX_NEW_PER_MONTH = 3            # 월 신규 등록 상한(창립 멤버 2026-10-22 제외)
INTAKE_EXCEPTIONS = {            # 월 상한 밖으로 들어온 멤버 — 운용자 결정만(규칙 변경이 아니라 건별 예외로 남긴다)
    "T6c": "운용자 예외(10-23): '6세대는 다음주에 바로 추가하자' — 10월 상한(저베타·퀄리티·D5a) 밖, 10-26 등록",
}
FOUNDING_DATE = "2026-10-22"
CHAMPION_ALERT_MDD = 20.0        # 챔피언 실계좌 낙폭이 넘으면 긴급 점검(자동 교체 없음)
CHAMPION_ALERT_YEAR = -10.0      # 챔피언 실계좌 올해 수익이 이 아래면 긴급 점검
STATUS_FILE = DATA_DIR / "league_status.json"


# ── 공통: 실전 시작일부터의 그림자 실행 ──────────────────────────────────────────
def exposure(out: dict[str, float] | None) -> float:
    """위험 비중 = 현금 자리(머니마켓) 밖의 비중 합."""
    return sum(w for c, w in (out or {}).items() if c != K.CASH)


def shadow_target(inner, start: str, equity: float, needs_nav: bool = True):
    """inner 를 과거부터 재생하되 start 전에는 자산을 equity 로 고정해 넣고 매매하지 않는다
    → start 일에 '실전 시작일에 새로 출발한' 상태. start 일엔 그날의 목표 비중을 강제로 낸다(실전의 첫 판단과 같다)."""
    desired: dict = {"out": None, "w": None, "hist": {}, "trade_days": set()}

    def target(i: int, d: str, nav: float):
        r = inner(i, d, equity if d < start else nav) if needs_nav else inner(i, d)
        if r is not None:
            desired["out"] = r
            desired["w"] = exposure(r)
        if d < start:
            return None
        desired["hist"][d] = desired["w"] or 0.0
        out = desired["out"] if d == start else r
        if out is not None:
            desired["trade_days"].add(d)
        return out
    target.desired = desired
    return target


def cash_fill(inner):
    """비중 합이 1 보다 작으면 나머지를 현금 자리(머니마켓)에 — 모든 멤버의 놀고 있는 돈을 같은 조건으로."""
    def target(*a):
        r = inner(*a)
        if r is None:
            return None
        out = dict(r)
        rest = 1.0 - sum(out.values())
        if rest > 1e-9:
            out[K.CASH] = out.get(K.CASH, 0.0) + rest
        return out
    return target


def remap(inner, mapping: dict[str, str]):
    """연구 코드의 현금 종목(153130 등)을 리그 현금 자리로 바꿔 낸다."""
    def target(*a):
        r = inner(*a)
        if r is None:
            return None
        out: dict[str, float] = {}
        for c, w in r.items():
            out[mapping.get(c, c)] = out.get(mapping.get(c, c), 0.0) + w
        return out
    return target


def next_weekday(d: str) -> str:
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x.isoformat()


def _calendar(data: dict, upto: str) -> list[str]:
    return sorted(d for d in data[K.BASE] if K.REPLAY_START <= d <= upto)


def _pack(res: L.SimResult, t, start: str, equity: float) -> dict:
    pts = [(d, v) for d, v in zip(res.dates, res.curve) if d >= start]
    return {"curve": [(d, round(v)) for d, v in pts], "w_hist": dict(t.desired["hist"]),
            "trade_days": sorted(t.desired["trade_days"]), "nav_hist": dict(pts), "w": t.desired["w"] or 0.0}


def std_run(build: Callable[[dict, list[str]], tuple]):
    """build(data, dates) → (자산 코드들, target, needs_nav[, 체결 방식]) 인 연구 함수를 리그 실행기로.
    체결 방식 'SAME_CLOSE' 면 신호 낸 날 종가 체결(RSI2 처럼 원전이 종가 매매인 것)."""
    def run(data: dict, start: str, equity: float, upto: str) -> dict:
        import lab_exec_timing as T
        dates = _calendar(data, upto)
        codes, inner, needs_nav, *rest = build(data, dates)
        fill = rest[0] if rest else None
        t = shadow_target(inner, start, equity, needs_nav)
        assets = {c: L.Asset(c, T.fill_bars(data[c], fill) if fill else data[c]) for c in codes}
        res = L.simulate(assets, dates, t, equity, pass_nav=True)
        return _pack(res, t, start, equity)
    return run


# ── 멤버 정의 ────────────────────────────────────────────────────────────────
def _b_i3(mode: str):
    def build(data, dates):
        return (K.BASE, K.CASH), R.i3r(data[K.BASE], data[KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, mode), True
    return build


def _b_i3x(spec: str):
    """lab_challengers 일반형(세대별 설계) — 같은 i3x 를 그대로 쓴다(다시 구현하지 않는다)."""
    def build(data, dates):
        import lab_challengers as CH
        return ((K.BASE, K.CASH),
                CH.i3x(data[K.BASE], data[KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, **CH.SPECS[spec]), True)
    return build


def _b_gen6(spec: str):
    """6세대(lab_gen6 선언 1406001) — 같은 i3x 에 선언한 배수 옵션만 얹는다(다시 구현하지 않는다)."""
    def build(data, dates):
        import lab_challengers as CH
        import lab_gen6 as G6
        return ((K.BASE, K.CASH),
                CH.i3x(data[K.BASE], data[KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, **G6.SPECS6[spec]), True)
    return build


def _b_gen7(spec: str):
    """7세대(lab_gen7 선언 ef2d207) — 같은 i3x 에 선언한 배수·브레이크 옵션만 얹는다."""
    def build(data, dates):
        import lab_challengers as CH
        import lab_gen7 as G7
        return ((K.BASE, K.CASH),
                CH.i3x(data[K.BASE], data[KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, **G7.SPECS7[spec]), True)
    return build


def _b_d5a(data, dates):
    """5세대 D5a — lab_gen5 선언(c9f5dfd) 그대로: I3 × 남는 돈은 방어 자산 TSMOM. 연구의 현금(153130)만 리그 현금 자리로."""
    import lab_classics as C
    import lab_gen5 as G5
    ends = month_ends_live(sorted(data[K.BASE]))
    t = G5.combine(data[K.BASE], data[KOSPI], C.tsmom({a: data[a] for a in G5.DEF3}, ends))
    return (K.BASE, *G5.DEF3, K.CASH), remap(t, {G5.CASH: K.CASH}), True


def _b_i1a(data, dates):
    import lab_dd_control as I
    t = I.reentry_confirmed(data[K.BASE], data[KOSPI], K.BASE, *I.I1_DEFAULT, K.CASH)
    return (K.BASE, K.CASH), t, False


def _b_ma60(data, dates):
    import lab_index_candidates as A
    return (K.BASE, K.CASH), cash_fill(A.ma_filter(data[KOSPI], A.DEFAULT_MA, K.BASE)), False


def _b_dual(data, dates):
    import lab_index_candidates as A
    t, nxt = A.dual_momentum({c: data[c] for c in (K.BASE, NDQ, "114260")}, A.DEFAULT_DM)
    ext = dates + [next_weekday(dates[-1])]           # 오늘이 월말인지는 다음 영업일로 판단(평일 근사)
    nxt.update(zip(ext, ext[1:]))
    return (K.BASE, NDQ, "114260", K.CASH), cash_fill(t), False


def _b_alloc(data, dates):
    import lab_buffett as B
    px = B.Prices({c: data[c] for c in B.D_ASSETS})
    t = B.strat_d(px, dates + [next_weekday(dates[-1])], *B.D_DEFAULT)
    return (*B.D_ASSETS, K.CASH), cash_fill(remap(t, {B.CASH_ETF: K.CASH})), False


def _run_half_half(data: dict, start: str, equity: float, upto: str) -> dict:
    """KODEX200 I3(KOSPI 추세) 절반 + 나스닥100 I3(자기 추세) 절반, 각자 낙폭 예산 — 재조정 없음."""
    def sleeve(asset, regime):
        def build(d, dates):
            return (asset, K.CASH), R.i3r(d[asset], d[regime], asset, K.CASH, K.M, K.LOOKBACK, "I3"), True
        return std_run(build)(data, start, equity / 2, upto)
    kr, us = sleeve(K.BASE, KOSPI), sleeve(NDQ, NDQ)
    us_nav = us["nav_hist"]
    curve = [(d, v + us_nav.get(d, 0)) for d, v in kr["curve"]]
    w_hist = {d: (kr["w_hist"].get(d, 0) + us["w_hist"].get(d, 0)) / 2 for d in kr["w_hist"]}
    return {"curve": curve, "w_hist": w_hist, "trade_days": sorted(set(kr["trade_days"]) | set(us["trade_days"])),
            "nav_hist": dict(curve), "w": (kr["w"] + us["w"]) / 2}


def _run_trend(data: dict, start: str, equity: float, upto: str) -> dict:
    """종료한 대형주 추세추종 — 라이브 설정 그대로(trend_paper 와 같은 엔진), 같은 자산으로 실전 시작일 출발."""
    os.environ.setdefault("TREND_BT_EQUITY", str(int(equity)))
    import backtest_trend_portfolio as P
    import trend_paper as TP
    from backtest_walkforward import Costs
    from src.mcp_servers.trend_mcp import costs as C
    cfg, k = TP._live_cfg()
    dates, _b, _c, _o = P._load(TP.DATA_START, upto, 100)
    win = [d for d in dates if d >= start]
    if not win:
        return {"curve": [(start, round(equity))], "w_hist": {}, "trade_days": [], "nav_hist": {start: equity}, "w": None}
    P._SIG_MEMO.clear()
    # end 는 위 _load 와 같은 값(upto)으로 — 다르면 캐시 키가 달라 100종목을 다시 받는다(10-22 리팩터에서 발견)
    res = P.simulate(TP.DATA_START, upto, 100, cfg, Costs(C.TAX_BPS, C.FEE_BPS, C.SLIPPAGE_BPS),
                     P.Sizing(mode="notional", position_pct=k["position_pct"]), k["max_pos"], 0,
                     "partial" in k["exits"], P._sector_map(), hard_stop_pct=k["hard_stop"],
                     rank_mode=k["rank_mode"], regime_ma=k["regime_ma"], breadth_min=k["breadth_min"],
                     exits=k["exits"], sim_from=start, sim_to=dates[-1])
    scale = equity / P.START_EQUITY                   # 다른 예탁으로 이미 로드됐으면 비율로 맞춘다
    curve = [(d, round(v * scale)) for d, v in zip(win, res.equity_curve)]
    return {"curve": curve, "w_hist": {}, "trade_days": [], "nav_hist": dict(curve), "w": None}


# ── 고전·펀드·논문·GitHub (lab_classics — 원 출처 파라미터 그대로) ─────────────────────────
def month_ends_live(days: list[str]) -> set[str]:
    """월말 영업일 — 마지막 날(오늘)은 다음 평일로 판단(매일 재실행에도 결과가 흔들리지 않게)."""
    import lab_classics as C
    nxt = next_weekday(days[-1])
    return C.month_ends(days + [nxt]) - {nxt}


def _b_classic(name: str):
    def build(data, dates):
        import lab_classics as C
        k = data[K.BASE]
        ends = month_ends_live(sorted(k))
        qends = {d for d in ends if int(d[5:7]) in (3, 6, 9, 12)}
        one = (K.BASE, K.CASH)
        table = {
            "FABER10": (one, C.faber10(k, K.BASE, ends), None),
            "TSMOM": ((*C.TSMOM_ASSETS, K.CASH), C.tsmom({a: data[a] for a in C.TSMOM_ASSETS}, ends), None),
            "VOLMGD": (one, C.volmgd(k, K.BASE, ends), None),
            "ALLWTHR": ((*C.AW_WEIGHTS, K.CASH), C.all_weather(qends), None),
            "TURTLE55": (one, C.turtle(k, K.BASE), None),
            "RSI2": (one, C.rsi2(k, K.BASE), "SAME_CLOSE"),
            "BOLLMR": (one, C.bollinger_mr(k, K.BASE), None),
            "GCROSS": (one, C.golden_cross(k, K.BASE), None),
        }
        codes, t, fill = table[name]
        return codes, cash_fill(t), False, fill
    return build


def _run_vbreak(data: dict, start: str, equity: float, upto: str) -> dict:
    """래리 윌리엄스 변동성 돌파(k=0.5) — 고가·저가가 필요해 OHLC 를 따로 쓴다. 출발일엔 사지 않는다."""
    import lab_classics as C
    ohlc = data[f"ohlc:{K.BASE}"]
    dates = _calendar(data, upto)
    d, v, _, buys = C.vbreak_curve(ohlc, data[K.CASH], dates, equity, start=start, no_trade_on_start=True)
    curve = [(x, round(y)) for x, y in zip(d, v)]
    bset = set(buys)
    w_hist = {x: (1.0 if x in bset else 0.0) for x in d}
    return {"curve": curve, "w_hist": w_hist, "trade_days": sorted(bset), "nav_hist": dict(curve),
            "w": w_hist.get(d[-1], 0.0) if d else 0.0}


def _run_factor(kind: str):
    """AQR 팩터(lab_factors) — 대형주 100 은 '추세추종' 멤버와 같은 _load 키라 캐시를 같이 쓴다(추가 로드 0)."""
    def run(data: dict, start: str, equity: float, upto: str) -> dict:
        import contextlib
        import io
        import backtest_trend_portfolio as P
        import lab_factors as F
        import trend_paper as TP
        with contextlib.redirect_stdout(io.StringIO()):
            _d, bars, _c, _o = P._load(TP.DATA_START, upto, 100)
        ends = month_ends_live(sorted(data[K.BASE]))
        inner = (F.bab_target(bars, data[KOSPI], ends) if kind == "BAB"
                 else F.qmj_target(bars, F.load_fund(), ends))
        # 종목 시세(FDR 날짜표 기준)는 15:50 에 하루 늦다 — KODEX 달력(오늘까지)으로 돌리면 오늘 칸이 가격 없이 0 이 되고
        # 기준일만 '오늘'로 보였다(10-23 저베타·퀄리티 0.00%). 시세가 있는 날까지만 돌려 기준일을 정직하게(추세추종과 같게).
        last = max((max(b) for b in bars.values() if b), default="")
        dates = [d for d in _calendar(data, upto) if d <= last]
        if not dates or dates[-1] < start:
            return {"curve": [(start, round(equity))], "w_hist": {}, "trade_days": [], "nav_hist": {start: equity},
                    "w": None}
        t = shadow_target(cash_fill(inner), start, equity, needs_nav=False)
        assets = {c: L.Asset(c, b, True) for c, b in bars.items()}
        assets[K.CASH] = L.Asset(K.CASH, data[K.CASH])
        res = L.simulate(assets, dates, t, equity, pass_nav=True)
        return _pack(res, t, start, equity)
    return run


@dataclass(frozen=True)
class Member:
    name: str
    family: str
    registered: str
    admitted: str
    note: str
    codes: tuple[str, ...]
    run: Callable[[dict, str, float, str], dict]


CHAMPION = "I3"
_D = "2026-10-22"
_OP = "운용자 결정(10-22): 연구한 계열 선언 기본값으로 경쟁"
MEMBERS: tuple[Member, ...] = (
    Member("I3", "I3", _D, "챔피언(실전)", "재진입 확인 엔진 × 낙폭 예산", (K.BASE, K.CASH, KOSPI), std_run(_b_i3("I3"))),
    Member("R1", "I3 계보", _D, "운용자 결정(10-22): 그림자 기록", "8차: 재진입 리셋 — 강세장 강점·연속 실패 약점",
           (K.BASE, K.CASH, KOSPI), std_run(_b_i3("R1"))),
    Member("R6", "I3 계보", _D,
           "운용자 예외(10-22): 입장 조건 E2(강세장 +1%p)를 0.2%p 차로 못 넘음 — 규칙 밖 결정으로 입장",
           "3세대: 1년 1회 리셋 + KOSPI 250일선 상승 때만 — 학습에서 위험은 I3 와 같고 연 +0.5%p",
           (K.BASE, K.CASH, KOSPI), std_run(_b_i3x("R6"))),
    Member("I1a", "I3 계보", _D, _OP, "5차: I3 의 엔진만(낙폭 예산 없음)", (K.BASE, K.CASH, KOSPI), std_run(_b_i1a)),
    Member("MA60", "지수 추세", _D, _OP, "1차 A: KODEX200 ⇔ KOSPI>MA60", (K.BASE, K.CASH, KOSPI), std_run(_b_ma60)),
    Member("듀얼모멘텀", "모멘텀", _D, _OP, "1차 C: 월말 KODEX200·나스닥100·국고채3년 12개월 수익 비교",
           (K.BASE, NDQ, "114260", K.CASH, KOSPI), std_run(_b_dual)),
    Member("자산배분", "자산배분", _D, _OP, "2차 D: 5자산 역변동성 + 변동성 목표 12%(월말)",
           ("069500", "133690", "148070", "132030", "138230", K.CASH, KOSPI), std_run(_b_alloc)),
    Member("한미반반", "자산배분", _D, _OP, "ETF 비교: KODEX200 I3 + 나스닥100 I3 반반(재조정 없음)",
           (K.BASE, NDQ, K.CASH, KOSPI), _run_half_half),
    Member("추세추종", "종목 추세추종", _D, _OP, "06~10월 실전 운용 후 종료한 대형주 추세추종(라이브 설정 그대로)",
           (K.BASE, KOSPI), _run_trend),
)
_CL = "운용자 결정(10-22): 고전·펀드·논문·GitHub 알고리즘, 원 출처 파라미터 그대로(lab_classics b09a202)"
_TS = ("069500", "133690", "148070", "132030", "138230")
_AW = ("069500", "148070", "114260", "132030")
MEMBERS = MEMBERS + (
    Member("Faber10", "논문 추세", _D, _CL, "Faber(2007) 월말 10개월선", (K.BASE, K.CASH, KOSPI), std_run(_b_classic("FABER10"))),
    Member("TSMOM", "논문 모멘텀", _D, _CL, "Moskowitz·Ooi·Pedersen(2012) 5자산 12개월, 롱온리",
           (*_TS, K.CASH, KOSPI), std_run(_b_classic("TSMOM"))),
    Member("변동성관리", "논문 변동성", _D, _CL, "Moreira·Muir(2017) 1/전월분산, 상한 1",
           (K.BASE, K.CASH, KOSPI), std_run(_b_classic("VOLMGD"))),
    Member("올웨더", "펀드 자산배분", _D, _CL, "브리지워터 올웨더 대중판 30/40/15/15 분기 재조정",
           (*_AW, K.CASH, KOSPI), std_run(_b_classic("ALLWTHR"))),
    Member("터틀", "추세 돌파", _D, _CL, "터틀 시스템2 55/20(종가 돈치안)", (K.BASE, K.CASH, KOSPI), std_run(_b_classic("TURTLE55"))),
    Member("RSI2", "단기 역추세", _D, _CL, "Connors(2009) 200일선 위 RSI(2)<10, 종가 매매",
           (K.BASE, K.CASH, KOSPI), std_run(_b_classic("RSI2"))),
    Member("볼린저", "단기 역추세", _D, _CL, "볼린저 20일 2σ 역추세", (K.BASE, K.CASH, KOSPI), std_run(_b_classic("BOLLMR"))),
    Member("골든크로스", "추세", _D, _CL, "50/200일선", (K.BASE, K.CASH, KOSPI), std_run(_b_classic("GCROSS"))),
    Member("변동성돌파", "단타", _D, _CL, "래리 윌리엄스 k=0.5, 돌파 매수 → 다음 날 시가 매도",
           (K.BASE, K.CASH, KOSPI, f"ohlc:{K.BASE}"), _run_vbreak),
)
_AQR = "리그 정책 ①(외부 알고리즘 원 출처 규칙 롱온리판, lab_factors 선언 8a69f6d) — 운용자 '남은 일 진행'(10-22)"
MEMBERS = MEMBERS + (
    Member("저베타", "펀드 팩터(AQR)", "2026-10-23", _AQR, "Frazzini·Pedersen(2014) BAB 롱온리 — 베타 하위 20종목",
           (K.BASE, K.CASH, KOSPI), _run_factor("BAB")),
    Member("퀄리티", "펀드 팩터(AQR)", "2026-10-23", _AQR, "Asness 외(2019) QMJ 롱온리 — 수익성·안전성 상위 20종목",
           (K.BASE, K.CASH, KOSPI), _run_factor("QMJ")),
)
_DEF3 = ("148070", "132030", "138230")          # 국고채10년·금·달러 = lab_gen5.DEF3 (테스트가 같은지 확인)
MEMBERS = MEMBERS + (
    Member("D5a", "I3 계보", "2026-10-23",
           "운용자 예외(10-22): 입장 조건 G3(미공개 ≥ I3 −1%p)만 미달 — 규칙 밖 결정으로 입장, 정원 20→25 도 같은 결정",
           "5세대: I3 × 남는 돈은 국고채10년·금·달러 중 12개월 수익 > 0 인 것에 1/3씩 — 학습에서 위험은 I3 와 같고 연 +1.6%p",
           (K.BASE, *_DEF3, K.CASH, KOSPI), std_run(_b_d5a)),
)
MEMBERS = MEMBERS + (
    Member("T6c", "I3 계보", "2026-10-26",
           "6세대 입장 조건 E1·G2·G3·G6 전부 통과(lab_gen6 선언 1406001 → 측정). 선언은 11-02 등록이었으나 "
           "운용자 예외(10-23)로 10-26 — 10월 신규 상한 밖(INTAKE_EXCEPTIONS)",
           "6세대: 낙폭 예산 배수를 KOSPI 250일선 방향으로 — 상승 8 · 그 외 4. 학습 연 13.8%·MDD 18.6%(I3 12.6%·19.8%), "
           "단 6월 갭 급락 −11.5%(I3 −10.5%)",
           (K.BASE, K.CASH, KOSPI), std_run(_b_gen6("T6c"))),
)
MEMBERS = MEMBERS + (
    Member("V7a", "I3 계보", "2026-11-02",
           "7세대 입장 조건 E1·G2·G3·G6·E7 전부 통과(lab_gen7 선언 ef2d207 → 측정). 단 G3(미공개) 여유 0.1%p",
           "7세대: T6c + 변동성 브레이크(배수 × min(1, σ252/σ20), 하한 2). 학습 연 13.2%·MDD 16.5%·6월 갭 −10.3% "
           "(T6c 13.8%·18.6%·−11.5%), 대신 미공개 −3.6%·박스권 4.2%",
           (K.BASE, K.CASH, KOSPI), std_run(_b_gen7("V7a"))),
)


# ── 데이터 점검 (운용자 10-22: "이번엔 백테스트 제대로 하는 거지?") ───────────────────────
AUDIT_TOL = 0.005                # 장기 이력(FDR)과 키움 원자료가 겹치는 날 종가 차이 한도 — 실전 판단과 같은 값


def audit_sources(hist: dict, recent: dict, upto: str) -> float | None:
    """겹치는 날(오늘 제외 최근 20일) 시가·종가 최대 상대 차이. 겹치는 날이 5일 미만이면 None."""
    common = sorted(d for d in recent if d in hist and d < upto)[-20:]
    if len(common) < 5:
        return None
    return max(abs(recent[d][f] / hist[d][f] - 1) for d in common for f in ("open", "close")
               if hist[d].get(f) and recent[d].get(f))


def run_league(data: dict, start: str, equity: float, upto: str,
               members: tuple[Member, ...] = MEMBERS) -> dict[str, dict]:
    """멤버별 결과. 실패한 멤버는 {'error': ...} 로 남기고 나머지는 계속한다."""
    out = {}
    for m in members:
        try:
            out[m.name] = m.run(data, start, equity, upto)
        except Exception as e:                     # 리그는 기록용 — 한 멤버 실패가 전체를 막지 않는다
            out[m.name] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return out


def run_models(base: dict, kospi: dict, cash: dict, start: str, equity: float, upto: str,
               models: dict[str, str] | None = None) -> dict:
    """I3 계보만 빠르게(테스트·진단용) — {이름: i3r mode}."""
    data = {K.BASE: base, KOSPI: kospi, K.CASH: cash}
    models = models or {"I3": "I3", "R1": "R1"}
    return {n: std_run(_b_i3(mode))(data, start, equity, upto) for n, mode in models.items()}


def promotion(champ: dict, chal: dict, since: str) -> dict:
    """등록일(since) 이후만 잘라 선언된 승격 규칙으로 판정."""
    cc = [(d, v) for d, v in champ["curve"] if d >= since]
    xc = [(d, v) for d, v in chal["curve"] if d >= since]
    if len(cc) < 2 or len(xc) < 2:
        return {"days": len(xc), "ok": False, "checks": {}}
    cm = L.metrics([d for d, _ in cc], [v for _, v in cc])
    xm = L.metrics([d for d, _ in xc], [v for _, v in xc])
    if chal.get("w_hist"):
        diverge = sum(1 for d, w in chal["w_hist"].items()
                      if d >= since and abs(w - champ["w_hist"].get(d, 0.0)) >= DIVERGE_PP)
    else:
        diverge = len(xc)                          # 비중을 모르는 계열(종목형) — 늘 다르게 행동한 것으로
    checks = {
        f"기록 ≥ {PROMO_MIN_DAYS}일": len(xc) >= PROMO_MIN_DAYS,
        f"다르게 행동한 날 ≥ {PROMO_MIN_DIVERGE_DAYS}": diverge >= PROMO_MIN_DIVERGE_DAYS,
        f"누적 ≥ 챔피언 +{PROMO_MARGIN_PP:g}%p": xm["total"] >= cm["total"] + PROMO_MARGIN_PP,
        f"MDD ≤ {PROMO_MAX_MDD:g}%": xm["mdd"] <= PROMO_MAX_MDD,
        f"MDD ≤ 챔피언 +{PROMO_MDD_TOL_PP:g}%p": xm["mdd"] <= cm["mdd"] + PROMO_MDD_TOL_PP,
    }
    return {"days": len(xc), "diverge_days": diverge, "ret": round(xm["total"], 3), "champ_ret": round(cm["total"], 3),
            "mdd": round(xm["mdd"], 3), "champ_mdd": round(cm["mdd"], 3), "checks": checks, "ok": all(checks.values())}


# ── 리그 운영: 탈락·승격 연속·중복·챔피언 점검 (순수 함수 — 테스트로 일부러 깨뜨린다) ─────────────
def _since(curve: list, since: str) -> list:
    return [(d, v) for d, v in curve if d >= since]


def relegation(champ: dict, chal: dict, since: str, review: bool) -> str | None:
    """탈락 사유 하나(없으면 None). 위험은 매일, 부진은 월간 점검 + 최소 체류 뒤."""
    xc = _since(chal["curve"], since)
    if len(xc) < 2:
        return None
    xm = L.metrics([d for d, _ in xc], [v for _, v in xc])
    if xm["mdd"] > RELEGATE_MDD:
        return f"위험: 등록 후 MDD {xm['mdd']:.1f}% > {RELEGATE_MDD:g}%"
    if not review or len(xc) < RELEGATE_MIN_DAYS:
        return None
    cc = _since(champ["curve"], since)
    if len(cc) < 2:
        return None
    cm = L.metrics([d for d, _ in cc], [v for _, v in cc])
    if xm["total"] < cm["total"] - RELEGATE_LAG_PP:
        return f"부진: 등록 후 {xm['total']:+.1f}% < 챔피언 {cm['total']:+.1f}% − {RELEGATE_LAG_PP:g}%p"
    return None


def _daily_rets(curve: list) -> dict[str, float]:
    return {b[0]: b[1] / a[1] - 1 for a, b in zip(curve, curve[1:]) if a[1] > 0}


def duplicates(results: dict, regs: dict[str, str]) -> list[tuple[str, str, float]]:
    """[(탈락할 이름, 남길 이름, 상관)] — 둘 다 최소 체류를 채웠고 최근 DUP_WINDOW 일 일간 수익 상관 ≥ DUP_CORR.
    먼저 들어온 쪽(같으면 이름순 앞)을 남긴다. 챔피언은 탈락시키지 않는다."""
    import statistics as stt
    names = [n for n, r in results.items() if "curve" in r]
    rets = {n: _daily_rets(results[n]["curve"]) for n in names}
    out, gone = [], set()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a in gone or b in gone:
                continue
            common = sorted(set(rets[a]) & set(rets[b]))[-DUP_WINDOW:]
            if len(common) < DUP_WINDOW:
                continue
            xa, xb = [rets[a][d] for d in common], [rets[b][d] for d in common]
            if stt.pstdev(xa) == 0 or stt.pstdev(xb) == 0:
                continue
            c = stt.correlation(xa, xb)
            if c >= DUP_CORR:
                keep, drop = sorted((a, b), key=lambda n: (n != CHAMPION, regs.get(n, ""), n))
                out.append((drop, keep, round(c, 4)))
                gone.add(drop)
    return out


def champion_alert(navs: list[list]) -> str | None:
    """실계좌(챔피언) 제1원칙 점검 — 최고 대비 낙폭 · 올해 수익. 자동 교체는 하지 않는다."""
    if len(navs) < 2:
        return None
    peak, mdd = navs[0][1], 0.0
    for _, v in navs:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    year = navs[-1][0][:4]
    first = next((v for d, v in navs if d[:4] == year), navs[0][1])
    ytd = (navs[-1][1] / first - 1) * 100
    if mdd > CHAMPION_ALERT_MDD:
        return f"실계좌 최고 대비 낙폭 {mdd:.1f}% > {CHAMPION_ALERT_MDD:g}%"
    if ytd < CHAMPION_ALERT_YEAR:
        return f"실계좌 올해 수익 {ytd:+.1f}% < {CHAMPION_ALERT_YEAR:+g}%"
    return None


def is_review_day(status: dict, upto: str) -> bool:
    """그 달 첫 리그 실행(= 첫 영업일 판단 뒤)이 월간 점검. 같은 달 두 번 하지 않는다."""
    return status.get("last_review", "")[:7] != upto[:7]


def govern(status: dict, res: dict, members, upto: str, live_navs: list[list]) -> tuple[dict, list[tuple[str, bool]]]:
    """운영 규칙을 오늘 결과에 적용 → (새 status, [(알림 문구, critical)]). status 는 append-only 성격으로 쌓는다."""
    st = json.loads(json.dumps(status or {}))
    st.setdefault("retired", {})
    st.setdefault("errors", {})
    st.setdefault("promo_streak", {})
    st.setdefault("reviews", {})
    msgs: list[tuple[str, bool]] = []
    regs = {m.name: m.registered for m in members}
    active = [m for m in members if m.name not in st["retired"]]
    champ = res.get(CHAMPION, {})

    def retire(name, reason):
        st["retired"][name] = {"date": upto, "reason": reason}
        msgs.append((f"🚪 [I3 리그] {name} 탈락 — {reason} (기록은 보관, 같은 설정 재입장 없음)", False))

    for m in active:                                   # 운용 불가
        if m.name == CHAMPION:
            continue
        if "error" in res.get(m.name, {}):
            st["errors"][m.name] = st["errors"].get(m.name, 0) + 1
            if st["errors"][m.name] >= DOWN_RUNS:
                retire(m.name, f"운용 불가: {DOWN_RUNS}회 연속 실패 ({res[m.name]['error'][:60]})")
        else:
            st["errors"][m.name] = 0
    review = is_review_day(st, upto)
    if "curve" in champ:
        for m in active:
            if m.name == CHAMPION or m.name in st["retired"] or "curve" not in res.get(m.name, {}):
                continue
            why = relegation(champ, res[m.name], m.registered, review)
            if why:
                retire(m.name, why)
    if review:
        alive = {m.name: res[m.name] for m in active if m.name not in st["retired"] and "curve" in res.get(m.name, {})}
        long_enough = {n: r for n, r in alive.items()
                       if len(_since(r["curve"], regs[n])) >= RELEGATE_MIN_DAYS or n == CHAMPION}
        dups = duplicates(long_enough, regs)
        for drop, keep, c in dups:
            msgs.append((f"🔁 [I3 리그] 중복 의심 — {drop} ↔ {keep} 최근 {DUP_WINDOW}일 일간 수익 상관 {c:.3f} "
                         f"(자동 탈락 안 함: 같은 국면에선 다른 설계도 같게 움직인다 — 운용자 판단)", False))
        cands = []
        if "curve" in champ:
            for m in active:
                if m.name == CHAMPION or m.name in st["retired"] or "curve" not in res.get(m.name, {}):
                    continue
                ok = promotion(champ, res[m.name], max(m.registered, champ["curve"][0][0]))["ok"]
                st["promo_streak"][m.name] = st["promo_streak"].get(m.name, 0) + 1 if ok else 0
                if st["promo_streak"][m.name] >= PROMO_CONSECUTIVE:
                    cands.append(m.name)
        for n in cands:
            msgs.append((f"🏆 [I3 리그] {n} 승격 후보 — 월간 점검 {PROMO_CONSECUTIVE}회 연속 승격 조건 충족. "
                         f"운용자 승인 전엔 챔피언을 바꾸지 않는다(실행 가능성·실전==검증 대조 먼저).", True))
        n_active = sum(1 for m in members if m.name not in st["retired"])
        st["reviews"][upto[:7]] = {"date": upto, "active": n_active, "retired_total": len(st["retired"]),
                                   "candidates": cands, "duplicate_suspects": [[a, b, c] for a, b, c in dups]}
        st["last_review"] = upto
        if n_active > CAPACITY:
            msgs.append((f"⚠️ [I3 리그] 활성 멤버 {n_active} > 정원 {CAPACITY} — 신규 등록 중지", False))
    why = champion_alert(live_navs)
    if why:
        msgs.append((f"⛔ [I3] 챔피언 긴급 점검 — {why}. 자동 교체 없음, 운용자 판단 필요", True))
    return st, msgs


def _slug(name: str) -> str:
    return name.lower()


def history_cols() -> list[str]:
    names = [m.name for m in MEMBERS]
    return ["date", "live_nav"] + [f"{_slug(n)}_nav" for n in names] + [f"{_slug(n)}_w" for n in names]


def append_history(row: dict, path: Path = HISTORY_FILE) -> None:
    """같은 날짜 행은 바꿔 쓴다(하루 두 번 돌아도 1행). 멤버가 늘면 열도 는다(옛 행은 빈칸)."""
    cols = history_cols()
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            cols = cols + [c for c in (rd.fieldnames or []) if c not in cols]
            rows = [r for r in rd if r.get("date") != row["date"]]
    rows.append({k: row.get(k, "") for k in cols})
    rows.sort(key=lambda r: r["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


async def _load_data(today: str) -> tuple[dict, dict]:
    """멤버가 쓰는 종목: 장기 이력 FDR + 최근·오늘 일봉 키움(실전 판단과 같은 출처).
    두 출처를 겹치는 날로 대조한 결과(audit)도 돌려준다 — 어긋나면 그날 리그 기록은 믿을 수 없다."""
    import i3_live as LV
    import lab_classics as C
    m = LV.KiwoomMarket()
    codes = sorted({c for mb in MEMBERS for c in mb.codes})
    data, audit = {}, {}
    for c in codes:
        if c == KOSPI:
            hist, rec = await m.kospi_bars(), await m.recent("KOSPI")
        elif c.startswith("ohlc:"):
            code = c.split(":", 1)[1]
            hist, rec = C.load_ohlc(code, "2010-01-01", today), await m.recent(code)   # 실전과 같은 조회(고가·저가 포함)
        else:
            hist = L.load_bars(c, "2010-01-01", today)
            try:
                rec = await m.recent(c)
            except Exception:
                rec = {}
        audit[c] = audit_sources(hist, rec, today)
        data[c] = {**hist, **rec}
    return data, audit


def summary_line(rec: dict) -> str:
    """텔레그램 한 통 — 시작일 대비 수익 순위."""
    rows = [(n, v) for n, v in rec["models"].items() if "ret" in v]
    rows.sort(key=lambda x: -x[1]["ret"])
    body = " · ".join(f"{'👑' if n == CHAMPION else ''}{n} {v['ret']:+.2f}%"
                      + (f"({v['asof'][5:]} 기준)" if v.get("asof") and v["asof"] != rec["asof"] else "")
                      for n, v in rows)
    errs = [n for n, v in rec["models"].items() if "error" in v]
    tail = f" · 오류 {', '.join(errs)}" if errs else ""
    return (f"🏟️ [I3 리그] {rec['asof']} (시작 {rec['start']} 대비) 실계좌 {rec['live']['ret']:+.2f}% | "
            f"{body}{tail} — 도전자는 주문 없음")


async def main_async(now: datetime) -> int:
    import i3_live as LV
    st = LV.load_state()
    navs = st.get("navs") or []
    if not navs:
        print(json.dumps({"skip": "실전 자산 이력 없음 — 첫 판단 전"}, ensure_ascii=False))
        return 0
    start, equity = navs[0][0], float(navs[0][1])
    today = now.strftime("%Y-%m-%d")
    data, audit = await _load_data(today)
    bad = {c: x for c, x in audit.items() if x is not None and x > AUDIT_TOL}
    if bad:
        await LV._notify("⛔ [I3 리그] 데이터 출처 불일치 — 오늘 리그 기록은 믿을 수 없다: "
                         + ", ".join(f"{c} {x:.2%}" for c, x in bad.items()), critical=True)
    base, kospi = data[K.BASE], data[KOSPI]
    # 장중엔 오늘 일봉이 미완성 — 15:35 전이면 어제까지만 본다
    upto = (today if now.time() >= AFTER_CLOSE and today in base and today in kospi
            else max(d for d in base if d < today))
    status = json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}
    retired = set((status.get("retired") or {}).keys())
    res = run_league(data, start, equity, upto, tuple(m for m in MEMBERS if m.name not in retired))
    champ = res[CHAMPION]
    live_nav = float(navs[-1][1])
    promo = {}
    models = {}
    for mb in MEMBERS:
        if mb.name in retired:
            models[mb.name] = {"retired": status["retired"][mb.name], "family": mb.family}
            continue
        r = res[mb.name]
        if "error" in r:
            models[mb.name] = {"error": r["error"], "family": mb.family}
            continue
        last = r["curve"][-1]
        mdd = L.metrics([d for d, _ in r["curve"]], [v for _, v in r["curve"]])["mdd"] if len(r["curve"]) > 1 else 0.0
        models[mb.name] = {"family": mb.family, "nav": last[1], "asof": last[0],
                           "ret": round((last[1] / equity - 1) * 100, 3), "mdd": round(mdd, 3),
                           "w": None if r["w"] is None else round(r["w"], 4),
                           "registered": mb.registered, "admitted": mb.admitted, "note": mb.note}
        if mb.name != CHAMPION and "error" not in champ:
            promo[mb.name] = promotion(champ, r, max(start, mb.registered))
    rec = {"asof": upto, "start": start, "equity": round(equity),
           "live": {"nav": round(live_nav), "ret": round((live_nav / equity - 1) * 100, 3), "date": navs[-1][0]},
           "models": models, "promotion": promo,
           "audit": {c: (None if x is None else round(x, 6)) for c, x in audit.items()}, "audit_ok": not bad}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SHADOW_FILE)
    row = {"date": upto, "live_nav": round(live_nav) if navs[-1][0] == upto else ""}
    for n, v in models.items():
        if "nav" in v:
            row[f"{_slug(n)}_nav"], row[f"{_slug(n)}_w"] = v["nav"], "" if v["w"] is None else v["w"]
    append_history(row)
    new_status, msgs = govern(status, res, MEMBERS, upto, navs)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_status, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    await LV._notify(weekly_table(rec) if now.weekday() == 4 else summary_line(rec))
    for text, critical in msgs:
        await LV._notify(text, critical=critical)
    return 0


def weekly_table(rec: dict) -> str:
    """매주 금요일 — 상세 순위표(등록 후 수익·MDD·위험 비중)."""
    rows = [(n, v) for n, v in rec["models"].items() if "ret" in v]
    rows.sort(key=lambda x: -x[1]["ret"])
    lines = [f"📊 [I3 리그 주간] {rec['asof']} · 실계좌 {rec['live']['ret']:+.2f}% (시작 {rec['start']})"]
    for i, (n, v) in enumerate(rows, 1):
        w = "-" if v.get("w") is None else f"{v['w']:.0%}"
        lag = f" ({v['asof'][5:]} 기준)" if v.get("asof") and v["asof"] != rec["asof"] else ""   # 데이터가 늦은 멤버
        lines.append(f"{i:>2}. {'👑' if n == CHAMPION else ''}{n} {v['ret']:+.2f}%{lag} · MDD {v['mdd']:.1f}% · 비중 {w}")
    gone = [n for n, v in rec["models"].items() if "retired" in v]
    if gone:
        lines.append("탈락: " + ", ".join(gone))
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    return asyncio.run(main_async(datetime.now()))


if __name__ == "__main__":
    raise SystemExit(main())
