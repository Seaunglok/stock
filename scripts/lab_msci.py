"""MSCI 한국 지수 정기변경 종목 판정대 — 패시브 자금이 정해진 날 종가에 사고파는 종목을 미리 사고, 그날 판다 (2026-11-23, 사전 선언).

운용자(11-23) "종목판정대는 진행해줘" — 아이디어 장부 7번. 지수 수준(리뷰마다 한국 비중 변화)은 유료 자료뿐이라, 공개된 **종목 수준**으로.

왜 돈이 되나 (누가 손해를 보며 사고파나)
-----------------------------------------
  · MSCI 지수를 따라가는 패시브 펀드는 편입 종목을 **시행일 종가에** 사야 하고 편출 종목을 그날 종가에 팔아야 한다 — 값과 무관하게
    날짜에 맞춰. 발표(시행 약 2주 전)부터 그날까지 미리 사 둔 쪽이 패시브의 매수에 넘긴다(편입), 패시브가 싸게 던진 편출 종목은
    그 뒤 되돌아온다(편출). 손해를 보는 쪽은 날짜에 묶인 패시브 펀드(그 비용은 추종 오차로 투자자가 진다).
  · 문헌: Harris·Gurel 1986 · Shleifer 1986(S&P 500 편입 효과), Chen·Noronha·Singal 2004(편입·편출 비대칭), 이후 편입 효과가 크게
    줄었다는 보고(Patel·Welch 2017 'Extended Stock Returns in Response to S&P 500 Index Changes' 등) — **이미 사라졌을 수 있다. 그것까지 잰다.**
  · 이 프로젝트에서 잰 적 없음(11-23 확인). 개별 주식 매매라 지금 틀(ETF)과 다르다 — 통과해도 그림자 기록부터(운용자 결정).

자료 (선언 전에 본 것 — 이름·날짜·주가 자료 범위뿐, **수익률은 한 번도 보지 않았다**)
  · MSCI 공개 목록 `https://www.msci.com/eqb/gimi/stdindex/MSCI_{Feb|May|Aug|Nov}{YY}_STPublicList.pdf` 2012-02~2026-08 59개
    (`docs_cache/lab/msci/pdf/`, SHA256 `sha256.json` — © MSCI, 커밋하지 않는다). 발표일("Geneva, May 12, 2015")·시행일("as of the close
    of May 29, 2015")·「MSCI KOREA INDEX」 편입/편출. 뽑은 건수가 59개 모두 PDF 요약표의 한국 건수와 같다(11-23 확인).
  · 이름 → 코드 `lab_msci_map.MSCI_TO_CODE`(146개, OpenDART 영문 이름 후보 → 손으로 확인).
  · 주가 FDR(`strategy_lab.load_bars`, 끝 2026-09-30 고정 캐시) — **한국 종목은 최근 3,000거래일(2014-08-29~)만 준다** →
    2012-08~2014-05 리뷰는 주가가 없다. 상장폐지 종목(셀트리온헬스케어·CJ E&M·현대증권 등)은 자료가 있다. 2026 신규 상장 0126Z0 은 없다.

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  표본     발표일이 SAMPLE_FROM(2014-11-01) 이후인 리뷰. 주가가 창을 덮지 못하는 종목은 빼고 '뺀 것'으로 보고한다.
  시각     MSCI 는 발표일 미국 장 뒤(한국 다음 날 새벽)에 낸다 → **진입 = 발표일 다음 KRX 거래일 시가**.
           시행일 종가 = 시행일 이하 마지막 KRX 거래일 종가(한국 휴장이면 그 전 거래일).
  후보 (2개 — 방향은 구조에서 미리)
    M1 편입 앞 매수   편입 종목, 진입(발표 다음 날 시가) → 시행일 종가 매도 · 상승
    M2 편출 뒤 되돌림 편출 종목, 시행일 종가 매수 → 그 POST_DAYS(5)거래일 뒤 종가 매도 · 상승
  단위     **리뷰 하나 = 사례 하나**: 그 리뷰의 해당 종목들을 같은 금액씩 같은 날 사고판다 → 종목 초과 수익(종목 − 같은 창 KOSPI ^KS11)의
           단순 평균. 같은 리뷰 안의 종목은 같은 날 움직여 독립이 아니라서 종목 수로 세지 않는다.
  비용     주식 매수 편도 `side_cost(True, False)` + 매도 `side_cost(True, True)`(거래세 포함) — strategy_lab 가정 그대로.
  구간     앞 2014-11~2020-12 · 뒤 2021-01~2026-08(발표일로) — 둘 다.
  통과(전부)
    P1 표본  구간마다 리뷰 ≥ MIN_REVIEWS(10)
    P2 방향  구간마다 리뷰 평균 초과 수익 > 0
    P3 매매  구간마다 리뷰 평균 초과 수익 − 왕복 비용 > 0
    P4 유의  두 구간 합친 t = 평균 ÷ (표준편차 ÷ √n) ≥ `hurdle_t(total_through('scripts/lab_msci.py'))`(이 묶음 2개까지 107 → 약 3.50)
  보고만   종목 수 · 적중률(초과 > 0 인 리뷰 비율) · KOSPI 대신 KODEX200(069500) · M1 의 발표 전 20거래일 초과(미리 사는 쪽) ·
           M1 의 시행일 뒤 5일 초과(되돌림) · 뺀 이벤트 목록. 반대가 강해도 채택하지 않는다.
  통과하면 공격형 리그에 앞으로만(그림자 50만원 · 다음 리뷰 2027-02 부터) — 실계좌 없음(11-10). 개별 주식이라 운용자 결정 먼저.

결과 (20f93c1 선언대로 1회, 기준 수정 없음 — 리뷰 59개 중 표본 2014-11~, 왕복 비용 0.43%) — **통과 없음**
  시험 107개 → 통과선 t ≥ 3.50.
        후보              구간  리뷰(종목)  평균 초과%  비용 뒤%  적중     t    P1 P2 P3
  M1 편입 앞 매수        앞   17 (40)     +3.64     +3.21   53%  +1.21   O  O  O
                         뒤   19 (45)     +0.35     −0.08   53%  +0.17   O  O  X   합침 36 · +1.91 · t +1.07 → 탈락
  M2 편출 뒤 되돌림      앞   15 (35)     −2.61     −3.04   27%  −1.74   O  X  X
                         뒤   20 (77)     +2.03     +1.60   70%  +1.67   O  O  O   합침 35 · +0.04 · t +0.04 → 탈락
  (KODEX200 대비도 같다: M1 +1.90 · t 1.07 / M2 −0.05) · 뺀 이벤트 2(0126Z0 삼성에피스홀딩스 — 자료 없음)
  보고만   편입 발표 **전** 20거래일 초과 +4.14%(앞 +7.02 · 뒤 +1.57, t 1.57) · 편입 시행일 **뒤** 5일 초과 −3.29%(앞 −2.28 · 뒤 −4.20, t −2.57)
읽는 법
  · **편입 효과는 발표 전에 대부분 끝나고(미리 사는 쪽이 가져간다), 발표 뒤 남은 몫은 2021 이후 비용만큼도 안 남았다.** 2014~2020 의
    +3.6% 도 적중 53%·t 1.21 — 몇 종목이 크게 오른 평균이다. 알려진 효과가 줄어드는 모양(Patel·Welch 2017) 그대로.
  · 편출 되돌림은 시대에 따라 **뒤집혔다**(2014~2020 은 더 빠지고 2021~ 은 되돌림 70%) — 수급 판정대 S1(외국인 극단 매도)과 같은 모양.
  · 가장 꾸준한 건 '편입 시행일 뒤 되밀림'(두 구간 모두 −) — 패시브가 시행일 종가에 산 값이 비쌌다. 공매도를 못 하니 매매로는
    못 쓰고, 표를 보고 본 것이라 판정하지 않는다(아이디어 장부에 기록만). 다시 재지 않는다.
"""
from __future__ import annotations

