"""집중도 낮은 한국 지수 ETF 찾기 — 백로그 ㉖ (2026-11-19 선언 · 사실 조사 · 과거 판정 없음).

운용자(11-19): "㉖ 집중도 낮은 지수 ETF 찾기 진행해줘."
까닭: KODEX200 이 삼성전자 34.4% + SK하이닉스 23.8% = **58.1%**, IT 업종 62.1%(네이버 ETF 분석, 11-19 — 기사 62% 는 기준일 다름).
I3 엔진(−10% 이탈 · 20일 고점 재진입 · 낙폭 예산)은 2015~2025 의 넓은 KOSPI200 에서 검증됐는데 지금은 사실상 반도체 두
종목 타이밍이다(연 변동성 2015~2024 10~21% → 2026 67%). 같은 엔진을 **검증 때처럼 넓은 한국 시장 지수**에 쓰는 ETF 를 찾는다.
수익 찾기가 아니라 '검증한 시장'을 되찾는 구조 문제다.

규칙 1 때문에 — 과거 성적으로 고르지 않는다
  · 2026 국면을 보고 떠올린 것이고, 10-22 ETF 스크린(`docs_cache/lab/etf_screen_2026-10-22.json`)이 이 후보들의 과거를 이미 쟀다.
    같은 숫자로 다시 재지 않는다 → **고르기는 구조 사실(집중도·순자산·거래대금·지수 계열)로만**, 10-22 숫자는 보고만.
  · 고른 1개는 리그에 **앞으로만** 기록하는 안으로 운용자에게 올린다. 등록은 운용자 결정(입장 시험 대신 운용자 예외 — R6·D5a 처럼 ·
    정원 25 의 마지막 자리 · 11월 신규 3번째). 등록하면 그때 이름·신호·등록일을 따로 선언하고 시험 횟수 장부 +1.

선언 (측정 전, 2026-11-19 — 아래 상수를 본 뒤 고치면 이 조사는 무효)
  대상     FDR ETF/KR 현재 목록 · 분류 1(국내 시장지수) · EXCLUDE(레버리지·인버스 류) 제외 · 이름에 LOWCONC_KEYWORDS 하나.
           비교용 REFERENCE_NAMES(시가총액 가중 넓은 지수 — 후보 아님)도 같은 사실을 적는다.
  사실     네이버 ETF 분석: 상위 2종목 비중 합 · IT 업종 비중 · 기초지수 · 상장일 · 순자산 · 총보수.
           FDR 일봉: 최근 LIQ_DAYS 거래일 평균 거래대금(종가 × 거래량).
  자격     상위 2종목 합 ≤ MAX_TOP2 · 순자산 ≥ MIN_NAV(상장폐지선 50억의 2배) · 평균 거래대금 ≥ MIN_VALUE ·
           상장 ≤ LISTED_BY(낙폭 예산 252일 + 여유 — 리그 기록을 바로 시작할 수 있게).
  고르기   자격 통과 중 지수 계열 FAMILY_ORDER 앞쪽(0: 코스피200 전 종목을 동일가중·상한 등으로 — 검증한 종목군 그대로 ·
           1: 중형·중소형 같은 크기 구간 · 2: 그 밖) → 그 안에서 평균 거래대금 내림차순 1등.
           같은 지수를 따르는 ETF 끼리는 차이가 비용·체결뿐이라(10-22 §5-A) 거래대금이 맞는 기준이다.
  보고만   10-22 스크린의 그 ETF 행(강세장 2019~2026-08 I3·보유·MDD·미공개 2개월) — 고르기에 쓰지 않는다.

한계: 현재 상장 목록만(생존편향 — 고르기가 성적이 아니라 영향 작음). 네이버 응답은 공식 PDF 가 아니다(KRX 자료는 로그인 필요).
상위 10종목만 주므로 '상위 2종목 합'까지만 잰다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 선언 (측정 전) ────────────────────────────────────────────────────────────
ASOF = "2026-11-19"
BASE = "069500"                                   # KODEX 200 — 비교 기준
CATEGORY = 1                                      # FDR 분류 1 = 국내 시장지수
EXCLUDE = ("레버리지", "인버스", "2X", "3X", "곱버스", "울트라")     # = lab_etf_screen.EXCLUDE
LOWCONC_KEYWORDS = ("동일가중", "균등", "캡", "exTOP", "제외", "중소형", "중형", "소형")
REFERENCE_NAMES = ("KODEX 200", "KODEX KRX300", "TIGER 코스피", "KODEX 코스피100")
MAX_TOP2 = 20.0                                   # % — KODEX200 58% 의 1/3 아래
MIN_NAV = 100e8                                   # 원
MIN_VALUE = 1e8                                   # 원/일
LIQ_DAYS = 20
LISTED_BY = "2025-06-30"
# 지수 계열 — 기초지수 이름으로. 0: 코스피200 전 종목을 시총 말고 다르게 담는 것(검증한 종목군 그대로) ·
# 1: 크기 구간(대형주를 빼는 것 — 종목군이 달라진다) · 2: 그 밖
FAMILY_ORDER = (("코스피200 전 종목 · 비시총가중", ("동일", "균등", "캡", "Equal")),
                ("크기 구간(중형·중소형·소형)", ("중형", "중소형", "소형")),
                ("그 밖", ()))
SCREEN = _ROOT / "docs_cache" / "lab" / "etf_screen_2026-10-22.json"
OUT = _ROOT / "docs_cache" / "lab" / f"lowconc_etf_{ASOF}.json"
NAVER = "https://m.stock.naver.com/api/stock/{code}/etfAnalysis"


# ── 사실 조사 ────────────────────────────────────────────────────────────────
def won(s: str | None) -> float:
    """'20조 3,467억' · '512억' → 원."""
    if not s:
        return 0.0
    s = s.replace(",", "")
    jo = re.search(r"([\d.]+)\s*조", s)
    eok = re.search(r"([\d.]+)\s*억", s)
    return (float(jo.group(1)) * 1e12 if jo else 0.0) + (float(eok.group(1)) * 1e8 if eok else 0.0)


def pct(s: str | None) -> float:
    try:
        return float(str(s).replace("%", "").replace(",", ""))
    except ValueError:
        return float("nan")


def naver(code: str) -> dict:
    req = urllib.request.Request(NAVER.format(code=code), headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    top = j.get("etfTop10MajorConstituentAssets") or []
    sect = {x.get("detailTypeCode"): x.get("weight") for x in (j.get("sectorPortfolioList") or [])}
    return {"index": j.get("etfBaseIndex"), "listed": j.get("listedDate"), "nav": won(j.get("totalNav")),
            "fee": j.get("totalFee"), "top2": sum(pct(x.get("etfWeight")) for x in top[:2]),
            "top2_names": [x.get("itemName") for x in top[:2]], "it": sect.get("IT")}


def liquidity(code: str) -> float:
    import FinanceDataReader as fdr
    start = (date.fromisoformat(ASOF) - timedelta(days=60)).isoformat()
    df = fdr.DataReader(code, start, ASOF).tail(LIQ_DAYS)
    return float((df["Close"] * df["Volume"]).mean()) if len(df) else 0.0


def family(index_name: str | None) -> int:
    name = index_name or ""
    if "200" in name and any(k in name for k in FAMILY_ORDER[0][1]):
        return 0
    if any(k in name for k in FAMILY_ORDER[1][1]):
        return 1
    return 2


def eligible(r: dict) -> list[str]:
    """자격 미달 이유(빈 목록 = 통과)."""
    why = []
    if not r["top2"] <= MAX_TOP2:
        why.append(f"상위2 {r['top2']:.1f}%")
    if r["nav"] < MIN_NAV:
        why.append(f"순자산 {r['nav'] / 1e8:,.0f}억")
    if r["value"] < MIN_VALUE:
        why.append(f"거래 {r['value'] / 1e8:.2f}억/일")
    listed = f"{r['listed'][:4]}-{r['listed'][4:6]}-{r['listed'][6:8]}" if r.get("listed") else "9999"
    if listed > LISTED_BY:
        why.append(f"상장 {listed}")
    return why


def pick(rows: list[dict]) -> dict | None:
    ok = [r for r in rows if r["candidate"] and not r["why"]]
    ok.sort(key=lambda r: (family(r["index"]), -r["value"]))
    return ok[0] if ok else None


def screen_rows() -> dict[str, dict]:
    if not SCREEN.exists():
        return {}
    b = json.loads(SCREEN.read_text(encoding="utf-8"))["b"]
    return {r["code"]: {"tier": t, **{k: r.get(k) for k in ("first", "bull", "bh_bull", "ho", "train")}}
            for t in ("tier1", "tier2") for r in b.get(t, [])}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import FinanceDataReader as fdr
    lst = fdr.StockListing("ETF/KR")
    rows = []
    for e in lst.itertuples():
        name, code = str(e.Name), str(e.Symbol)
        if int(e.Category) != CATEGORY or any(k in name for k in EXCLUDE):
            continue
        cand = any(k in name for k in LOWCONC_KEYWORDS)
        if not cand and name not in REFERENCE_NAMES:
            continue
        try:
            r = {"code": code, "name": name, "candidate": cand, **naver(code), "value": liquidity(code)}
        except Exception as ex:                    # 사실을 못 읽으면 후보에서 뺀다(추측하지 않는다)
            r = {"code": code, "name": name, "candidate": cand, "error": f"{type(ex).__name__}: {ex}"[:120],
                 "index": None, "listed": None, "nav": 0.0, "fee": None, "top2": float("nan"), "it": None, "value": 0.0}
        r["why"] = eligible(r) if "error" not in r else ["조회 실패"]
        rows.append(r)
        time.sleep(0.3)
    chosen = pick(rows)
    prior = screen_rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"asof": ASOF, "rows": rows, "pick": chosen and chosen["code"]}, ensure_ascii=False,
                              default=str), encoding="utf-8")

    print(f"집중도 낮은 한국 지수 ETF — 사실 조사 {ASOF} (자격: 상위2 ≤ {MAX_TOP2:.0f}% · 순자산 ≥ {MIN_NAV / 1e8:.0f}억 · "
          f"거래 ≥ {MIN_VALUE / 1e8:.0f}억/일 · 상장 ≤ {LISTED_BY})")
    print(f"  {'코드':7}{'이름':24}{'상위2%':>7}{'IT%':>6}{'순자산억':>9}{'거래억/일':>9}{'보수%':>6}  {'상장':9} 기초지수 / 미달 이유")
    for r in sorted(rows, key=lambda r: (not r["candidate"], family(r["index"]), -r["value"])):
        mark = "▶" if chosen and r["code"] == chosen["code"] else ("·" if r["candidate"] else "참고")
        it = f"{r['it']:.0f}" if isinstance(r.get("it"), (int, float)) else "-"
        print(f"{mark:>4} {r['code']:7}{r['name'][:22]:24}{r['top2']:>7.1f}{it:>6}{r['nav'] / 1e8:>9,.0f}"
              f"{r['value'] / 1e8:>9.2f}{(r['fee'] or 0):>6.2f}  {str(r['listed'] or '')[:8]:9} "
              f"{r['index'] or r.get('error', '')} {'/ ' + ', '.join(r['why']) if r['why'] and r['candidate'] else ''}")
    print(f"\n고른 것: {chosen['code'] + ' ' + chosen['name'] if chosen else '없음'}")
    print("보고만 — 10-22 스크린이 이미 잰 숫자(고르기에 안 씀):")
    for r in rows:
        p = prior.get(r["code"])
        if p and (r["candidate"] or r["code"] == BASE):
            bull, bh, ho = p.get("bull") or {}, p.get("bh_bull") or {}, p.get("ho") or {}
            print(f"  {r['code']} {r['name'][:20]:22} {p['tier']}  강세장 I3 {bull.get('cagr', float('nan')):+.1f}%·MDD "
                  f"{bull.get('mdd', float('nan')):.1f}% · 보유 {bh.get('cagr', float('nan')):+.1f}% · 미공개 {ho.get('total', float('nan')):+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
