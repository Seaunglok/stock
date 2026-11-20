"""리그 10세대 — 엔진 이탈폭을 변동성에 비례 (백로그 ㉕ · 2026-11-20 선언 · 과거 판정 없이 앞으로만).

운용자(11-20): ㉕ 는 "리그 정원 마지막 자리" 라 묻자 → "리그정원을 30으로 늘리고 추가해줘". 정원 25 → 30 은 1월 점검 밖의 운용자 예외
(10-22 의 20 → 25 와 같은 방식). 이 파일은 그 멤버의 선언이다.

근거 — 어디서 왔나 (2026 국면을 보고 떠올림 → **규칙 1: 과거로 판정하지 않고 앞으로만 기록**)
  · 11-19 구성 평가: KODEX200 이 두 종목 약 60% 인 상품이 됐고 실전 4주 변동성 연 57%(검증 구간 15~20%). I3 의 고정 −10% 이탈은
    변동성 기준으로 약 3배 빡빡하다 → 재진입 직후 휩쏘 반복이 주 위험.
  · 08-28 추세추종 진단의 교훈: ATR 트레일(변동성 2배 폭의 **좁은** 손절)이 휩쏘마다 손실을 확정해 "천 번 베여 죽는" 원인이었다.
    2세대 R4(재진입 뒤 손절 −5%)도 급등장에 털렸다 → **좁히는 쪽은 하지 않는다. 넓히기만.**
  · ㉘(11-20): I3 낙폭 축소의 67~77% 가 타이밍 몫 — 이탈 시점을 건드리는 축은 낙폭에 직접 닿는다. 그래서 상한을 둔다.

선언 (이 값을 결과를 보고 바꾸지 않는다)
---------------------------------------
  X10a 변동성 비례 이탈폭
    이탈폭 X = 10% × clip(σ20 / SIGMA_REF, 1, CAP_MULT) — σ20 = KODEX200 최근 20거래일 종가 수익 표준편차 × √252(그날까지).
    X 는 **진입한 날과 새 고점을 낸 날에만** 다시 잡는다(고점 때의 변동성으로 이탈선을 정한다). 하락 중에 변동성이 가라앉아도
    이탈선이 다시 좁아지지 않는다 — 급락 뒤 진정될 때 바닥에서 털리는 것을 막는다.
    SIGMA_REF = 15.6% — 검증 구간(2015-07-28~2026-08-24) KODEX200 σ20 의 중앙값(성과가 아니라 입력 자료의 성질, 11-20 계산).
             평소 변동성 이하면 X = 10% 로 I3 와 같다.
    CAP_MULT = 2 → X 최대 20% = 운용자 제1원칙 MDD 한도(이탈 전 허용 낙폭이 한도를 넘지 않게). 낙폭 예산이 그 전에 비중을 줄인다.
    재진입(20일 고점 + KOSPI > 120일선)·낙폭 예산(252일 최고의 82% · m 6 · 밴드 10%p)·현금 자리는 I3 그대로
    (`lab_jump.with_budget` — `lab_reentry.i3r` 와 같은 줄임을 시험이 잠갔다).
  등록     REGISTER_ON = 2026-11-23(선언 다음 거래일) · 계열 'I3 계보' · 11월 신규 3번째(V7a 11-02 · 가치저변동 11-20) — 월 상한 3 안.
           정원 30 중 25번째.
  판정     리그 규칙 그대로(승격 120영업일·다르게 행동 20일·누적 +2%p·MDD ≤ 20% 월간 2회 연속 + 운용자 승인 · 탈락 MDD > 25% 즉시 등).
           과거 재생은 하지 않는다 — 이 아이디어는 2026 국면을 보고 떠올렸으므로 과거 숫자는 판정에도 보고에도 쓰지 않는다.
  시험 횟수 장부 +1(앞으로만 기록도 결국 판정하므로 센다).
"""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_jump as J  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
NAME = "X10a"
FAMILY = "I3 계보"
REGISTER_ON = "2026-11-23"
SOURCE = "scripts/lab_gen10.py"
X_BASE = 10.0                       # I3 이탈폭(%) — K.ENGINE_X
SIGMA_N = 20                        # σ 창 = 엔진의 20일 고점 n
SIGMA_REF = 0.156                   # 검증 구간 KODEX200 σ20 중앙값(연)
CAP_MULT = 2.0                      # 최대 20%
KOSPI = "^KS11"


def sigma(closes: list[float], k: int, n: int = SIGMA_N) -> float | None:
    """k 번째 날까지 최근 n 개 종가 수익의 표준편차 × √252. 자료가 모자라면 None."""
    if k < n:
        return None
    r = [closes[j] / closes[j - 1] - 1 for j in range(k - n + 1, k + 1)]
    return statistics.stdev(r) * math.sqrt(252)


def exit_pct(closes: list[float], k: int, x_base: float = X_BASE, ref: float = SIGMA_REF,
             cap: float = CAP_MULT) -> float:
    """그날의 이탈폭(%) — 평소 이하 변동성이면 x_base, 높으면 비례해서 넓히되 cap 배까지."""
    s = sigma(closes, k)
    if s is None:
        return x_base
    return x_base * min(cap, max(1.0, s / ref))


def vol_exit_engine(bars: dict, kospi: dict, asset: str, cash: str | None, n: int = K.ENGINE_N,
                    x_base: float = X_BASE, ref: float = SIGMA_REF, cap: float = CAP_MULT,
                    regime_ma: int = I.I1_REGIME_MA):
    """lab_dd_control.reentry_confirmed 와 같은 약속·재진입 — 이탈폭만 진입일·새 고점일의 변동성으로."""
    days = sorted(bars)
    pos = {d: k for k, d in enumerate(days)}
    closes = [bars[d]["close"] for d in days]
    kdays = sorted(kospi)
    kpos = {d: k for k, d in enumerate(kdays)}
    kcl = [kospi[d]["close"] for d in kdays]
    out_w = {cash: 1.0} if cash else {}
    st: dict = {"in": True, "peak": None, "x": x_base, "started": False}

    def regime_up(d: str) -> bool:
        k = kpos.get(d)
        if k is None or k + 1 < regime_ma:
            return False
        return kcl[k] > sum(kcl[k + 1 - regime_ma:k + 1]) / regime_ma

    def target(i: int, d: str, *_):
        k = pos.get(d)
        if k is None:
            return None
        c = closes[k]
        if not st["started"]:
            st["started"], st["peak"], st["x"] = True, c, exit_pct(closes, k, x_base, ref, cap)
            return {asset: 1.0}
        if st["in"]:
            if c > st["peak"]:
                st["peak"], st["x"] = c, exit_pct(closes, k, x_base, ref, cap)
            if c <= st["peak"] * (1 - st["x"] / 100.0):
                st["in"] = False
                return dict(out_w)
            return None
        if k >= n and c > max(closes[k - n:k]) and regime_up(d):
            st["in"], st["peak"], st["x"] = True, c, exit_pct(closes, k, x_base, ref, cap)
            return {asset: 1.0}
        return None
    target.state = st
    return target


def build(data: dict, dates: list[str], cash: str = K.CASH):
    """i3_shadow.std_run 용 — (자산 코드들, target, needs_nav). 낙폭 예산·m·L·현금은 I3 그대로."""
    eng = vol_exit_engine(data[K.BASE], data[KOSPI], K.BASE, cash)
    return (K.BASE, cash), J.with_budget(eng, K.BASE, cash, K.M, K.LOOKBACK), True
