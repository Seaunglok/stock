"""공격형 트랙 1세대 B — 5분 시가 범위 돌파(ORB) 단타, **앞으로만 기록** (2026-10-28, 사전 선언).

운용자(10-28): 공격형 트랙 연구 방향 A(양방향, lab_aggr)·**B(단타, 분봉 장중 매매)**. 목표 "월 10% 수익을 3년 동안".

근거 — 어디서 왔나
-----------------
  Zarattini·Barbon·Aziz(2023), "Can Day Trading Really Be Profitable?"(SSRN 4416622) 의 5분 ORB(QQQ, 2016-01~2023-02).
  규칙(CXO Advisory 요약으로 확인 10-28): 첫 5분봉이 오르면 매수·내리면 공매도·시가=종가면 쉼 → 두 번째 5분 시작에 진입,
  손절 = 첫 5분봉 저가(매수)/고가(공매도), 익절 = 진입가 ± 10 × |진입 − 손절|(10R), 둘 다 아니면 장 마감 청산.
  크기 = 손절 시 자본의 1% 를 잃게, 레버리지 상한 4배. 비용은 수수료만(호가 차이·슬리피지 없음).
  경고: 독립 재현(지수 CFD 5종)은 "비용 전 재현, 비용 후 0" — 이 전략의 승패는 **비용**이 가른다.

우리 판(바뀌는 점만, 숫자는 원 출처 그대로)
-----------------------------------------
  신호  KODEX200(069500) 첫 5분(09:00~09:04 1분봉 5개): 마지막 종가 > 첫 시가 → 상승, < → 하락, = → 쉼.
  진입  09:05 봉 시가. 상승 → 롱 상품 매수, 하락 → KODEX 인버스(114800) 매수(공매도 대신).
        B1 롱 = 069500(1배) · B2 롱 = 122630(레버리지 2배). 200선물인버스2X 는 1틱 ~1% 라 제외(lab_aggr.EXCLUDED).
  손절  **산 상품 자신의** 첫 5분 저가(인버스를 샀으면 인버스의 저가). 진입가 ≤ 손절이면 쉼.
  익절  진입가 + 10R (R = 진입가 − 손절).  같은 봉에서 손절·익절 둘 다 닿으면 **손절 먼저**(보수적).
        봉 시가가 이미 손절 아래(갭)면 그 시가에 청산.
  청산  09:05~15:19 연속매매 중 손절/익절 아니면 15:30 종가(동시호가) — 실전은 15:20 동시호가 시장가 매도.
  크기  min(1, 1% ÷ (R/진입가)) — 원 출처 1% 위험, 레버리지 상한은 현금 계좌라 1배(원 출처 4배 불가).
  비용  편도 strategy_lab 공통(수수료 1.5 + 슬리피지 10bp), ETF 라 거래세 없음. 하루 왕복 23bp × 크기.
  기록  B_START(2026-10-29) 부터의 날만 — 선언 커밋 뒤에 온 데이터만 성적이다. 그 전 분봉(10-20~)으로 돌린 결과는
        **구현 확인용**(판정에 안 씀). 과거 분봉 이력이 없어 백테스트는 없다(키움 1분봉 ~900봉만).
  판정  2주(10영업일)는 '체결·비용이 모델과 같은가'만 본다 — 10번 매매로는 운과 실력을 못 가른다.
        실전 후보 자격은 B_JUDGE_DAYS(60영업일) 기록 뒤: 누적 순수익 > 0 · 최대 낙폭 ≤ 30%(공격형 정지선).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.mcp_servers.trend_mcp import costs as C  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
SIGNAL, INV = "069500", "114800"
VARIANTS = {"B1": "069500", "B2": "122630"}
OR_BARS = ("0900", "0901", "0902", "0903", "0904")
ENTRY_T = "0905"
LAST_CONT_T = "1519"                  # 연속매매 마지막 1분봉
CLOSE_T = "1530"                      # 종가 동시호가
TARGET_R = 10.0
RISK_PCT = 1.0
MAX_SIZE = 1.0
SIDE_COST = (C.FEE_BPS + C.SLIPPAGE_BPS) / 10_000.0
B_START = "2026-10-29"
B_JUDGE_DAYS = 60
B_MAX_MDD_PCT = 30.0
MINUTE_DIR = _ROOT / "data" / "minute"


def _first5(bars: list[dict]) -> tuple[float, float, float, float] | None:
    """첫 5분봉 (시가, 고가, 저가, 종가) — 5개 1분봉이 다 있어야 한다."""
    by = {b["t"]: b for b in bars}
    if not all(t in by for t in OR_BARS):
        return None
    xs = [by[t] for t in OR_BARS]
    return xs[0]["o"], max(x["h"] for x in xs), min(x["l"] for x in xs), xs[-1]["c"]


def orb_day(signal: list[dict], long_bars: list[dict], inv_bars: list[dict]) -> dict:
    """하루 결과 — {'side': 'long'|'inv'|None, 'ret': 순수익(자본 대비 소수), ...}. 순수 함수."""
    s5 = _first5(signal)
    if s5 is None:
        return {"side": None, "ret": 0.0, "why": "첫 5분 자료 없음"}
    if s5[3] == s5[0]:
        return {"side": None, "ret": 0.0, "why": "첫 5분 시가=종가(쉼)"}
    side = "long" if s5[3] > s5[0] else "inv"
    bars = long_bars if side == "long" else inv_bars
    by = {b["t"]: b for b in bars}
    f5 = _first5(bars)
    if f5 is None or ENTRY_T not in by or CLOSE_T not in by:
        return {"side": side, "ret": 0.0, "why": "상품 분봉 부족(쉼)"}
    entry, stop = by[ENTRY_T]["o"], f5[2]
    if entry <= stop:
        return {"side": side, "ret": 0.0, "why": "진입가 ≤ 손절(쉼)"}
    risk = (entry - stop) / entry
    size = min(MAX_SIZE, (RISK_PCT / 100.0) / risk)
    target = entry + TARGET_R * (entry - stop)
    exit_px, how = by[CLOSE_T]["c"], "종가"
    for b in sorted(bars, key=lambda x: x["t"]):
        if not (ENTRY_T <= b["t"] <= LAST_CONT_T):
            continue
        if b["l"] <= stop:
            exit_px, how = min(stop, b["o"]), "손절"
            break
        if b["h"] >= target:
            exit_px, how = max(target, b["o"]), "익절"
            break
    ret = size * (exit_px / entry - 1) - size * 2 * SIDE_COST
    return {"side": side, "ret": ret, "size": size, "entry": entry, "stop": stop, "target": target,
            "exit": exit_px, "how": how}


def _load_day(code: str, day: str) -> list[dict]:
    p = MINUTE_DIR / code / f"{day}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def replay(variant: str, start: str = B_START, end: str = "9999-12-31") -> list[tuple[str, dict]]:
    """저장된 분봉으로 날마다 orb_day — 신호 종목 파일이 있는 날만."""
    days = sorted(p.stem for p in (MINUTE_DIR / SIGNAL).glob("*.json") if start <= p.stem <= end)
    return [(d, orb_day(_load_day(SIGNAL, d), _load_day(VARIANTS[variant], d), _load_day(INV, d))) for d in days]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    start = sys.argv[1] if len(sys.argv) > 1 else B_START
    tag = "기록" if start >= B_START else "구현 확인용(판정 아님)"
    for v in VARIANTS:
        nav = 1.0
        print(f"{v} ({VARIANTS[v]} / 인버스 {INV}) — {start}~ {tag}")
        for d, r in replay(v, start):
            nav *= 1 + r["ret"]
            extra = (f" {r['side']:4} 크기 {r['size']:.0%} 진입 {r['entry']:,.0f} 손절 {r['stop']:,.0f} → {r['how']} {r['exit']:,.0f}"
                     if "size" in r else f" {r.get('why', '')}")
            print(f"  {d} {r['ret'] * 100:+6.2f}%{extra}")
        print(f"  누적 {(nav - 1) * 100:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
