"""구조적 수급 날짜 판정대 — '억지로 사고파는 사람'이 생기는 날, KOSPI 가 평소와 다르게 움직이나 (2026-11-18, 사전 선언).

운용자(11-18): "오픈되지 않은 좋은 조건식이나 매매 알고리즘이 많이 있을 거 같어. 이런거를 더 발굴하는거는 어때?" → 제안(아이디어
장부 `docs/strategy-ideas.md` · 시험 횟수 장부 `lab_trials` · 첫 묶음 = 구조적 수급 날짜) → "진행해줘".

왜 이 묶음인가
-------------
  · 결과표에서 찾은 패턴이 아니라 **이유가 있는 수급** — 제도·세금·펀드 규칙 때문에 날짜에 맞춰 사고팔아야 하는 쪽이 있다.
    운용자 관점("수급량과 방향을 봐서")과 같은 방향이고, 날짜는 미리 알 수 있어(달력·공시된 회의 일정) 미래 정보가 섞이지 않는다.
  · 학계에 알려진 효과들이라 **이미 사라졌을 수 있다**(McLean·Pontiff 2016 — 발표 뒤 평균 절반 넘게 줄어든다). 그것까지 잰다.
  · 이 프로젝트에서 잰 적 없음(11-18 확인): 10-12 전략 점검은 '추세추종 매매가 금리 변경 발표 ±5일에 진입했을 때'와 KOSPI 월별
    수익을 봤다 — 아래 창(월말·월초 4일 · 연휴 전날 · 만기일 · 회의 전 한국 장)은 아니다.

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  자료     KOSPI 지수(^KS11, FDR) 시가·종가. 거래일 달력도 이것 — 2010~ 키움 수급 이력(KRX) 거래일과 한 날도 다르지 않다(11-18 확인),
           시가는 2000~ 유효(시가=종가 대체 의심 2016·2024·2026 에 4일뿐).
  후보 (방향·창은 문헌·구조에서 미리 정한다)
    C1 월말·월초       월 마지막 거래일 **전날 종가 → 다음 달 3번째 거래일 종가**(−1~+3일 · Lakonishok·Smidt 1988, McConnell·Xu 2008) · 상승
                       까닭: 월급·연금·적립식 펀드 자금이 월초에 들어온다(정해진 날 사야 한다), 월말 결산.
    C2 연휴 전날       평일 휴장 바로 앞 거래일 — **그 전날 종가 → 그날 종가** · 상승(Ariel 1990 연휴 전 효과)
                       까닭: 연휴 동안 위험을 들고 있지 않으려는 매도 포지션 정리(숏 커버), 연휴 전 낙관.
    C3 옵션 만기일     매월 둘째 목요일(휴장이면 그 전 거래일) **시가 → 종가** · 하락
                       까닭: 만기 청산 프로그램 매도가 장 마감 동시호가에 몰린다(Stoll·Whaley 1987 만기 효과).
    C4 만기 다음 날    **만기일 종가 → 다음 거래일 종가** · 상승 — 일시적 가격 압력의 되돌림(같은 문헌).
    C5 연준 회의 전    미국 정례 회의 결정일 D(둘째 날, 미국 날짜)와 같은 날짜의 한국 거래일 — **그 전날 종가 → 그날 종가** · 상승
                       (Lucca·Moench 2015 발표 전 상승. 한국 장 마감 15:30 은 발표(미국 14:00 = 한국 다음 날 03:00~04:00) 11.5~12.5시간 전 —
                       창(전날 종가→그날 종가)이 문헌 창(발표 전 24시간)과 일부만 겹친다.
                       2011 이후 약해졌다는 연구도 있다 — Kurov·Wolfe·Gilbert 2021). D 가 한국 휴장이면 그 회의는 뺀다.
                       회의 일정은 연준 공식 페이지(fomchistorical2010~2020 · fomccalendars, 11-18 수집) — 임시 회의·화상 회의는 뺀다.
  실행     상승 = KODEX200, 하락 = 인버스(114800) — 시가·종가 동시호가 체결(공격형 리그 ORB 와 같은 체결 모델). 비용 편도 11.5bp.
           인버스의 장중 복리 차이는 무시(수급 판정대와 같다).
  구간     앞 2010-01-04~2020-12-31 · 뒤 2021-01-01~2026-11-17 — 둘 다(수급 판정대와 같은 경계). 사례는 진입일로 구간을 가른다.
  통과(전부)
    P1 표본  구간마다 사례 ≥ MIN_EVENTS(30)
    P2 방향  구간마다 사례 평균(가설 방향) − 같은 모양 창의 그 구간 모든 날 평균 > 0
    P3 매매  구간마다 사례 평균(가설 방향) − 왕복 비용(2 × 11.5bp) > 0  — 같은 후보의 사례끼리는 겹치지 않는다(겹치면 앞 것만)
    P4 유의  두 구간을 합친 t = (사례 평균 − 같은 모양 창 모든 날 평균) ÷ (사례 표준편차 ÷ √n) ≥ 시험 횟수 장부 통과선
             `lab_trials.hurdle_t(lab_trials.total('2026-11-18'))` — 이 묶음 5개까지 합친 93개, 본페로니 양측 5% → 약 3.46
             (11-18 같은 날 2묶음 lab_jkp 선언 때 `total_through('scripts/lab_calendar.py')` 로 바꿈 — 값 93 그대로)
  보고만   구간별 t · 적중률(가설 방향 > 0 인 비율) · 반대 방향. **반대가 강해도 채택하지 않는다**(다음 선언 후보로 기록만).
  통과하면 공격형 리그에 앞으로만 기록하는 멤버 후보(50만원, 다음 거래일부터) — 실계좌는 11-10 운용자 결정대로 없다.

결과 (83e8173 선언대로 1회, 기준 수정 없음 — KOSPI 2009-10-01~2026-11-16, 4,210일) — **통과 없음**
  자료 끝이 11-17 이 아니라 11-16 이었다(FDR end 인자가 그날을 빼는 쪽) — 11-17 에 시작하는 사례가 없어 사례 수는 같고 기저만 하루 적다.
  다시 재지 않는다. 시험 93개 → 통과선 t ≥ 3.46.
        후보                구간  사례   평균%   기저%  초과%p  비용 뒤%  적중     t   P1 P2 P3
  C1 월말·월초(−1~+3일)    앞   132  +0.051  +0.107  −0.056  −0.179  47.7%  −0.32  O X X
                           뒤    70  +0.494  +0.216  +0.279  +0.264  55.7%  +0.59  O O O   합침 202 · 초과 +0.060 · t +0.30 → 탈락
  C2 연휴 전날             앞   114  +0.087  +0.026  +0.061  −0.143  57.9%  +0.75  O O X
                           뒤    67  −0.076  +0.055  −0.131  −0.306  53.7%  −0.72  O X X   합침 181 · −0.010 · t −0.11 → 탈락
  C3 옵션 만기일 장중(하락) 앞   132  −0.012  +0.044  −0.056  −0.242  49.2%  −0.69  O X X
                           뒤    71  −0.099  +0.061  −0.160  −0.329  43.7%  −1.38  O X X   합침 203 · −0.092 · t −1.39 → 탈락
  C4 만기 다음 날           앞   132  −0.019  +0.026  −0.045  −0.249  51.5%  −0.52  O X X
                           뒤    71  +0.059  +0.055  +0.004  −0.171  49.3%  +0.02  O O X   합침 203 · −0.028 · t −0.32 → 탈락
  C5 연준 회의 전 한국 장   앞    80  +0.134  +0.026  +0.108  −0.096  52.5%  +1.09  O O X
                           뒤    43  +0.336  +0.055  +0.282  +0.106  62.8%  +1.01  O O O   합침 123 · +0.169 · t +1.45 → 탈락
  (평균·기저는 가설 방향 — C3 은 부호를 뒤집었다: 기저 +0.044 = 보통 날 장중 −0.044%)
읽는 법
  · **다섯 개 모두 우연과 구분되지 않는다**(가장 큰 |t| 1.45 — 통과선 3.46 의 절반도 안 된다). 월말·월초는 2010~2020 엔 오히려 평소보다
    약했고(−0.056%p), 연휴 전날은 비용(왕복 0.23%)을 못 넘는다. 알려진 달력 효과는 이 시장·이 기간에 남아 있지 않거나 매매할 만큼 크지 않다.
  · 만기일 장중 약세(C3)는 **반대**였다 — 만기일은 보통 날보다 장중에 조금 더 올랐다(t −1.39, 유의하지 않음). 프로그램 매도 압력
    가설은 이 기간엔 보이지 않는다.
  · 가장 꾸준한 건 연준 회의 전(C5): 두 구간 모두 평소보다 +0.11·+0.28%p, 적중 53·63% — 문헌의 '발표 전 상승' 방향 그대로지만
    t 1.45 · 2010~2020 은 비용 뒤 마이너스. 한 해 8번뿐이라 앞으로만 기록해도 판정까지 수년 — 리그에 넣지 않는다(보고만).
  · 보고만: 보통 날 장중(시가→종가) 평균이 두 구간 모두 마이너스(−0.044 · −0.061%) — 아이디어 장부 11번(밤새 오르고 장중엔 안 오른다)과
    같은 모양. 매일 왕복 비용 때문에 매매로는 이미 탈락으로 적어 둔 것.
"""
from __future__ import annotations

