"""I3 도전자 리그 — 챔피언(실전 I3)과 도전자들을 매일 같은 조건으로 기록하고, 선언된 승격 규칙으로 판정한다.

운용자(10-22): "매일매일 발전해야지, 계속 그대로이면 안 된다. 안정적으로 벌 수 있는 구조를 만들어야 한다."
발전을 '매일 코드를 고치는 것'으로 하면 과거 데이터 끼워 맞추기가 된다(추세추종의 교훈). 대신:

    연구(사전선언·백테스트) ──통과·유망──▶ 도전자 등록(주문 없음) ──매일 새 데이터로 기록──▶
    승격 규칙(아래, 측정 전 선언) 충족 ──▶ 텔레그램 '승격 후보' ──운용자 승인──▶ 실전(i3_core 교체 + 대조 테스트)

- **주문과 무관하다.** 별도 프로세스(i3_decide.cmd 가 판단 뒤 실행) — 실패해도 실전 판단·매매에 영향 없다.
- 모든 모델이 실전과 같은 조건: 엔진은 2015-07-28 부터 재생(i3_core 와 같음), 낙폭 예산은 **실전 시작일**
  (state navs[0]) 자산으로 새로 시작, 체결은 다음 날 시가(모델), 현금 자리는 i3_core.CASH.
- 챔피언 모델(I3)은 실계좌의 기준선이기도 하다(모델 − 실계좌 = 체결 괴리·정수 주식수·예수금 잔돈).
- 결과: `data/i3/shadow.json`(최신·승격 판정) · `data/i3/shadow_history.csv`(일별 1행).
  텔레그램: 도전자 목표 비중이 챔피언과 10%p 이상 다른 날 · 승격 조건을 처음 충족한 날.

도전자 등록 규칙: lab 에서 사전선언으로 측정한 것만. 학습 잣대 통과가 필수는 아니다(R1 은 장기·미공개에서
기각됐지만 강세장 개선이 뚜렷해 '실전 데이터로 다시 본다'). 등록 날짜를 남긴다 — 그 이전 성적은 쓰지 않는다.
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

import i3_core as K  # noqa: E402
import lab_reentry as R  # noqa: E402
import strategy_lab as L  # noqa: E402

DATA_DIR = _ROOT / "data" / "i3"
SHADOW_FILE = DATA_DIR / "shadow.json"
HISTORY_FILE = DATA_DIR / "shadow_history.csv"
AFTER_CLOSE = dtime(15, 35)
DIVERGE_PP = 0.10                # 목표 비중이 이만큼 다르면 '다르게 행동한 날'(I3 매매 밴드와 같은 값)

CHAMPION = "I3"
# 도전자 — {이름: (i3r mode, 등록일, 근거)}. 새 도전자는 lab 사전선언 측정 후에만 추가한다.
CHALLENGERS: dict[str, tuple[str, str, str]] = {
    "R1": ("R1", "2026-10-22", "8차 lab_reentry: 재진입 리셋 — 학습 연 +2.1%p·강세장 +3.1%p, 장기 MDD 43%·미공개 −11.4% 로 기각"),
}

# ── 승격 규칙 (2026-10-22 선언 — 실전 데이터를 보기 전. 결과를 보고 고치면 무효) ──────────────
PROMO_MIN_DAYS = 120             # 실전 기록 최소 영업일(약 6개월)
PROMO_MIN_DIVERGE_DAYS = 20      # 챔피언과 다르게 행동한 날이 이만큼은 있어야 비교가 된다
PROMO_MARGIN_PP = 2.0            # 등록 이후 누적 수익 ≥ 챔피언 + 2%p
PROMO_MAX_MDD = 20.0             # 운용자 ① 그대로
PROMO_MDD_TOL_PP = 3.0           # 그리고 MDD ≤ 챔피언 MDD + 3%p


def shadow_target(inner, start: str, equity: float):
    """inner(i3r) 를 2015 부터 재생하되 start 전에는 자산을 equity 로 고정해 넣고 매매하지 않는다
    → start 일에 '낙폭 예산을 새로 시작한 실전'과 같은 상태. start 일엔 그날의 목표 비중을 강제로 낸다
    (실전의 첫 판단과 같다). desired['w'] = 마지막 목표 비중(KODEX200)."""
    desired: dict = {"out": None, "w": None, "hist": {}, "trade_days": set()}

    def target(i: int, d: str, nav: float):
        r = inner(i, d, equity if d < start else nav)
        if r is not None:
            desired["out"] = r
            desired["w"] = r.get(K.BASE, 0.0)
        if d < start:
            return None
        desired["hist"][d] = desired["w"] or 0.0
        out = desired["out"] if d == start else r
        if out is not None:
            desired["trade_days"].add(d)
        return out
    target.desired = desired
    return target


def run_models(base: dict, kospi: dict, cash: dict, start: str, equity: float, upto: str,
               models: dict[str, str] | None = None) -> dict:
    """모델별 {nav, ret, mdd, w, curve, w_hist} — start 부터 upto 까지(체결은 다음 날 시가)."""
    models = models or {CHAMPION: "I3", **{k: v[0] for k, v in CHALLENGERS.items()}}
    dates = sorted(d for d in base if K.REPLAY_START <= d <= upto)
    out = {}
    for name, mode in models.items():
        t = shadow_target(R.i3r(base, kospi, K.BASE, K.CASH, K.M, K.LOOKBACK, mode), start, equity)
        res = L.simulate({K.BASE: L.Asset(K.BASE, base), K.CASH: L.Asset(K.CASH, cash)}, dates, t,
                         equity, pass_nav=True)
        pts = [(d, v) for d, v in zip(res.dates, res.curve) if d >= start]
        m = L.metrics([d for d, _ in pts], [v for _, v in pts]) if len(pts) > 1 else {"mdd": 0.0}
        out[name] = {"nav": round(pts[-1][1]), "ret": round((pts[-1][1] / equity - 1) * 100, 3),
                     "mdd": round(m["mdd"], 3), "w": round(t.desired["w"] or 0.0, 4),
                     "curve": [(d, round(v)) for d, v in pts], "w_hist": t.desired["hist"],
                     "trade_days": sorted(t.desired["trade_days"]), "nav_hist": dict(pts)}
    return out


def promotion(champ: dict, chal: dict, since: str) -> dict:
    """등록일(since) 이후만 잘라 선언된 승격 규칙으로 판정."""
    cc = [(d, v) for d, v in champ["curve"] if d >= since]
    xc = [(d, v) for d, v in chal["curve"] if d >= since]
    if len(cc) < 2 or len(xc) < 2:
        return {"days": len(xc), "ok": False, "checks": {}}
    cm = L.metrics([d for d, _ in cc], [v for _, v in cc])
    xm = L.metrics([d for d, _ in xc], [v for _, v in xc])
    diverge = sum(1 for d, w in chal["w_hist"].items()
                  if d >= since and abs(w - champ["w_hist"].get(d, 0.0)) >= DIVERGE_PP)
    checks = {
        f"기록 ≥ {PROMO_MIN_DAYS}일": len(xc) >= PROMO_MIN_DAYS,
        f"다르게 행동한 날 ≥ {PROMO_MIN_DIVERGE_DAYS}": diverge >= PROMO_MIN_DIVERGE_DAYS,
        f"누적 ≥ 챔피언 +{PROMO_MARGIN_PP:g}%p": xm["total"] >= cm["total"] + PROMO_MARGIN_PP,
        f"MDD ≤ {PROMO_MAX_MDD:g}%": xm["mdd"] <= PROMO_MAX_MDD,
        f"MDD ≤ 챔피언 +{PROMO_MDD_TOL_PP:g}%p": xm["mdd"] <= cm["mdd"] + PROMO_MDD_TOL_PP,
    }
    return {"days": len(xc), "diverge_days": diverge, "ret": round(xm["total"], 3), "champ_ret": round(cm["total"], 3),
            "mdd": round(xm["mdd"], 3), "champ_mdd": round(cm["mdd"], 3), "checks": checks, "ok": all(checks.values())}


def history_cols() -> list[str]:
    names = [CHAMPION, *CHALLENGERS]
    return ["date", "live_nav"] + [f"{n.lower()}_nav" for n in names] + [f"{n.lower()}_w" for n in names]


def append_history(row: dict, path: Path = HISTORY_FILE) -> None:
    """같은 날짜 행은 바꿔 쓴다(하루 두 번 돌아도 1행). 도전자가 늘면 열도 는다(옛 행은 빈칸)."""
    cols = history_cols()
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") != row["date"]]
    rows.append({k: row.get(k, "") for k in cols})
    rows.sort(key=lambda r: r["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


async def main_async(now: datetime) -> int:
    import i3_live as LV
    st = LV.load_state()
    navs = st.get("navs") or []
    if not navs:
        print(json.dumps({"skip": "실전 자산 이력 없음 — 첫 판단 전"}, ensure_ascii=False))
        return 0
    start, equity = navs[0][0], float(navs[0][1])
    m = LV.KiwoomMarket()
    today = now.strftime("%Y-%m-%d")
    base = {**await m.base_bars(), **await m.recent(K.BASE)}
    kospi = {**await m.kospi_bars(), **await m.recent("KOSPI")}
    cash = {**L.load_bars(K.CASH, "2024-01-01", today), **await m.recent(K.CASH)}
    # 장중엔 오늘 일봉이 미완성 — 15:35 전이면 어제까지만 본다
    upto = (today if now.time() >= AFTER_CLOSE and today in base and today in kospi
            else max(d for d in base if d < today))
    res = run_models(base, kospi, cash, start, equity, upto)
    champ = res[CHAMPION]
    live_nav = float(navs[-1][1])
    prev = json.loads(SHADOW_FILE.read_text(encoding="utf-8")) if SHADOW_FILE.exists() else {}
    promo = {n: promotion(champ, res[n], max(start, CHALLENGERS[n][1])) for n in CHALLENGERS}
    rec = {"asof": upto, "start": start, "equity": round(equity),
           "live": {"nav": round(live_nav), "ret": round((live_nav / equity - 1) * 100, 3), "date": navs[-1][0]},
           "models": {k: {kk: vv for kk, vv in v.items() if kk not in ("curve", "w_hist", "trade_days", "nav_hist")}
                      for k, v in res.items()},
           "promotion": promo}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SHADOW_FILE)
    row = {"date": upto, "live_nav": round(live_nav) if navs[-1][0] == upto else ""}
    for n, v in res.items():
        row[f"{n.lower()}_nav"], row[f"{n.lower()}_w"] = v["nav"], v["w"]
    append_history(row)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    for n in CHALLENGERS:
        if abs(res[n]["w"] - champ["w"]) >= DIVERGE_PP:
            await LV._notify(
                f"🪞 [I3 리그] {upto} 도전자 {n} 은 KODEX200 {res[n]['w']:.0%} · 챔피언 I3 {champ['w']:.0%} — "
                f"등록 후 {n} {promo[n].get('ret', 0):+.2f}% · I3 모델 {promo[n].get('champ_ret', 0):+.2f}% · "
                f"실계좌 {rec['live']['ret']:+.2f}% (주문 없음, 기록만)")
        if promo[n]["ok"] and not (prev.get("promotion", {}).get(n, {}) or {}).get("ok"):
            await LV._notify(
                f"🏆 [I3 리그] 도전자 {n} 승격 조건 충족 — {promo[n]['days']}영업일 · 누적 {promo[n]['ret']:+.2f}% "
                f"(I3 {promo[n]['champ_ret']:+.2f}%) · MDD {promo[n]['mdd']:.1f}%. 운용자 승인 전엔 바꾸지 않는다.",
                critical=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    return asyncio.run(main_async(datetime.now()))


if __name__ == "__main__":
    raise SystemExit(main())
