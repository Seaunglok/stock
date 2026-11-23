"""연말 대주주 양도세 매도 판정대 — 세금 때문에 '정해진 날까지 팔아야 하는' 개인이 코스닥을 누르고, 그날이 지나면 되돌아오나
(2026-11-23, 사전 선언 · 아이디어 장부 6번).

운용자(11-18): "오픈되지 않은 좋은 조건식이나 매매 알고리즘이 많이 있을 거 같어. 이런거를 더 발굴하는거는 어때?" → 1묶음 달력
(`lab_calendar`, 전부 탈락) · 2묶음 해외 팩터 한국판(`lab_jkp`, 가치 통과 → 「가치저변동」 리그) → 운용자(11-23) "지난주에 하던 업무
진행해줘" — 남은 묶음 둘(연말 대주주 매도 · MSCI 정기변경) 중 자료가 있는 쪽.

왜 돈이 되나 (누가 손해를 보며 사고파나)
-----------------------------------------
  · 한국 상장주식 양도세는 '대주주'만 낸다. 대주주 여부는 **그해 마지막 날 보유액(종목당)** 으로 정해지고 다음 해에 판 주식에 매긴다.
    기준 금액 근처의 개인은 연말에 팔아 기준 밑으로 내려갔다가 해가 바뀌면 다시 산다 — 가격과 무관하게 **날짜에 맞춰** 판다.
  · 결제가 T+2 라 **폐장일 2거래일 전(매도 마감일 D)** 까지 판 주식만 명부에서 빠진다(기사: 2021 은 12-28 · 2023 은 12-26 — 아래 규칙으로
    계산한 날과 같다, 2026 은 12-28 로 예고). 그날까지 파는 개인이 손해(세금을 피하려고 싸게 판다)를 보고, 그 물량을 받아 간 쪽이
    D 뒤의 되돌림을 가져간다. D+1 부터 산 주식은 명부에 오르지 않으니 되사기는 D+1 부터 시작할 수 있다.
  · 개인 비중이 높은 코스닥에서 클 것(기사: 2021-12-28 개인 코스닥 −1.13조 · 기준이 50억으로 오른 2023-12-26 엔 개인 코스닥 +1,000억 순매수).
  출처: 소득세법 시행령 대주주 범위(종목당 보유액, 코스피 기준 — 100억 → 2013-07 50억(코스닥 40억) → 2016-04 25억(코스닥 20억) →
    2018-04 15억 → 2020-04 10억 → 2023-12 50억 → 2025-09-15 기획재정부 50억 유지) — 한국경제 2020-08-30 · 경향신문 2025-08-25 ·
    매일신문 2026-10-14(2026 마감일 12-28) · 이코노미스트 2021-12-29 · 아이뉴스24(2023 연말). **이 효과를 잰 학술 논문은 찾지 못했다**
    (11-23 검색). 미국 연말 세금 매도(Roll 1983 · Reinganum 1983)는 '손실 종목'을 파는 구조라 같은 근거로 쓰지 않는다.

선언 전에 본 것 (정직하게)
  · 기사 속 순매도 금액(위 둘 · 12월 개인 순매도 2016 1.6조 · 2017 5.1조 · 2018 1.6조) — 수급(메커니즘)이지 수익률이 아니다.
  · 자료 범위(^KQ11 2009-10-01~2026-03-30 4,056일 · 229200 2015-10-01~ · 251340 2016-08-10~ · 수급 이력 12·1월 check 전부 ok)와
    해마다의 D 날짜(아래 `deadline_positions` — 날짜만). **수익률은 한 번도 보지 않았다.**

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  자료     코스닥 종합지수 ^KQ11(FDR) 종가, 2009-10-01~2026-03-31(고정 기준일 캐시). 거래일 달력도 이것.
  날짜     해마다(2010~2025, 16번) 폐장일 = 12월 마지막 거래일 · 매도 마감일 D = 폐장일 2거래일 전.
  후보 (방향·창은 구조에서 미리 정한다 — 2개)
    Y1 마감일 앞 약세    D−5 거래일 종가 → D 종가(마감 직전 5거래일 — 팔아야 하는 사람이 몰리는 날들) · 하락
    Y2 마감일 뒤 되돌림  D 종가 → D+5 거래일 종가(되사기 · 해가 바뀐 뒤 재진입) · 상승
  실행     Y1 = KODEX 코스닥150선물인버스(251340) 매수 · Y2 = KODEX 코스닥150(229200) 매수, 종가 체결, 편도 11.5bp.
  구간     앞 2010~2020(사례 11) · 뒤 2021~(사례 5) — 진입일로 가른다(`lab_calendar`·`lab_flows` 와 같은 경계).
  통과(전부)
    P1 표본  16년이 전부 계산된다(한 해라도 자료가 없으면 탈락) — 연 1회라 `lab_calendar` 의 30 은 불가.
             **힘이 약한 시험이다**: n 16 에서 t ≥ 3.49 는 (평균 − 기저) ÷ 표준편차 ≥ 0.87 — 해마다 거의 같은 방향으로 커야 넘는다.
    P2 방향  구간마다 사례 평균(가설 방향) − 같은 모양 창(cc 5) 그 구간 모든 날 평균 > 0
    P3 매매  구간마다 사례 평균(가설 방향) − 왕복 비용(2 × 11.5bp) > 0
    P4 유의  두 구간 합친 t = (사례 평균 − 모든 날 평균) ÷ (사례 표준편차 ÷ √n) ≥ `hurdle_t(total_through('scripts/lab_taxsell.py'))`
             (이 묶음 2개까지 누적 104 → 약 3.49)
    P5 실행  실제 ETF(Y1 251340 · Y2 229200, 상장 뒤 해만)로 같은 날짜 창의 사례 평균 − 왕복 비용 > 0 — 검증 조건 = 운용 조건
             (판정 지수는 코스닥 종합, 실행은 코스닥150 이라 따로 확인한다)
  보고만(채택에 쓰지 않는다 — 반대가 강해도 채택하지 않는다)
    R1 같은 창의 KOSPI(^KS11) · R2 코스닥 − KOSPI(개인 비중 차이만큼 코스닥이 더 움직이나)
    R3 기준 금액별 — 낮은 해(코스닥 기준 ≤ 20억: 2015~2022 연말 8번) vs 높은 해(≥ 40억: 2010~2014·2023~2025 8번).
       세금이 원인이면 낮은 해가 더 커야 한다(용량–반응). 8 대 8 이라 판정에 쓰지 않는다.
    R4 수급 — 같은 창의 개인 코스닥 순매수 합(억원, `data/market_flows/daily.csv` check ok) vs 같은 길이 모든 창 평균.
  탈락하면 '효과 없음'이 아니라 '16번으로는 우연과 구분 못 한다'. 앞으로만 기록도 연 1회라 판정까지 수십 년 — 그때는 리그에 넣지 않는다.
  통과하면 공격형 리그에 앞으로만(50만원 · 2026 연말: Y1 진입 12-18 종가 → D 12-28 · Y2 12-28 → 2027-01-06) — 실계좌는 없다(11-10 결정).
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_calendar as C  # noqa: E402  — 창 수익·통계는 1묶음과 같은 함수
import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
DECLARED_ON = "2026-11-23"
SOURCE = "scripts/lab_taxsell.py"                 # 시험 횟수 장부의 이 묶음 행
DATA_RANGE = ("2009-10-01", "2026-03-31")
INDEX, KOSPI = "^KQ11", "^KS11"
YEARS: tuple[int, ...] = tuple(range(2010, 2026))
MIN_EVENTS_TOTAL = len(YEARS)                      # 16 — 한 해도 빠지면 안 된다
PERIODS = {"앞": ("2010-01-04", "2020-12-31"), "뒤": ("2021-01-01", "2026-03-31")}
SHAPE = ("cc", 5)
DEADLINE_BEFORE_LAST = 2                           # 매도 마감일 = 폐장일 2거래일 전(T+2 결제)
CANDIDATES: dict[str, tuple[str, int, int, str]] = {   # 이름 → (설명, 방향, D 기준 진입 오프셋(거래일), 실행 ETF — 매수)
    "Y1": ("마감일 앞 약세", -1, -5, "251340"),
    "Y2": ("마감일 뒤 되돌림", +1, 0, "229200"),
}
# 보고만(R3): 연말 → 그 연말 보유로 다음 해 매도에 쓰인 코스닥 종목당 기준(억원). 기사 기준 — 2012~2014 의 40 은 확실하지 않지만
# 묶음 경계(≤ 20억)는 영향을 받지 않는다.
THRESHOLD_KOSDAQ_EOK: dict[int, int] = {
    2010: 50, 2011: 50, 2012: 40, 2013: 40, 2014: 40, 2015: 20, 2016: 20, 2017: 15,
    2018: 15, 2019: 10, 2020: 10, 2021: 10, 2022: 10, 2023: 50, 2024: 50, 2025: 50,
}
LOW_THRESHOLD_EOK = 20
FLOWS_CSV = _ROOT / "data" / "market_flows" / "daily.csv"


def side_cost() -> float:
    return L.side_cost(False, False)              # ETF 편도 수수료+슬리피지(거래세 없음) = 11.5bp


def trials() -> int:
    return T.total_through(SOURCE)


def hurdle() -> float:
    return T.hurdle_t(trials())


def low_years() -> frozenset[int]:
    return frozenset(y for y, v in THRESHOLD_KOSDAQ_EOK.items() if v <= LOW_THRESHOLD_EOK)


# ── 날짜 (순수 함수 — 거래일 목록만 본다) ──────────────────────────────────────
def deadline_positions(days: list[str], years: tuple[int, ...] = YEARS) -> dict[int, int]:
    """해 → 매도 마감일 D 의 위치. 폐장일 = 그해 12월 마지막 거래일 — 다음 거래일이 다음 해로 자료에 있어야 확정(자료 끝이면 뺀다)."""
    out: dict[int, int] = {}
    for y in years:
        dec = [i for i, d in enumerate(days) if d.startswith(f"{y}-12")]
        if not dec:
            continue
        last = dec[-1]
        if last + 1 >= len(days) or not days[last + 1].startswith(f"{y + 1}-"):
            continue
        if last - DEADLINE_BEFORE_LAST >= 0:
            out[y] = last - DEADLINE_BEFORE_LAST
    return out


def entries(name: str, days: list[str]) -> dict[int, int]:
    """해 → 진입 위치 k(창은 k 종가 → k+5 종가)."""
    off = CANDIDATES[name][2]
    return {y: d + off for y, d in deadline_positions(days).items() if d + off >= 0}


# ── 판정 ────────────────────────────────────────────────────────────────────
def judge(bars: dict[str, dict], days: list[str], name: str, hurdle_t: float, cost: float) -> dict:
    """후보 하나 — 구간별 P2·P3, 합친 t 와 P1·P4. P5(실행 ETF)는 exec_check 가 따로."""
    _, direction, _, _ = CANDIDATES[name]
    ev = entries(name, days)
    per_year = {y: direction * r for y, k in ev.items() if (r := C.window_ret(bars, days, SHAPE, k)) is not None}
    out: dict = {"periods": {}, "years": per_year}
    pooled_ev, pooled_base, ok = [], [], True
    for pname, (a, b) in PERIODS.items():
        base = [direction * r for k in range(len(days)) if a <= days[k] <= b
                and (r := C.window_ret(bars, days, SHAPE, k)) is not None]
        xs = [per_year[y] for y, k in ev.items() if y in per_year and a <= days[k] <= b]
        s = C.stats(xs, statistics.fmean(base) if base else float("nan"))
        checks = {"P2": s["n"] > 0 and s["excess"] > 0, "P3": s["n"] > 0 and s["mean"] - 2 * cost > 0}
        s["checks"], s["net"] = checks, (s["mean"] - 2 * cost) if s["n"] else float("nan")
        out["periods"][pname] = s
        ok &= all(checks.values())
        pooled_ev += xs
        pooled_base += base
    p = C.stats(pooled_ev, statistics.fmean(pooled_base) if pooled_base else float("nan"))
    p["P1"] = p["n"] >= MIN_EVENTS_TOTAL
    p["P4"] = p["n"] > 1 and p["t"] >= hurdle_t
    out["pooled"], out["pass_index"] = p, ok and p["P1"] and p["P4"]
    return out


def exec_check(etf_bars: dict[str, dict], days: list[str], name: str, cost: float) -> dict:
    """P5 — 실행 ETF 를 같은 날짜(지수 달력의 진입일·청산일)에 사고판다. 두 날 모두 ETF 종가가 있는 해만."""
    out = {}
    for y, k in entries(name, days).items():
        if k + SHAPE[1] >= len(days):
            continue
        a, b = etf_bars.get(days[k], {}).get("close"), etf_bars.get(days[k + SHAPE[1]], {}).get("close")
        if a and b:
            out[y] = b / a - 1
    xs = list(out.values())
    m = statistics.fmean(xs) if xs else float("nan")
    return {"years": out, "n": len(xs), "mean": m, "net": m - 2 * cost if xs else float("nan"),
            "P5": bool(xs) and m - 2 * cost > 0}


# ── 보고만 ──────────────────────────────────────────────────────────────────
def report_kospi(kq: dict[str, dict], ks: dict[str, dict], days: list[str], name: str) -> dict:
    """R1·R2 — 같은 날짜 창의 KOSPI 와 코스닥 − KOSPI(가설 방향). KOSPI 에 그날이 없으면 그해는 뺀다."""
    direction = CANDIDATES[name][1]
    r1, r2 = {}, {}
    for y, k in entries(name, days).items():
        if k + SHAPE[1] >= len(days):
            continue
        d0, d1 = days[k], days[k + SHAPE[1]]
        a, b = ks.get(d0, {}).get("close"), ks.get(d1, {}).get("close")
        q = C.window_ret(kq, days, SHAPE, k)
        if a and b and q is not None:
            r1[y] = direction * (b / a - 1)
            r2[y] = direction * q - r1[y]
    return {"kospi": r1, "spread": r2}


def report_threshold(per_year: dict[int, float]) -> dict:
    """R3 — 낮은 기준 해와 높은 기준 해의 평균(가설 방향)."""
    lo = [v for y, v in per_year.items() if y in low_years()]
    hi = [v for y, v in per_year.items() if y not in low_years()]
    return {"low": (len(lo), statistics.fmean(lo) if lo else float("nan")),
            "high": (len(hi), statistics.fmean(hi) if hi else float("nan"))}


def load_indiv_kosdaq(path: Path = FLOWS_CSV) -> dict[str, float]:
    """개인 코스닥 순매수(억원) — check ok 인 날만(연구 규칙)."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("check") == "ok" and r.get("kosdaq_indiv_eok") not in (None, ""):
                out[r["date"]] = float(r["kosdaq_indiv_eok"])
    return out


