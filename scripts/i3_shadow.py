"""I3 리그 — 챔피언(실전 I3)과 여러 계열의 도전자를 매일 같은 조건으로 기록하고, 선언된 승격 규칙으로 판정한다.

운용자(10-22): "매일매일 발전해야 한다" · "도전자를 계속 만들어 발전 — 약점은 줄이고 강점은 살려라" ·
"기본은 I3 로 꾸준히 벌면서 더 나은 알고리즘을 검증하며 보완" · "추세추종·단타 등 다양한 알고리즘을 가져와 경쟁".

    연구(사전선언·백테스트) ──▶ 리그 입장(주문 없음) ──매일 15:50 판단 뒤 기록──▶ 승격 규칙 충족
        ──▶ 텔레그램 '승격 후보' ──운용자 승인──▶ 실전(i3_core 교체 + 실전==검증 대조 테스트)

- **주문과 무관하다.** 별도 프로세스(i3_decide.cmd 가 판단 뒤 실행) — 실패해도 실전 판단·매매에 영향 없다.
  멤버 하나가 실패해도 나머지는 기록한다.
- 모든 멤버가 같은 조건: **실전 시작일**(state navs[0])에 같은 자산으로 출발, 신호는 과거부터 재생(워밍업),
  체결은 각 엔진의 검증 가정, 남는 돈은 i3_core.CASH(머니마켓). 챔피언 모델은 실계좌의 기준선이기도 하다.
- 결과: `data/i3/shadow.json`(최신·순위·승격 판정) · `data/i3/shadow_history.csv`(일별 1행).
  텔레그램: 매일 리그 순위 한 통 · 승격 조건을 처음 충족한 날(critical).

입장 규칙: ① 연구에서 사전선언으로 측정한 계열의 **선언 기본값**은 운용 가능하면 들어온다(운용자 결정 10-22).
② 결과를 보고 만든 새 설계(세대)는 `lab_challengers` 입장 조건(E1·E2·E3)을 통과해야 한다.
등록일을 남긴다 — 승격 판정은 등록일 이후 실전 데이터만 쓴다.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable

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
DIVERGE_PP = 0.10                # 위험 비중이 이만큼 다르면 '다르게 행동한 날'(I3 매매 밴드와 같은 값)
KOSPI = "^KS11"
NDQ = "133690"                   # TIGER 미국나스닥100

# ── 승격 규칙 (2026-10-22 선언 — 실전 데이터를 보기 전. 결과를 보고 고치면 무효) ──────────────
PROMO_MIN_DAYS = 120             # 실전 기록 최소 영업일(약 6개월)
PROMO_MIN_DIVERGE_DAYS = 20      # 챔피언과 다르게 행동한 날이 이만큼은 있어야 비교가 된다
PROMO_MARGIN_PP = 2.0            # 등록 이후 누적 수익 ≥ 챔피언 + 2%p
PROMO_MAX_MDD = 20.0             # 운용자 ① 그대로
PROMO_MDD_TOL_PP = 3.0           # 그리고 MDD ≤ 챔피언 MDD + 3%p


# ── 공통: 실전 시작일부터의 그림자 실행 ──────────────────────────────────────────
def exposure(out: dict[str, float] | None) -> float:
    """위험 비중 = 현금 자리(머니마켓) 밖의 비중 합."""
    return sum(w for c, w in (out or {}).items() if c != K.CASH)


def shadow_target(inner, start: str, equity: float, needs_nav: bool = True):
    """inner 를 과거부터 재생하되 start 전에는 자산을 equity 로 고정해 넣고 매매하지 않는다
    → start 일에 '실전 시작일에 새로 출발한' 상태. start 일엔 그날의 목표 비중을 강제로 낸다(실전의 첫 판단과 같다)."""
    desired: dict = {"out": None, "w": None, "hist": {}, "trade_days": set()}

    def target(i: int, d: str, nav: float):
        r = inner(i, d, equity if d < start else nav) if needs_nav else inner(i, d)
        if r is not None:
            desired["out"] = r
            desired["w"] = exposure(r)
        if d < start:
            return None
        desired["hist"][d] = desired["w"] or 0.0
        out = desired["out"] if d == start else r
        if out is not None:
            desired["trade_days"].add(d)
        return out
    target.desired = desired
    return target


def cash_fill(inner):
    """비중 합이 1 보다 작으면 나머지를 현금 자리(머니마켓)에 — 모든 멤버의 놀고 있는 돈을 같은 조건으로."""
    def target(*a):
        r = inner(*a)
        if r is None:
            return None
        out = dict(r)
        rest = 1.0 - sum(out.values())
        if rest > 1e-9:
            out[K.CASH] = out.get(K.CASH, 0.0) + rest
        return out
    return target


def remap(inner, mapping: dict[str, str]):
    """연구 코드의 현금 종목(153130 등)을 리그 현금 자리로 바꿔 낸다."""
    def target(*a):
        r = inner(*a)
        if r is None:
            return None
        out: dict[str, float] = {}
        for c, w in r.items():
            out[mapping.get(c, c)] = out.get(mapping.get(c, c), 0.0) + w
        return out
    return target


def next_weekday(d: str) -> str:
    x = date.fromisoformat(d) + timedelta(days=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x.isoformat()


def _calendar(data: dict, upto: str) -> list[str]:
    return sorted(d for d in data[K.BASE] if K.REPLAY_START <= d <= upto)


def _pack(res: L.SimResult, t, start: str, equity: float) -> dict:
    pts = [(d, v) for d, v in zip(res.dates, res.curve) if d >= start]
    return {"curve": [(d, round(v)) for d, v in pts], "w_hist": dict(t.desired["hist"]),
            "trade_days": sorted(t.desired["trade_days"]), "nav_hist": dict(pts), "w": t.desired["w"] or 0.0}


def std_run(build: Callable[[dict, list[str]], tuple[tuple[str, ...], Callable, bool]]):
    """build(data, dates) → (자산 코드들, target, needs_nav) 인 연구 함수를 리그 실행기로."""
    def run(data: dict, start: str, equity: float, upto: str) -> dict:
        dates = _calendar(data, upto)
        codes, inner, needs_nav = build(data, dates)
        t = shadow_target(inner, start, equity, needs_nav)
        res = L.simulate({c: L.Asset(c, data[c]) for c in codes}, dates, t, equity, pass_nav=True)
        return _pack(res, t, start, equity)
    return run


# ── 멤버 정의 ────────────────────────────────────────────────────────────────
def _b_i3(mode: str):
    def build(data, dates):
        return (K.BASE, K.CASH), R.i3r(data[K.BASE], data[KOSPI], K.BASE, K.CASH, K.M, K.LOOKBACK, mode), True
    return build


def _b_i1a(data, dates):
    import lab_dd_control as I
    t = I.reentry_confirmed(data[K.BASE], data[KOSPI], K.BASE, *I.I1_DEFAULT, K.CASH)
    return (K.BASE, K.CASH), t, False


def _b_ma60(data, dates):
    import lab_index_candidates as A
    return (K.BASE, K.CASH), cash_fill(A.ma_filter(data[KOSPI], A.DEFAULT_MA, K.BASE)), False


def _b_dual(data, dates):
    import lab_index_candidates as A
    t, nxt = A.dual_momentum({c: data[c] for c in (K.BASE, NDQ, "114260")}, A.DEFAULT_DM)
    ext = dates + [next_weekday(dates[-1])]           # 오늘이 월말인지는 다음 영업일로 판단(평일 근사)
    nxt.update(zip(ext, ext[1:]))
    return (K.BASE, NDQ, "114260", K.CASH), cash_fill(t), False


def _b_alloc(data, dates):
    import lab_buffett as B
    px = B.Prices({c: data[c] for c in B.D_ASSETS})
    t = B.strat_d(px, dates + [next_weekday(dates[-1])], *B.D_DEFAULT)
    return (*B.D_ASSETS, K.CASH), cash_fill(remap(t, {B.CASH_ETF: K.CASH})), False


def _run_half_half(data: dict, start: str, equity: float, upto: str) -> dict:
    """KODEX200 I3(KOSPI 추세) 절반 + 나스닥100 I3(자기 추세) 절반, 각자 낙폭 예산 — 재조정 없음."""
    def sleeve(asset, regime):
        def build(d, dates):
            return (asset, K.CASH), R.i3r(d[asset], d[regime], asset, K.CASH, K.M, K.LOOKBACK, "I3"), True
        return std_run(build)(data, start, equity / 2, upto)
    kr, us = sleeve(K.BASE, KOSPI), sleeve(NDQ, NDQ)
    us_nav = us["nav_hist"]
    curve = [(d, v + us_nav.get(d, 0)) for d, v in kr["curve"]]
    w_hist = {d: (kr["w_hist"].get(d, 0) + us["w_hist"].get(d, 0)) / 2 for d in kr["w_hist"]}
    return {"curve": curve, "w_hist": w_hist, "trade_days": sorted(set(kr["trade_days"]) | set(us["trade_days"])),
            "nav_hist": dict(curve), "w": (kr["w"] + us["w"]) / 2}


def _run_trend(data: dict, start: str, equity: float, upto: str) -> dict:
    """종료한 대형주 추세추종 — 라이브 설정 그대로(trend_paper 와 같은 엔진), 같은 자산으로 실전 시작일 출발."""
    os.environ.setdefault("TREND_BT_EQUITY", str(int(equity)))
    import backtest_trend_portfolio as P
    import trend_paper as TP
    from backtest_walkforward import Costs
    from src.mcp_servers.trend_mcp import costs as C
    cfg, k = TP._live_cfg()
    dates, _b, _c, _o = P._load(TP.DATA_START, upto, 100)
    win = [d for d in dates if d >= start]
    if not win:
        return {"curve": [(start, round(equity))], "w_hist": {}, "trade_days": [], "nav_hist": {start: equity}, "w": None}
    P._SIG_MEMO.clear()
    res = P.simulate(TP.DATA_START, dates[-1], 100, cfg, Costs(C.TAX_BPS, C.FEE_BPS, C.SLIPPAGE_BPS),
                     P.Sizing(mode="notional", position_pct=k["position_pct"]), k["max_pos"], 0,
                     "partial" in k["exits"], P._sector_map(), hard_stop_pct=k["hard_stop"],
                     rank_mode=k["rank_mode"], regime_ma=k["regime_ma"], breadth_min=k["breadth_min"],
                     exits=k["exits"], sim_from=start, sim_to=dates[-1])
    scale = equity / P.START_EQUITY                   # 다른 예탁으로 이미 로드됐으면 비율로 맞춘다
    curve = [(d, round(v * scale)) for d, v in zip(win, res.equity_curve)]
    return {"curve": curve, "w_hist": {}, "trade_days": [], "nav_hist": dict(curve), "w": None}


@dataclass(frozen=True)
class Member:
    name: str
    family: str
    registered: str
    admitted: str
    note: str
    codes: tuple[str, ...]
    run: Callable[[dict, str, float, str], dict]


CHAMPION = "I3"
_D = "2026-10-22"
_OP = "운용자 결정(10-22): 연구한 계열 선언 기본값으로 경쟁"
MEMBERS: tuple[Member, ...] = (
    Member("I3", "I3", _D, "챔피언(실전)", "재진입 확인 엔진 × 낙폭 예산", (K.BASE, K.CASH, KOSPI), std_run(_b_i3("I3"))),
    Member("R1", "I3 계보", _D, "운용자 결정(10-22): 그림자 기록", "8차: 재진입 리셋 — 강세장 강점·연속 실패 약점",
           (K.BASE, K.CASH, KOSPI), std_run(_b_i3("R1"))),
    Member("I1a", "I3 계보", _D, _OP, "5차: I3 의 엔진만(낙폭 예산 없음)", (K.BASE, K.CASH, KOSPI), std_run(_b_i1a)),
    Member("MA60", "지수 추세", _D, _OP, "1차 A: KODEX200 ⇔ KOSPI>MA60", (K.BASE, K.CASH, KOSPI), std_run(_b_ma60)),
    Member("듀얼모멘텀", "모멘텀", _D, _OP, "1차 C: 월말 KODEX200·나스닥100·국고채3년 12개월 수익 비교",
           (K.BASE, NDQ, "114260", K.CASH, KOSPI), std_run(_b_dual)),
    Member("자산배분", "자산배분", _D, _OP, "2차 D: 5자산 역변동성 + 변동성 목표 12%(월말)",
           ("069500", "133690", "148070", "132030", "138230", K.CASH, KOSPI), std_run(_b_alloc)),
    Member("한미반반", "자산배분", _D, _OP, "ETF 비교: KODEX200 I3 + 나스닥100 I3 반반(재조정 없음)",
           (K.BASE, NDQ, K.CASH, KOSPI), _run_half_half),
    Member("추세추종", "종목 추세추종", _D, _OP, "06~10월 실전 운용 후 종료한 대형주 추세추종(라이브 설정 그대로)",
           (K.BASE, KOSPI), _run_trend),
)


def run_league(data: dict, start: str, equity: float, upto: str,
               members: tuple[Member, ...] = MEMBERS) -> dict[str, dict]:
    """멤버별 결과. 실패한 멤버는 {'error': ...} 로 남기고 나머지는 계속한다."""
    out = {}
    for m in members:
        try:
            out[m.name] = m.run(data, start, equity, upto)
        except Exception as e:                     # 리그는 기록용 — 한 멤버 실패가 전체를 막지 않는다
            out[m.name] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    return out


def run_models(base: dict, kospi: dict, cash: dict, start: str, equity: float, upto: str,
               models: dict[str, str] | None = None) -> dict:
    """I3 계보만 빠르게(테스트·진단용) — {이름: i3r mode}."""
    data = {K.BASE: base, KOSPI: kospi, K.CASH: cash}
    models = models or {"I3": "I3", "R1": "R1"}
    return {n: std_run(_b_i3(mode))(data, start, equity, upto) for n, mode in models.items()}


def promotion(champ: dict, chal: dict, since: str) -> dict:
    """등록일(since) 이후만 잘라 선언된 승격 규칙으로 판정."""
    cc = [(d, v) for d, v in champ["curve"] if d >= since]
    xc = [(d, v) for d, v in chal["curve"] if d >= since]
    if len(cc) < 2 or len(xc) < 2:
        return {"days": len(xc), "ok": False, "checks": {}}
    cm = L.metrics([d for d, _ in cc], [v for _, v in cc])
    xm = L.metrics([d for d, _ in xc], [v for _, v in xc])
    if chal.get("w_hist"):
        diverge = sum(1 for d, w in chal["w_hist"].items()
                      if d >= since and abs(w - champ["w_hist"].get(d, 0.0)) >= DIVERGE_PP)
    else:
        diverge = len(xc)                          # 비중을 모르는 계열(종목형) — 늘 다르게 행동한 것으로
    checks = {
        f"기록 ≥ {PROMO_MIN_DAYS}일": len(xc) >= PROMO_MIN_DAYS,
        f"다르게 행동한 날 ≥ {PROMO_MIN_DIVERGE_DAYS}": diverge >= PROMO_MIN_DIVERGE_DAYS,
        f"누적 ≥ 챔피언 +{PROMO_MARGIN_PP:g}%p": xm["total"] >= cm["total"] + PROMO_MARGIN_PP,
        f"MDD ≤ {PROMO_MAX_MDD:g}%": xm["mdd"] <= PROMO_MAX_MDD,
        f"MDD ≤ 챔피언 +{PROMO_MDD_TOL_PP:g}%p": xm["mdd"] <= cm["mdd"] + PROMO_MDD_TOL_PP,
    }
    return {"days": len(xc), "diverge_days": diverge, "ret": round(xm["total"], 3), "champ_ret": round(cm["total"], 3),
            "mdd": round(xm["mdd"], 3), "champ_mdd": round(cm["mdd"], 3), "checks": checks, "ok": all(checks.values())}


def _slug(name: str) -> str:
    return name.lower()


def history_cols() -> list[str]:
    names = [m.name for m in MEMBERS]
    return ["date", "live_nav"] + [f"{_slug(n)}_nav" for n in names] + [f"{_slug(n)}_w" for n in names]


def append_history(row: dict, path: Path = HISTORY_FILE) -> None:
    """같은 날짜 행은 바꿔 쓴다(하루 두 번 돌아도 1행). 멤버가 늘면 열도 는다(옛 행은 빈칸)."""
    cols = history_cols()
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


async def _load_data(today: str) -> dict:
    """멤버가 쓰는 종목: 장기 이력 FDR + 최근·오늘 일봉 키움(실전 판단과 같은 출처)."""
    import i3_live as LV
    m = LV.KiwoomMarket()
    codes = sorted({c for mb in MEMBERS for c in mb.codes})
    data = {}
    for c in codes:
        if c == KOSPI:
            data[c] = {**await m.kospi_bars(), **await m.recent("KOSPI")}
        else:
            hist = L.load_bars(c, "2010-01-01", today)
            try:
                rec = await m.recent(c)
            except Exception:
                rec = {}
            data[c] = {**hist, **rec}
    return data


def summary_line(rec: dict) -> str:
    """텔레그램 한 통 — 시작일 대비 수익 순위."""
    rows = [(n, v) for n, v in rec["models"].items() if "ret" in v]
    rows.sort(key=lambda x: -x[1]["ret"])
    body = " · ".join(f"{'👑' if n == CHAMPION else ''}{n} {v['ret']:+.2f}%"
                      + (f"({v['asof'][5:]} 기준)" if v.get("asof") and v["asof"] != rec["asof"] else "")
                      for n, v in rows)
    errs = [n for n, v in rec["models"].items() if "error" in v]
    tail = f" · 오류 {', '.join(errs)}" if errs else ""
    return (f"🏟️ [I3 리그] {rec['asof']} (시작 {rec['start']} 대비) 실계좌 {rec['live']['ret']:+.2f}% | "
            f"{body}{tail} — 도전자는 주문 없음")


async def main_async(now: datetime) -> int:
    import i3_live as LV
    st = LV.load_state()
    navs = st.get("navs") or []
    if not navs:
        print(json.dumps({"skip": "실전 자산 이력 없음 — 첫 판단 전"}, ensure_ascii=False))
        return 0
    start, equity = navs[0][0], float(navs[0][1])
    today = now.strftime("%Y-%m-%d")
    data = await _load_data(today)
    base, kospi = data[K.BASE], data[KOSPI]
    # 장중엔 오늘 일봉이 미완성 — 15:35 전이면 어제까지만 본다
    upto = (today if now.time() >= AFTER_CLOSE and today in base and today in kospi
            else max(d for d in base if d < today))
    res = run_league(data, start, equity, upto)
    champ = res[CHAMPION]
    live_nav = float(navs[-1][1])
    prev = json.loads(SHADOW_FILE.read_text(encoding="utf-8")) if SHADOW_FILE.exists() else {}
    promo = {}
    models = {}
    for mb in MEMBERS:
        r = res[mb.name]
        if "error" in r:
            models[mb.name] = {"error": r["error"], "family": mb.family}
            continue
        last = r["curve"][-1]
        mdd = L.metrics([d for d, _ in r["curve"]], [v for _, v in r["curve"]])["mdd"] if len(r["curve"]) > 1 else 0.0
        models[mb.name] = {"family": mb.family, "nav": last[1], "asof": last[0],
                           "ret": round((last[1] / equity - 1) * 100, 3), "mdd": round(mdd, 3),
                           "w": None if r["w"] is None else round(r["w"], 4),
                           "registered": mb.registered, "admitted": mb.admitted, "note": mb.note}
        if mb.name != CHAMPION and "error" not in champ:
            promo[mb.name] = promotion(champ, r, max(start, mb.registered))
    rec = {"asof": upto, "start": start, "equity": round(equity),
           "live": {"nav": round(live_nav), "ret": round((live_nav / equity - 1) * 100, 3), "date": navs[-1][0]},
           "models": models, "promotion": promo}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SHADOW_FILE)
    row = {"date": upto, "live_nav": round(live_nav) if navs[-1][0] == upto else ""}
    for n, v in models.items():
        if "nav" in v:
            row[f"{_slug(n)}_nav"], row[f"{_slug(n)}_w"] = v["nav"], "" if v["w"] is None else v["w"]
    append_history(row)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    await LV._notify(summary_line(rec))
    for n, p in promo.items():
        if p.get("ok") and not (prev.get("promotion", {}).get(n, {}) or {}).get("ok"):
            await LV._notify(
                f"🏆 [I3 리그] 도전자 {n} 승격 조건 충족 — {p['days']}영업일 · 누적 {p['ret']:+.2f}% "
                f"(I3 {p['champ_ret']:+.2f}%) · MDD {p['mdd']:.1f}%. 운용자 승인 전엔 바꾸지 않는다.", critical=True)
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    return asyncio.run(main_async(datetime.now()))


if __name__ == "__main__":
    raise SystemExit(main())
