"""한국 상장 ETF 전수 스크린 — I3 를 다른 ETF 에 쓰면 KODEX200 보다 나은가 (2026-10-22, 탐색).

운용자: "KODEX200 으로 진행하고, 다른 ETF 는 없는지 찾아봐줘."
운용은 KODEX200 I3 그대로다. 이 스크립트는 **찾아보기**이고 채택 절차가 아니다.

⚠️ 수백 개 중 1등은 운만으로도 좋아 보인다(다중 비교). 그래서 아래 규칙을 **결과를 보기 전에** 상수로
선언·커밋한다. 결과를 본 뒤 대상·순위 규칙·'더 낫다'의 정의를 고치면 이 스크린은 무효다.

선언 (측정 전, 2026-10-22)
--------------------------
A. 같은 지수(KOSPI200)를 따라가는 ETF — 규칙은 같고 **보수·추적오차만** 다르다. 공통 기간 그냥 보유
   연 수익 차이(= 실질 비용 차이)와 거래대금을 본다. 데이터 선택이 아니라 비용 비교라 다중 비교 문제 없음.
B. 주식형 ETF 전체에 I3 — 대상: FDR ETF/KR 현재 목록 중 분류 1(국내 시장지수)·2(국내 업종/테마)·
   4(해외 주식), 이름에 EXCLUDE 키워드가 있는 것(레버리지·인버스 류) 제외.
   - 1군: LISTED_BY_FULL 이전 상장 → strategy_lab 잣대 ①②③④ 전부(학습 구간 FULL).
   - 2군: LISTED_BY_BULL 이전 상장 → 강세장 구간(2019~2026-08)만, ①② + 그냥 보유 대비.
   - I3 는 기본값(H.I3_DEFAULT) 그대로. 재진입 추세 확인: 국내(1·2)=KOSPI>MA120(운용과 같음),
     해외(4)=자기 가격 MA120. 현금=KODEX 단기채권(153130). 예탁=EQUITY(운용 투입).
   - 세금: 해외(4)는 매매차익 15.4% 과세 → 순위는 **세후 근사**(연 수익 × TAX_KEEP_FOREIGN)로 매긴다.
     (모든 이익이 매년 실현·과세된다고 본 보수적 근사.) 국내 주식형은 매매차익 비과세.
   - 순위: 학습 구간 ①② 통과 → 세후 근사 연 수익 내림차순. 상위 TOP_K 와 KODEX200 I3 를 함께 출력.
   - 'KODEX200 I3 보다 낫다'(BEATS) = 학습 ①② 통과 AND 세후 근사 연 수익 > KODEX200 I3
     AND 미공개 구간(HOLDOUT) 수익 ≥ KODEX200 I3 의 미공개 수익 AND HO③.
     학습 순위가 미공개 2개월에도 이어졌나가 '실력이냐 운이냐'의 1차 신호다(2개월이라 약한 신호).
C. 현금 자리(KODEX 단기채권) 대안 — 분류 6·7 중 CASH_KEYWORDS 이름. 상장 이후 공통 기간에
   153130 대비 연 수익 차이·최대 낙폭·최악 20일 수익을 본다.

한계: 현재 상장 목록만 있다(상장폐지 ETF 누락 = 생존편향). 가격은 FDR 수정주가(분배금 반영, 10-22 확인:
KODEX200/200TR 비율 9년간 0.360→0.362). 해외 ETF 는 환노출.
"""
from __future__ import annotations

import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import lab_holdout as H  # noqa: E402

# ── 선언 (결과를 보기 전) ──────────────────────────────────────────────────────
END = L.HOLDOUT[1]                       # 2026-10-21
EQUITY = 3_640_000.0                     # 운용 투입(예탁 − I3 외 보유) ≈ 364만원
BASE, CASH = "069500", "153130"
CATEGORIES = {1: "국내지수", 2: "국내업종", 4: "해외"}
EXCLUDE = ("레버리지", "인버스", "2X", "3X", "곱버스", "울트라")
LISTED_BY_FULL = "2015-01-30"            # 학습 시작(2015-07-28) 전 ~120영업일 이력
LISTED_BY_BULL = "2018-07-31"            # 강세장 시작(2019-01-02) 전 ~100영업일 이력
BULL = L.PERIODS["강세장"]
TAX_KEEP_FOREIGN = 1 - 0.154
TOP_K = 10
KOSPI200_NAMES = ("200", "200TR")        # A: 이름이 '<운용사> 200' 또는 '<운용사> 200TR' 인 것
CASH_KEYWORDS = ("단기채", "단기통안", "CD금리", "KOFR", "머니마켓", "초단기", "SOFR")
WORKERS = 6

_OUT = _ROOT / "docs_cache" / "lab" / "etf_screen_2026-10-22.json"


def _listing() -> list[dict]:
    import FinanceDataReader as fdr
    df = fdr.StockListing("ETF/KR")
    return [{"code": str(r.Symbol), "cat": int(r.Category), "name": str(r.Name),
             "amount": float(r.Amount or 0)} for r in df.itertuples()]


