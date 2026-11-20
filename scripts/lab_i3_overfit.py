"""I3 과최적화 점검 — 보고만 (백로그 ㉘ · 2026-11-20 선언, 측정 전).

왜
--
  I3 는 연구소 5차(10-22)에서 뽑혔다 — 그때까지 이름 붙은 후보 15개를 쟀고, 지금 시험 장부는 99개다. 새 후보에는 통과선
  (`lab_trials.hurdle_t`)을 쓰지만 **챔피언 I3 자신은 시험 횟수 보정을 받은 적이 없다**(11-19 구성 평가). 그리고 I3 의 존재
  이유는 수익이 아니라 낙폭이다 — 낙폭이 준 것이 '타이밍을 잘해서'인지 '주식을 덜 들고 있어서'인지 가른 적이 없다.

질문 셋 (+ 재료 하나)
  Q1 낙폭 축소는 타이밍 덕인가, 노출을 줄인 덕인가 — 같은 노출·같은 보유 구간 길이를 시점만 옮긴 무작위 전략과 비교
  Q2 시험 횟수를 보정해도 샤프 비율이 0보다 크다고 말할 수 있나 — PSR·DSR(Bailey·López de Prado 2012·2014) + 본페로니 통과선
  Q3 5차 가족에서 '학습 성적이 가장 좋은 설정 고르기'가 과최적화였나 — PBO(CSCV, Bailey 외 2017)
  재료 MinTRL — 샤프 차이를 말하려면 기록이 며칠 필요한가(㉔ 리그 통계 기준 — 2027-01 점검 전 선언의 재료)

선언 (측정 전 고정 — 결과를 보고 고치면 무효)
---------------------------------------
  자료   학습 FULL 2015-07-28~2026-08-24 · KODEX200(069500) + 현금 153130 · 예탁 364만원 정수 주식 · 비용 strategy_lab 가정.
         장기 1998-01-02~2026-08-24 · ^KS11 · 현금 0 · 소수 단위(lab_dd_control.LONG_STRESS 그대로).
         I3 = `lab_reentry.i3r(..., i3_core.M, i3_core.LOOKBACK, "I3")`(실전==검증 시험이 잠근 길). 미공개·리그 기간은 넣지 않는다.
  Q1     I3 재생에서 날마다 위험자산 목표 비중 e_t(그날 종가 신호)를 적는다. 마찰 없는 재구성: 밤사이(전일 종가→시가)는 e_{t−2},
         장중(시가→종가)은 e_{t−1}(종가 신호 → 다음 날 시가 체결), 나머지는 현금. 무작위 = e 를 원형으로 s 일 민 것,
         s = SHIFT_MIN … T−SHIFT_MIN 전부(보유 비율·보유 구간 길이·비중 분포는 그대로, 시장과의 시점만 다르다).
         실제(s=0)도 같은 재구성으로 잰다(정수 주식·비용 재생 값은 옆에 적는다).
         p_MDD = (1 + #{무작위 MDD ≤ 실제}) / (1 + 무작위 수) · p_CAGR = (1 + #{무작위 CAGR ≥ 실제}) / (1 + 무작위 수).
         분해 보고: KODEX200(지수) 보유 MDD → 무작위 중앙값(노출을 줄인 몫) → 실제(타이밍 몫).
  Q2     일간 초과 수익 = I3 − 현금 153130(장기는 현금 0이라 수익 그대로). SR·왜도 γ₃·첨도 γ₄(정규 3) →
         PSR z = SR·√(T−1) / √(1 − γ₃SR + (γ₄−1)/4·SR²). 통과선 hurdle_t(N) — N_SELECT(연구소 1~5차 누적, I3 가 뽑힐 때까지) ·
         N_NOW(장부 전체, 참고). DSR: 기대 최대 SR₀ = √V·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))), V = 5차 가족 22개 설정의 일간 SR
         분산(같은 구간) → DSR = Φ(PSR z(SR₀)). V 를 서로 닮은 격자에서 재므로 SR₀ 가 낮게(관대하게) 나온다 — 적어 둔다.
         + 학습 구간 I3 대 KODEX200 샤프 차이(Memmel 2003 보정 Jobson-Korkie z, 둘 다 현금 초과 수익).
  Q3     학습 구간 5차 KODEX200 가족 22개 — I1a 격자 9(X·n) · I2a 격자 4(m) · I3 격자 9(m·L), 정수 주식·비용 재생의 일간 수익.
         CSCV: 연속 16토막(마지막 토막이 나머지 날을 갖는다), 8토막씩 학습/검증 모든 조합 C(16,8)=12,870. 학습 최고 설정의 검증
         상대 순위 ω = 순위/(N+1)(1 = 가장 나쁨) → λ = ln(ω/(1−ω)), PBO = P(λ ≤ 0). 지표 둘: 샤프(현금 초과 수익) ·
         MAR(토막을 시간 순으로 이어 붙인 경로의 CAGR/MDD, 수익 그대로). + I3 기본값(6·252)의 검증 순위 중앙값 ·
         학습 최고가 I3 격자인 비율. 1~4차 가족(A~H)은 넣지 않는다 — '5차 안에서 고르기'만 잰다.
  재료   MinTRL = 1 + (1 − γ₃SR + (γ₄−1)/4·SR²)·(z₀.₉₅/SR)² 일(단측 5%) — 학습 구간 I3 초과 수익 · I3−KODEX200 차이 수익 ·
         정규 가정 연 샤프 0.25/0.5/1.0. 거꾸로 60·120영업일(공격형·I3 리그 판정 길이)로 5% 유의를 말할 수 있는 최소 연 샤프.

읽는 법 (측정 전 고정 — 판정이 아니라 보고, **어느 결과든 I3 운용·리그 규칙은 그대로**)
  Q1 학습·장기 **둘 다** p_MDD ≤ P_OK → "낙폭 축소에 타이밍 몫이 있다" · 하나라도 넘으면 "그 구간에선 같은 노출의 무작위와 구별 안 된다".
  Q2 PSR z ≥ hurdle_t(N_SELECT) 그리고 DSR(N_SELECT) ≥ DSR_OK → "보정 뒤에도 0보다 큰 샤프" — 학습·장기 따로 적는다.
  Q3 PBO < 0.25 낮음 · 0.25~0.5 보통 · ≥ 0.5 높음(학습 최고 고르기가 검증에서 절반 넘게 중앙값 아래).
  시험 횟수 장부: 새 후보가 아니라 챔피언 점검이라 행을 더하지 않는다.

결과 (b381beb 선언 뒤 1회 — 2026-11-20, 학습 2,716일 · 장기 7,054일, 18초)
  Q1 타이밍 대 노출 — **둘 다 타이밍 몫 있음**(MDD). 수익은 무작위와 구별 안 됨.
                  평균 비중   지수 MDD   무작위 중앙값(5~95%)   I3 MDD(재구성 / 정수·비용)   p_MDD    p_CAGR
     학습          61%       40.8      35.6 (25.9~40.3)       18.6 / 19.8                 0.0004   0.26
     장기          49%       55.7      47.4 (35.2~60.8)       30.7 / 31.2                 0.0090   0.31
     분해: 학습 지수 40.8 → 노출 몫 −5.2%p → 타이밍 몫 −17.0%p · 장기 55.7 → −8.3%p → −16.7%p.
     연수익: 학습 I3 13.4% vs 무작위 중앙값 10.7%(95% 17.4%) · 장기 6.6% vs 5.4%(95% 9.1%).
  Q2 시험 횟수 보정 샤프 — **학습·장기 둘 다 미달**(PSR z 가 통과선 3.00 아래).
     학습 연 샤프 0.78(왜도 −0.91·첨도 21.4) · PSR z 2.49 · DSR(15) 0.980 · DSR(99) 0.969 — DSR 은 넘지만 z 가 3.00 아래.
     장기 연 샤프 0.54 · PSR z 2.85 · DSR(15) 0.932 · DSR(99) 0.818.
     가족 22개 학습 연 샤프 0.63~0.89, I3 기본값 13번째 · 장기 0.08~0.61, 12번째.
     I3 대 KODEX200 샤프 0.78 vs 0.68, Memmel z +0.42(p 0.67) — 샤프 차이 유의 아님. 차이 수익(I3 − 지수) 연 샤프 −0.31.
  Q3 PBO — **샤프 0.696 · MAR 0.602 둘 다 높음.** 학습 최고는 대부분 I1a(X10·n20 이 34%·32%), I3 격자는 4%·21%.
     I3 기본값 검증 순위 중앙값 9/22(샤프)·12/22(MAR).
  재료 MinTRL — I3 초과 수익 샤프 0.78 을 단독으로 말하는 데 4.7년. 정규 가정 연 샤프 0.25/0.5/1.0 → 43.3/10.8/2.7년.
     60영업일로 말할 수 있는 최소 연 샤프 3.44 · 120영업일 2.41.

  읽는 법(판정 아님 — I3 운용·리그 규칙 불변)
    · I3 의 일(낙폭 줄이기)은 우연이 아니다 — 같은 비율로 주식을 들되 시점만 무작위인 전략 수천 개 중 학습 0.04%·장기 0.9% 만
      I3 만큼 낙폭이 얕았다. 줄인 낙폭 중 타이밍 몫이 학습 77%(22.2 중 17.0%p)·장기 67%(25.0 중 16.7%p), 노출 몫은 5~8%p.
    · 수익·샤프는 실력이라고 말할 수 없다 — 수익은 무작위 중앙값보다 높지만 p 0.26~0.31, 샤프는 통과선 아래, 지수보다 나은 샤프도
      아니다. 'I3 가 더 번다'는 주장은 하지 않는다(원래 하지 않았다 — 운용자 제1원칙은 MDD).
    · 5차 가족 안에서 무엇이 가장 좋은지는 자료가 못 가른다(PBO 0.6~0.7) — I3 는 학습 최고라서가 아니라 MDD ≤ 20% 잣대를
      지켜서 뽑혔으므로 이 숫자가 I3 선택을 무효로 하지는 않지만, '격자 안에서 더 나은 설정 고르기'는 하지 않는다(10-22 이후 그대로).
    · ㉔ 재료: 리그 승격 120영업일로 5% 유의를 말하려면 두 멤버 차이 수익의 연 샤프가 2.4 넘어야 한다 — 지금 '+2%p' 규칙은
      통계로는 거의 가를 수 없다. 숫자는 2027-01 점검 전 선언에서 쓴다.
"""
from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402
import lab_reentry as R  # noqa: E402
import lab_trials as TR  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
FULL = L.FULL                       # ("2015-07-28", "2026-08-24")
LONG = I.LONG_STRESS                # ("1998-01-02", "2026-08-24")
EQUITY = R.EQUITY                   # 3,640,000 — 정수 주식
CASH = R.CASH                       # 153130 — 검증 현금(488770 은 2024 상장)
SHIFT_MIN = 21                      # 한 달보다 가까운 이동은 사실상 같은 타이밍
CSCV_S = 16
P_OK = 0.05
DSR_OK = 0.95
ALPHA = 0.05                        # MinTRL 단측
PBO_BANDS = (0.25, 0.5)
MINTRL_SR = (0.25, 0.5, 1.0)        # 정규 가정 연 샤프
JUDGE_DAYS = (60, 120)              # 공격형 리그 · I3 리그 판정 길이(영업일)
EULER = 0.5772156649015329
I3_LABEL = f"I3 m{K.M}·L{K.LOOKBACK}"
_ND = NormalDist()


