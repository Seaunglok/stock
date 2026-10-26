"""I3 리그 도전자 2세대 — 부모(R1)의 강점은 잇고 약점만 고친다 (2026-10-22, 사전 선언).

운용자(10-22): "도전자들을 계속 만들어서 발전해야 한다. 도전자들의 설계도 참고해서 추가해야 발전한다.
약점은 줄이고 강점은 더 살리는 방향으로."

리그 규칙(i3_shadow): 도전자는 lab 사전선언 측정 후 등록, 승격은 **등록 이후 실전 데이터**로만(과거 성적 무관).
그래서 과거 결과를 보고 설계한 2세대라도 괜찮다 — 판정은 아직 오지 않은 데이터가 한다. 다만 리그를 망가뜨릴
설계(제1원칙 위반·부모보다 약점이 더 큰 것)는 입장 단계에서 거른다.

부모 R1(재진입 리셋, 8차) — 강점: 재진입 때 100% 진입 → 강세장 +3.1%p, 연 +2.1%p.
                             약점: 재진입이 연달아 실패하면 손실 상한 없음 → 장기 MDD 43%, 미공개 −11.4%.

선언 (측정 전 — 결과를 보고 고치면 무효)
---------------------------------------
  R3 1년 1회 리셋   리셋은 직전 리셋 후 L(252)영업일이 지났을 때만. 아니면 I3 예산 그대로(연속 휩쏘 차단).
  R4 리셋+초기 손절 R1 리셋 + 재진입 후 TIGHT_DAYS(60)영업일 동안 엔진 이탈선 −10% → −TIGHT_X(5)%.
                    실패한 재진입의 손실을 절반으로(강세장 재진입은 대개 60일 안에 실패하거나 자리 잡는다).
  R5 둘 다          R3 + R4.
  (엔진·m·L·바닥 18%·밴드 10%p 는 I3 그대로. 숫자는 위 하나씩 — 격자 탐색 없음.)
리그 입장 조건(기본값, 전부):
  E1 제1원칙   학습 MDD ≤ 20% · 최악연도 ≥ −10%
  E2 강점 유지 강세장 연수익 ≥ I3 + 1.0%p
  E3 약점 감소 장기(1998~ KOSPI) MDD ≤ R1 − 5%p **그리고** 미공개 수익 ≥ R1 + 3%p
통과한 것은 i3_shadow.CHALLENGERS 에 오늘 날짜로 등록. 떨어진 것은 기록만 하고 같은 숫자로 다시 재지 않는다.

2세대 결과(3a7594b 선언대로, 기본값): R3 13.37%·MDD 18.8%·강세장 16.7%·미공개 −2.7%·장기 MDD 39.2% → E3 장기
0.9%p 차로 탈락. R4 11.24%·MDD 21.8%(E1 탈락) — 손절을 좁히면 급등장 흔들림에 털려 강세장까지 잃는다(이 방향 폐기).
R5 10.52%·강세장 12.5%(E2 탈락).

3세대 선언 (2세대 결과를 본 뒤 설계 — 측정 전 커밋)
-------------------------------------------------
진단: R3 의 장기 MDD 구간은 1999-07→2001-09(닷컴). 그 사이 100% 리셋 재진입 두 번(2000-07-10, 2001-08-14)이
모두 **KOSPI 250일선이 내려가던 장기 하락장**. → 장기 하락장에선 손실을 용서하지 않는다.
  R6 R3 + 장기 추세 조건  리셋은 KOSPI 250일선이 20영업일 전보다 높을 때만(아니면 I3 예산).
  R7 R1 + 장기 추세 조건  1년 1회 제한 없이 추세 조건만으로 충분한가.
  (R4 의 교훈대로 손절은 건드리지 않는다. 250·20 은 관습값 하나씩 — 격자 없음.)
입장 조건은 2세대와 같다(E1·E2·E3, E3 는 원래 부모 R1 대비).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_dd_control as I  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
TIGHT_X = 5.0
TIGHT_DAYS = 60
SPECS: dict[str, dict] = {           # 이름 → i3x 옵션
    "I3": {"reset": "none"},
    "R1": {"reset": "always"},
    "R3": {"reset": "once"},
    "R4": {"reset": "always", "tight_x": TIGHT_X, "tight_days": TIGHT_DAYS},
    "R5": {"reset": "once", "tight_x": TIGHT_X, "tight_days": TIGHT_DAYS},
    "R6": {"reset": "once", "reset_trend_ma": 250, "reset_trend_lag": 20},
    "R7": {"reset": "always", "reset_trend_ma": 250, "reset_trend_lag": 20},
}
GEN2 = ("R3", "R4", "R5")
GEN3 = ("R6", "R7")
NEW = GEN2 + GEN3
E2_BULL_GAIN_PP = 1.0
E3_LONG_MDD_CUT_PP = 5.0
E3_HO_GAIN_PP = 3.0
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
BASE, CASH = "069500", "153130"


def i3x(bars: dict, kospi: dict, asset: str, cash: str | None, m: float, lookback: int,
        reset: str = "none", tight_x: float | None = None, tight_days: int = 0,
        reset_trend_ma: int | None = None, reset_trend_lag: int = 20,
        m_trend_ma: int | None = None, m_trend_lag: int = 20,
        m_up: float | None = None, m_down: float | None = None,
        vol_short: int | None = None, vol_long: int = 252, m_min: float = 0.0,
        brake_off_high: int | None = None, brake_off_ma: int | None = None,
        x_pct: float = 10, n: int = 20, regime_ma: int = I.I1_REGIME_MA,
        floor_dd: float = H.I3_FLOOR_DD, band: float = H.I3_BAND):
    """I3 일반형 — reset: none(I3) · always(R1) · once(직전 리셋 후 lookback 일 지나야 리셋).
    tight_x: 재진입 후 tight_days 동안 엔진 이탈선(%). reset_trend_ma: 리셋은 KOSPI 의 이 이동평균이
    reset_trend_lag 영업일 전보다 높을 때만(장기 하락장에선 손실을 용서하지 않는다).
    m_trend_ma(6세대): 낙폭 예산 배수를 KOSPI 장기선 방향으로 바꾼다 — 올라가면 m_up, 아니면 m_down
    (각각 없으면 m). 지정하지 않으면 m 하나(I3 그대로).
    vol_short(7세대): 변동성 브레이크 — KOSPI 일간 수익률의 최근 vol_short 일 표준편차가 vol_long 일보다 크면 그 비율만큼
    배수를 줄인다(배수 × min(1, σ_long/σ_short), 하한 m_min). 조용한 장에선 배수를 늘리지 않는다.
    brake_off_high / brake_off_ma(8세대): 회복이 확인된 날엔 브레이크를 걸지 않는다 — KOSPI 종가가 직전 n일 최고 종가보다
    높을 때(엔진 재진입의 n일 고점과 같은 정의) / n일 이동평균보다 높을 때.
    엔진 나머지는 lab_dd_control.reentry_confirmed 와 같다."""
    days = sorted(bars)
    pos = {d: k for k, d in enumerate(days)}
    closes = [bars[d]["close"] for d in days]
    kdays = sorted(kospi)
    kpos = {d: k for k, d in enumerate(kdays)}
    kcl = [kospi[d]["close"] for d in kdays]
    kret = [0.0] + [kcl[j] / kcl[j - 1] - 1 for j in range(1, len(kcl))]
    out_w = {cash: 1.0} if cash else {}
    eng = {"in": True, "peak": None, "started": False, "entry_i": None}
    st: dict = {"in": True, "navs": [], "w": None, "ref": None, "last_reset": None}

    def regime_up(d: str) -> bool:
        k = kpos.get(d)
        if k is None or k + 1 < regime_ma:
            return False
        return kcl[k] > sum(kcl[k + 1 - regime_ma:k + 1]) / regime_ma

    def trend_up(d: str, ma: int, lag: int) -> bool:
        """KOSPI ma 일선이 lag 영업일 전보다 높은가(그날까지의 값만)."""
        k = kpos.get(d)
        if k is None or k + 1 < ma + lag:
            return False
        now = sum(kcl[k + 1 - ma:k + 1]) / ma
        j = k - lag
        then = sum(kcl[j + 1 - ma:j + 1]) / ma
        return now > then

    def long_up(d: str) -> bool:
        return True if reset_trend_ma is None else trend_up(d, reset_trend_ma, reset_trend_lag)

    def sd(k: int, w: int) -> float:
        xs = kret[k + 1 - w:k + 1]
        mu = sum(xs) / w
        return (sum((x - mu) ** 2 for x in xs) / w) ** 0.5

    def recovered(d: str) -> bool:
        """회복 확인(브레이크 해제) — 그날까지의 KOSPI 종가만."""
        k = kpos.get(d)
        if k is None:
            return False
        if brake_off_high is not None and k >= brake_off_high and kcl[k] > max(kcl[k - brake_off_high:k]):
            return True
        if brake_off_ma is not None and k + 1 >= brake_off_ma and \
                kcl[k] > sum(kcl[k + 1 - brake_off_ma:k + 1]) / brake_off_ma:
            return True
        return False

    def mult(d: str) -> float:
        if m_trend_ma is None:
            base = m
        elif trend_up(d, m_trend_ma, m_trend_lag):
            base = m if m_up is None else m_up
        else:
            base = m if m_down is None else m_down
        if vol_short is not None and not recovered(d):
            k = kpos.get(d)
            if k is not None and k >= vol_long:                     # 이력이 모자라면 브레이크 없음(그날까지의 값만)
                s_short, s_long = sd(k, vol_short), sd(k, vol_long)
                if s_short > 0:
                    base = max(m_min, base * min(1.0, s_long / s_short))
        return base

    def engine(i: int, d: str):
        k = pos.get(d)
        if k is None:
            return None
        c = closes[k]
        if not eng["started"]:
            eng["started"], eng["peak"] = True, c
            return {asset: 1.0}
        if eng["in"]:
            eng["peak"] = max(eng["peak"], c)
            x = x_pct
            if tight_x is not None and eng["entry_i"] is not None and i - eng["entry_i"] < tight_days:
                x = tight_x
            if c <= eng["peak"] * (1 - x / 100.0):
                eng["in"] = False
                return out_w
            return None
        if k >= n and c > max(closes[k - n:k]) and regime_up(d):
            eng["in"], eng["peak"], eng["entry_i"] = True, c, i
            return {asset: 1.0}
        return None

    def target(i: int, d: str, nav: float):
        sig = engine(i, d)
        st["navs"].append(nav)
        if sig is not None:
            now_in = asset in sig
            if now_in and not st["in"] and reset != "none":
                here = len(st["navs"]) - 1
                yearly_ok = reset == "always" or st["last_reset"] is None or here - st["last_reset"] >= lookback
                if yearly_ok and long_up(d):
                    st["ref"] = st["last_reset"] = here
                else:
                    st["ref"] = None                     # 1년 1회 — 이번엔 용서하지 않는다(I3 예산)
            st["in"] = now_in
        peak = max(st["navs"][-lookback:])
        floor = (1 - floor_dd / 100.0) * peak
        if st["ref"] is not None:
            floor = (1 - floor_dd / 100.0) * max(st["navs"][st["ref"]:][-lookback:])
        e = min(1.0, max(0.0, mult(d) * (nav - floor) / nav)) if nav > 0 else 0.0
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


def measure(spec: dict, kodex, cash, ks, dates, long_dates) -> dict:
    m, lb = H.I3_DEFAULT
    res = L.simulate({BASE: L.Asset(BASE, kodex), CASH: L.Asset(CASH, cash)}, dates,
                     i3x(kodex, ks, BASE, CASH, m, lb, **spec), EQUITY, pass_nav=True)
    lr = L.simulate({"IDX": L.Asset("IDX", ks)}, long_dates, i3x(ks, ks, "IDX", None, m, lb, **spec),
                    0.0, pass_nav=True)
    return {"전체": L.slice_metrics(res, *L.FULL), "박스권": L.slice_metrics(res, *L.PERIODS["박스권"]),
            "강세장": L.slice_metrics(res, *L.PERIODS["강세장"]), "미공개": L.slice_metrics(res, *L.HOLDOUT),
            "장기": L.metrics(lr.dates, lr.curve), "trades": res.trades}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kodex = L.load_bars(BASE, "2014-01-01", END)
    cash = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    dates = [d for d in L.calendar(kodex, L.FULL[0], END) if d in cash]
    long_dates = L.calendar(ks, *I.LONG_STRESS)
    M = {name: measure(spec, kodex, cash, ks, dates, long_dates) for name, spec in SPECS.items()}
    print("=" * 108)
    print(f"도전자 2세대 — 기본값 {H.I3_DEFAULT}, 예탁 {EQUITY:,.0f}원 (부모 R1: 강점 강세장 · 약점 연속 실패)")
    print(f"  {'':5}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'장기MDD':>9}{'장기최악':>9}{'매매':>6}")
    for name, r in M.items():
        print(f"  {name:5}{r['전체']['cagr']:>7.2f}%{r['전체']['mdd']:>6.1f}%{r['전체']['worst_year']:>+6.1f}%"
              f"{r['박스권']['cagr']:>7.1f}%{r['강세장']['cagr']:>7.1f}%{r['미공개']['total']:>+7.1f}%"
              f"{r['장기']['mdd']:>8.1f}%{r['장기']['worst_year']:>+8.1f}%{r['trades']:>6}")
    print("=" * 108)
    admitted = []
    for name in NEW:
        r = M[name]
        checks = [
            ("E1 제1원칙", r["전체"]["mdd"] <= L.MAX_MDD_PCT and r["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT),
            ("E2 강점(강세장 +1%p)", r["강세장"]["cagr"] >= M["I3"]["강세장"]["cagr"] + E2_BULL_GAIN_PP),
            ("E3 약점(장기 MDD −5%p·미공개 +3%p vs R1)",
             r["장기"]["mdd"] <= M["R1"]["장기"]["mdd"] - E3_LONG_MDD_CUT_PP
             and r["미공개"]["total"] >= M["R1"]["미공개"]["total"] + E3_HO_GAIN_PP),
        ]
        ok = all(x for _, x in checks)
        if ok:
            admitted.append(name)
        print(f"  {name}: " + " · ".join(f"{n}{'O' if x else 'X'}" for n, x in checks) + f" → {'리그 입장' if ok else '탈락'}")
    print(f"\n리그 입장: {', '.join(admitted) if admitted else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
