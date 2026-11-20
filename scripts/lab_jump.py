"""점프 모형 국면 × 낙폭 예산 — I3 엔진 자리에 통계적 점프 모형 (백로그 ㉗ · 2026-11-20 사전 선언, 측정 전).

근거 — 어디서 왔나 (결과를 보기 전)
  · 11-19 구성 평가: Shu·Yu·Mulvey(2024) 통계적 점프 모형(Statistical Jump Model) 0/1 전략이 미국·독일·일본 1990~2023 표본 밖에서
    변동성·MDD 를 크게 줄였다(비용·하루 지연 포함). 점프 모형 = 2개 국면 군집 + 국면을 바꿀 때마다 벌점 λ(Nystrup·Lindström·
    Madsen 2020) — 은닉 마르코프 모형보다 국면이 덜 깜빡인다.
  · I3 엔진(−10% 이탈 · 20일 고점 + KOSPI>120일선 재진입)과 목적이 같고 신호가 다르다 — 가격 수준이 아니라 **수익·하방 변동성의
    분포**로 국면을 본다. ㉘(11-20): I3 낙폭 축소의 67~77% 가 타이밍 몫 — 엔진(타이밍)을 바꾸는 축이 의미 있다.
  · 논문은 벌점 λ 를 성과로 고른다(교차 검증 — 과최적화 위험) → 여기선 **고정값 사전 선언**, 격자는 강건성만.
  · 왜 돈이 되나: 수익 예측이 아니라 위험 예측 — 변동성은 군집하고 하락 국면은 이어진다. 국면 변화를 늦게 알아채고 끝까지
    들고 있는 쪽(단순 보유·뒤늦은 강제 청산)이 하락 국면 손실을 진다. 아이디어 장부 14번.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  특징 9개   KOSPI(^KS11) 일간 종가 수익 r 로, 반감기 h ∈ {5, 10, 21}일 지수가중(EWM) — 평균 수익 · log 하방 편차
             √EWM(min(r,0)²) · 소르티노(평균 ÷ 하방 편차). 첫 63일은 버린다(예열). 학습 창의 평균·표준편차로 표준화.
             (논문 계열의 특징 — 세부는 우리 고정값.)
  모형       2국면 점프 모형: min Σ‖x_t − θ_{s_t}‖² + λ·#{s_t ≠ s_{t−1}}. 좌표 하강(동적 계획으로 s, 평균으로 θ),
             시작점 10개(시드 0~9 — 무작위 두 날을 중심으로), 최대 20회, 목적 함수가 가장 작은 것.
             강세 국면 = 학습 창에서 그 국면 날들의 평균 r 이 큰 쪽.
  학습·추론  126거래일(반년)마다 다시 학습 — 창 = 직전 최대 2,772거래일(11년), 최소 1,260(5년). 그 사이 날마다 고정 θ·표준화로
             창 시작부터 앞으로만 동적 계획 → 그날 누적 비용이 작은 국면(그날 종가까지의 자료만 — 시험이 잠근다).
             종가 신호 → 다음 날 시가(I3·strategy_lab 과 같다).
  λ          기본 50 · 격자 {25, 50, 100}(강건성 — 논문이 고른 값의 대략적 범위로 아는 값, 정확히 확인하지 못했다. 우리 고정값).
  후보
    J1 점프 모형 0/1          강세 국면이면 KODEX200 100%, 약세면 현금(153130) 100% — 논문 전략 그대로.
    J2 점프 모형 × 낙폭 예산  엔진만 점프 모형으로 바꾸고 낙폭 예산(252일 최고의 82% 바닥 · m 6 · 밴드 10%p)·현금 자리는 I3 그대로.
  자료       학습 2015-07-28~2026-08-24 + 미공개 08-25~10-21(6~9세대와 같은 날짜 — 현금 바가 있는 날) · 예탁 364만원 정수 주식.
             장기 = ^KS11, 현금 0, 소수 단위 — **점프 모형 첫 신호일(1996 + 예열 63 + 5년 ≈ 2001)부터 2026-08-24**,
             I3 도 같은 날부터 다시 잰다(1998~ 31.2% 는 옆에 적기만).
  입장 조건(J1·J2 각각, 기본 λ, I3 대비 — 6~9세대와 같다):
             E1 학습 MDD ≤ 20% · 최악 연도 ≥ −10%
             G2 (MDD ≤ I3 − 2%p 이고 연수익 ≥ I3 − 0.5%p) 또는 (연수익 ≥ I3 + 1%p 이고 MDD ≤ I3 + 0.5%p)
             G3 미공개 ≥ I3 − 1%p
             G6 장기 MDD ≤ I3(같은 구간) + 3%p
             GJ 격자 중앙값(λ 3개) 학습 MDD ≤ 20% — 벌점 하나에만 기대지 않는다
  통과하면  리그 등록 '후보' — 정원 25 의 마지막 자리 · 11월 신규 3번째라 **등록은 운용자 확인 뒤**(둘 다 통과하면 J2 먼저).
             떨어지면 기록만. 특징·반감기·λ·창·시작점을 바꿔 다시 재지 않는다.
  시험 횟수 장부 +2(J1·J2). λ 격자는 강건성이라 세지 않는다(장부 규칙).
같이 보고만: 박스권 · 강세장 · 6월 사례 · 매매 횟수 · 국면 전환(연) · 강세 국면 비율 · ㉘ 방식 타이밍 p(J2, 학습+미공개).

결과 (71a64ad 선언 뒤 1회 — 2026-11-20, 23초, 기준 수정 없음) — **J1·J2 둘 다 탈락**
        연수익   MDD    최악   박스권  강세장  미공개  6월 사례  장기MDD  매매
  I3    12.61%  19.8%  −6.1%   6.2%  15.6%  −2.7%  −10.5%   28.4%   355
  J1     8.50%  28.7% −20.0%   1.0%  12.0%  +0.4%  −12.9%   36.5%   115   → E1·G2·G6·GJ 탈락
  J2     6.23%  22.7% −11.3%   2.0%   8.2%  +0.4%  −10.7%   28.9%   319   → E1·G2·GJ 탈락 (G3·G6 통과)
  장기 = 2002-05-09~2026-08-24(^KS11 캐시 첫날 1996-12-11 + 예열 + 5년 — 선언의 '≈ 2001' 보다 늦다, 정의는 같다).
  국면(학습): 전환 57번(연 5.3) · 강세 비율 55%. λ 격자 학습 MDD·연수익 — 25: J1 23.0%·11.30% / J2 20.3%·8.89% ·
  50: 28.7%·8.50% / 22.7%·6.23% · 100: 32.2%·4.64% / 27.5%·4.17% (격자 중앙 MDD J1 28.7 · J2 22.7).
  [보고만] J2 타이밍 p_MDD 0.082 · p_CAGR 0.46 — 같은 노출 무작위와 구별 안 됨(I3 는 ㉘ 에서 0.0004).
  [보고만, 결과 뒤 진단] 연도별 I3 / J1 / J2: 2018 −5.3 / −20.0 / −11.3 · 2020 +29.9 / +15.6 / +6.7 · 2023 +10.3 / −0.5 / +1.6.
    2020: 02-24 약세(좋았다) → 05-29 강세(I3 05-26 과 비슷) → 06-29~07-21 · 09-24~11-11 다시 약세 — 반등 중 눌림마다 나갔다.
  교훈: 변동성·하방 편차로 본 국면은 한국에선 **반등장의 눌림을 하락 국면으로 읽는다**(2020·2023) · 완만한 하락(2018)은 변동성이
    낮아 늦게 잡는다. 미공개 급락(08-25~10-21)만은 I3 보다 +3.1%p — 급락 초기 변동성 반응은 빨랐다. 벌점이 클수록 나빴다
    (25 → 100: J1 MDD 23 → 32%) — 국면을 오래 붙들수록 늦는다. **같은 특징·λ 로 다시 재지 않는다**(규칙 1). λ 25 가 가장 나았던 것은
    결과를 보고 안 것이라 과거로 판정하지 않는다. 점프 모형 축은 여기서 닫는다 — 다시 꺼내면 이 표부터.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_gen4 as G4  # noqa: E402
import lab_gen6 as G6  # noqa: E402
import lab_holdout as H  # noqa: E402
import lab_i3_overfit as O  # noqa: E402
import lab_reentry as R  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
HALFLIVES = (5, 10, 21)
WARMUP = 63
LAM = 50.0
LAM_GRID = (25.0, 50.0, 100.0)
N_INIT = 10
MAX_ITER = 20
REFIT = 126
WIN_MAX = 2772
WIN_MIN = 1260
KOSPI = "^KS11"
SOURCE = "scripts/lab_jump.py"
EQUITY, END, BASE, CASH = G4.EQUITY, G4.END, G4.BASE, G4.CASH
LONG_END = I.LONG_STRESS[1]
G6_LONG_MDD_TOL = G6.G6_LONG_MDD_TOL      # 3.0


# ── 특징 ─────────────────────────────────────────────────────────────────────
def ewm(x: np.ndarray, halflife: float) -> np.ndarray:
    """지수가중 평균 — 첫 값에서 시작, 그날까지의 값만."""
    a = 1 - 0.5 ** (1 / halflife)
    out = np.empty(len(x))
    v = float(x[0])
    for k, xi in enumerate(x.tolist()):
        v = xi if k == 0 else (1 - a) * v + a * xi
        out[k] = v
    return out


def features(closes) -> tuple[np.ndarray, np.ndarray]:
    """종가 → (특징 (T, 9), 일간 수익 r). 첫날 r = 0."""
    c = np.asarray(closes, float)
    r = np.zeros(len(c))
    r[1:] = c[1:] / c[:-1] - 1
    cols = []
    for h in HALFLIVES:
        m = ewm(r, h)
        dd = np.maximum(np.sqrt(ewm(np.minimum(r, 0.0) ** 2, h)), 1e-8)
        cols += [m, np.log(dd), m / dd]
    return np.stack(cols, axis=1), r


# ── 점프 모형 ─────────────────────────────────────────────────────────────────
def best_path(d0: list[float], d1: list[float], lam: float) -> tuple[list[int], float]:
    """두 국면의 날마다 비용 → 벌점 λ 를 넣은 최소 비용 경로(동적 계획)와 목적 함수."""
    n = len(d0)
    v0, v1 = d0[0], d1[0]
    b0, b1 = [0] * n, [0] * n
    for t in range(1, n):
        if v0 <= v1 + lam:
            s0, x0 = v0, 0
        else:
            s0, x0 = v1 + lam, 1
        if v1 <= v0 + lam:
            s1, x1 = v1, 1
        else:
            s1, x1 = v0 + lam, 0
        v0, v1 = s0 + d0[t], s1 + d1[t]
        b0[t], b1[t] = x0, x1
    s = [0] * n
    s[-1] = 0 if v0 <= v1 else 1
    for t in range(n - 1, 0, -1):
        s[t - 1] = b0[t] if s[t] == 0 else b1[t]
    return s, min(v0, v1)


def _costs(Z: np.ndarray, th: np.ndarray) -> np.ndarray:
    return ((Z[:, None, :] - th[None, :, :]) ** 2).sum(axis=2)


def fit(Z: np.ndarray, lam: float, n_init: int = N_INIT, max_iter: int = MAX_ITER) -> tuple[float, np.ndarray, np.ndarray]:
    """(목적 함수, 중심 θ (2, F), 국면 s (T,)) — 시작점 n_init 개 중 가장 작은 목적."""
    best = None
    for seed in range(n_init):
        rng = np.random.default_rng(seed)
        th = Z[rng.choice(len(Z), 2, replace=False)].copy()
        s_prev, s, obj = None, None, None
        for _ in range(max_iter):
            D = _costs(Z, th)
            s, obj = best_path(D[:, 0].tolist(), D[:, 1].tolist(), lam)
            if s == s_prev:
                break
            s_prev = s
            sa = np.asarray(s)
            for k in (0, 1):
                if (sa == k).any():
                    th[k] = Z[sa == k].mean(axis=0)
        if best is None or obj < best[0]:
            best = (obj, th.copy(), np.asarray(s))
    return best


def _bull_state(s: np.ndarray, r: np.ndarray) -> int:
    """학습 창에서 평균 r 이 큰 국면. 한 국면이 비었으면 채워진 쪽."""
    means = [float(r[s == k].mean()) if (s == k).any() else -np.inf for k in (0, 1)]
    return 0 if means[0] >= means[1] else 1


def regimes(bars: dict[str, dict], lam: float, win_min: int = WIN_MIN, win_max: int = WIN_MAX,
            refit: int = REFIT, n_init: int = N_INIT, warmup: int = WARMUP) -> dict[str, int]:
    """{날짜: 1 강세 / 0 약세} — 첫 학습일부터. 그날 종가까지의 자료만 쓴다(미래 자료를 넣어도 지난 날 값은 같다)."""
    days = sorted(bars)
    F, r = features([bars[d]["close"] for d in days])
    F, r, days = F[warmup:], r[warmup:], days[warmup:]
    out: dict[str, int] = {}
    for t0 in range(win_min - 1, len(days), refit):
        lo = max(0, t0 - win_max + 1)
        tr = F[lo:t0 + 1]
        mu, sd = tr.mean(axis=0), tr.std(axis=0)
        sd[sd == 0] = 1.0
        _, th, s = fit((tr - mu) / sd, lam, n_init)
        bull = _bull_state(s, r[lo:t0 + 1])
        hi = min(len(days), t0 + refit)
        D = _costs((F[lo:hi] - mu) / sd, th)
        d0, d1 = D[:, 0].tolist(), D[:, 1].tolist()
        v0, v1 = d0[0], d1[0]
        for k in range(1, len(d0)):
            v0, v1 = min(v0, v1 + lam) + d0[k], min(v1, v0 + lam) + d1[k]
            if lo + k >= t0:
                out[days[lo + k]] = int((0 if v0 <= v1 else 1) == bull)
    return out


# ── 전략 ─────────────────────────────────────────────────────────────────────
def jm_engine(states: dict[str, int], asset: str, cash: str | None):
    """reentry_confirmed 와 같은 약속 — target(i, d): 첫날·국면이 바뀐 날만 비중을 낸다. 신호 없는 날은 그대로(시작 전이면 보유)."""
    out_w = {cash: 1.0} if cash else {}
    st: dict = {"in": None}

    def target(i: int, d: str, *_):
        b = states.get(d)
        if b is None:
            if st["in"] is None:
                st["in"] = True
                return {asset: 1.0}
            return None
        now = bool(b)
        if st["in"] is None or now != st["in"]:
            st["in"] = now
            return {asset: 1.0} if now else dict(out_w)
        return None
    return target


def with_budget(engine, asset: str, cash: str | None, m: float = K.M, lookback: int = K.LOOKBACK,
                floor_dd: float = H.I3_FLOOR_DD, band: float = H.I3_BAND):
    """I3 낙폭 예산을 아무 엔진에나 — lab_reentry.i3r(mode I3) 와 같은 줄(시험이 같은 결과를 잠근다)."""
    st: dict = {"in": True, "navs": [], "w": None}

    def target(i: int, d: str, nav: float):
        sig = engine(i, d)
        st["navs"].append(nav)
        if sig is not None:
            st["in"] = asset in sig
        peak = max(st["navs"][-lookback:])
        floor = (1 - floor_dd / 100.0) * peak
        e = min(1.0, max(0.0, m * (nav - floor) / nav)) if nav > 0 else 0.0
        w = e if st["in"] else 0.0
        if (st["w"] is not None and sig is None and abs(w - st["w"]) < band
                and not (w == 0.0 and st["w"] > 0)):
            return None
        st["w"] = w
        out = {asset: w} if w > 0 else {}
        if cash and w < 1.0:
            out[cash] = 1.0 - w
        return out
    return target


def builders(states: dict[str, int]) -> dict[str, tuple]:
    """이름 → (학습용 target 만들기(kodex, ks), 장기용 만들기(ks), pass_nav)."""
    return {
        "J1": (lambda kodex, ks: jm_engine(states, BASE, CASH), lambda ks: jm_engine(states, "IDX", None), False),
        "J2": (lambda kodex, ks: with_budget(jm_engine(states, BASE, CASH), BASE, CASH),
               lambda ks: with_budget(jm_engine(states, "IDX", None), "IDX", None), True),
        "I3": (lambda kodex, ks: R.i3r(kodex, ks, BASE, CASH, K.M, K.LOOKBACK, "I3"),
               lambda ks: R.i3r(ks, ks, "IDX", None, K.M, K.LOOKBACK, "I3"), True),
    }


def switches(states: dict[str, int], dates: list[str]) -> tuple[int, float]:
    """dates 안의 국면 전환 수 · 강세 비율."""
    seq = [states[d] for d in dates if d in states]
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b), (sum(seq) / len(seq) if seq else float("nan"))


def measure(name: str, states, kodex, cash, ks, dates, long_dates) -> dict:
    make, make_long, pn = builders(states)[name]
    tr = O.tracked(make(kodex, ks), BASE)
    res = L.simulate({BASE: L.Asset(BASE, kodex), CASH: L.Asset(CASH, cash)}, dates, tr, EQUITY, pass_nav=pn)
    lr = L.simulate({"IDX": L.Asset("IDX", ks)}, long_dates, make_long(ks), 0.0, pass_nav=pn)
    out = G4.spans(res)
    out["장기"] = L.metrics(lr.dates, lr.curve)
    out["trades"] = res.trades
    out["e"] = np.array(tr.hist + [tr.hist[-1]], float)
    return out


def verdict(r: dict, ref: dict, grid_mdd_median: float) -> list[tuple[str, bool]]:
    full, rf = r["전체"], ref["전체"]
    return [
        ("E1", full["mdd"] <= L.MAX_MDD_PCT and full["worst_year"] >= L.MIN_YEAR_RET_PCT),
        ("G2", (full["mdd"] <= rf["mdd"] - G4.G2_MDD_CUT and full["cagr"] >= rf["cagr"] - G4.G2_CAGR_TOL)
         or (full["cagr"] >= rf["cagr"] + G4.G2_CAGR_UP and full["mdd"] <= rf["mdd"] + G4.G2_MDD_TOL)),
        ("G3", r["미공개"]["total"] >= ref["미공개"]["total"] - G4.HO_TOL),
        ("G6", r["장기"]["mdd"] <= ref["장기"]["mdd"] + G6_LONG_MDD_TOL),
        ("GJ", grid_mdd_median <= L.MAX_MDD_PCT),
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars(KOSPI, "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    grid = {lam: regimes(ks, lam) for lam in LAM_GRID}
    states = grid[LAM]
    long_start = min(states)
    long_dates = L.calendar(ks, long_start, LONG_END)
    M = {n: measure(n, states, kodex, cash, ks, dates, long_dates) for n in ("I3", "J1", "J2")}
    full_dates = [d for d in dates if d <= L.FULL[1]]
    print("=" * 120)
    print(f"점프 모형 국면(㉗) — 학습 {L.FULL[0]}~{L.FULL[1]} + 미공개 ~{END} · 예탁 {EQUITY:,.0f}원 · λ {LAM:g} · "
          f"장기 {long_dates[0]}~{long_dates[-1]}")
    print(f"  {'':4}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}"
          f"{'장기MDD':>9}{'매매':>6}")
    for n, r in M.items():
        print(f"  {n:4}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['사례']['total']:>+8.1f}%{r['장기']['mdd']:>8.1f}%{r['trades']:>6}")
    n_sw, bull = switches(states, full_dates)
    years = len(full_dates) / 252
    print(f"  국면(학습 구간): 전환 {n_sw}번(연 {n_sw / years:.1f}) · 강세 비율 {bull:.0%}")
    print("  λ 격자(학습 MDD · 연수익):")
    gmdd: dict[str, list[float]] = {"J1": [], "J2": []}
    for lam, stt in grid.items():
        row = []
        for n in ("J1", "J2"):
            r = M[n] if lam == LAM else measure(n, stt, kodex, cash, ks, dates, long_dates)
            gmdd[n].append(r["전체"]["mdd"])
            row.append(f"{n} {r['전체']['mdd']:.1f}%·{r['전체']['cagr']:+.2f}%")
        sw, _ = switches(stt, full_dates)
        print(f"    λ {lam:>5g}: " + " · ".join(row) + f" · 전환 연 {sw / years:.1f}")
    print("=" * 120)
    ref = M["I3"]
    passed = []
    for n in ("J1", "J2"):
        med = statistics.median(gmdd[n])
        checks = verdict(M[n], ref, med)
        ok = all(x for _, x in checks)
        if ok:
            passed.append(n)
        print(f"  {n}: " + " · ".join(f"{k}{'O' if x else 'X'}" for k, x in checks) +
              f"  (격자 중앙 MDD {med:.1f}%) → {'리그 등록 후보(운용자 확인 뒤)' if ok else '탈락'}")
    tt = O.timing_test(M["J2"]["e"], O.legs(kodex, dates), O.legs(cash, dates), O.year_ends(dates))
    print(f"  [보고만] J2 타이밍 p_MDD {tt['p_mdd']:.4f} · p_CAGR {tt['p_cagr']:.4f} (평균 비중 {tt['exposure']:.0%}, 학습+미공개)")
    print(f"  [보고만] I3 장기 1998~ 기준(6~9세대 표) 31.2% — 이 표의 I3 장기는 {long_dates[0]}~ 다시 잰 값")
    print("결론: " + (", ".join(passed) + " 리그 등록 후보" if passed else "J1·J2 모두 탈락 — 기록만"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