def _through_name(prefix: str) -> int:
    """시험 장부에서 이름이 prefix 로 시작하는 첫 행까지의 누적 변형 수."""
    s = 0
    for _, name, n, _ in TR.TRIALS:
        s += n
        if name.startswith(prefix):
            return s
    raise KeyError(prefix)


N_SELECT = _through_name("연구소 5차")    # I3 가 뽑힐 때까지(연구소 1~5차) = 15
N_NOW = TR.total_through("scripts/lab_value_etf.py")   # 선언·측정 당시 장부 전체(99) — 뒤에 행이 늘어도 이 값(참고)


# ── 통계 ─────────────────────────────────────────────────────────────────────
def moments(x) -> tuple[float, float, float]:
    """일간 SR · 왜도 γ₃ · 첨도 γ₄(정규 = 3)."""
    x = np.asarray(x, float)
    d = x - x.mean()
    m2 = float((d ** 2).mean())
    return (float(x.mean() / x.std(ddof=1)), float((d ** 3).mean() / m2 ** 1.5), float((d ** 4).mean() / m2 ** 2))


def psr_z(sr: float, t: int, g3: float, g4: float, sr_star: float = 0.0) -> float:
    """확률적 샤프 비율의 z — Φ(z) 가 'SR > sr_star' 일 확률(Bailey·López de Prado 2012)."""
    return (sr - sr_star) * math.sqrt(t - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr * sr)


