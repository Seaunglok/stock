"""공격형 리그 — 공격형 트랙 멤버를 주문 없이 매일 기록 (2026-10-28, 운용자 결정).

운용자(10-28): 공격형 트랙은 리그 그림자 기록 2주 → 운용자 승인 시 실계좌 50만원, 트랙 −30% 정지.
I3 리그(i3_shadow)와 따로 둔다 — I3 리그는 입장 조건(E1~E3)·정원·월 상한이 있고, 공격형은 잣대가 다르다
(최대 낙폭 30%·"3년 동안 계속 번다").

  멤버  ORB-B1 · ORB-B2 (lab_orb 5분 시가 범위 돌파, 10-29 부터 저장 분봉으로)
        FEAR-V1 · FEAR-V2 · FEAR-K1 · FEAR-K2 (lab_fear 공포 매수, 10-28 종가 판단 → 10-29 시가 첫 체결)
  조건  모두 50만원 출발. 판정은 각 lab 의 선언(ORB: 60영업일 누적>0·MDD≤30% / FEAR: lab_fear.verdict).

- **주문과 무관하다.** i3_decide.cmd 가 분봉 수집 뒤 실행(ORB 는 그날 분봉이 있어야 한다) — 실패해도 실전 판단·
  매매·I3 리그에 영향 없다. 멤버 하나가 실패해도 나머지는 기록한다.
- 결과: `data/aggr/shadow.json`(최신) · `data/aggr/history.csv`(일별 1행). 텔레그램 매일 한 줄.
- 그림자 최대 낙폭이 공격형 정지선(30%)을 처음 넘은 날 critical — 그 멤버는 실전 후보 자격을 잃는다(기록은 계속).
- ORB 는 분봉이 없는 거래일을 건너뛴다 → '분봉 없음'으로 따로 표시(조용히 빠지면 성적이 부풀거나 줄어든다).
  ORB 크기는 소수 주식 가정(lab_orb 그대로) — 정수 주식수 차이는 2주 점검 때 실체결로 확인한다.
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_fear as F  # noqa: E402
import lab_orb as B  # noqa: E402
import strategy_lab as L  # noqa: E402

DATA_DIR = _ROOT / "data" / "aggr"
SHADOW_FILE = DATA_DIR / "shadow.json"
HISTORY_FILE = DATA_DIR / "history.csv"
AFTER_CLOSE = dtime(15, 35)
EQUITY = F.F_EQUITY
STOP_PCT = F.F_MAX_MDD_PCT
KOSPI, VIX = "^KS11", "^VIX"
DAILY = (F.BASE, F.LONGS["2"], F.CASH)
MEMBERS = tuple(f"ORB-{v}" for v in B.VARIANTS) + F.MEMBERS


# ── 멤버 실행 ────────────────────────────────────────────────────────────────
def orb_run(variant: str, dates: list[str], upto: str, equity: float = EQUITY, replay=B.replay) -> dict:
    """B_START~upto 저장 분봉으로 날마다 lab_orb.orb_day. curve 첫 점 = ANCHOR(출발 자금)."""
    rows = replay(variant, B.B_START, upto)
    nav, curve = equity, [(F.ANCHOR, equity)]
    for d, r in rows:
        nav *= 1 + r["ret"]
        curve.append((d, nav))
    seen = {d for d, _ in rows}
    missing = [d for d in dates if B.B_START <= d <= upto and d not in seen]
    return {"curve": curve, "last": rows[-1] if rows else None, "missing": missing, "days": len(rows)}


def orb_verdict(curve: list[tuple[str, float]]) -> dict:
    n = max(0, len(curve) - 1)
    if n < B.B_JUDGE_DAYS:
        return {"judged": False, "why": f"기록 {n}/{B.B_JUDGE_DAYS}영업일"}
    vals = [v for _, v in curve]
    mdd = L.metrics([d for d, _ in curve], vals)["mdd"]
    checks = {"누적>0": vals[-1] > vals[0], f"MDD≤{B.B_MAX_MDD_PCT:g}%": mdd <= B.B_MAX_MDD_PCT}
    return {"judged": True, "pass": all(checks.values()), "checks": checks}


def _record(curve: list[tuple[str, float]], equity: float) -> dict:
    if not curve:
        return {"nav": round(equity), "ret": 0.0, "mdd": 0.0, "asof": None}
    vals = [v for _, v in curve]
    mdd = L.metrics([d for d, _ in curve], vals)["mdd"] if len(vals) > 1 else 0.0
    return {"nav": round(vals[-1]), "ret": round((vals[-1] / equity - 1) * 100, 3), "mdd": round(mdd, 3),
            "asof": curve[-1][0]}


def run_members(px: dict, upto: str, equity: float = EQUITY, replay=B.replay) -> dict:
    dates = L.calendar(px[F.BASE], F.ANCHOR, upto)
    out: dict[str, dict] = {}
    for v in B.VARIANTS:
        name = f"ORB-{v}"
        try:
            r = orb_run(v, dates, upto, equity, replay)
            last = r["last"]
            today = None
            if last and last[0] == upto:
                x = last[1]
                today = (f"{'인버스' if x['side'] == 'inv' else '롱'} {x['how']} {x['ret'] * 100:+.2f}%"
                         if "size" in x else x.get("why", "쉼"))
            out[name] = {**_record(r["curve"], equity), "days": r["days"], "missing": r["missing"],
                         "today": today, "verdict": orb_verdict(r["curve"])}
        except Exception as e:      # noqa: BLE001 — 한 멤버 실패가 리그 전체를 멈추지 않게
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    for name in F.MEMBERS:
        sig, lv = name[-2], name[-1]
        try:
            r = F.run(px, sig, lv, upto, F.ANCHOR, equity)
            out[name] = {**_record(r["curve"], equity), "entries": r["entries"], "held": len(r["held"]),
                         "on_today": r["on_today"],
                         "verdict": F.verdict(r["curve"], r["held"], px[F.BASE], r["dates"])}
        except Exception as e:      # noqa: BLE001
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    return out


def stop_alerts(models: dict, stopped: dict, upto: str) -> tuple[dict, list[str]]:
    """그림자 최대 낙폭이 정지선을 **처음** 넘은 멤버만 알린다(매일 반복하지 않는다)."""
    stopped = dict(stopped)
    msgs = []
    for n, v in models.items():
        if "mdd" in v and v["mdd"] > STOP_PCT and n not in stopped:
            stopped[n] = upto
            msgs.append(f"⛔ [공격형 리그] {n} 그림자 최대 낙폭 {v['mdd']:.1f}% > 정지선 {STOP_PCT:g}% — "
                        f"실전 후보 자격 상실(기록은 계속)")
    return stopped, msgs


def summary_line(rec: dict) -> str:
    rows = [(n, v) for n, v in rec["models"].items() if "ret" in v]
    rows.sort(key=lambda x: -x[1]["ret"])
    g = rec.get("gauges") or {}
    gauge = (f"VIX {g.get('vix')} · KOSPI 변동성 {g.get('kospi_vol')}%" if g else "")
    if rec["asof"] < B.B_START:
        plan = [n for n in F.MEMBERS if rec["models"].get(n, {}).get("on_today")]
        return (f"🥊 [공격형 리그] {rec['asof']} 기록 준비 — {B.B_START} 부터 · {gauge} · 내일 시가: "
                + (f"{', '.join(plan)} 매수" if plan else "공포 매수 없음(현금)")
                + " — 주문 없음")
    body = " · ".join(f"{n} {v['ret']:+.2f}%" + (f"[{v['today']}]" if v.get("today") else "")
                      + ("🔥" if v.get("on_today") else "") for n, v in rows)
    errs = [n for n, v in rec["models"].items() if "error" in v]
    miss = sorted({d for v in rec["models"].values() for d in v.get("missing", [])})
    tail = (f" · 오류 {', '.join(errs)}" if errs else "") + (f" · 분봉 없음 {', '.join(miss)}" if miss else "")
    return (f"🥊 [공격형 리그] {rec['asof']} (시작 {B.B_START}, 50만원) {gauge} | {body}{tail} "
            f"— 🔥=내일 공포 매수 보유 · 주문 없음")


def append_history(row: dict, path: Path = HISTORY_FILE) -> None:
    """같은 날짜 행은 바꿔 쓴다(하루 두 번 돌아도 1행)."""
    cols = ["date"] + [f"{n.lower()}_nav" for n in MEMBERS]
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            cols = cols + [c for c in (rd.fieldnames or []) if c not in cols]
            rows = [r for r in rd if r.get("date") != row["date"]]
    rows.append({k: row.get(k, "") for k in cols})
    rows.sort(key=lambda r: r["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


# ── 실행 ─────────────────────────────────────────────────────────────────────
async def _load(today: str) -> tuple[dict, dict]:
    """일봉: 장기 FDR + 최근·오늘 키움(실전·I3 리그와 같은 출처, 겹치는 날 대조). VIX 는 FDR 만."""
    import i3_live as LV
    from i3_shadow import audit_sources
    m = LV.KiwoomMarket()
    px, audit = {}, {}
    for c in DAILY + (KOSPI,):
        if c == KOSPI:
            hist, rec = await m.kospi_bars(), await m.recent("KOSPI")
        else:
            hist = L.load_bars(c, "2010-01-01", today)
            try:
                rec = await m.recent(c)
            except Exception:
                rec = {}
        audit[c] = audit_sources(hist, rec, today)
        px[c] = {**hist, **rec}
    px[VIX] = L.load_bars(VIX, "2010-01-01", today)
    return px, audit


async def main_async(now: datetime) -> int:
    import i3_live as LV
    from i3_shadow import AUDIT_TOL
    today = now.strftime("%Y-%m-%d")
    if today < F.ANCHOR:
        print(json.dumps({"skip": f"{F.ANCHOR} 전"}, ensure_ascii=False))
        return 0
    px, audit = await _load(today)
    base, kospi = px[F.BASE], px[KOSPI]
    upto = (today if now.time() >= AFTER_CLOSE and today in base and today in kospi
            else max(d for d in base if d < today))
    if upto < F.ANCHOR:
        print(json.dumps({"skip": f"{F.ANCHOR} 종가 전"}, ensure_ascii=False))
        return 0
    bad = {c: x for c, x in audit.items() if x is not None and x > AUDIT_TOL}
    prev = json.loads(SHADOW_FILE.read_text(encoding="utf-8")) if SHADOW_FILE.exists() else {}
    models = run_members(px, upto)
    stopped, msgs = stop_alerts(models, prev.get("stopped") or {}, upto)
    rec = {"asof": upto, "start": B.B_START, "equity": round(EQUITY), "gauges": F.gauges(px, upto),
           "models": models, "stopped": stopped,
           "audit": {c: (None if x is None else round(x, 6)) for c, x in audit.items()}, "audit_ok": not bad}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SHADOW_FILE)
    row = {"date": upto}
    for n, v in models.items():
        if "nav" in v:
            row[f"{n.lower()}_nav"] = v["nav"]
    append_history(row)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    if bad:
        await LV._notify("⛔ [공격형 리그] 데이터 출처 불일치 — 오늘 기록은 믿을 수 없다: "
                         + ", ".join(f"{c} {x:.2%}" for c, x in bad.items()), critical=True)
    await LV._notify(summary_line(rec))
    for text in msgs:
        await LV._notify(text, critical=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    return asyncio.run(main_async(datetime.now()))


if __name__ == "__main__":
    raise SystemExit(main())
