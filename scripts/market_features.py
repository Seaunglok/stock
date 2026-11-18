"""뉴스·경제 지표 일지 — 앞으로만 쌓고, 정해 둔 날 미리 정한 가설로 판정 (2026-11-16, 사전 선언).

운용자(11-16): "뉴스와 경제를 읽고, 수급량과 방향을 봐서 단기 대응" → "1, 2 번 진행해보자"의 2번(1번은 `lab_flows.py`).
과거 뉴스는 복원이 안 된다 → 시장 일지(`market_journal.py`, 11-06~)가 모으는 원자료에서 **매일 같은 정의로** 지표 한 줄을 만들어
`data/market_features/daily.csv` 에 쌓는다(판단 배치 15:50 — 시장 일지 close 뒤). 결과(KOSPI 수익)는 파일에 넣지 않고 판정 때 계산한다.

지표(그날 15:50 에 아는 것만)
  밤사이 미국   sox_chg · ixic_chg · spx_chg(등락 %) · vix · tnx(미국 10년물) · usdkrw — 아침 일지(미국 d−1 장)
  뉴스         news_n(아침+장중, 링크 기준 중복 제거) · neg_n · pos_n(제목에 NEG·POS 단어가 하나라도 있는 기사 수) ·
               neg_ratio = neg_n ÷ (neg_n + pos_n) · t_<주제>(market_journal.KEYWORDS 주제별 건수)
  공시·일정     dart_n(주요사항보고) · events(그날 일정 이름)
  잠정 수급     prelim_foreign(장 마감 잠정 외국인 억원 — 확정치는 수급 이력에)

가설 (선언 — 판정일 전엔 결과를 보지 않는다: 그 전 실행은 '해당 날 수'만 보여 준다)
  N1 밤사이 반도체(SOX)가 ±2% 이상 움직인 날, 그 방향이 한국 **장중**(KODEX200 시가→종가)에도 이어진다
     (시가 갭은 이미 가격에 들어가 있다 — 사고팔 수 있는 것은 시가 뒤다).
  N2 헤드라인 부정 비율이 높은 날(직전 20일 평균 + 1 표준편차 이상) 뒤 5일(다음 날 시가 → 6일째 시가, ^KS11)이 평소보다 약하다.
  N3 N2 이면서 장 마감 잠정 외국인이 순매도인 날 — 뒤 5일이 더 약하다.
판정일   기록 JUDGE_DAYS(120)거래일(2027-05 무렵). 그 전엔 판정하지 않고, 해당 날이 모자라면 기준을 낮추지 않고 미룬다.
통과     N1: 해당 날 ≥ 15 · 방향 적중 ≥ 60% · 방향 맞춘 평균 장중 수익 > 왕복 비용(2 × 11.5bp)
         N2·N3: 해당 날 ≥ 15 · 뒤 5일 평균이 기록 기간 전체 평균보다 0.5%p 이상 낮다 · 하락 적중 ≥ 기저율 + 10%p
통과하면  공격형 리그 앞으로만 기록 멤버 후보(실계좌 없음 — 11-10 결정). 규칙 기반 지표만 — AI 해설·감성 모델은 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io as AIO  # noqa: E402
import market_journal as MJ  # noqa: E402

FEATURES_FILE = _ROOT / "data" / "market_features" / "daily.csv"
NEG = ("급락", "폭락", "하락", "약세", "우려", "쇼크", "공포", "충격", "위기", "손실", "적자", "이탈", "경고", "둔화", "침체",
       "패닉", "추락", "급감", "부진", "리스크")
POS = ("급등", "폭등", "상승", "강세", "반등", "호조", "기대", "회복", "최고", "신고가", "흑자", "유입", "개선", "돌파", "랠리",
       "호재", "급증", "성장")
SOX_MOVE = 2.0
NEG_WIN = 20
NEG_Z = 1.0
H = 5
JUDGE_DAYS = 120
MIN_EVENTS = 15
N1_HIT = 0.60
N2_GAP_PCT = 0.5
N2_HIT_GAIN_PP = 10.0
OVERSEAS_COLS = {"^SOX": "sox_chg", "^IXIC": "ixic_chg", "^GSPC": "spx_chg"}
LEVEL_COLS = {"^VIX": "vix", "^TNX": "tnx", "USD/KRW": "usdkrw"}
COLS = (["date", "complete"] + list(OVERSEAS_COLS.values()) + list(LEVEL_COLS.values())
        + ["news_n", "neg_n", "pos_n", "neg_ratio", "dart_n", "prelim_foreign", "events"]
        + [f"t_{k}" for k in MJ.KEYWORDS])


# ── 지표 ────────────────────────────────────────────────────────────────────
def tone(titles: list[str]) -> tuple[int, int]:
    """(부정 단어가 하나라도 든 제목 수, 긍정 단어가 하나라도 든 제목 수)."""
    neg = sum(1 for t in titles if any(w in t for w in NEG))
    pos = sum(1 for t in titles if any(w in t for w in POS))
    return neg, pos


def features_for(day: str, journal_dir: Path = MJ.JOURNAL_DIR) -> dict | None:
    """그날 시장 일지 → 지표 한 줄. 일지가 없으면 None. 아침·장중 중 하나만 있으면 complete=0."""
    rec = MJ.load_day(day, journal_dir)
    m, c = rec.get("morning") or {}, rec.get("close") or {}
    if not m and not c:
        return None
    row: dict = {"date": day, "complete": int(bool(m) and bool(c))}
    ov = m.get("overseas") or {}
    for k, col in OVERSEAS_COLS.items():
        v = ov.get(k) or {}
        row[col] = None if v.get("chg_pct") is None else round(float(v["chg_pct"]), 3)
    for k, col in LEVEL_COLS.items():
        v = ov.get(k) or {}
        row[col] = None if v.get("close") is None else round(float(v["close"]), 3)
    seen, titles = set(), []
    for n in (m.get("news") or []) + (c.get("news") or []):
        key = n.get("link") or n.get("title")
        if key and key not in seen:
            seen.add(key)
            titles.append(str(n.get("title") or ""))
    neg, pos = tone(titles)
    row.update(news_n=len(titles), neg_n=neg, pos_n=pos,
               neg_ratio=None if neg + pos == 0 else round(neg / (neg + pos), 4),
               dart_n=len(c.get("dart") or []) if c else None)
    pf = ((c.get("flows_prelim") or {}).get("kospi") or {}).get("외국인")
    row["prelim_foreign"] = None if pf is None else float(pf)
    cal = m.get("calendar") or c.get("calendar") or []
    row["events"] = " · ".join(e.get("event", "") for e in cal if e.get("date") == day)
    for k in MJ.KEYWORDS:
        row[f"t_{k}"] = int((m.get("topics") or {}).get(k, 0)) + int((c.get("topics") or {}).get(k, 0))
    return row


def update(journal_dir: Path = MJ.JOURNAL_DIR, out: Path = FEATURES_FILE) -> int:
    """일지가 있는 모든 날을 다시 계산해 통째로 쓴다(작다 — 정의가 같으니 결과도 같다). 행 수."""
    rows = [r for p in sorted(journal_dir.glob("*.json")) if (r := features_for(p.stem, journal_dir))]
    AIO.write_csv(out, COLS, ({k: ("" if r.get(k) is None else r.get(k)) for k in COLS} for r in rows))
    return len(rows)


def load(path: Path = FEATURES_FILE) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _f(v) -> float | None:
    return None if v in (None, "") else float(v)


# ── 가설 해당 날 (결과 없이 셀 수 있다) ───────────────────────────────────────
def n1_days(rows: list[dict]) -> list[tuple[str, int]]:
    """(날짜, 방향 ±1) — 밤사이 SOX 가 ±SOX_MOVE% 이상."""
    out = []
    for r in rows:
        s = _f(r.get("sox_chg"))
        if s is not None and abs(s) >= SOX_MOVE:
            out.append((r["date"], 1 if s > 0 else -1))
    return out


def n2_days(rows: list[dict]) -> list[str]:
    """부정 비율이 직전 NEG_WIN 일 평균 + NEG_Z 표준편차 이상(그날까지의 값만)."""
    xs = [_f(r.get("neg_ratio")) for r in rows]
    out = []
    for k, r in enumerate(rows):
        prev = [x for x in xs[max(0, k - NEG_WIN):k] if x is not None]
        if xs[k] is None or len(prev) < NEG_WIN:
            continue
        sd = statistics.stdev(prev)
        if sd > 0 and xs[k] >= statistics.fmean(prev) + NEG_Z * sd:
            out.append(r["date"])
    return out


def n3_days(rows: list[dict]) -> list[str]:
    n2 = set(n2_days(rows))
    return [r["date"] for r in rows if r["date"] in n2 and (_f(r.get("prelim_foreign")) or 0) < 0]


# ── 판정 (JUDGE_DAYS 전엔 결과를 보지 않는다) ──────────────────────────────────
def judge(rows: list[dict], kodex: dict, kospi: dict, cost: float) -> dict:
    """N1~N3 판정. kodex/kospi = {날짜: {open, close}}."""
    days = [r["date"] for r in rows]
    kdays = sorted(kospi)
    fwd = {}
    for k, d in enumerate(kdays):
        if k + 1 + H < len(kdays):
            fwd[d] = kospi[kdays[k + 1 + H]]["open"] / kospi[kdays[k + 1]]["open"] - 1
    out = {}
    n1 = [(d, s) for d, s in n1_days(rows) if d in kodex and kodex[d].get("open")]
    got = [s * (kodex[d]["close"] / kodex[d]["open"] - 1) for d, s in n1]
    out["N1"] = {"n": len(got), "hit": (sum(x > 0 for x in got) / len(got)) if got else None,
                 "mean_pct": statistics.fmean(got) * 100 if got else None}
    out["N1"]["pass"] = bool(got) and len(got) >= MIN_EVENTS and out["N1"]["hit"] >= N1_HIT and \
        statistics.fmean(got) > 2 * cost
    base = [fwd[d] for d in days if d in fwd]
    for name, sel in (("N2", n2_days(rows)), ("N3", n3_days(rows))):
        x = [fwd[d] for d in sel if d in fwd]
        res = {"n": len(x)}
        if x and base:
            res.update(gap_pct=(statistics.fmean(x) - statistics.fmean(base)) * 100,
                       hit=sum(v < 0 for v in x) / len(x), base_hit=sum(v < 0 for v in base) / len(base))
            res["pass"] = len(x) >= MIN_EVENTS and res["gap_pct"] <= -N2_GAP_PCT and \
                (res["hit"] - res["base_hit"]) * 100 >= N2_HIT_GAIN_PP
        else:
            res["pass"] = False
        out[name] = res
    return out


def report(rows: list[dict], allow_judge: bool) -> str:
    n = len(rows)
    counts = f"N1 {len(n1_days(rows))}일 · N2 {len(n2_days(rows))}일 · N3 {len(n3_days(rows))}일"
    if n < JUDGE_DAYS or not allow_judge:
        return f"[market_features] 기록 {n}/{JUDGE_DAYS}거래일 — 판정 전(결과는 보지 않는다) · 해당 날 {counts}"
    import strategy_lab as L
    a, b = rows[0]["date"], rows[-1]["date"]
    res = judge(rows, L.load_bars("069500", a, b), L.load_bars("^KS11", a, "9999-12-31"), L.side_cost(False, False))
    return f"[market_features] 판정({n}거래일) " + " · ".join(f"{k} {'통과' if v['pass'] else '탈락'} {v}" for k, v in res.items())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", action="store_true", help=f"기록이 {JUDGE_DAYS}거래일 이상일 때만 판정한다")
    args = ap.parse_args()
    n = update()
    print(f"[market_features] {n}행 → {FEATURES_FILE}")
    print(report(load(), args.judge))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