def expected_max_sr(var_sr: float, n: int) -> float:
    """실력 없는 시험 n 개 중 최대 SR 의 기댓값(SR 분산 var_sr) — DSR 의 기준선."""
    if n < 2:
        raise ValueError("n ≥ 2")
    return math.sqrt(var_sr) * ((1 - EULER) * _ND.inv_cdf(1 - 1 / n) + EULER * _ND.inv_cdf(1 - 1 / (n * math.e)))


def dsr(sr: float, t: int, g3: float, g4: float, var_sr: float, n: int) -> float:
    """보정 샤프 비율 — 시험 n 개의 기대 최대를 넘을 확률."""
    return _ND.cdf(psr_z(sr, t, g3, g4, expected_max_sr(var_sr, n)))


def min_trl(sr: float, g3: float = 0.0, g4: float = 3.0, alpha: float = ALPHA, sr_star: float = 0.0) -> float:
    """일간 SR 이 sr 일 때 'SR > sr_star' 를 단측 alpha 로 말하는 데 필요한 날 수(MinTRL). sr ≤ sr_star 면 무한."""
    if sr <= sr_star:
        return math.inf
    z = _ND.inv_cdf(1 - alpha)
    return 1 + (1 - g3 * sr + (g4 - 1) / 4 * sr * sr) * (z / (sr - sr_star)) ** 2