import bisect
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
MIN_EVENTS = 30
PERIODS = {"앞": ("2010-01-04", "2020-12-31"), "뒤": ("2021-01-01", "2026-11-17")}
DATA_RANGE = ("2009-10-01", "2026-11-17")       # 앞 구간 첫 사례의 전날 종가까지 들어가게
DECLARED_ON = "2026-11-18"                       # 시험 횟수 장부의 이 묶음 행
CANDIDATES: dict[str, tuple[str, int, tuple[str, int]]] = {   # 이름 → (설명, 방향, 창 모양 ('cc', L) 종가→L일 뒤 종가 · ('oc', 0) 그날 시가→종가)
    "C1": ("월말·월초(−1~+3일)", +1, ("cc", 4)),
    "C2": ("연휴 전날", +1, ("cc", 1)),
    "C3": ("옵션 만기일 장중", -1, ("oc", 0)),
    "C4": ("만기 다음 날", +1, ("cc", 1)),
    "C5": ("연준 회의 전 한국 장", +1, ("cc", 1)),
}
# 미국 연준 정례 회의 결정일(둘째 날, 미국 날짜) — federalreserve.gov fomchistorical2010~2020.htm · fomccalendars.htm(11-18 수집).
# 2020-03-17/18 정례 회의는 취소(03-15 임시 회의로 대체)라 2020 은 7회. 임시 회의·화상 회의·서면 의결은 넣지 않는다.
FOMC_DATES: tuple[str, ...] = (
    "2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23", "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14",
    "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22", "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20", "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19", "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18", "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17", "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15", "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14", "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13", "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
)


