"""리그 판정 통계 기준 (백로그 ㉔ — 2026-11-23 선언, **2027-01 월간 점검(1월 규칙 점검 ⑨)부터 시행**).

왜
--
  I3 리그 승격 '누적 ≥ 챔피언 +2%p'(120영업일)와 공격형 리그 판정 '누적 > 0 · MDD ≤ 30%'(60영업일)는 우연과 실력을 못 가른다.
  비중이 50% 다른 두 멤버의 120영업일 누적 차이 표준편차는 지금 변동성에서 약 20%p(평시 6%p) — +2%p 는 0.1~0.3σ(11-19 구성 평가).
  ㉘(`lab_i3_overfit`, 11-20)의 재료: 120영업일로 단측 5% 유의를 말하려면 차이 수익 연 샤프 ≥ 2.41 · 60영업일 ≥ 3.44.
  운용자(11-23) "나머지 진행해줘" → 숫자를 **1월 점검 전에** 여기 잠근다(규칙 변경은 1월만 — 결과를 보고 고르지 않게).

선언 (리그 결과를 판정에 쓰기 전 — 바꾸려면 다음 1월 점검에서, 바꾼 이유와 함께)
--------------------------------------------------------------------------
  공통   일간 수익의 확률적 샤프 z(Bailey·López de Prado 2012, 왜도·첨도 보정) — `lab_i3_overfit.psr_z`·`moments`·`min_trl` 그대로.
         z_PSR = SR·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²), SR = 일간 평균 ÷ 표준편차, γ₄ 는 정규 3 기준.
         **z = min(z_PSR, 정규 z = SR·√(T−1))** — 보정은 불리할 때만 반영한다. PSR 은 양의 왜도를 유리하게 세서, '챔피언이 크게
         빠진 하루만 피한' 도전자(차이 수익이 하루만 +4%)가 z 1.97 로 단일 시험 통과선 1.645 를 넘었다(11-23 설계 중 시험으로 발견 —
         리그 결과를 보기 전). 정규 z 로는 1.0. 더 필요한 날도 둘 중 긴 쪽.
         통과선 = Φ⁻¹(1 − ALPHA / N) — 단측 ALPHA 5% 를 그 점검에서 함께 재는 멤버 수 N 으로 나눈다(본페로니 — 시험 장부와 같은 생각:
         멤버가 많을수록 '운 좋은 1등'이 나온다). 관측 T < MIN_OBS 면 계산하지 않는다(판정 불가 = 미달).
         더 필요한 날 = ⌈MinTRL(관측 SR·γ₃·γ₄, ALPHA/N) − T⌉ — 지금 속도가 이어진다는 가정의 참고값(SR ≤ 0 이면 '끝나지 않음').
  I3 리그 승격(S1)   d_t = 도전자 일간 수익 − 챔피언(I3 그림자) 일간 수익, 등록일 이후 **둘 다 값이 있는 날**만.
                     N = 그 점검의 활성 도전자 수(챔피언 제외). 기존 다섯 조건은 그대로 두고 **여섯째 조건**으로 더한다.
                     기존 다섯은 충족 · S1 미달 → '보류(통계)': 연속 횟수에 넣지 않고 기록을 이어 간다(알림 1통, 일반).
  공격형 리그(S2)    e_t = 멤버 일간 수익 − 현금 자리(488770) 일간 수익. N = 공격형 멤버 수(MEMBERS, 지금 10).
                     각 lab 이 선언한 판정(누적 > 0 · MDD ≤ 30% · FEAR 공포일 실력)은 **그대로** — S2 는 그 결과로 이어지는
                     '실계좌 재검토 자격'에만 붙는다(11-10 운용자 결정: 통과 멤버가 생기면 그때 다시). 판정 통과 · S2 미달 → 연장 기록.
  시행   STAT_FROM 달(2027-01)의 월간 점검부터. 그 전에는 매일 기록에 **보고만**(판정·연속 횟수에 안 쓴다).
  알고 정한 대가: N 29 · 120영업일이면 차이 수익 연 샤프 약 4.2 가 있어야 승격 — 실제로는 1~2년 이상 기록이 쌓이거나 차이가 아주
         커야 한다. 공격형 60영업일(N 10)은 초과 수익 연 샤프 약 5.3. 위험 쪽 규칙(MDD 탈락·정지선)은 빠른 그대로 둔다 —
         나쁜 쪽을 빨리 자르는 데는 통계가 필요 없고, 좋은 쪽을 믿는 데만 필요하다.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from statistics import NormalDist

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_i3_overfit as O  # noqa: E402  — ㉘ 의 식 그대로(다시 구현하지 않는다)

STAT_FROM = "2027-01"
ALPHA = 0.05
MIN_OBS = 20
_ND = NormalDist()


def in_force(day: str) -> bool:
    """그날(YYYY-MM-DD 또는 YYYY-MM)의 점검에서 통계 조건이 판정에 쓰이나."""
    return day[:7] >= STAT_FROM


def hurdle_z(n_tests: int, alpha: float = ALPHA) -> float:
    if n_tests < 1:
        raise ValueError("n_tests ≥ 1")
    return _ND.inv_cdf(1 - alpha / n_tests)


def daily_rets(curve: list[tuple[str, float]], since: str = "") -> dict[str, float]:
    """곡선 → {날짜: 그날 수익}(since 이후 날짜만 — 첫 수익은 since 다음 점부터)."""
    pts = [(d, v) for d, v in curve if d >= since]
    return {b[0]: b[1] / a[1] - 1 for a, b in zip(pts, pts[1:]) if a[1] > 0}


def paired(a: dict[str, float], b: dict[str, float]) -> list[float]:
    """같은 날 둘 다 있는 수익의 차이 a − b(날짜 순)."""
    return [a[d] - b[d] for d in sorted(set(a) & set(b))]


def edge_stat(x: list[float], n_tests: int, alpha: float = ALPHA) -> dict:
    """일간 (초과·차이) 수익 x 의 확률적 샤프 z 와 통과 여부."""
    t = len(x)
    h = hurdle_z(n_tests, alpha)
    base = {"n": t, "hurdle": round(h, 3), "n_tests": n_tests}
    if t < MIN_OBS:
        return {**base, "z": None, "pass": False, "why": f"관측 {t} < {MIN_OBS}일"}
    if max(x) - min(x) < 1e-12:
        return {**base, "z": 0.0, "pass": False, "why": "차이 없음(날마다 같은 수익)"}
    sr, g3, g4 = O.moments(x)
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr * sr
    if den <= 0:
        return {**base, "z": None, "pass": False, "why": "분포 보정 불가(분모 ≤ 0)"}
    z = min(O.psr_z(sr, t, g3, g4), O.psr_z(sr, t, 0.0, 3.0))          # 보정은 불리할 때만(정규 z 가 상한)
    need = max(O.min_trl(sr, g3, g4, alpha / n_tests), O.min_trl(sr, 0.0, 3.0, alpha / n_tests))
    more = None if math.isinf(need) else max(0, math.ceil(need - t))
    return {**base, "z": round(z, 3), "pass": z >= h, "sr_ann": round(sr * math.sqrt(252), 2),
            "more_days": more, "why": "" if z >= h else
            (f"z {z:.2f} < {h:.2f}" + (f" · 이 속도면 약 {more}영업일 더" if more is not None else " · 차이 수익 ≤ 0 — 이 속도로는 끝나지 않음"))}
