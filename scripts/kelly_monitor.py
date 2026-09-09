"""켈리 과베팅 감시 — **판정 기준을 표본이 쌓이기 전에 선언한다** (2026-09-09).

무엇이고 무엇이 아닌가
----------------------
**주문에 전혀 관여하지 않는다.** 포지션 크기를 바꾸지 않고, 진입/청산을 막지도 않는다.
하는 일은 하나 — 실현된 거래 분포로 켈리 f* 를 재서 **현재 노출이 과한지** 알리는 것.
노출을 실제로 바꾸려면 워크포워드 격자에 후보로 넣어 OOS 로 검증해야 한다(2026-08-28 원칙).

왜 자동 사이징이 아닌가
-----------------------
f* 는 구간마다 10배 흔들린다(12년 표본 4분할: 106.8% / 29.0% / 40.6% / 285.0%).
그 값을 사이징에 직결하면 포지션 크기가 그만큼 출렁인다 — 전략이 아니라 잡음 증폭기다.
게다가 순환적으로 나쁘다: 손실 → f*↓ → 크기↓ → 회복 지연. 엣지가 진짜 사라진 것인지
잡음인지 구분할 방법이 지금 없다.

왜 지금 선언만 하는가
---------------------
채택 구성(EXITS=ma,hold, 2026-08-28) 이후 **실제 진입이 0건**이다 — 레짐 게이트가
38영업일째 막고 있다. 잴 표본이 없다. 표본이 생긴 **뒤에** 임계를 정하면 숫자를 보고
기준을 맞추게 되고, 그건 이 프로젝트가 반복해서 틀린 방식이다(2026-08-27 `blend` 채택).
그래서 계산과 기준을 지금 고정하고, 실행은 표본이 찰 때까지 "표본 부족"만 출력한다.

사용법
------
    python scripts/kelly_monitor.py            # 현재 표본으로 판정(부족하면 그렇게 말한다)
    python scripts/kelly_monitor.py --explain  # 기준 전문 출력
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 판정 기준 — **표본을 보기 전에 선언한다** ────────────────────────────────
#
# ① 주 지표: 전체 분포 켈리 f*. 상위 절단본은 **판정에 쓰지 않는다**.
#    추세추종의 엣지는 오른쪽 꼬리 그 자체다(상위 5% 를 지우면 f* 133%→27.9%).
#    꼬리를 지운 값으로 "과베팅"을 판정하면, '큰 승자가 없다면'이라는 가정 아래
#    판정하는 셈이라 전제가 틀렸다. 스트레스 참고치로만 함께 출력한다.
#
# ② 임계: f* < 현재 총노출 → 과베팅. 노출은 슬롯수 × 종목당% 로 읽는다.
#    단발 교차는 무시하고 PERSIST_N 회 연속 위반일 때만 경보한다(f* 가 흔들리므로).
#
# ③ 표본: 채택 구성 청산 MIN_TRADES 건 이상. 그 전엔 어떤 판정도 하지 않는다.
#    ⚠️ 이 분포는 상위 5% 가 결과를 지배한다 — 50건이면 그 5% 가 2~3건이다.
#       50 은 "판정을 시작해도 될 최소"지 "충분"이 아니다. 판정 시 표본 수를 함께 읽을 것.
#
# ④ 행동: 알림뿐. 자동 축소 없음. 노출 변경은 워크포워드 재검증을 거친다.
#    반대 방향(f* 가 노출보다 훨씬 높음)으로도 자동으로 올리지 않는다 —
#    노출은 학습 대상이 아니라 운용자의 위험 선호다(2026-08-28 선언).
#
# ⑤ 폐기 조건: 측정이 ABANDON_AFTER 회 쌓였는데 f* 의 최대/최소 비가 ABANDON_SWING 배를
#    넘으면, 이 지표는 감시에 부적합하다고 결론내고 **폐기한다**. 쓸모없는 지표를
#    "그래도 있으니까" 남겨두면 8030 오탐처럼 로그만 오염시킨다.
MIN_TRADES = 50            # 판정 개시 최소 청산 건수(채택 구성 한정)
PERSIST_N = 2              # 연속 위반 횟수 — 단발 교차는 f* 의 흔들림일 뿐
STRESS_CUT_PCT = 5.0       # 스트레스 참고치: 상위 N% 절단 (판정에는 미사용)
ABANDON_AFTER = 12         # 측정 횟수(월 1회 기준 1년)
ABANDON_SWING = 5.0        # f* 최대/최소 비가 이 배수를 넘으면 지표 폐기

ADOPTED_SINCE = "2026-08-28"   # 채택 구성(EXITS=ma,hold) 시행일 — 이전 거래는 다른 분포다
LOG_FILE = _ROOT / "data" / "trend_follow" / "kelly_log.jsonl"


# ── 계산 ────────────────────────────────────────────────────────────────────
def kelly_fraction(returns: list[float], hi: float = 10.0) -> float:
    """E[log(1 + f·R)] 을 최대화하는 f. R 은 소수(0.05 = +5%).

    교과서 `f* = (bp-q)/b` 를 쓰지 않는 이유: 그 식은 '지면 전액 손실'을 전제한다.
    우리 최악 거래는 -10.4% 다(하드손절이 바닥). 전제가 다르면 답도 다르다 —
    실제 표본으로 직접 최대화한다.
    """
    if not returns:
        return 0.0

    def g(f: float) -> float:
        t = 0.0
        for r in returns:
            v = 1 + f * r
            if v <= 1e-9:
                return -1e9              # 파산 구간
            t += math.log(v)
        return t / len(returns)

    lo, h = 0.0, hi
    for _ in range(200):                 # 삼분탐색 — g 는 단봉이다
        a, b = lo + (h - lo) / 3, h - (h - lo) / 3
        if g(a) < g(b):
            lo = a
        else:
            h = b
    return (lo + h) / 2


def kelly_stress(returns: list[float], cut_pct: float = STRESS_CUT_PCT) -> float:
    """상위 cut_pct% 수익 거래를 지운 f* — '꼬리가 안 나온다면' 시나리오.

    **판정에 쓰지 않는다**(위 기준 ①). 추세추종에서 꼬리를 지우는 것은 엣지를 지우는 것이다.
    """
    if not returns:
        return 0.0
    k = int(len(returns) * cut_pct / 100.0)
    kept = sorted(returns)[:len(returns) - k] if k else list(returns)
    return kelly_fraction(kept)


def assess(returns: list[float], exposure: float) -> dict:
    """판정. exposure 는 총노출 소수(1.0 = 100%)."""
    n = len(returns)
    if n < MIN_TRADES:
        return {"verdict": "표본부족", "n": n, "need": MIN_TRADES,
                "f_star": None, "f_stress": None, "exposure": exposure}
    f = kelly_fraction(returns)
    return {"verdict": "과베팅" if f < exposure else "정상",
            "n": n, "need": MIN_TRADES, "f_star": f,
            "f_stress": kelly_stress(returns), "exposure": exposure,
            "note": f"연속 {PERSIST_N}회 위반 시에만 경보 — 이번 회차는 1회분"}


# ── 표본 수집 ───────────────────────────────────────────────────────────────
def adopted_returns() -> list[float]:
    """채택 구성 시행일 이후 **실제 청산**된 거래의 net%(소수).

    이전 거래는 청산 사다리가 달라(트레일·부분익절 포함) 분포 자체가 다르다.
    섞으면 지금 안 쓰는 규칙의 f* 를 감시하게 된다.
    """
    from trend_runtime import read_journal
    out: list[float] = []
    for r in read_journal():
        if not isinstance(r, dict) or not r.get("closed"):
            continue
        when = str(r.get("exit_date") or r.get("date") or "")[:10]
        net = r.get("net_pct")
        if when >= ADOPTED_SINCE and isinstance(net, (int, float)):
            out.append(float(net) / 100.0)
    return out


def live_exposure() -> float:
    from trend_config import MAX_POS, POSITION_PCT
    return MAX_POS * POSITION_PCT / 100.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--explain", action="store_true", help="선언된 기준 전문 출력")
    args = ap.parse_args()
    if args.explain:
        print(__doc__)
        print(f"MIN_TRADES={MIN_TRADES} · PERSIST_N={PERSIST_N} · "
              f"STRESS_CUT_PCT={STRESS_CUT_PCT} · ABANDON={ABANDON_AFTER}회/{ABANDON_SWING}배")
        return 0

    rets = adopted_returns()
    exp = live_exposure()
    a = assess(rets, exp)
    print("=" * 74)
    print(f"켈리 과베팅 감시 — 채택 구성({ADOPTED_SINCE}~) 청산 {a['n']}건 · 총노출 {exp*100:.0f}%")
    print("=" * 74)
    if a["verdict"] == "표본부족":
        print(f"  판정 보류 — 청산 {a['n']}/{a['need']}건.")
        print("  기준은 이미 코드 상수로 고정돼 있다. 표본이 차면 그대로 판정한다.")
        print("  (레짐 게이트가 진입을 막는 동안은 표본이 늘지 않는다 — 정상이다.)")
        return 0
    print(f"  f* {a['f_star']*100:.1f}%  vs  총노출 {exp*100:.0f}%  →  **{a['verdict']}**")
    print(f"  스트레스 참고(상위 {STRESS_CUT_PCT:g}% 절단): {a['f_stress']*100:.1f}% "
          f"— 판정에는 쓰지 않는다")
    print(f"  {a['note']}")
    print("  ※ 이 지표는 주문에 관여하지 않는다. 노출 변경은 워크포워드 재검증을 거친다.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