def side_cost() -> float:
    return L.side_cost(False, False)          # ETF 편도 수수료+슬리피지(거래세 없음) = 11.5bp


def trials() -> int:
    """이 묶음 행까지의 누적(93) — 11-18 같은 날 2묶음(lab_jkp)을 선언하며 날짜 합(total)에서 행 기준(total_through)으로 바꿨다, 값 그대로."""
    return T.total_through("scripts/lab_calendar.py")


def hurdle() -> float:
    return T.hurdle_t(trials())


# ── 날짜 (순수 함수 — 거래일 목록만 본다) ──────────────────────────────────────
def month_last(days: list[str]) -> list[int]:
    """그달 마지막 거래일의 위치(다음 거래일이 다른 달). 자료 끝 날은 다음 날을 모르니 넣지 않는다."""
    return [j for j in range(len(days) - 1) if days[j][:7] != days[j + 1][:7]]


def holiday_eves(days: list[str]) -> list[int]:
    """다음 거래일까지 사이에 평일이 하나라도 비는 거래일(= 평일 휴장 바로 앞 거래일)의 위치."""
    out = []
    for i in range(len(days) - 1):
        x, end = date.fromisoformat(days[i]) + timedelta(days=1), date.fromisoformat(days[i + 1])
        while x < end:
            if x.weekday() < 5:
                out.append(i)
                break
            x += timedelta(days=1)
    return out