def sr_needed(days: int, alpha: float = ALPHA) -> float:
    """정규 가정에서 days 일 기록으로 단측 alpha 유의를 말할 수 있는 최소 일간 SR(min_trl 의 역)."""
    z = _ND.inv_cdf(1 - alpha)
    return z / math.sqrt(days - 1 - z * z / 2)


def memmel_z(x1, x2) -> float:
    """두 전략 샤프 차이 z(Jobson-Korkie, Memmel 2003 보정) — 같은 날의 수익 쌍."""
    x1, x2 = np.asarray(x1, float), np.asarray(x2, float)
    t = len(x1)
    s1, s2 = x1.mean() / x1.std(ddof=1), x2.mean() / x2.std(ddof=1)
    rho = float(np.corrcoef(x1, x2)[0, 1])
    v = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / t
    return float((s1 - s2) / math.sqrt(v))


# ── Q1 타이밍 대 노출 ─────────────────────────────────────────────────────────
def legs(bars: dict | None, dates: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """날마다 (밤사이, 장중) 수익 — 첫날 0. 바가 없거나 시가가 0 인 날은 직전 종가로 채운다. bars None = 현금 0."""
    n = len(dates)
    on, intra = np.zeros(n), np.zeros(n)
    if bars is None:
        return on, intra
    last = None
    for k, d in enumerate(dates):
        b = bars.get(d)
        c = b["close"] if b and b.get("close") else last
        o = b["open"] if b and b.get("open") else (last if last else c)
        if last and o and c:
            on[k] = o / last - 1
            intra[k] = c / o - 1
        if c:
            last = c
    return on, intra


def recon(E: np.ndarray, a: tuple[np.ndarray, np.ndarray], c: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """E (k, T) 목표 비중 → (k, T) 일간 수익. 밤사이 = e_{t−2}, 장중 = e_{t−1}, 시작 전 비중 0, 나머지 현금."""
    E = np.atleast_2d(E)
    h_in = np.zeros_like(E)
    h_in[:, 1:] = E[:, :-1]
    h_on = np.zeros_like(E)
    h_on[:, 2:] = E[:, :-2]
    r = (1 + c[0] + h_on * (a[0] - c[0])) * (1 + c[1] + h_in * (a[1] - c[1])) - 1
    r[:, 0] = 0.0
    return r


def year_ends(dates: list[str]) -> np.ndarray:
    """각 해의 마지막 날 위치(마지막 날 포함)."""
    idx = [k for k in range(len(dates) - 1) if dates[k][:4] != dates[k + 1][:4]]
    return np.array(idx + [len(dates) - 1])


def path_stats(r: np.ndarray, ye: np.ndarray) -> dict[str, np.ndarray]:
    """r (k, T) 일간 수익(0열 = 첫날 0) → CAGR·MDD·최악 연도(%) — strategy_lab.metrics 와 같은 정의."""
    curve = np.cumprod(1 + r, axis=1)
    peak = np.maximum.accumulate(curve, axis=1)
    n = r.shape[1]
    ends = curve[:, ye]
    prev = np.concatenate([curve[:, :1], ends[:, :-1]], axis=1)
    return {"cagr": (curve[:, -1] / curve[:, 0]) ** (252.0 / n) * 100 - 100,
            "mdd": ((peak - curve) / peak).max(axis=1) * 100,
            "worst": ((ends / prev - 1) * 100).min(axis=1)}


def timing_test(e: np.ndarray, a: tuple, c: tuple, ye: np.ndarray, shift_min: int = SHIFT_MIN,
                chunk: int = 400) -> dict:
    """e(T,) 의 원형 이동 전부와 실제를 비교 — p_MDD·p_CAGR·무작위 분포."""
    e = np.asarray(e, float)
    t = len(e)
    act = {k: float(v[0]) for k, v in path_stats(recon(e[None, :], a, c), ye).items()}
    shifts = np.arange(shift_min, t - shift_min + 1)
    mdd, cagr = [], []
    for part in np.array_split(shifts, max(1, math.ceil(len(shifts) / chunk))):
        st = path_stats(recon(np.stack([np.roll(e, int(s)) for s in part]), a, c), ye)
        mdd.append(st["mdd"])
        cagr.append(st["cagr"])
    mdd, cagr = np.concatenate(mdd), np.concatenate(cagr)
    n = len(mdd)
    return {"act": act, "n": n, "mdd": mdd, "cagr": cagr,
            "p_mdd": (1 + int((mdd <= act["mdd"] + 1e-9).sum())) / (1 + n),
            "p_cagr": (1 + int((cagr >= act["cagr"] - 1e-9).sum())) / (1 + n),
            "exposure": float(e.mean())}


# ── Q3 PBO(CSCV) ─────────────────────────────────────────────────────────────
def _ranks(v: np.ndarray) -> np.ndarray:
    """1 = 가장 낮음(동률은 순서대로 — 실수 지표라 거의 없다)."""
    out = np.empty(len(v))
    out[np.argsort(v, kind="stable")] = np.arange(1, len(v) + 1)
    return out


def _mar(sub: np.ndarray) -> np.ndarray:
    curve = np.cumprod(1 + sub, axis=1)
    full = np.concatenate([np.ones((sub.shape[0], 1)), curve], axis=1)
    peak = np.maximum.accumulate(full, axis=1)
    mdd = ((peak - full) / peak).max(axis=1)
    cagr = curve[:, -1] ** (252.0 / sub.shape[1]) - 1
    return np.where(mdd > 0, cagr / np.maximum(mdd, 1e-12), np.inf)


def cscv(R_: np.ndarray, s: int = CSCV_S, metric: str = "sharpe") -> dict:
    """R_ (N, T) 일간 수익 → PBO · λ · 조합마다 학습 최고 설정 · 검증 순위(조합 × N)."""
    n_cfg, t = R_.shape
    b = t // s
    bounds = [(k * b, (k + 1) * b if k < s - 1 else t) for k in range(s)]
    if metric == "sharpe":
        s1 = np.stack([R_[:, lo:hi].sum(1) for lo, hi in bounds], 1)
        s2 = np.stack([(R_[:, lo:hi] ** 2).sum(1) for lo, hi in bounds], 1)
        cnt = np.array([hi - lo for lo, hi in bounds], float)

        def score(mask):
            n = cnt[mask].sum()
            mu = s1[:, mask].sum(1) / n
            var = (s2[:, mask].sum(1) - n * mu * mu) / (n - 1)
            return mu / np.sqrt(var)
    elif metric == "mar":
        blocks = [np.arange(lo, hi) for lo, hi in bounds]

        def score(mask):
            return _mar(R_[:, np.concatenate([blocks[k] for k in range(s) if mask[k]])])
    else:
        raise ValueError(metric)
    lam, best, oos_ranks = [], [], []
    for combo in itertools.combinations(range(s), s // 2):
        mask = np.zeros(s, bool)
        mask[list(combo)] = True
        star = int(np.argmax(score(mask)))
        rk = _ranks(score(~mask))
        w = rk[star] / (n_cfg + 1)
        lam.append(math.log(w / (1 - w)))
        best.append(star)
        oos_ranks.append(rk)
    lam = np.array(lam)
    return {"pbo": float((lam <= 0).mean()), "lambda": lam, "best": np.array(best),
            "oos_ranks": np.array(oos_ranks), "combos": len(lam)}


# ── 재생 ─────────────────────────────────────────────────────────────────────
def tracked(target, asset: str):
    """target 을 감싸 날마다 '그 자산의 목표 비중'(마지막으로 낸 값)을 적는다(lab_value_etf.tracked 와 같은 뜻)."""
    hist: list[float] = []
    last = {"w": 0.0}

    def t(i, d, *nav):
        r = target(i, d, *nav)
        if r is not None:
            last["w"] = float(r.get(asset, 0.0))
        hist.append(last["w"])
        return r
    t.hist = hist
    return t


def family(bars: dict, ks: dict, asset: str, cash: str | None) -> list[tuple[str, object, bool]]:
    """5차 KODEX200 가족 22개 — (이름, 만들기, pass_nav)."""
    out: list[tuple[str, object, bool]] = []
    for x, n in I.I1_GRID:
        out.append((f"I1a X{x}·n{n}", lambda x=x, n=n: I.reentry_confirmed(bars, ks, asset, x, n, cash), False))
    for m in I.I2_GRID:
        out.append((f"I2a m{m}", lambda m=m: I.drawdown_budget(asset, m, cash), True))
    for m, lb in H.I3_GRID:
        out.append((f"I3 m{m}·L{lb}", lambda m=m, lb=lb: R.i3r(bars, ks, asset, cash, m, lb, "I3"), True))
    return out


def daily(curve: list[float]) -> np.ndarray:
    c = np.asarray(curve, float)
    return c[1:] / c[:-1] - 1


def cash_returns(bars: dict | None, dates: list[str]) -> np.ndarray:
    """현금 자리 일간 종가 수익(T−1,) — 바가 없는 날은 직전 종가."""
    if bars is None:
        return np.zeros(len(dates) - 1)
    px, last = [], None
    for d in dates:
        b = bars.get(d)
        last = b["close"] if b and b.get("close") else last
        px.append(last)
    p = np.asarray(px, float)
    return p[1:] / p[:-1] - 1


def run_period(bars: dict, ks: dict, asset: str, cash_bars: dict | None, cash: str | None,
               dates: list[str], equity: float) -> dict:
    assets = {asset: L.Asset(asset, bars)}
    if cash:
        assets[cash] = L.Asset(cash, cash_bars)
    rc = cash_returns(cash_bars if cash else None, dates)
    fam: dict[str, dict] = {}
    e = None
    for label, make, pn in family(bars, ks, asset, cash):
        tr = tracked(make(), asset)
        res = L.simulate(assets, dates, tr, equity, pass_nav=pn)
        r = daily(res.curve)
        fam[label] = {"res": res, "r": r, "x": r - rc, "m": L.metrics(res.dates, res.curve)}
        if label == I3_LABEL:
            e = np.array(tr.hist + [tr.hist[-1]], float)
    bench = L.buy_and_hold(asset, dates, bars, equity)
    rb = daily(bench.curve)
    return {"fam": fam, "e": e, "rc": rc, "bench": {"res": bench, "r": rb, "x": rb - rc,
                                                     "m": L.metrics(bench.dates, bench.curve)},
            "a_legs": legs(bars, dates), "c_legs": legs(cash_bars if cash else None, dates),
            "ye": year_ends(dates), "dates": dates}


def report_q1(name: str, p: dict) -> dict:
    tt = timing_test(p["e"], p["a_legs"], p["c_legs"], p["ye"])
    act, sim = tt["act"], p["fam"][I3_LABEL]["m"]
    bh = {k: float(v[0]) for k, v in path_stats(recon(np.ones((1, len(p["e"]))), p["a_legs"], p["c_legs"]),
                                                p["ye"]).items()}
    print(f"\n[Q1 {name}] 평균 위험 비중 {tt['exposure']:.0%} · 무작위 {tt['n']}개(원형 이동 {SHIFT_MIN}~{len(p['e']) - SHIFT_MIN}일)")
    print(f"  {'':22}{'MDD%':>8}{'연%':>8}{'최악 연도%':>11}")
    print(f"  {'지수 보유(재구성)':22}{bh['mdd']:>8.1f}{bh['cagr']:>+8.2f}{bh['worst']:>+11.1f}")
    print(f"  {'무작위 중앙값':22}{np.median(tt['mdd']):>8.1f}{np.median(tt['cagr']):>+8.2f}")
    print(f"  {'  무작위 5%·95%':22}{np.percentile(tt['mdd'], 5):>8.1f}{np.percentile(tt['cagr'], 5):>+8.2f}   "
          f"(MDD 95% {np.percentile(tt['mdd'], 95):.1f} · 연 95% {np.percentile(tt['cagr'], 95):+.2f})")
    print(f"  {'I3 실제(재구성)':22}{act['mdd']:>8.1f}{act['cagr']:>+8.2f}{act['worst']:>+11.1f}")
    print(f"  {'I3 재생(정수·비용)':22}{sim['mdd']:>8.1f}{sim['cagr']:>+8.2f}{sim['worst_year']:>+11.1f}")
    print(f"  p_MDD = {tt['p_mdd']:.4f} · p_CAGR = {tt['p_cagr']:.4f}  "
          f"→ {'타이밍 몫 있음' if tt['p_mdd'] <= P_OK else '같은 노출 무작위와 구별 안 됨'}(이 구간)")
    print(f"  분해: 지수 MDD {bh['mdd']:.1f} → 노출 몫 {bh['mdd'] - np.median(tt['mdd']):+.1f}%p → "
          f"타이밍 몫 {np.median(tt['mdd']) - act['mdd']:+.1f}%p → I3 {act['mdd']:.1f}")
    return tt


def report_q2(name: str, p: dict) -> dict:
    x = p["fam"][I3_LABEL]["x"]
    sr, g3, g4 = moments(x)
    t = len(x)
    srs = np.array([moments(f["x"])[0] for f in p["fam"].values()])
    var = float(srs.var(ddof=1))
    z0 = psr_z(sr, t, g3, g4)
    out = {"sr": sr, "g3": g3, "g4": g4, "t": t, "z0": z0, "var": var}
    print(f"\n[Q2 {name}] I3 일간 초과 수익 {t}일 · 연 샤프 {sr * math.sqrt(252):.2f} · 왜도 {g3:+.2f} · 첨도 {g4:.1f}")
    print(f"  가족 22개 연 샤프 {srs.min() * math.sqrt(252):.2f}~{srs.max() * math.sqrt(252):.2f}"
          f"(I3 기본값 순위 {int((srs > sr).sum()) + 1}/22) · 일간 SR 분산 V = {var:.3g}")
    for tag, n in (("N_SELECT", N_SELECT), ("N_NOW", N_NOW)):
        h = TR.hurdle_t(n)
        d = dsr(sr, t, g3, g4, var, n)
        sr0 = expected_max_sr(var, n)
        ok = z0 >= h and d >= DSR_OK
        out[tag] = {"n": n, "hurdle": h, "dsr": d, "sr0": sr0, "ok": ok}
        print(f"  {tag} {n:>3}: PSR z {z0:.2f} vs 통과선 {h:.2f} · SR₀ 연 {sr0 * math.sqrt(252):.2f} · DSR {d:.3f}"
              f"  → {'보정 뒤에도 0보다 큰 샤프' if ok else '보정 뒤엔 말하기 어렵다'}")
    return out


def report_q3(p: dict) -> dict:
    labels = list(p["fam"])
    i3k = labels.index(I3_LABEL)
    i3_set = [k for k, lb in enumerate(labels) if lb.startswith("I3 ")]
    out = {}
    for metric, key in (("sharpe", "x"), ("mar", "r")):
        res = cscv(np.stack([p["fam"][lb][key] for lb in labels]), CSCV_S, metric)
        pbo = res["pbo"]
        band = "낮음" if pbo < PBO_BANDS[0] else ("보통" if pbo < PBO_BANDS[1] else "높음")
        top = np.bincount(res["best"], minlength=len(labels))
        print(f"\n[Q3 {metric}] CSCV {CSCV_S}토막 · 조합 {res['combos']} · PBO {pbo:.3f}({band}) · λ 중앙값 {np.median(res['lambda']):+.2f}")
        print(f"  I3 기본값 검증 순위 중앙값 {np.median(res['oos_ranks'][:, i3k]):.0f}/22 · "
              f"학습 최고가 I3 격자 {np.isin(res['best'], i3_set).mean():.0%} · 학습 최고 자주 뽑힌 것: " +
              ", ".join(f"{labels[k]} {top[k] / res['combos']:.0%}" for k in np.argsort(-top)[:3]))
        out[metric] = res
    return out


def report_mintrl(q2: dict, p: dict) -> None:
    sr, g3, g4 = q2["sr"], q2["g3"], q2["g4"]
    diff = p["fam"][I3_LABEL]["r"] - p["bench"]["r"]
    ds, d3, d4 = moments(diff)
    z = memmel_z(p["fam"][I3_LABEL]["x"], p["bench"]["x"])
    bs = moments(p["bench"]["x"])[0]
    print(f"\n[재료] 학습 구간 샤프 I3 {sr * math.sqrt(252):.2f} vs KODEX200 {bs * math.sqrt(252):.2f} · "
          f"Memmel z {z:+.2f}(p 양측 {2 * (1 - _ND.cdf(abs(z))):.3f})")
    print(f"  MinTRL(단측 5%) I3 초과 수익: {min_trl(sr, g3, g4) / 252:.1f}년 · I3−KODEX200 차이(연 샤프 "
          f"{ds * math.sqrt(252):+.2f}): " + (f"{min_trl(ds, d3, d4) / 252:.1f}년" if ds > 0 else "무한(차이가 0 이하)"))
    print("  정규 가정 MinTRL: " + " · ".join(f"연 샤프 {a:g} → {min_trl(a / math.sqrt(252)) / 252:.1f}년"
                                           for a in MINTRL_SR))
    print("  판정 길이로 말할 수 있는 최소 연 샤프: " + " · ".join(f"{dd}영업일 {sr_needed(dd) * math.sqrt(252):.2f}"
                                                   for dd in JUDGE_DAYS))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(K.BASE, "2014-01-01", FULL[1])
    cash = L.load_bars(CASH, "2014-01-01", FULL[1])
    ks = L.load_bars("^KS11", "1996-01-01", FULL[1])
    full = run_period(kodex, ks, K.BASE, cash, CASH, L.calendar(kodex, *FULL), EQUITY)
    long_ = run_period(ks, ks, "IDX", None, None, L.calendar(ks, *LONG), 0.0)
    print(f"I3 과최적화 점검(보고만 · ㉘) — 학습 {FULL[0]}~{FULL[1]} {len(full['dates'])}일 · "
          f"장기 {long_['dates'][0]}~{long_['dates'][-1]} {len(long_['dates'])}일 · N_SELECT {N_SELECT} · N_NOW {N_NOW}")
    q1 = {"학습": report_q1("학습", full), "장기": report_q1("장기", long_)}
    q2 = {"학습": report_q2("학습", full), "장기": report_q2("장기", long_)}
    report_q3(full)
    report_mintrl(q2["학습"], full)
    both = all(v["p_mdd"] <= P_OK for v in q1.values())
    print("\n요약(읽는 법대로): Q1 " + ("낙폭 축소에 타이밍 몫이 있다(학습·장기 둘 다)" if both else
                                    "적어도 한 구간에선 같은 노출 무작위와 구별 안 된다") +
          " · Q2 " + " · ".join(f"{k} {'통과' if v['N_SELECT']['ok'] else '미달'}" for k, v in q2.items()) +
          " — I3 운용·리그 규칙은 그대로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