def report_flows(flows: dict[str, float], days: list[str], name: str) -> dict:
    """R4 — 창 안 5거래일(k+1..k+5)의 개인 코스닥 순매수 합 vs 같은 길이 모든 창 평균(수급 이력이 빠짐없는 창만)."""
    n = SHAPE[1]

    def wsum(k: int) -> float | None:
        ds = days[k + 1:k + 1 + n]
        if len(ds) < n or any(d not in flows for d in ds):
            return None
        return sum(flows[d] for d in ds)

    ev = {y: s for y, k in entries(name, days).items() if (s := wsum(k)) is not None}
    base = [s for k in range(len(days)) if (s := wsum(k)) is not None]
    return {"years": ev, "mean": statistics.fmean(ev.values()) if ev else float("nan"),
            "base": statistics.fmean(base) if base else float("nan")}


def measure(kq: dict[str, dict], ks: dict[str, dict], etfs: dict[str, dict[str, dict]],
            flows: dict[str, float]) -> dict:
    days = sorted(d for d in kq if kq[d].get("close"))
    h, c = hurdle(), side_cost()
    res = {}
    for name, (_, _, _, etf) in CANDIDATES.items():
        r = judge(kq, days, name, h, c)
        r["exec"] = exec_check(etfs.get(etf, {}), days, name, c)
        r["pass"] = r["pass_index"] and r["exec"]["P5"]
        r["R12"] = report_kospi(kq, ks, days, name)
        r["R3"] = report_threshold(r["years"])
        r["R4"] = report_flows(flows, days, name)
        res[name] = r
    return {"hurdle": h, "trials": trials(), "days": (days[0], days[-1], len(days)),
            "deadlines": {y: days[k] for y, k in deadline_positions(days).items()}, "res": res}