def second_thursday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(3 - d.weekday()) % 7)      # 첫 목요일
    return d + timedelta(days=7)


def expiry_days(days: list[str]) -> list[int]:
    """옵션 만기일 위치 — 둘째 목요일, 휴장이면 그 전 거래일(같은 달 안). 자료 범위 밖 달은 뺀다."""
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        if (y, m) in seen:
            continue
        seen.add((y, m))
        t = second_thursday(y, m).isoformat()
        if t > days[-1]:
            continue
        k = bisect.bisect_right(days, t) - 1      # t 이하 마지막 거래일
        if k >= 0 and days[k][:7] == t[:7]:
            out.append(k)
    return out


def fomc_days(days: list[str], dates: tuple[str, ...] = FOMC_DATES) -> list[int]:
    """미국 결정일과 같은 날짜의 한국 거래일 위치 — 한국 휴장이면 뺀다."""
    pos = {d: k for k, d in enumerate(days)}
    return [pos[d] for d in dates if d in pos]


def entries(name: str, days: list[str]) -> list[int]:
    """후보의 진입 위치 k — 창은 CANDIDATES 의 모양으로 k 에서 시작한다."""
    if name == "C1":
        return [j - 1 for j in month_last(days) if j >= 1]
    if name == "C2":
        return [i - 1 for i in holiday_eves(days) if i >= 1]
    if name in ("C3", "C4"):
        return expiry_days(days)
    if name == "C5":
        return [i - 1 for i in fomc_days(days) if i >= 1]
    raise KeyError(name)


# ── 수익·판정 ────────────────────────────────────────────────────────────────
def window_ret(bars: dict[str, dict], days: list[str], shape: tuple[str, int], k: int) -> float | None:
    """창 수익 — ('cc', L) 진입일 종가 → L 거래일 뒤 종가 · ('oc', 0) 그날 시가 → 종가. 자료가 없으면 None."""
    kind, n = shape
    if kind == "cc":
        if k < 0 or k + n >= len(days):
            return None
        a, b = bars[days[k]].get("close"), bars[days[k + n]].get("close")
    elif kind == "oc":
        if k < 0 or k >= len(days):
            return None
        a, b = bars[days[k]].get("open"), bars[days[k]].get("close")
    else:
        raise ValueError(kind)
    return (b / a - 1) if a and b else None


def non_overlapping(ks: list[int], shape: tuple[str, int]) -> list[int]:
    """같은 후보의 사례끼리 겹치면 앞 것만 — 'cc' L 은 [k, k+L], 'oc' 는 그날 하루."""
    span = shape[1] if shape[0] == "cc" else 0
    out, free = [], -1
    for k in sorted(set(ks)):
        if k >= free:
            out.append(k)
            free = k + span if span else k + 1
    return out


def stats(xs: list[float], base: float) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0}
    m = statistics.fmean(xs)
    sd = statistics.stdev(xs) if n > 1 else float("nan")
    t = (m - base) / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    return {"n": n, "mean": m, "base": base, "excess": m - base, "t": t, "hit": sum(x > 0 for x in xs) / n}


