"""Claude 뉴스 판단 5일 양방향 — 공격형 리그에 **앞으로만** 기록 (LLM-N1 · 2026-11-25 선언).

운용자(11-25): Claude 뉴스 판단 일지(`llm_news`)를 시작한 뒤 "이걸 바로 후보로 등록하는거는 어때?" — 판정(L1·L2) 통과를 기다리지
않고 공격형 리그 그림자 멤버로 바로 넣는다(FLOW-S1 처럼 과거 검증 없이 앞으로만 — 언어 모델은 과거로는 못 잰다).
L1·L2(판단이 맞았나)와 따로, **실제로 굴렸으면 얼마였나**(비용·정수 주식·50만원)를 같은 틀에서 다른 공격형 멤버와 나란히 본다.
주문 없음 · 실계좌 없음(11-10 결정). 판정 전에 규칙을 바꾸지 않는다(바꾸려면 새 변형을 선언해 나란히).

선언 (기록 전)
  신호   `llm_news.load()` 의 날 d(≥ START): direction ≤ −1 → 하락(KODEX 인버스 114800) · ≥ +1 → 상승(KODEX200 069500) · 0 → 없음.
         d 판단은 그날 판단 배치 맨 끝(장 마감 뒤)에 나온다 → **d+1 시가 진입**(`strategy_lab.simulate` 의 '종가 판단 → 다음 시가').
         공격형 리그는 같은 배치에서 llm_news 보다 먼저 돌므로, 그날 리그는 전날까지의 판단만 본다(미래를 보지 않는다).
  보유   HOLD(5)거래일 — 진입 뒤 6번째 거래일 시가 청산(질문과 같다: 내일 시가 → 6거래일째 시가). 보유 중 신호는 건너뛴다.
         단 청산 판단일(진입 뒤 5번째 거래일 종가)의 신호: 같은 방향이면 이어서 다시 5일 · 반대 방향이면 그 시가에 바꿔 탄다 ·
         없으면 현금. 그 밖엔 현금 자리 488770. 50만원 · 정수 주식 · 비용 strategy_lab 가정(공격형 리그 공통).
  시작   신호 날 ≥ START(2026-11-26). 출발 자금 기준일 ANCHOR 2026-11-25(첫 판단 11-25 는 선언 전에 본 날 — 넣지 않는다. 값은 0).
  판정   `llm_news` 기록 ≥ JUDGE_DAYS(120)거래일 **그리고** 완료 거래 ≥ JUDGE_MIN_TRADES(10) 뒤에만: 누적 > 0 · MDD ≤ 30% ·
         완료 거래당 평균(시가→시가, 왕복 비용 뺌) > 0 (FLOW-S1 과 같은 잣대). 실계좌 재검토 자격은 ㉔ S2(`aggr_shadow.with_stat`).
  정지선 그림자 MDD 30%(공격형 리그 공통 `aggr_shadow.stop_alerts`).
  장부   `lab_trials` +1(앞으로만도 센다).
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_fear as F  # noqa: E402  — 공격형 공통(자금·현금 자리·MDD 한도)
import llm_news as N  # noqa: E402  — 판단 일지(신호 원천)
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
NAME = "LLM-N1"
INV = "114800"
LONG = F.BASE
CASH = F.CASH
HOLD = 5
ANCHOR = "2026-11-25"
START = "2026-11-26"
JUDGE_DAYS = N.JUDGE_DAYS
JUDGE_MIN_TRADES = 10
MAX_MDD_PCT = F.F_MAX_MDD_PCT
EQUITY = F.F_EQUITY
DECLARED_ON = "2026-11-25"


def asset(side: int) -> str:
    return LONG if side > 0 else INV


def signals(path: Path | None = None, start: str = START) -> dict[str, int]:
    """START 이후 판단 → {날짜: +1 상승 / −1 하락}(0 은 넣지 않는다)."""
    out = {}
    for r in (N.load(path) if path else N.load()):
        d = r.get("direction")
        if r["date"] >= start and d not in (None, ""):
            s = int(d)
            if s <= -1 or s >= 1:
                out[r["date"]] = 1 if s > 0 else -1
    return out


def plan(dates: list[str], sig: dict[str, int], hold: int = HOLD) -> tuple[dict[int, dict], list[tuple[int, int, int]]]:
    """(종가 판단 위치 → 목표 비중, [(진입 위치, 청산 위치, 방향)]). 진입 = 신호 다음 날 시가, 청산 = 진입 + hold 거래일 뒤 시가."""
    targets: dict[int, dict] = {}
    trades: list[tuple[int, int, int]] = []
    until, entry, side = -1, -1, 0
    for k, d in enumerate(dates):
        s = sig.get(d, 0)
        if until >= 0 and k == until:
            if s == side:                       # 같은 방향 — 이어서 다시 hold 일
                until = k + hold
                continue
            trades.append((entry, k + 1, side))
            if s:                               # 반대 방향 — 그 시가에 바꿔 탄다
                targets[k] = {asset(s): 1.0}
                entry, until, side = k + 1, k + hold, s
            else:
                targets[k] = {CASH: 1.0}
                until, side = -1, 0
            continue
        if until < 0 and s:
            targets[k] = {asset(s): 1.0}
            entry, until, side = k + 1, k + hold, s
    if until >= 0:
        trades.append((entry, -1, side))        # 아직 보유 중(청산 전)
    return targets, trades


def run(px: dict, upto: str, sig: dict[str, int] | None = None, equity: float = EQUITY) -> dict:
    """ANCHOR 종가부터 upto 까지 그림자 기록."""
    dates = [d for d in L.calendar(px[F.BASE], ANCHOR, upto)
             if d in px.get(INV, {}) and d in px.get(CASH, {}) and d in px.get(LONG, {})]
    if not dates:
        return {"curve": [], "trades": [], "on_today": 0, "dates": [], "signals": {}}
    sig = signals() if sig is None else sig
    targets, trades = plan(dates, sig)
    first = {"w": None}

    def target(i, d):
        if i == 0 and first["w"] is None:       # 출발은 현금
            first["w"] = True
            return targets.get(0, {CASH: 1.0})
        return targets.get(i)
    res = L.simulate({c: L.Asset(c, px[c]) for c in (INV, LONG, CASH)}, dates, target, equity)
    cost = L.side_cost(False, False)
    done = []
    for a, b, s in trades:
        if 0 <= b < len(dates) and a < len(dates):
            c = asset(s)
            o0, o1 = px[c][dates[a]].get("open"), px[c][dates[b]].get("open")
            if o0 and o1:
                done.append({"entry": dates[a], "exit": dates[b], "side": s, "ret": o1 / o0 - 1 - 2 * cost})
    holding = trades[-1][2] if trades and trades[-1][1] == -1 else 0
    return {"curve": list(zip(res.dates, res.curve)), "trades": done, "on_today": holding, "dates": dates,
            "signals": {d: s for d, s in sig.items() if d <= upto}}


def verdict(curve: list[tuple[str, float]], done: list[dict], n_records: int) -> dict:
    """선언한 판정 — 판단 기록 JUDGE_DAYS · 완료 거래 JUDGE_MIN_TRADES 가 모자라면 판정하지 않는다."""
    if n_records < JUDGE_DAYS or len(done) < JUDGE_MIN_TRADES:
        return {"judged": False, "why": f"판단 기록 {n_records}/{JUDGE_DAYS} · 완료 거래 {len(done)}/{JUDGE_MIN_TRADES}"}
    vals = [v for _, v in curve]
    mdd = L.metrics([d for d, _ in curve], vals)["mdd"]
    checks = {"누적>0": vals[-1] > vals[0], f"MDD≤{MAX_MDD_PCT:g}%": mdd <= MAX_MDD_PCT,
              "거래당>0": statistics.fmean(x["ret"] for x in done) > 0}
    return {"judged": True, "pass": all(checks.values()), "checks": checks}
