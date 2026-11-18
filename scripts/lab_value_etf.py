"""가치 ETF × I3 엔진 — 리그 도전자 등록 선언 (2026-11-18 선언 · 2026-11-20 등록 · 앞으로만).

운용자(11-18): 2묶음 결과 보고 뒤 "진행하자". 근거는 `lab_jkp` 선언(fb77fa5)의 "통과하면 그 팩터 ETF 로 I3 엔진을 돌리는 도전자를
리그에 앞으로만 등록(어느 ETF·신호를 무엇으로 볼지는 통과 뒤 따로 선언)" — 결과(33e666d)에서 **F3 가치만 통과**.
이 파일이 그 '따로 선언'이다. 입장은 lab_jkp 에서 이미 정해졌다 — 아래 재생 성적은 보고만이고 등록 여부를 바꾸지 않는다.

선언
----
  멤버     이름 NAME('가치저변동') · 계열 '외부 팩터(JKP 가치)' · 등록 REGISTER_ON = 2026-11-20.
           11-19 은 수능 판단 배치(16:45, 새 save_state 첫 실전)를 먼저 확인한다 — 그 전엔 리그 코드(MEMBERS)를 건드리지 않는다.
  ETF      KODEX 200가치저변동(223190) — 한국 가치 ETF 중 **유일하게** 두 조건을 채운다:
             ① 리그 재생 시작(2015-07-28) 전 상장(2015-06-26) — 낙폭 예산·엔진 상태를 다른 멤버와 같은 길이로 만든다
             ② 하루 거래 약 10억원(11-18 최근 20일) — 예탁 수백만 원 매매에 충분
           버린 후보: TIGER 우량가치(227570) 하루 0.12억·순자산 51억(상장폐지선 근처) · KODEX 배당가치(325020) 2019 상장 ·
           코리아밸류업 ETF 들(2024-11 상장 · 다른 개념). 가치 상품이 아니라 배당 상품인 PLUS 고배당주는 F5(탈락)의 것이라 쓰지 않는다.
           ⚠️ 이 ETF 는 순수 가치가 아니다 — 코스피200 안에서 **가치 + 저변동**을 함께 본다(저변동 F1 은 탈락). JKP 가치의
           '사는 쪽'(코스피·코스닥 전체, 소형주 포함)보다 잡히는 몫이 작을 수 있다. 그래서 판정은 리그 기록으로만.
  신호     I3 엔진을 **그 ETF 의 가격으로** 돌린다 — `lab_reentry.i3r(ETF 일봉, KOSPI, ETF, 현금, K.M, K.LOOKBACK, "I3")`:
             이탈 = 진입 뒤 ETF 최고 대비 −10% · 재진입 = ETF 종가 > 직전 20일 최고 + KOSPI > MA120(I3 그대로) ·
             낙폭 예산 = 자기 자산 252일 최고의 82% 바닥선, 비중 min(1, 6 × 쿠션) · 현금 자리 = 리그 현금(488770).
           까닭: 신호를 KODEX200 에 두면 위험 비중이 매일 챔피언과 같아져(예산만 조금 다르다) 승격 조건 '다르게 행동한 날
           ≥ 20'(i3_shadow.DIVERGE_PP 10%p)을 구조적으로 못 채운다 — '가치 ETF 에 I3 를 돌린다'는 선언 문장 그대로가 자연스럽다.
           파라미터는 I3 그대로(다시 고르지 않는다).
  리그 규칙 그대로(승격 120영업일·다르게 행동 20일·누적 +2%p·MDD≤20% 월간 점검 2회 연속 + 운용자 승인 · 탈락 MDD>25% 즉시 등).
           정원 25 중 24번째 · 11월 신규 2번째(V7a 11-02) — 월 상한 3 안.
  가격     리그와 같은 FDR+키움 일봉(분배금 빠진 가격). 고배당 성격이라 KODEX200 보다 분배금이 많을 것 — 기록이 조금 불리한 쪽.
  보고만   2015-07-28~ 재생(연구 현금 153130 — 리그 현금 488770 은 2024 상장이라): I3(KODEX200) vs 가치저변동 · 단순 보유 둘 ·
           구간 2015-07~2020 · 2021~ · 다르게 행동한 날 수. 판정·등록에 쓰지 않는다(lab_jkp 결과 B·C 구간을 이미 봤다).
  시험 횟수 장부 +1(앞으로만 기록도 결국 판정하므로 센다).

보고만 결과 (525b308 선언 뒤 1회 — 2015-07-28~2026-11-17, 2,769일, 연구 현금 153130, 예탁 364만원, 분배금 빠진 가격)
                      연%    MDD%  최악 연도   누적%  | ~2020 연%  MDD% | 2021~ 연%  MDD%
  I3(KODEX200)      +11.96  19.9    −6.1   +246.0  |   +7.76  19.9  |  +15.49  16.9
  가치저변동         +12.66  21.6    −6.1   +270.6  |   +5.98  21.6  |  +19.04  16.5
  KODEX200 보유     +13.23  47.4   −24.1   +291.5  |  +11.43  38.0  |  +14.39  47.4
  223190 보유       +14.02  42.4   −16.6   +322.7  |  +10.27  42.4  |  +17.41  35.8
  다르게 행동한 날(위험 비중 차 ≥ 10%p): 765일 / 2,769일(28%) — 승격 조건 '20일'은 구조적으로 채울 수 있다.
  읽는 법(판정 아님): 전체로는 I3 보다 연 +0.7%p, 2021 이후 +3.6%p 지만 2015~2020 은 −1.8%p 이고 **MDD 21.6% 로 I3(19.9%)보다 깊다**
  — 연구 잣대 ①(MDD ≤ 20%)에 걸리는 값이다. 입장은 lab_jkp 선언대로라 등록은 그대로 하고, 승격 조건(등록 뒤 MDD ≤ 20% 그리고
  ≤ 챔피언 +3%p)이 이 약점을 앞으로의 기록으로 잰다. 단순 보유끼리는 223190 이 연 +0.8%p · MDD 5%p 얕다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import lab_reentry as R  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
NAME = "가치저변동"
FAMILY = "외부 팩터(JKP 가치)"
ETF = "223190"                       # KODEX 200가치저변동
REGISTER_ON = "2026-11-20"
SOURCE = "scripts/lab_value_etf.py"
BASIS = "lab_jkp F3 가치 통과(선언 fb77fa5 → 결과 33e666d)"
KOSPI = "^KS11"                      # = i3_shadow.KOSPI (시험이 같은지 본다)
DIVERGE_PP = 0.10                    # = i3_shadow.DIVERGE_PP
REPORT_CASH = "153130"
REPORT_END = "2026-11-18"
REPORT_EQUITY = 3_640_000.0
REPORT_SPLIT = "2021-01-01"


def build(data: dict, dates: list[str], cash: str = K.CASH):
    """i3_shadow.std_run 용 — (자산 코드들, target, needs_nav). 엔진·예산은 I3 그대로, 가격만 ETF."""
    return (ETF, cash), R.i3r(data[ETF], data[KOSPI], ETF, cash, K.M, K.LOOKBACK, "I3"), True


# ── 보고만: 과거 재생 ─────────────────────────────────────────────────────────
def tracked(target, asset: str):
    """target 을 감싸 날마다 '그 자산의 목표 비중'(마지막으로 낸 값)을 적는다."""
    hist: dict[str, float] = {}
    last = {"w": 0.0}

    def t(i, d, nav):
        r = target(i, d, nav)
        if r is not None:
            last["w"] = r.get(asset, 0.0)
        hist[d] = last["w"]
        return r
    t.hist = hist
    return t


def hold(asset: str):
    def t(i, d, *_):
        return {asset: 1.0} if i == 0 else None
    return t


def replay(k: dict, v: dict, ks: dict, cash: dict, start: str = K.REPLAY_START, equity: float = REPORT_EQUITY) -> dict:
    dates = sorted(d for d in k if d >= start and d in v and d in ks)     # 셋 다 있는 날만(FDR 지수는 하루 늦을 때가 있다)
    a_i3 = {K.BASE: L.Asset(K.BASE, k), REPORT_CASH: L.Asset(REPORT_CASH, cash)}
    a_v = {ETF: L.Asset(ETF, v), REPORT_CASH: L.Asset(REPORT_CASH, cash)}
    t_i3 = tracked(R.i3r(k, ks, K.BASE, REPORT_CASH, K.M, K.LOOKBACK, "I3"), K.BASE)
    t_v = tracked(R.i3r(v, ks, ETF, REPORT_CASH, K.M, K.LOOKBACK, "I3"), ETF)
    out = {"I3": L.simulate(a_i3, dates, t_i3, equity, pass_nav=True),
           NAME: L.simulate(a_v, dates, t_v, equity, pass_nav=True),
           "KODEX200 보유": L.simulate({K.BASE: a_i3[K.BASE]}, dates, hold(K.BASE), equity, pass_nav=True),
           "가치저변동 보유": L.simulate({ETF: a_v[ETF]}, dates, hold(ETF), equity, pass_nav=True)}
    diverge = sum(1 for d in dates if abs(t_v.hist.get(d, 0.0) - t_i3.hist.get(d, 0.0)) >= DIVERGE_PP)
    return {"res": out, "dates": (dates[0], dates[-1], len(dates)), "diverge": diverge,
            "w_i3": t_i3.hist, "w_v": t_v.hist}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    k = L.load_bars(K.BASE, "2014-01-01", REPORT_END)
    v = L.load_bars(ETF, "2014-01-01", REPORT_END)
    ks = L.load_bars(KOSPI, "1996-01-01", REPORT_END)
    c = L.load_bars(REPORT_CASH, "2014-01-01", REPORT_END)
    r = replay(k, v, ks, c)
    d0, d1, n = r["dates"]
    print(f"가치 ETF × I3 엔진 — 보고만(등록 여부와 무관) · {d0}~{d1} {n}일 · 연구 현금 {REPORT_CASH} · 예탁 {REPORT_EQUITY:,.0f}")
    print(f"  {'':16}{'연%':>8}{'MDD%':>8}{'최악 연도%':>11}{'누적%':>9}  |{'~2020 연%':>10}{'MDD%':>7}  |{'2021~ 연%':>10}{'MDD%':>7}")
    for name, res in r["res"].items():
        m = L.metrics(res.dates, res.curve)
        a = L.slice_metrics(res, d0, "2020-12-31")
        b = L.slice_metrics(res, REPORT_SPLIT, d1)
        print(f"  {name:16}{m['cagr']:>+8.2f}{m['mdd']:>8.1f}{m['worst_year']:>+11.1f}{m['total']:>+9.1f}  |"
              f"{a['cagr']:>+10.2f}{a['mdd']:>7.1f}  |{b['cagr']:>+10.2f}{b['mdd']:>7.1f}")
    print(f"  다르게 행동한 날(위험 비중 차 ≥ {DIVERGE_PP:.0%}): {r['diverge']}일 / {n}일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