def judge(bars: dict[str, dict], days: list[str], name: str, hurdle_t: float, cost: float) -> dict:
    """후보 하나 — 구간별 재료와 P1~P3, 합친 t 와 P4."""
    _, direction, shape = CANDIDATES[name]
    ev = non_overlapping(entries(name, days), shape)
    out: dict = {"periods": {}}
    pooled_ev, pooled_base = [], []
    ok = True
    for pname, (a, b) in PERIODS.items():
        in_p = [k for k in range(len(days)) if a <= days[k] <= b]
        base = [direction * r for k in in_p if (r := window_ret(bars, days, shape, k)) is not None]
        xs = [direction * r for k in ev if a <= days[k] <= b and (r := window_ret(bars, days, shape, k)) is not None]
        s = stats(xs, statistics.fmean(base) if base else float("nan"))
        checks = {"P1": s["n"] >= MIN_EVENTS,
                  "P2": s["n"] > 0 and s["excess"] > 0,
                  "P3": s["n"] > 0 and s["mean"] - 2 * cost > 0}
        s["checks"], s["net"] = checks, (s["mean"] - 2 * cost) if s["n"] else float("nan")
        out["periods"][pname] = s
        ok &= all(checks.values())
        pooled_ev += xs
        pooled_base += base
    p = stats(pooled_ev, statistics.fmean(pooled_base) if pooled_base else float("nan"))
    p["P4"] = p["n"] > 1 and p["t"] >= hurdle_t
    out["pooled"], out["pass"] = p, ok and p["P4"]
    return out


def measure(bars: dict[str, dict]) -> dict:
    days = sorted(d for d in bars if bars[d].get("close"))
    h, c = hurdle(), side_cost()
    return {"hurdle": h, "trials": trials(), "days": (days[0], days[-1], len(days)),
            "res": {n: judge(bars, days, n, h, c) for n in CANDIDATES}}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bars = L.load_bars("^KS11", *DATA_RANGE)
    m = measure(bars)
    print("=" * 118)
    print(f"구조적 수급 날짜 판정대 — KOSPI {m['days'][0]}~{m['days'][1]} ({m['days'][2]}일) · 편도 {side_cost() * 1e4:.1f}bp · "
          f"시험 {m['trials']}개 → 통과선 t ≥ {m['hurdle']:.2f}")
    print(f"  {'':4}{'후보':22}{'구간':4}{'사례':>5}{'평균%':>8}{'기저%':>8}{'초과%p':>8}{'비용 뒤%':>9}{'적중':>7}{'t':>7}  P1 P2 P3")
    passed = []
    for name, (desc, _, _) in CANDIDATES.items():
        r = m["res"][name]
        for pname, s in r["periods"].items():
            ch = " ".join("O " if s["checks"].get(k) else "X " for k in ("P1", "P2", "P3"))
            if s["n"]:
                print(f"  {name:4}{desc:22}{pname:4}{s['n']:>5}{s['mean'] * 100:>+8.3f}{s['base'] * 100:>+8.3f}"
                      f"{s['excess'] * 100:>+8.3f}{s['net'] * 100:>+9.3f}{s['hit'] * 100:>6.1f}%{s['t']:>+7.2f}  {ch}")
            else:
                print(f"  {name:4}{desc:22}{pname:4}{0:>5}  (사례 없음)")
        p = r["pooled"]
        if p["n"] < 2:
            print(f"  {'':4}{'→ 두 구간 합침':22}  사례 {p['n']} — 판정 불가(탈락)")
            continue
        print(f"  {'':4}{'→ 두 구간 합침':22}{'':4}{p['n']:>5}{p['mean'] * 100:>+8.3f}{p['base'] * 100:>+8.3f}"
              f"{p['excess'] * 100:>+8.3f}{'':>9}{p['hit'] * 100:>6.1f}%{p['t']:>+7.2f}  P4 {'O' if p['P4'] else 'X'}"
              f"  {'통과' if r['pass'] else '탈락'}")
        if r["pass"]:
            passed.append(name)
    print("=" * 118)
    print(f"통과(앞·뒤 P1~P3 + 합친 t ≥ {m['hurdle']:.2f}): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