import bisect
import contextlib
import io
import json
import math
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_msci_map as M  # noqa: E402
import lab_trials as T  # noqa: E402
import strategy_lab as L  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
DECLARED_ON = "2026-11-23"
SOURCE = "scripts/lab_msci.py"
PDF_DIR = _ROOT / "docs_cache" / "lab" / "msci" / "pdf"
PRICE_RANGE = ("2014-06-01", "2026-09-30")
SAMPLE_FROM = "2014-11-01"
PERIODS = {"앞": ("2014-11-01", "2020-12-31"), "뒤": ("2021-01-01", "2026-08-31")}
POST_DAYS = 5
PRE_DAYS = 20                                    # 보고만
MIN_REVIEWS = 10
BENCH, BENCH2 = "^KS11", "069500"
CANDIDATES = {"M1": ("편입 앞 매수(발표 다음 날 시가 → 시행일 종가)", "add"),
              "M2": ("편출 뒤 되돌림(시행일 종가 → 5거래일 뒤 종가)", "del")}
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def round_trip() -> float:
    return L.side_cost(True, False) + L.side_cost(True, True)


def trials() -> int:
    return T.total_through(SOURCE)


def hurdle() -> float:
    return T.hurdle_t(trials())


# ── 목록 PDF 읽기 ────────────────────────────────────────────────────────────
def _date(s: str) -> str:
    return datetime.strptime(re.sub(r"\s+", " ", s.strip()), "%B %d, %Y").date().isoformat()