def main() -> int:
    import contextlib
    import io
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with contextlib.redirect_stdout(io.StringIO()):
        kq = L.load_bars(INDEX, *DATA_RANGE)
        ks = L.load_bars(KOSPI, *DATA_RANGE)
        etfs = {etf: L.load_bars(etf, *DATA_RANGE) for _, _, _, etf in CANDIDATES.values()}
    m = measure(kq, ks, etfs, load_indiv_kosdaq())
    pct = lambda x: f"{x * 100:+.2f}"   # noqa: E731
    print("=" * 112)
    print(f"연말 대주주 매도 판정대 — 코스닥 {m['days'][0]}~{m['days'][1]} ({m['days'][2]}일) · 편도 {side_cost() * 1e4:.1f}bp · "
          f"시험 {m['trials']}개 → 통과선 t ≥ {m['hurdle']:.2f}")
    print("  매도 마감일 D: " + " · ".join(f"{y % 100:02d} {d[5:]}" for y, d in m["deadlines"].items()))
    passed = []
    for name, (desc, _, _, etf) in CANDIDATES.items():
        r = m["res"][name]
        print(f"\n  {name} {desc} (창 {SHAPE[1]}거래일, 가설 방향 %)")
        print("    해별: " + " ".join(f"{y % 100:02d}:{pct(v)}" for y, v in r["years"].items()))
        for pname, s in r["periods"].items():
            ch = " ".join(f"{k}{'O' if v else 'X'}" for k, v in s["checks"].items())
            if s["n"]:
                print(f"    {pname} 사례 {s['n']:>2} 평균 {pct(s['mean'])} 기저 {pct(s['base'])} 초과 {pct(s['excess'])} "
                      f"비용 뒤 {pct(s['net'])} 적중 {s['hit'] * 100:.0f}% t {s['t']:+.2f}  {ch}")
            else:
                print(f"    {pname} 사례 없음  {ch}")
        p = r["pooled"]
        if p["n"] > 1:
            print(f"    합침 사례 {p['n']} 초과 {pct(p['excess'])} 적중 {p['hit'] * 100:.0f}% t {p['t']:+.2f}  "
                  f"P1{'O' if p['P1'] else 'X'} P4{'O' if p['P4'] else 'X'}")
        e = r["exec"]
        print(f"    P5 실행 {etf}: 사례 {e['n']} 평균 {pct(e['mean']) if e['n'] else '-'} 비용 뒤 "
              f"{pct(e['net']) if e['n'] else '-'}  P5{'O' if e['P5'] else 'X'}   → {'통과' if r['pass'] else '탈락'}")
        k1, k2 = r["R12"]["kospi"], r["R12"]["spread"]
        if k1:
            print(f"    보고만 R1 KOSPI 평균 {pct(statistics.fmean(k1.values()))} · R2 코스닥−KOSPI {pct(statistics.fmean(k2.values()))}")
        lo, hi = r["R3"]["low"], r["R3"]["high"]
        print(f"    보고만 R3 기준 ≤{LOW_THRESHOLD_EOK}억 {lo[0]}해 {pct(lo[1])} · 그 외 {hi[0]}해 {pct(hi[1])}")
        f4 = r["R4"]
        print(f"    보고만 R4 개인 코스닥 순매수(창 5일 합) 평균 {f4['mean']:+,.0f}억 · 모든 창 {f4['base']:+,.0f}억 "
              f"(해 {len(f4['years'])})")
        if r["pass"]:
            passed.append(name)
    print("=" * 112)
    print(f"통과(앞·뒤 P2·P3 + P1 16년 + 합친 t ≥ {m['hurdle']:.2f} + P5 실행 ETF): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
