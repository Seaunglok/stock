"""추세추종/모멘텀 종목선정 — 순수 함수 ("차수재시실" + 손익비 1:3 관리).

블로그A(4단계 관리, 손익비 1:3) + 블로그B(차수재시실: 차트·수급·재료·시황·실적) 통합.
closing_bet_mcp 의 점수/청산 순수함수를 재사용한다. 데이터 fetching 없음 — 호출자가 OHLCV/수급을 넘긴다.

OHLCV item 표준 키: {open, high, low, close, volume, value(거래대금)}. 한/영 키 모두 허용(_g).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.mcp_servers.closing_bet_mcp.exit_rules import init_stop_price, ratchet_stop
from src.mcp_servers.closing_bet_mcp.scorer import (
    _g,
    score_candle_shape,
    score_consolidation,
    score_institutional,
    score_volume_surge,
)


# ─── 설정 ──────────────────────────────────────────────────────────────────

@dataclass
class TrendConfig:
    mode: str = "largecap"          # gainers | largecap | watchlist(=largecap 게이트)
    ma_trend: int = 200             # 장기 추세선 (gainers 모드 게이트)
    ma_support: int = 50            # 지지/청산 기준선
    ma_fast: int = 60               # largecap 정배열
    ma_slow: int = 120
    ma_pullback: int = 20           # 눌림 기준선
    pullback_pct: float = 3.0       # 현재가 ≤ MA20×(1+pullback_pct%) 면 눌림권
    rs_days: int = 60               # 상대강도 비교 기간
    vol_mult: float = 2.0           # 거래량 ≥ 20일평균 × vol_mult
    body_pct: float = 4.0           # 장대양봉 몸통 % (gainers)
    wick_max: float = 0.3           # 위꼬리 비율 상한
    consol_lookback: int = 20       # 횡보 판정 직전 봉 수
    consol_max_range: float = 15.0  # 횡보 박스 폭 상한 % (저변동)
    stop_pct: float = 7.0           # ATR 없을 때 고정 손절 %
    atr_k: float = 2.0              # 트레일 밴드 = atr_k × ATR
    atr_period: int = 14
    rr: float = 3.0                 # 손익비(목표 = 손절폭 × rr)
    partial_pct: float = 30.0       # 첫 목표 도달 시 일부 익절 비율(%) — 나머지는 트레일
    max_hold: int = 60              # 백테스트 보유 상한(영업일) — 추세 안 끝나도 강제 마감


# ─── 지표 헬퍼 ──────────────────────────────────────────────────────────────

def _closes(ohlcv: list[dict]) -> list[float]:
    return [_g(d, "close") for d in ohlcv]


def moving_average(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def ma_uptrend(closes: list[float], n: int, slope_days: int = 20) -> bool:
    """MA(n) 이 slope_days 전보다 높으면 우상향."""
    if len(closes) < n + slope_days:
        return False
    now = sum(closes[-n:]) / n
    past = sum(closes[-n - slope_days:-slope_days]) / n
    return now > past


def atr(ohlcv: list[dict], period: int = 14) -> float:
    if len(ohlcv) < 2:
        return 0.0
    trs = []
    for i in range(1, len(ohlcv)):
        h, l, pc = _g(ohlcv[i], "high"), _g(ohlcv[i], "low"), _g(ohlcv[i - 1], "close")
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    k = trs[-period:]
    return sum(k) / len(k) if k else 0.0


def relative_strength(stock_closes: list[float], kospi_closes: list[float], days: int) -> float:
    """종목 days 수익률 − KOSPI days 수익률 (%). 데이터 부족 시 0."""
    def ret(c: list[float]) -> float:
        if len(c) < days + 1 or c[-days - 1] <= 0:
            return 0.0
        return (c[-1] - c[-days - 1]) / c[-days - 1] * 100.0
    return ret(stock_closes) - ret(kospi_closes)


def is_big_bullish_candle(bar: dict, body_pct: float, wick_max: float) -> bool:
    """장대양봉: 몸통 ≥ body_pct% 상승 & 위꼬리비율 ≤ wick_max & 양봉."""
    o, h, c = _g(bar, "open"), _g(bar, "high"), _g(bar, "close")
    if o <= 0 or h <= 0:
        return False
    if c < o:
        return False
    body_ret = (c - o) / o * 100.0
    rng = h - _g(bar, "low")
    upper_wick = (h - max(o, c)) / rng if rng > 0 else 0.0
    return body_ret >= body_pct and upper_wick <= wick_max


def is_consolidation(ohlcv: list[dict], lookback: int, max_range_pct: float) -> bool:
    """직전 lookback 봉(당일 제외)이 저변동 박스(고저 폭 ≤ max_range_pct%)면 횡보."""
    if len(ohlcv) < lookback + 1:
        return False
    box = ohlcv[-lookback - 1:-1]
    hi = max(_g(d, "high") for d in box)
    lo = min(_g(d, "low") for d in box)
    if lo <= 0:
        return False
    return (hi - lo) / lo * 100.0 <= max_range_pct


def volume_surge_ok(ohlcv: list[dict], mult: float) -> bool:
    if len(ohlcv) < 21:
        return False
    today = _g(ohlcv[-1], "volume")
    avg20 = sum(_g(d, "volume") for d in ohlcv[-21:-1]) / 20.0
    return avg20 > 0 and today >= avg20 * mult


# ─── 진입 신호 ──────────────────────────────────────────────────────────────

@dataclass
class TrendSignal:
    passed: bool
    score: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    reason: str = ""
    gates: dict[str, bool] = field(default_factory=dict)
    breakdown: dict[str, Any] = field(default_factory=dict)


def _composite_score(ohlcv: list[dict], foreign_net: float | None, inst_net: float | None) -> tuple[float, dict]:
    """차수재시실 점수 — closing_bet scorer 컴포넌트 재사용 (순위용)."""
    vs, vb = score_volume_surge(ohlcv)
    cs, cb = score_candle_shape(ohlcv)          # 위꼬리 작을수록 高
    co, ob = score_consolidation(ohlcv)
    inn, ib = score_institutional(foreign_net, inst_net)
    score = vs * 0.30 + cs * 0.20 + co * 0.30 + inn * 0.20
    return round(score, 1), {"volume": vb, "candle": cb, "consolidation": ob, "institutional": ib}


def _levels(entry: float, ohlcv: list[dict], cfg: TrendConfig) -> tuple[float, float]:
    a = atr(ohlcv, cfg.atr_period)
    stop = init_stop_price(entry, a, cfg.atr_k, -cfg.stop_pct)
    target = entry + cfg.rr * (entry - stop)
    return round(stop, 2), round(target, 2)


def entry_signal(
    ohlcv: list[dict],
    kospi_closes: list[float],
    cfg: TrendConfig,
    foreign_net: float | None = None,
    inst_net: float | None = None,
    rs_pass: bool | None = None,
) -> TrendSignal:
    """모드별 진입 게이트 + 점수 + 손절/목표. passed=False 면 진입 불가.

    rs_pass: RS 게이트 외부 오버라이드(예: cross-sectional RS 상위 N% 랭킹).
             None 이면 기존 절대값(RS>0=종목 60일수익률>KOSPI) 사용.
    """
    need = max(cfg.ma_trend if cfg.mode == "gainers" else cfg.ma_slow, 21) + 1
    if len(ohlcv) < need:
        return TrendSignal(False, reason=f"데이터 부족(<{need}봉)")

    closes = _closes(ohlcv)
    price = closes[-1]
    gates: dict[str, bool] = {}

    if cfg.mode == "gainers":
        ma_t = moving_average(closes, cfg.ma_trend)
        ma_s = moving_average(closes, cfg.ma_support)
        gates["price>MA200"] = ma_t is not None and price > ma_t
        gates["MA200_up"] = ma_uptrend(closes, cfg.ma_trend)
        gates["big_bullish"] = is_big_bullish_candle(ohlcv[-1], cfg.body_pct, cfg.wick_max)
        gates["vol_surge"] = volume_surge_ok(ohlcv, cfg.vol_mult)
        gates["consolidation"] = is_consolidation(ohlcv, cfg.consol_lookback, cfg.consol_max_range)
        gates["MA50_support"] = ma_s is not None and price >= ma_s * 0.97
    else:  # largecap / watchlist
        ma_f = moving_average(closes, cfg.ma_fast)
        ma_w = moving_average(closes, cfg.ma_slow)
        ma_p = moving_average(closes, cfg.ma_pullback)
        gates["price>MA60"] = ma_f is not None and price > ma_f
        gates["price>MA120"] = ma_w is not None and price > ma_w
        gates["RS>0"] = rs_pass if rs_pass is not None else (relative_strength(closes, kospi_closes, cfg.rs_days) > 0)
        gates["pullback"] = ma_p is not None and price <= ma_p * (1 + cfg.pullback_pct / 100.0)
        gates["vol_up"] = volume_surge_ok(ohlcv, 1.0)

    passed = all(gates.values())
    score, bd = _composite_score(ohlcv, foreign_net, inst_net)
    stop, target = _levels(price, ohlcv, cfg)
    reason = "진입가능" if passed else "게이트 미충족: " + ",".join(k for k, v in gates.items() if not v)
    return TrendSignal(passed, score, stop, target, reason, gates, bd)


# ─── 라이브 가점 레이어 ("차수재시실"의 실적·시황 — 게이트 아님, 순위 가점만) ──────

def fundamentals_bonus(revenue_yoy: float | None, op_income_yoy: float | None,
                       bonus: float = 5.0) -> tuple[float, dict]:
    """실적 가점 (블로그B '실적': 매출·영업이익 YoY↑).

    둘 다 증가 → bonus, 영업이익만 증가 → bonus/2, 그 외/데이터 없음 → 0.
    검증된 진입 게이트는 건드리지 않고 후보 순위에만 반영(악재 veto 아님).
    """
    detail = {"revenue_yoy": revenue_yoy, "op_income_yoy": op_income_yoy}
    if revenue_yoy is None or op_income_yoy is None:
        return 0.0, {**detail, "why": "데이터 없음"}
    if revenue_yoy > 0 and op_income_yoy > 0:
        return round(bonus, 1), {**detail, "why": "매출·영업이익 YoY 동반 증가"}
    if op_income_yoy > 0:
        return round(bonus / 2, 1), {**detail, "why": "영업이익 YoY 증가"}
    return 0.0, {**detail, "why": "YoY 증가 없음"}


def leading_sectors(sector_rows: list[dict], *,
                    min_avg_pct: float = 1.0, min_breadth: float = 0.6,
                    min_count: int = 3, top_k: int = 3) -> list[dict]:
    """당일 주도섹터(집단상승) 판정 (블로그B '시황') — 업종지수 스냅샷 기반.

    sector_rows: [{sector, change_pct(지수 등락률%), rising, falling, flat(구성종목 수)}]
    (키움 ka20001 업종현재가의 flu_rt/rising/fall/stdns).
    집단상승 = 등락률 ≥ min_avg_pct AND 상승종목 비율 ≥ min_breadth AND 구성종목 ≥ min_count.
    등락률 내림차순 top_k. 반환: [{sector, change_pct, breadth, count}].
    """
    out = []
    for r in sector_rows:
        total = int(r.get("rising", 0)) + int(r.get("falling", 0)) + int(r.get("flat", 0))
        chg = r.get("change_pct")
        if total < min_count or chg is None or chg != chg:   # 표본 부족/NaN 제외
            continue
        breadth = int(r.get("rising", 0)) / total
        if chg >= min_avg_pct and breadth >= min_breadth:
            out.append({"sector": r.get("sector", ""), "change_pct": round(float(chg), 2),
                        "breadth": round(breadth, 2), "count": total})
    out.sort(key=lambda x: -x["change_pct"])
    return out[:top_k]


def market_breadth(sector_rows: list[dict]) -> float | None:
    """KOSPI 시장 breadth — 전체 업종 구성종목의 상승 비율 (0.0 ~ 1.0).

    sector_rows: 키움 ka20001 업종지수 스냅샷 [{sector, change_pct, rising, falling, flat}].
    rising/falling/flat 합산 → 상승비율. 약세장 자동 감지용 (예: < 0.4 면 신규진입 차단 게이트).
    데이터 없음/표본 부족 시 None 반환 (fail-open — 호출자가 게이트 미적용 결정).
    """
    if not sector_rows:
        return None
    total_rising = total_falling = total_flat = 0
    for r in sector_rows:
        total_rising += int(r.get("rising", 0))
        total_falling += int(r.get("falling", 0))
        total_flat += int(r.get("flat", 0))
    total = total_rising + total_falling + total_flat
    if total < 50:        # universe 너무 작으면 신뢰 X (KOSPI 전체는 보통 800+)
        return None
    return total_rising / total


# ─── 외인 수급 신호 (ka10008 rows → 5일 순매수 판정) ─────────────────────────

def foreign_net_signal(rows: list[dict], today: str, min_ratio: float = 0.2,
                       days: int = 5, vol_days: int = 20) -> float | None:
    """외국인 최근 N영업일 순매수(보유변동 chg_qty) 합산 — **완성일 기준 + 규모 임계값**.

    2026-07-15 삼성생명 오발동 교훈: ① 당일 잠정치가 마감 후 부호 반전(잠정 -→확정 +36,598),
    ② 5일합 -2,372주(유통주식 0.001%) 노이즈에 부호만 보고 청산. → 두 결함 모두 여기서 차단:
    - rows 중 dt == today(잠정치)는 제외, 완성일 최근 days개만 합산 (시스템의 '완성봉' 원칙과 정합).
    - |합산| < min_ratio × 20일 평균거래량 이면 노이즈로 보고 None(신호 없음, fail-open).
      min_ratio=0 이면 임계값 off(부호만 판정 — 구 동작).

    Args:
        rows: ka10008 stk_frgnr 리스트(최신순). [{dt, chg_qty, trde_qty, ...}]
        today: 오늘 날짜 "YYYYMMDD" (잠정치 제외 기준).
    Returns:
        완성일 days일 순매수 합(음수=순매도) 또는 None(데이터 부족/노이즈 — 룰 미적용).
    """
    def _f(v: Any) -> float | None:
        try:
            return float(str(v).replace(",", ""))
        except Exception:
            return None

    done = []
    for r in rows or []:
        if not isinstance(r, dict) or str(r.get("dt", "")) == today:
            continue
        q = _f(r.get("chg_qty"))
        if q is None:
            continue
        done.append((q, _f(r.get("trde_qty")) or 0.0))
    if len(done) < days:
        return None                       # 완성일 데이터 부족 → 판정 불가
    net = sum(q for q, _ in done[:days])
    if min_ratio > 0:
        vols = [v for _, v in done[:vol_days] if v > 0]
        avg_vol = sum(vols) / len(vols) if vols else 0.0
        if avg_vol > 0 and abs(net) < min_ratio * avg_vol:
            return None                   # 노이즈(평균거래량 대비 미미) → 신호 아님
    return net


# ─── 청산 신호 ──────────────────────────────────────────────────────────────

def trend_exit(
    entry_price: float,
    current_price: float,
    ma_support: float | None,
    stop_price: float,
    foreign_net_5d: float | None = None,
    use_foreign_exit: bool = False,
) -> dict:
    """청산 판정: 트레일/손절 이탈 → 이평선(MA50) 하방돌파 → 외인 순매도전환 → 보유.

    트레일 stop 갱신은 호출자가 ratchet_stop 으로 수행 후 stop_price 를 넘긴다.
    """
    pnl = (current_price - entry_price) / entry_price * 100.0 if entry_price > 0 else 0.0
    if stop_price > 0 and current_price <= stop_price:
        return {"action": "SELL_ALL", "reason": f"트레일/손절 이탈 ({pnl:+.2f}%) — stop {stop_price:,.0f}"}
    if ma_support is not None and current_price < ma_support:
        return {"action": "SELL_ALL", "reason": f"이평선(MA지지) 하방돌파 ({pnl:+.2f}%)"}
    if use_foreign_exit and foreign_net_5d is not None and foreign_net_5d < 0:
        return {"action": "SELL_ALL", "reason": f"외국인 5일 순매도 전환 ({pnl:+.2f}%)"}
    return {"action": "HOLD", "reason": f"보유 ({pnl:+.2f}%)"}


# ─── JH ZONE (PDF 매매구역 모델) ─────────────────────────────────────────────

def classify_zone(price: float, ma60: float | None, ma120: float | None, *,
                  held: bool = False, stop_price: float | None = None) -> str:
    """JH ZONE 판정 (PDF 모델) — GO/HOLD/CAUTION/STOP_LOSS/WATCH.

    미보유(후보): GO=60일선 부근(±3%) 정배열 지지 진입최적 / WATCH=추세 위지만 진입존 밖 /
                  CAUTION=MA60 이탈 / STOP_LOSS=MA120 이탈.
    보유: STOP_LOSS=손절가 이탈 or MA120 이탈 / CAUTION=MA60 이탈 / HOLD=추세 유지.
    """
    if held:
        if stop_price and price <= stop_price:
            return "STOP_LOSS"
        if ma120 is not None and price < ma120:
            return "STOP_LOSS"
        if ma60 is not None and price < ma60:
            return "CAUTION"
        return "HOLD"
    if ma60 is None or ma120 is None:
        return "WATCH"
    if price < ma120:
        return "STOP_LOSS"
    if price < ma60:
        return "CAUTION"
    if ma60 > ma120 and price <= ma60 * 1.03:   # 정배열 + 60일선 ±3% 지지
        return "GO"
    return "WATCH"


# ─── 실행 결정(순수) — 사이징 / 청산 분기 ────────────────────────────────────

def is_rising(cur: float, opn: float) -> bool:
    """상승 중 = 현재가 ≥ 당일 시가. 시가/현재가 불명이면 True(차단 안 함, fail-open)."""
    if cur <= 0 or opn <= 0:
        return True
    return cur >= opn


def position_size(price: float, *, mode: str = "pct_equity", equity: float = 0.0,
                  cash: float = 0.0, pct: float = 8.0, invest_fixed: float = 500000.0,
                  stop: float = 0.0, risk_pct: float = 1.5, max_notional_pct: float = 25.0) -> int:
    """매수 수량.

    - risk: 예탁자산 risk_pct% ÷ 손절폭(price−stop) = 종목당 감수 리스크 균등(터틀식). notional 은
      max_notional_pct% 로 상한(손절폭 극소 종목 과대편입 방지). 손절폭↑ 종목은 적게, ↓ 종목은 많이 사서
      거래별 실질 리스크를 맞춘다 → equity 곡선 MDD/변동성 대폭 축소(백테스트 검증: MAR 0.87→2.34).
    - pct_equity: 예탁자산 pct% notional (현금 한도 내).
    - fixed / 데이터 부족: 고정금액(invest_fixed).

    예탁자산 조회 실패(equity=0) 또는 risk 모드인데 손절폭 무효(stop<=0 or price<=stop) 시 안전 폴백:
    pct_equity(equity>0) → notional, 그 외 → 고정금액. price<=0 이면 0.
    """
    if price <= 0:
        return 0
    if mode == "risk" and equity > 0 and stop > 0 and price > stop:
        qty = int(equity * risk_pct / 100.0 / (price - stop))
        qty = min(qty, int(equity * max_notional_pct / 100.0 / price))   # notional 상한
        if cash > 0:
            qty = min(qty, int(cash / price))
        return max(0, qty)
    if mode in ("pct_equity", "risk") and equity > 0:   # risk 폴백 = notional
        qty = int(equity * pct / 100.0 / price)
        if cash > 0:
            qty = min(qty, int(cash / price))
        return max(0, qty)
    return max(1, int(invest_fixed / price))


def exit_decision(*, entry: float, cur: float, qty: int, target: float, stop: float,
                  partial_done: bool, hard_stop_pct: float = 0.0, partial_pct: float = 30.0,
                  ma_exit: float | None = None, exit_ma_label: int = 120,
                  foreign_net: float | None = None, use_foreign: bool = False,
                  aged_out: bool = False
                  ) -> tuple[str | None, str, int]:
    """포지션 청산/부분익절 판정 → (action, reason, sell_qty). action ∈ {None, PARTIAL, EXIT}.

    우선순위: 하드손절 → 첫목표 부분익절 → 트레일/손절 이탈 → 이평선 이탈 → 외인 전환 → 보유만기.
    ma_exit/foreign_net/aged_out 은 do_exit_signals 시에만 호출자가 채워 넘긴다(None/False=미평가).
    부분익절 수량이 1주 미만(qty 소량)이면 쪼갤 수 없으므로 익절 없이 트레일 지속(우측꼬리 유지) —
    qty 전량이 나가면 qty=0 좀비 포지션이 되기 때문.
    aged_out: 백테스트 max_hold(60영업일 강제 마감)와 동일 의미의 시간청산.
    """
    pnl = (cur - entry) / entry * 100.0 if entry > 0 else 0.0
    if hard_stop_pct > 0 and pnl <= -hard_stop_pct:
        return "EXIT", f"하드 손절 ({pnl:.2f}% ≤ -{hard_stop_pct:.0f}%)", qty
    if not partial_done and target > 0 and cur >= target:
        part_qty = max(1, int(qty * partial_pct / 100))
        if part_qty < qty:   # qty=1 등 쪼갤 수 없으면 익절 없이 트레일 지속
            return "PARTIAL", f"첫 목표 도달 {partial_pct:.0f}% 익절", part_qty
    if stop > 0 and cur <= stop:
        return "EXIT", f"트레일/손절 이탈 stop {stop:,.0f}", qty
    if ma_exit is not None and cur < ma_exit:
        return "EXIT", f"MA{exit_ma_label} 이평선 하방돌파 ({cur:,.0f} < {ma_exit:,.0f})", qty
    if use_foreign and foreign_net is not None and foreign_net < 0:
        return "EXIT", "외국인 5일 순매도 전환", qty
    if aged_out:
        return "EXIT", f"보유기간 만료 ({pnl:+.2f}%) — 시간청산", qty
    return None, "", 0


# ─── 진단 ──────────────────────────────────────────────────────────────────
def analyze_gate_funnel(
    universe: list[tuple[str, str]],
    kospi_closes: list[float],
    cfg: TrendConfig,
    held: set[str] | None = None,
    ohlcv_loader=None,
) -> dict:
    """진입 게이트 퍼널 분석 — 유니버스 종목별로 entry_signal 실행해 게이트별 통과율 집계.

    어떤 게이트가 후보를 떨구는지 진단(튜닝 보조). 데몬과 무관한 순수 분석 함수.

    Args:
        universe: [(code, name)] 평가 대상 종목 리스트.
        kospi_closes: KOSPI 종가 시계열 (RS 계산용).
        cfg: TrendConfig.
        held: 평가 제외 종목 (보유 중). None=빈 set.
        ohlcv_loader: callable(code) -> list[dict] OHLCV. 호출자가 데이터 소스 주입.

    Returns:
        {
          "total": 평가 종목 수,
          "pass_counts": {gate_name: 통과 수},
          "all_pass": 전 게이트 통과(후보) 수,
          "near_miss": [(code, name, missing_gate, score)] — 1개만 부족한 종목,
        }
    """
    if held is None:
        held = set()
    if ohlcv_loader is None:
        raise ValueError("ohlcv_loader 콜백 필수(데이터 소스 주입)")
    pass_counts: dict[str, int] = {}
    total = 0
    all_pass = 0
    near_miss: list[tuple[str, str, str, float]] = []
    for code, name in universe:
        if code in held:
            continue
        ohlcv = ohlcv_loader(code)
        if not ohlcv:
            continue
        sig = entry_signal(ohlcv, kospi_closes, cfg, None, None)
        if not sig.gates:
            continue
        total += 1
        for k, v in sig.gates.items():
            if v:
                pass_counts[k] = pass_counts.get(k, 0) + 1
        fails = [k for k, v in sig.gates.items() if not v]
        if not fails:
            all_pass += 1
        elif len(fails) == 1:
            near_miss.append((code, name[:10], fails[0], round(sig.score, 1)))
    return {"total": total, "pass_counts": pass_counts,
            "all_pass": all_pass, "near_miss": near_miss}