def _load_all(codes: list[str]) -> dict[str, dict]:
    def one(c):
        try:
            return c, L.load_bars(c, "2014-01-01", END)
        except Exception:
            return c, {}
    # load_bars 의 redirect_stdout 은 프로세스 전역이라 스레드가 겹치면 sys.stdout 이 StringIO 로
    # 남을 수 있다 — 끝나면 원래 것으로 되돌린다.
    real = sys.stdout
    try:
        with ThreadPoolExecutor(WORKERS) as ex:
            return dict(ex.map(one, codes))
    finally:
        sys.stdout = real


def _i3(code: str, bars: dict, regime: dict, cash: dict, dates: list[str]) -> L.SimResult:
    return L.simulate({code: L.Asset(code, bars), CASH: L.Asset(CASH, cash)}, dates,
                      H.i3(bars, regime, code, CASH, *H.I3_DEFAULT), EQUITY, pass_nav=True)


def _cagr_diff(a: dict, b: dict) -> tuple[str, float, int]:
    """공통 기간 그냥 보유 연 수익 차이(a − b, %p) — 종가 기준."""
    common = sorted(set(a) & set(b))
    n = len(common)
    ca = (a[common[-1]]["close"] / a[common[0]]["close"]) ** (252 / n) - 1
    cb = (b[common[-1]]["close"] / b[common[0]]["close"]) ** (252 / n) - 1
    return common[0], (ca - cb) * 100, n


def section_a(etfs: list[dict], bars: dict) -> list[dict]:
    rows = []
    for e in etfs:
        parts = e["name"].split()
        if e["cat"] != 1 or len(parts) != 2 or parts[1] not in KOSPI200_NAMES or not bars.get(e["code"]):
            continue
        since, diff, n = _cagr_diff(bars[e["code"]], bars[BASE])
        rows.append({**e, "since": since, "diff_pp": diff, "days": n})
    return sorted(rows, key=lambda r: -r["diff_pp"])


def section_b(etfs: list[dict], bars: dict, kospi: dict) -> dict:
    cash = bars[CASH]
    base_dates = L.calendar(bars[BASE], L.FULL[0], END)
    base_i3 = _i3(BASE, bars[BASE], kospi, cash, [d for d in base_dates if d in cash])
    bench = L.buy_and_hold(BASE, base_dates, bars[BASE], EQUITY)
    ref = {"train": L.slice_metrics(base_i3, *L.FULL), "bull": L.slice_metrics(base_i3, *BULL),
           "ho": L.slice_metrics(base_i3, *L.HOLDOUT)}
    tier1, tier2 = [], []
    for e in etfs:
        b = bars.get(e["code"]) or {}
        if e["cat"] not in CATEGORIES or any(k in e["name"] for k in EXCLUDE) or not b or e["code"] == BASE:
            continue
        first = min(b)
        if first > LISTED_BY_BULL:
            continue
        regime = kospi if e["cat"] in (1, 2) else b
        dates = [d for d in base_dates if d in b and d in cash]
        if len(dates) < 500:
            continue
        res = _i3(e["code"], b, regime, cash, dates)
        bh = L.buy_and_hold(e["code"], dates, b, EQUITY)
        keep = TAX_KEEP_FOREIGN if e["cat"] == 4 else 1.0
        row = {**e, "first": first, "ho": L.slice_metrics(res, *L.HOLDOUT),
               "bull": L.slice_metrics(res, *BULL), "bh_bull": L.slice_metrics(bh, *BULL), "keep": keep}
        if first <= LISTED_BY_FULL:
            s, bm, rows = L.evaluate(res, bench)
            row.update(train=s["전체"], box=s["박스권"], judge=[(n, ok) for n, ok, _ in rows],
                       bh_train=L.slice_metrics(bh, *L.FULL))
            row["p12"] = rows[0][1] and rows[1][1]
            row["cagr_at"] = s["전체"]["cagr"] * keep
            row["beats"] = (row["p12"] and row["cagr_at"] > ref["train"]["cagr"]
                            and row["ho"]["total"] >= ref["ho"]["total"]
                            and row["ho"]["total"] >= L.HO_MIN_RET_PCT)
            tier1.append(row)
        else:
            bm = row["bull"]
            row["p12"] = bm["mdd"] <= L.MAX_MDD_PCT and bm["worst_year"] >= L.MIN_YEAR_RET_PCT
            row["cagr_at"] = bm["cagr"] * keep
            tier2.append(row)
    key = lambda r: (not r["p12"], -r["cagr_at"])  # noqa: E731
    return {"ref": ref, "bench_train": L.slice_metrics(bench, *L.FULL),
            "tier1": sorted(tier1, key=key), "tier2": sorted(tier2, key=key)}


