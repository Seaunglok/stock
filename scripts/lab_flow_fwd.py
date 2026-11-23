"""외국인 극단 순매도 뒤 20일 인버스 — 공격형 리그에 **앞으로만** 기록 (아이디어 장부 10번 · 2026-11-23 선언).

운용자(11-23) "나머지 진행해줘" — 남은 일 목록의 '아이디어 10번 앞으로만 기록'.

출처   `lab_flows`(11-16, c4c077f → 7d490e1) 보고만: S1(외국인 확정 순매수의 60일 z ≤ −2) 뒤 **20일**은 두 구간 모두 평소보다 약했다
       (초과 +1.15 · +0.85%p, 가설 방향). 선언된 5일 보유는 2021~ 뒤집혀 탈락. **표를 보고 떠올린 것이라 과거로 판정하지 않는다**
       (작업 규칙 1) — 이 선언 뒤의 신호만 성적이다. 같은 숫자(60·2)는 신호 정의를 바꾸지 않으려고 그대로 쓴다(새로 고르지 않음).
왜 돈이 되나(누가 손해) — 가설: 외국인의 큰 매도는 한 번에 끝나지 않는다(운용사 비중 조정·위험 축소는 며칠~몇 주에 나눠 판다).
       첫 큰 매도를 '바닥'으로 보고 받아 간 쪽이 그 뒤 한 달의 추가 매도를 떠안는다. 문헌은 외국인 수급의 앞날 예측력이 약하다는 쪽
       (Choe·Kho·Stulz 1999 · Richards 2005 — `lab_flows` 머리말) — 그래서 과거가 아니라 앞으로 잰다.
선언 (기록 전 — 바꾸려면 새 변형을 선언해 나란히, 공격형 리그 방식)
  신호   `lab_flows.fires("S1")` 를 `lab_flows.load`(확정치 check ok)·`zscores` 로 그대로. d 일 확정치는 d+1 08:30(시장 일지)에 나온다 →
         d 종가 판단 · **d+1 시가 진입**(`strategy_lab.simulate` 의 '종가 판단 → 다음 시가'). 오늘 확정치는 내일 나오므로 마지막 날은 신호 없음.
  보유   KODEX 인버스(114800) HOLD(20)거래일 → 진입 뒤 21번째 거래일 시가 청산(`lab_flows.forward` 와 같은 시가→시가).
         보유 중 신호는 건너뛴다 — 단 청산 판단일(진입 뒤 20번째 거래일 종가)의 신호는 이어서 다시 20일(`lab_flows.trades` 규칙).
         그 밖엔 현금 자리 488770. 50만원 · 정수 주식 · 비용 strategy_lab 가정(공격형 리그 공통).
  시작   신호 날 ≥ START(2026-11-24) 만. 출발 자금 기준일 ANCHOR 2026-11-23(11-20 외국인 −1.10조는 선언 전에 본 날 — 넣지 않는다).
  판정   완료 거래 ≥ JUDGE_MIN_TRADES(10) 뒤에만: 누적 > 0 · MDD ≤ 30% · 완료 거래당 평균(시가→시가, 왕복 비용 뺌) > 0.
         실계좌 재검토 자격은 ㉔ S2(`league_stats`, `aggr_shadow.with_stat`). 신호가 연 6~8번이라 판정은 약 2년 뒤 — 그때까지 기록만.
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
import lab_flows as FL  # noqa: E402  — 신호 정의 그대로(다시 구현하지 않는다)
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
NAME = "FLOW-S1"
SIGNAL = "S1"
INV = "114800"
CASH = F.CASH
HOLD = 20
ANCHOR = "2026-11-23"
START = "2026-11-24"
JUDGE_MIN_TRADES = 10
MAX_MDD_PCT = F.F_MAX_MDD_PCT
EQUITY = F.F_EQUITY
DECLARED_ON = "2026-11-23"


def signal_days(flows_path: Path | None = None, start: str = START) -> set[str]:
    """START 이후 S1 이 난 날(확정치 기준)."""
    days, flows = FL.load(flows_path) if flows_path else FL.load()
    zf = FL.zscores(flows["f"])
    return {d for d, z in zip(days, zf) if d >= start and FL.fires(SIGNAL, {"f": z})}


def plan(dates: list[str], sig: set[str], hold: int = HOLD) -> tuple[dict[int, dict], list[tuple[int, int]]]:
    """(종가 판단 위치 → 목표 비중, [(진입 위치, 청산 위치)]). 진입 = 신호 다음 날 시가, 청산 = 진입 + hold 거래일 뒤 시가."""
    targets: dict[int, dict] = {}
    trades: list[tuple[int, int]] = []
    until = -1                                  # 이 위치의 종가에 청산 판단
    entry = -1
    for k, d in enumerate(dates):
        if until >= 0 and k == until:
            if d in sig:                        # 청산 판단일의 신호 — 이어서 다시 hold 일(보유 유지)
                until = k + hold
                continue
            targets[k] = {CASH: 1.0}
            trades.append((entry, k + 1))
            until = -1
            continue
        if until < 0 and d in sig:
            targets[k] = {INV: 1.0}
            entry, until = k + 1, k + hold
    if until >= 0:
        trades.append((entry, -1))              # 아직 보유 중(청산 전)
    return targets, trades


def run(px: dict, upto: str, sig: set[str] | None = None, equity: float = EQUITY) -> dict:
    """ANCHOR 종가부터 upto 까지 그림자 기록."""
    dates = [d for d in L.calendar(px[F.BASE], ANCHOR, upto) if d in px.get(INV, {}) and d in px.get(CASH, {})]
    if not dates:
        return {"curve": [], "trades": [], "on_today": False, "dates": []}
    sig = signal_days() if sig is None else sig
    targets, trades = plan(dates, sig)
    first = {"w": None}

    def target(i, d):
        if i == 0 and first["w"] is None:       # 출발은 현금
            first["w"] = True
            return targets.get(0, {CASH: 1.0})
        return targets.get(i)
    res = L.simulate({c: L.Asset(c, px[c]) for c in (INV, CASH)}, dates, target, equity)
    cost = L.side_cost(False, False)
    done = []
    for a, b in trades:
        if b >= 0 and b < len(dates) and a < len(dates):
            o0, o1 = px[INV][dates[a]].get("open"), px[INV][dates[b]].get("open")
            if o0 and o1:
                done.append({"entry": dates[a], "exit": dates[b], "ret": o1 / o0 - 1 - 2 * cost})
    holding = bool(trades) and trades[-1][1] == -1
    return {"curve": list(zip(res.dates, res.curve)), "trades": done, "on_today": holding,
            "signals": sorted(d for d in sig if d <= upto), "dates": dates}


def verdict(curve: list[tuple[str, float]], done: list[dict]) -> dict:
    """선언한 판정 — 완료 거래가 모자라면 판정하지 않는다."""
    if len(done) < JUDGE_MIN_TRADES:
        return {"judged": False, "why": f"완료 거래 {len(done)}/{JUDGE_MIN_TRADES}"}
    vals = [v for _, v in curve]
    mdd = L.metrics([d for d, _ in curve], vals)["mdd"]
    checks = {"누적>0": vals[-1] > vals[0], f"MDD≤{MAX_MDD_PCT:g}%": mdd <= MAX_MDD_PCT,
              "거래당>0": statistics.fmean(x["ret"] for x in done) > 0}
    return {"judged": True, "pass": all(checks.values()), "checks": checks}