def parse_text(t: str) -> dict:
    """목록 글자(layout) → {announced, effective, add, del}. 한국 절이 없으면 빈 목록(그 리뷰엔 한국 변경 없음)."""
    ann = re.search(rf"(?:Geneva|New York|London)[^,\n]*,\s*((?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}})", t)
    eff = re.search(rf"as of the close of\s*((?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}})", t, re.S)
    if not ann or not eff:
        raise ValueError("발표일·시행일을 못 찾았다")
    lines = t.splitlines()
    adds, dels = [], []
    k = next((i for i, l in enumerate(lines) if re.search(r"MSCI\s+KOREA\s+INDEX", l)), None)
    if k is not None:
        hdr = next(i for i in range(k + 1, min(k + 4, len(lines))) if "Additions" in lines[i] and "Deletions" in lines[i])
        col = lines[hdr].index("Deletions")
        for l in lines[hdr + 1:]:
            if re.search(r"MSCI\s+[A-Z ]+INDEX", l) or re.match(r"\s*(EUROPE|AMERICAS)", l):
                break
            if not l.strip() or re.match(r"\s*Page \d", l):
                continue
            a, d = l[:col].strip(), l[col:].strip()
            if a and a != "None":
                adds.append(a)
            if d and d != "None":
                dels.append(d)
    return {"announced": _date(ann.group(1)), "effective": _date(eff.group(1)), "add": adds, "del": dels}


def load_reviews(pdf_dir: Path = PDF_DIR) -> dict[str, dict]:
    from pypdf import PdfReader
    out = {}
    for p in sorted(pdf_dir.glob("*.pdf")):
        t = "\n".join((pg.extract_text(extraction_mode="layout") or "") for pg in PdfReader(str(p)).pages)
        out[p.stem] = parse_text(t)
    return out


# ── 창 (순수 함수 — 거래일 목록만 본다) ─────────────────────────────────────
def first_after(days: list[str], d: str) -> int | None:
    k = bisect.bisect_right(days, d)
    return k if k < len(days) else None


def last_on_or_before(days: list[str], d: str) -> int | None:
    k = bisect.bisect_right(days, d) - 1
    return k if k >= 0 else None


def window(days: list[str], rev: dict, cand: str) -> tuple[tuple[int, str], tuple[int, str]] | None:
    """((진입 위치, 'open'|'close'), (청산 위치, 'close')) — 자료 밖이면 None."""
    e = last_on_or_before(days, rev["effective"])
    if e is None:
        return None
    if cand == "M1":
        a = first_after(days, rev["announced"])
        return None if a is None or a > e else ((a, "open"), (e, "close"))
    if cand == "M2":
        return None if e + POST_DAYS >= len(days) else ((e, "close"), (e + POST_DAYS, "close"))
    if cand == "PRE":                                                     # 보고만: 발표 전 20거래일(종가 → 발표일 종가)
        a = last_on_or_before(days, rev["announced"])
        return None if a is None or a - PRE_DAYS < 0 else ((a - PRE_DAYS, "close"), (a, "close"))
    if cand == "AFTER":                                                   # 보고만: 편입 시행일 뒤 5일
        return None if e + POST_DAYS >= len(days) else ((e, "close"), (e + POST_DAYS, "close"))
    raise KeyError(cand)


def ret(bars: dict, days: list[str], w) -> float | None:
    (i, fi), (j, fj) = w
    a, b = bars.get(days[i], {}).get(fi), bars.get(days[j], {}).get(fj)
    return (b / a - 1) if a and b else None


def review_excess(rev: dict, side: str, cand: str, px: dict[str, dict], days: list[str], bench: dict) -> dict:
    """리뷰 하나 — 해당 종목들의 초과 수익 평균(같은 날 같은 금액). 뺀 종목은 'skipped'."""
    w = window(days, rev, cand)
    names = rev[side]
    if w is None or not names:
        return {"n": 0, "skipped": list(names)}
    rb = ret(bench, days, w)
    xs, skipped = [], []
    for n in names:
        code = M.MSCI_TO_CODE.get(n)
        r = ret(px.get(code, {}), days, w) if code else None
        if r is None or rb is None:
            skipped.append(n)
            continue
        xs.append(r - rb)
    return {"n": len(xs), "excess": statistics.fmean(xs) if xs else None, "skipped": skipped,
            "entry": days[w[0][0]], "exit": days[w[1][0]]}


def tstat(xs: list[float]) -> float:
    return statistics.fmean(xs) / (statistics.stdev(xs) / math.sqrt(len(xs))) if len(xs) > 1 and statistics.stdev(xs) > 0 \
        else float("nan")