def section_c(etfs: list[dict], bars: dict) -> list[dict]:
    cash = bars[CASH]
    rows = []
    for e in etfs:
        b = bars.get(e["code"]) or {}
        if e["cat"] not in (6, 7) or not any(k in e["name"] for k in CASH_KEYWORDS) or not b or e["code"] == CASH:
            continue
        common = sorted(set(b) & set(cash))
        if len(common) < 120:
            continue
        since, diff, n = _cagr_diff(b, cash)
        cur = [b[d]["close"] for d in common]
        peak, mdd = cur[0], 0.0
        for v in cur:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak * 100)
        worst20 = min((cur[i] / cur[i - 20] - 1) * 100 for i in range(20, len(cur)))
        own = (cur[-1] / cur[0]) ** (252 / n) * 100 - 100
        rows.append({**e, "since": since, "days": n, "cagr": own, "diff_pp": diff, "mdd": mdd, "worst20": worst20})
    return sorted(rows, key=lambda r: -r["diff_pp"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    etfs = _listing()
    want = [e["code"] for e in etfs
            if (e["cat"] in CATEGORIES and not any(k in e["name"] for k in EXCLUDE))
            or (e["cat"] in (6, 7) and any(k in e["name"] for k in CASH_KEYWORDS))]
    bars = _load_all(sorted(set(want) | {BASE, CASH}))
    kospi = L.load_bars("^KS11", "1996-01-01", END)
    a, b, c = section_a(etfs, bars), section_b(etfs, bars, kospi), section_c(etfs, bars)

    print("=" * 100)
    print("[A] KOSPI200 추종 ETF — 공통 기간 그냥 보유 연 수익 차이(KODEX200 대비, = 실질 비용 차이)")
    for r in a:
        print(f"  {r['name']:16}{r['code']:>8}  {r['since']}~  {r['diff_pp']:+.2f}%p/년  거래대금 {r['amount']:>9,.0f}백만")

    ref = b["ref"]
    print("=" * 100)
    print(f"[B-1군] {LISTED_BY_FULL} 이전 상장 {len(b['tier1'])}개 — 학습 2015-07~2026-08 · 미공개 08-25~10-21")
    print(f"  기준: KODEX200 I3 연 {ref['train']['cagr']:.1f}% · MDD {ref['train']['mdd']:.1f}% · "
          f"최악 {ref['train']['worst_year']:+.1f}% · 미공개 {ref['ho']['total']:+.1f}% "
          f"| KODEX200 보유 연 {b['bench_train']['cagr']:.1f}%")
    print(f"  ①② 통과 {sum(r['p12'] for r in b['tier1'])}개 · 전부 통과(①②③④) "
          f"{sum(all(ok for _, ok in r['judge']) for r in b['tier1'])}개 · BEATS {sum(r['beats'] for r in b['tier1'])}개")
    hdr = f"  {'#':>3} {'ETF':28}{'분류':>5}{'연수익':>7}{'세후≈':>7}{'MDD':>6}{'최악':>7}{'박스':>6}{'강세':>6}{'미공개':>7}{'보유':>6}  판정"
    print(hdr)
    for i, r in enumerate(b["tier1"][:TOP_K], 1):
        t = r["train"]
        marks = "".join("O" if ok else "x" for _, ok in r["judge"])
        print(f"  {i:>3} {r['name'][:26]:28}{CATEGORIES[r['cat']]:>5}{t['cagr']:>6.1f}%{r['cagr_at']:>6.1f}%"
              f"{t['mdd']:>5.1f}%{t['worst_year']:>+6.1f}%{r['box']['cagr']:>5.1f}%{r['bull']['cagr']:>5.1f}%"
              f"{r['ho']['total']:>+6.1f}%{r['bh_train']['cagr']:>5.1f}%  {marks}{' ★BEATS' if r['beats'] else ''}")
    print("=" * 100)
    print(f"[B-2군] {LISTED_BY_FULL}~{LISTED_BY_BULL} 상장 {len(b['tier2'])}개 — 강세장 2019~2026-08 만 "
          f"(KODEX200 I3 강세장 연 {ref['bull']['cagr']:.1f}%·MDD {ref['bull']['mdd']:.1f}%)")
    for i, r in enumerate(b["tier2"][:TOP_K], 1):
        m = r["bull"]
        print(f"  {i:>3} {r['name'][:26]:28}{CATEGORIES[r['cat']]:>5}{m['cagr']:>6.1f}%{r['cagr_at']:>6.1f}%"
              f"{m['mdd']:>5.1f}%{m['worst_year']:>+6.1f}%  보유 {r['bh_bull']['cagr']:.1f}%  "
              f"미공개 {r['ho']['total']:+.1f}%  {'①②O' if r['p12'] else '①②x'}")
    print("=" * 100)
    print("[C] 현금 자리 대안 — KODEX 단기채권(153130) 대비, 공통 기간")
    for r in c:
        print(f"  {r['name'][:30]:32}{r['code']:>8}  {r['since']}~ 연 {r['cagr']:.2f}% ({r['diff_pp']:+.2f}%p)"
              f"  MDD {r['mdd']:.2f}%  최악20일 {r['worst20']:+.2f}%  거래대금 {r['amount']:,.0f}백만")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps({"a": a, "b": b, "c": c}, ensure_ascii=False, default=str), encoding="utf-8")
    med = statistics.median(r["train"]["cagr"] for r in b["tier1"]) if b["tier1"] else 0.0
    print(f"\n1군 I3 연 수익 중앙값 {med:.1f}% · 결과 저장 {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
