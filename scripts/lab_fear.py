"""공격형 트랙 — 공포 매수, **앞으로만 기록** (2026-10-28, 사전 선언).

운용자(10-28): 하락 예측 판정대(lab_downside) 결과에 "넣어두자" — VIX 가 높을 때 박스권의 다음 날 하락 비율이
25~38%(오히려 오른 날이 많음)였다는 관찰을 '공포 때 매수'로 공격형 리그에 기록한다.

왜 앞으로만인가
--------------
  이 아이디어는 판정대 결과 표를 보고 떠올렸다 — 같은 과거 자료로 재면 답을 보고 문제를 낸 셈이다. 그래서 백테스트로
  판정하지 않고, 선언 커밋 뒤에 오는 날만 성적으로 센다(lab_orb 와 같은 방식).

선언 (결과를 보고 고치면 무효)
-----------------------------
  신호 — 새 숫자를 고르지 않는다(lab_downside 선언 기본값을 import 해서 그대로 쓴다):
    V  VIX 종가 > 30 (lab_downside V1)                 — 미국발 공포
    K  KOSPI 20일 실현 변동성(연율) > 25% (lab_downside K2) — 한국발 공포. 10-28 VIX 는 17 안팎인데 KOSPI 는 120일 최고
       9,115 → 10-26 5,469 — 이번 급락은 미국 공포 지수에 안 잡혔다. 그래서 한국 쪽 공포 지표를 같이 기록한다.
  보유  신호가 켜져 있는 동안 매수 보유, 꺼지면 현금(488770 머니마켓 — I3 리그와 같은 현금 자리).
        하루 끝 상태 → 다음 거래일 시가 체결(strategy_lab 공통). V 의 미국 d 일 종가는 한국 d+1 시가 전에 확정된다
        (미국 장 마감 = 한국 05~06시) → 실전이면 아침 판단. K 는 15:50 판단과 같다.
  상품  1 = KODEX200(069500) · 2 = KODEX 레버리지(122630)  → FEAR-V1 · FEAR-V2 · FEAR-K1 · FEAR-K2
  조건  예탁 50만원(공격형 트랙) · 정수 주식수 · 편도 11.5bp.
  시작  ANCHOR(10-28) 종가 판단 → 10-29 시가 첫 체결. 성적은 10-29 부터.
  판정  F_JUDGE_DAYS(60) 영업일 기록 **그리고** 보유일 ≥ F_MIN_HELD(20) 뒤에만:
          누적 순수익 > 0 · 최대 낙폭 ≤ 30%(공격형 정지선) ·
          보유한 날의 KODEX200 수익(시가→다음 시가) 평균 > 기록 기간 전체 평균 — '공포일을 고른 실력'.
          (마지막 조건이 없으면 그냥 상승장에 오래 들고 있어서 번 돈이 실력처럼 보인다.)
        신호가 드물어 보유일이 모자라면 판정하지 않고 계속 기록한다(기준을 낮추지 않는다).

FEAR-P — 공포가 정점을 지난 뒤 매수 (2026-11-10 선언, 운용자 "ORB-B3 · FEAR-K 정점 뒤" — **앞으로만**)
------------------------------------------------------------------------------------------------
  진단(첫 2주, 판정 아님): FEAR-K 는 변동성이 25% 를 넘자마자 산다 — 10-29 시가(반등 다음 날)에 사서 하락이 이어지자
  FEAR-K2 가 6영업일 만에 그림자 MDD 31.5%(정지선). '떨어지는 칼'을 잡았다. → 공포가 **꺾인 뒤**에 산다.
  규칙(KOSPI 20일 실현 변동성, FEAR-K 와 같은 정의 · 같은 25%):
    국면   변동성 > 25% 가 이어진 날들 = 한 공포 국면. 25% 이하(또는 자료 없음)면 국면 끝 → 현금.
    정점   그 국면 안에서 **최근 PEAK_WINDOW(20)거래일** 최고치(20 = 변동성 창 D.VOL_WINDOW 그대로, 새 숫자 아님).
    매수   변동성 ≤ 정점 × (1 − PEAK_DROP 20%) — 정점에서 20% 꺾이면 다음 날 시가에 산다.
    내려놓음 변동성이 앞선 날들의 정점을 넘으면(새 정점 = 공포 재확대) 현금으로 돌아가 다시 기다린다.
    그 사이(꺾임 20% 와 새 정점 사이)는 직전 상태를 유지.
  상품·조건·판정은 FEAR-K 와 같다(1 = KODEX200 · 2 = 레버리지, 50만원). 시작: 11-10 종가 판단 → 11-11 시가부터(ANCHORS).
  20% 는 이번에 처음 정한 숫자다 — 2주 기록을 보고 만든 규칙이라 과거로 판정하지 않고, 선언 뒤에 바꾸지 않는다.
  ※ 커밋 전 고침(11-10, 성적 0일): 초안은 '켜진 뒤 전체 정점'이었는데 실데이터 시험에서 변동성이 2026-02-03 부터
    25% 아래로 한 번도 안 내려와 07-31 의 103.6% 를 정점으로 기억 → 지금 59%(오늘이 20일 최고 = 공포 확대 중)를
    '꺾임'으로 보고 11-11 에 바로 사는 것을 확인. '떨어지는 칼을 피한다'는 이 후보의 목적과 반대라 최근 20거래일로 고쳤다.
    (성적이 아니라 상태 기계가 의도와 다르게 도는 것을 보고 고친 것 — 고친 뒤 과거 성적은 재지 않는다.)
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
import lab_aggr as A  # noqa: E402
import lab_downside as D  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
BASE, CASH = "069500", "488770"
LONGS = {"1": "069500", "2": "122630"}
SIGNALS = {"V": ("V1", "VIX 종가 > 30(미국발 공포)"), "K": ("K2", "KOSPI 20일 변동성 > 25%(한국발 공포)"),
           "P": ("K2", "KOSPI 20일 변동성이 25% 위에서 정점 대비 20% 꺾인 뒤(공포가 잦아들 때)")}
MEMBERS = tuple(f"FEAR-{s}{lv}" for s in SIGNALS for lv in LONGS)      # FEAR-V1 V2 K1 K2 P1 P2
ANCHOR = "2026-10-28"
ANCHORS = {"V": ANCHOR, "K": ANCHOR, "P": "2026-11-10"}              # 신호별 첫 종가 판단일(그다음 거래일 시가 첫 체결)
PEAK_DROP = 0.20
PEAK_WINDOW = D.VOL_WINDOW                                            # 정점 = 이번 국면의 최근 20거래일 최고
F_EQUITY = A.AG_EQUITY
F_JUDGE_DAYS = 60
F_MIN_HELD = 20
F_MAX_MDD_PCT = A.AG_MAX_MDD_PCT


def peak_after(vols: list[float | None], th: float, drop: float = PEAK_DROP,
               window: int = PEAK_WINDOW) -> list[bool]:
    """FEAR-P 상태 기계 — 변동성 열 → 날마다 보유 여부. 그날까지의 값만 쓴다.
    정점 = 이번 공포 국면(변동성 > th 연속) 안의 최근 window 거래일 최고 — 몇 달 전 정점을 기억하지 않는다."""
    out, on, s = [], False, None                     # s = 이번 국면 첫날 index
    for k, v in enumerate(vols):
        if v is None or v <= th:
            on, s = False, None                      # 국면 끝(또는 자료 없음) → 현금
        else:
            if s is None:
                s = k
            prev = [vols[j] for j in range(max(s, k - window + 1), k)]
            if not prev or v > max(prev):
                on = False                           # 국면 첫날 · 새 정점 = 공포 확대 중
            elif v <= max(prev) * (1 - drop):
                on = True                            # 정점에서 20% 꺾임
        out.append(on)
    return out


def kospi_vols(ks: dict) -> tuple[list[str], list[float | None]]:
    """KOSPI 20일 실현 변동성(연율 %) — lab_downside._vol_above 와 같은 정의(최근 20개 일간 수익률의 표본 표준편차)."""
    import math
    ds, c = D.series(ks)
    out: list[float | None] = []
    for k in range(len(c)):
        if k < D.VOL_WINDOW:
            out.append(None)
            continue
        r = [c[j] / c[j - 1] - 1 for j in range(k - D.VOL_WINDOW + 1, k + 1)]
        out.append(statistics.stdev(r) * math.sqrt(252) * 100)
    return ds, out


def fear_on(sig: str, px: dict):
    """d → True(공포)·False·None(자료 부족). V·K 는 lab_downside 의 선언 기본값 그대로, P 는 그 K 에 정점 뒤 규칙."""
    code = SIGNALS[sig][0]
    if sig == "P":
        ds, vols = kospi_vols(px["^KS11"])
        st = dict(zip(ds, peak_after(vols, D.CANDIDATES[code][2])))

        def f(d):
            k = D.at_or_before(ds, d)
            return None if k < 0 else st[ds[k]]
        return f
    return D.down_fn(code, D.CANDIDATES[code][2], px)


def fear_target(on, asset: str, cash: str = CASH):
    """공포면 asset, 아니면(자료 부족 포함) 현금. 상태가 바뀐 날만 목표를 낸다."""
    st = {"w": None}

    def target(i, d):
        w = {asset: 1.0} if on(d) else {cash: 1.0}
        if w == st["w"]:
            return None
        st["w"] = w
        return w
    return target


def run(px: dict, sig: str, lv: str, upto: str, anchor: str = ANCHOR, equity: float = F_EQUITY) -> dict:
    """anchor 종가 판단부터 upto 까지. held = 그 상품을 들고 시작한 날(전 거래일 공포 → 그날 시가 체결)."""
    asset = LONGS[lv]
    dates = [d for d in L.calendar(px[BASE], anchor, upto) if d in px[asset] and d in px[CASH]]
    if not dates:
        return {"curve": [], "held": [], "on_today": None, "entries": 0, "dates": []}
    on = fear_on(sig, px)
    res = L.simulate({c: L.Asset(c, px[c]) for c in (asset, CASH)}, dates, fear_target(on, asset), equity)
    states = {d: on(d) for d in dates}
    held = [x for p, x in zip(dates, dates[1:]) if states[p]]
    return {"curve": list(zip(res.dates, res.curve)), "held": held, "on_today": bool(states[dates[-1]]),
            "entries": D.entries(states, dates[:-1]), "dates": dates}


def verdict(curve: list[tuple[str, float]], held: list[str], base: dict, dates: list[str]) -> dict:
    """선언한 판정 — 기록·보유일이 모자라면 판정하지 않는다."""
    n = max(0, len(curve) - 1)
    if n < F_JUDGE_DAYS or len(held) < F_MIN_HELD:
        return {"judged": False, "why": f"기록 {n}/{F_JUDGE_DAYS}영업일 · 보유 {len(held)}/{F_MIN_HELD}일"}
    vals = [v for _, v in curve]
    mdd = L.metrics([d for d, _ in curve], vals)["mdd"]
    r = {x: base[y]["open"] / base[x]["open"] - 1 for x, y in zip(dates, dates[1:])}
    hr = [r[x] for x in held if x in r]
    checks = {"누적>0": vals[-1] > vals[0], f"MDD≤{F_MAX_MDD_PCT:g}%": mdd <= F_MAX_MDD_PCT,
              "공포일 실력": bool(hr) and statistics.fmean(hr) > statistics.fmean(r.values())}
    return {"judged": True, "pass": all(checks.values()), "checks": checks}


def gauges(px: dict, d: str) -> dict:
    """그날 공포 계기판(보고용) — VIX 는 날짜 ≤ d 인 마지막 값, KOSPI 변동성은 신호와 **같은 함수**(`kospi_vols`)의 그날 값.
    (11-12 리팩터링: 전엔 같은 식을 여기서 한 번 더 계산했다 — 어긋나면 '보여 준 값 ≠ 판단한 값'이 된다.)"""
    vd, vc = D.series(px["^VIX"])
    kd, vols = kospi_vols(px["^KS11"])
    kv = D.at_or_before(vd, d)
    kk = D.at_or_before(kd, d)
    vol = vols[kk] if kk >= 0 else None
    return {"vix": None if kv < 0 else round(vc[kv], 2), "vix_date": None if kv < 0 else vd[kv],
            "kospi_vol": None if vol is None else round(vol, 1)}