def judge(reviews: dict[str, dict], cand: str, px: dict, days: list[str], bench: dict, h: float, cost: float) -> dict:
    side = CANDIDATES[cand][1] if cand in CANDIDATES else "add"
    per = {}
    for tag, rev in sorted(reviews.items(), key=lambda kv: kv[1]["announced"]):
        if rev["announced"] < SAMPLE_FROM or not rev[side]:
            continue
        per[tag] = {**review_excess(rev, side, cand, px, days, bench), "announced": rev["announced"]}
    out, pooled, ok = {"reviews": per, "periods": {}}, [], True
    for pname, (a, b) in PERIODS.items():
        xs = [r["excess"] for r in per.values() if r["n"] and a <= r["announced"] <= b]
        s = {"n": len(xs)}
        if xs:
            m = statistics.fmean(xs)
            s.update(mean=m, net=m - cost, hit=sum(x > 0 for x in xs) / len(xs), t=tstat(xs),
                     stocks=sum(r["n"] for r in per.values() if r["n"] and a <= r["announced"] <= b))
        s["checks"] = {"P1": len(xs) >= MIN_REVIEWS, "P2": bool(xs) and s["mean"] > 0, "P3": bool(xs) and s["net"] > 0}
        ok &= all(s["checks"].values())
        out["periods"][pname] = s
        pooled += xs
    t = tstat(pooled)
    out["pooled"] = {"n": len(pooled), "mean": statistics.fmean(pooled) if pooled else float("nan"), "t": t,
                     "P4": len(pooled) > 1 and t >= h}
    out["pass"] = ok and out["pooled"]["P4"]
    out["skipped"] = sorted({(tag, n) for tag, r in per.items() for n in r["skipped"]})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reviews = load_reviews()
    codes = sorted({M.MSCI_TO_CODE[n] for r in reviews.values() for n in r["add"] + r["del"] if n in M.MSCI_TO_CODE})
    px = {}
    with contextlib.redirect_stdout(io.StringIO()):
        bench = L.load_bars(BENCH, *PRICE_RANGE)
        bench2 = L.load_bars(BENCH2, *PRICE_RANGE)
        for c in codes:
            try:
                px[c] = L.load_bars(c, *PRICE_RANGE)
            except Exception:              # noqa: BLE001 — 자료 없는 종목은 '뺀 것'으로 보고
                px[c] = {}
    days = sorted(d for d in bench if bench[d].get("close"))
    h, cost = hurdle(), round_trip()
    pct = lambda x: f"{x * 100:+.2f}"   # noqa: E731
    print("=" * 110)
    print(f"MSCI 한국 지수 정기변경 판정대 — 리뷰 {len(reviews)}개(표본 {SAMPLE_FROM}~) · 왕복 비용 {cost * 100:.2f}% · "
          f"시험 {trials()}개 → 통과선 t ≥ {h:.2f}")
    passed = []
    for cand, (desc, _) in CANDIDATES.items():
        r = judge(reviews, cand, px, days, bench, h, cost)
        print(f"\n  {cand} {desc}")
        for pname, s in r["periods"].items():
            ch = " ".join(f"{k}{'O' if v else 'X'}" for k, v in s["checks"].items())
            if s["n"]:
                print(f"    {pname} 리뷰 {s['n']:>2}(종목 {s['stocks']}) 평균 초과 {pct(s['mean'])} 비용 뒤 {pct(s['net'])} "
                      f"적중 {s['hit'] * 100:.0f}% t {s['t']:+.2f}  {ch}")
            else:
                print(f"    {pname} 리뷰 0  {ch}")
        p = r["pooled"]
        print(f"    합침 리뷰 {p['n']} 평균 {pct(p['mean'])} t {p['t']:+.2f} P4{'O' if p['P4'] else 'X'} → "
              f"{'통과' if r['pass'] else '탈락'}")
        r2 = judge(reviews, cand, px, days, bench2, h, cost)
        print(f"    보고만 KODEX200 대비: 합침 평균 {pct(r2['pooled']['mean'])} t {r2['pooled']['t']:+.2f}")
        print(f"    뺀 이벤트 {len(r['skipped'])}: {', '.join(f'{a}:{b}' for a, b in r['skipped'][:12])}")
        if r["pass"]:
            passed.append(cand)
    for extra, desc in (("PRE", "편입 발표 전 20거래일(미리 사는 쪽)"), ("AFTER", "편입 시행일 뒤 5일(되돌림)")):
        r = judge(reviews, extra, px, days, bench, h, cost)
        p = r["pooled"]
        print(f"\n  보고만 {desc}: 리뷰 {p['n']} 평균 초과 {pct(p['mean'])} t {p['t']:+.2f} · "
              + " · ".join(f"{k} {pct(s['mean'])}" for k, s in r["periods"].items() if s["n"]))
    print("=" * 110)
    print(f"통과(앞·뒤 P1~P3 + 합친 t ≥ {h:.2f}): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
