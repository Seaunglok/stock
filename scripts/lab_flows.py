"""수급 판정대 — 외국인·기관·프로그램 수급이 다음 며칠 KOSPI 방향을 알려 주는가 (2026-11-16, 사전 선언).

운용자(11-16): "패턴을 찾는 게 아니라, 뉴스와 경제를 읽고, 수급량과 방향을 봐서 단기 대응하는 게 답" → "1, 2 번 진행해보자".
1번 = 이미 있는 수급 이력(`data/market_flows/daily.csv`, 2010-01-04~, KRX 확정치, check=='ok' 만)으로 재는 판정대.
2번(뉴스·경제 지표, 앞으로만) 은 `market_features.py`.

왜 이렇게 재나
-------------
  · 9세대(재진입 × 외국인 수급, 11-10)에서 외국인 수급은 '실패할 재진입'을 걸렀지만 V자 반등엔 늦었다 — 수급에 정보는 있다.
    이번엔 재진입 확인이 아니라 **수급 그 자체가 단기 방향을 알려 주는지** 직접 잰다.
  · 11-16 외국인 −1.38조·개인 +1.35조(잠정) 같은 날이 '뒤에 어떻게 됐나'를 먼저 보면 판정이 오염된다 → 기준을 먼저 커밋.
  · 문헌: 외국인 매매와 한국·아시아 주가는 같이 움직이고 가격 충격이 크다(Choe·Kho·Stulz 1999, Richards 2005) — 앞날 예측력은
    약하다는 쪽이 많다. **이 판정대는 우리 가설을 재는 것이다.**

선언 (측정 전 — 결과를 보고 고치면 무효, 같은 숫자로 다시 재지 않는다)
-------------------------------------------------------------------
  수급 크기    시가총액이 2010→2026 몇 배라 금액 그대로는 시대마다 다르다 → **평소 대비 표준화**:
               z = (오늘 − 직전 Z_WIN(60)거래일 평균) ÷ 직전 60거래일 표준편차.
  신호(방향은 미리 정한다 — '지속' 가설)
    S1 외국인 극단 순매도    외국인 z ≤ −2          → 하락
    S2 외국인 극단 순매수    외국인 z ≥ +2          → 상승
    S3 외국인·기관 동반 매수  외국인 z ≥ 1 그리고 기관 z ≥ 1 → 상승
    S4 외국인·기관 동반 매도  외국인 z ≤ −1 그리고 기관 z ≤ −1 → 하락
    S5 프로그램 비차익 극단 매도  비차익 z ≤ −2      → 하락
  실행(검증 = 운용) d 일 수급 확정치는 d+1 아침(시장 일지 08:30)에 나온다 → **d+1 시가 진입, H(5)거래일 뒤 시가 청산**.
               KOSPI 지수(^KS11) 시가→시가로 잰다(상승 = KODEX200, 하락 = 인버스 — 인버스 다일 복리 차이는 무시). 비용 편도 11.5bp.
  구간         앞 2010-04~2020 · 뒤 2021~2026-11 — **둘 다** 통과해야 인정(맞추는 값이 없으니 '학습'이 아니라 두 번의 독립 시험).
  통과(구간마다 전부)
    P1 표본      신호 날 ≥ MIN_EVENTS(20)
    P2 방향      신호 날의 적중률(5일 뒤 방향 맞음) ≥ 그 구간 모든 날의 기저율 + HIT_GAIN_PP(5)%p
    P3 크기      신호 날 평균 5일 수익(가설 방향) − 그 구간 모든 날 평균 ≥ EXCESS_MIN_PCT(+0.3)%p
    P4 매매      겹치지 않게 매매(보유 중 신호는 건너뜀) 비용 뺀 거래당 평균 > 0 그리고 합계 > 0
  보고만      보유 1일·20일, 반대 방향(되돌림) 결과. **반대 방향이 강해도 이번엔 채택하지 않는다**(결과를 보고 방향을 고르는 셈 —
              다음 선언 후보로 기록만).
  통과하면    공격형 리그에 앞으로만 기록하는 멤버로(다음 거래일부터, 50만원, 상승 KODEX200 · 하락 인버스, 5일 보유) — 판정은 리그 기록.
              실계좌는 11-10 운용자 결정대로 없다.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402
import market_flows as MF  # noqa: E402

# ── 선언 ─────────────────────────────────────────────────────────────────────
Z_WIN = 60
Z_EXTREME = 2.0
Z_JOINT = 1.0
H = 5
H_REPORT = (1, 20)
MIN_EVENTS = 20
HIT_GAIN_PP = 5.0
EXCESS_MIN_PCT = 0.3
PERIODS = {"앞": ("2010-04-01", "2020-12-31"), "뒤": ("2021-01-01", "2026-11-13")}
COLS = {"f": "kospi_foreign_eok", "i": "kospi_inst_eok", "p": "prog_nonarb"}
SIGNALS: dict[str, tuple[str, int]] = {          # 이름 → (설명, 가설 방향 +1 상승 / −1 하락)
    "S1": ("외국인 극단 순매도", -1),
    "S2": ("외국인 극단 순매수", +1),
    "S3": ("외국인·기관 동반 매수", +1),
    "S4": ("외국인·기관 동반 매도", -1),
    "S5": ("프로그램 비차익 극단 매도", -1),
}


def side_cost() -> float:
    return L.side_cost(False, False)          # ETF 편도 수수료+슬리피지(거래세 없음) = 11.5bp


# ── 순수 함수 ────────────────────────────────────────────────────────────────
def load(path: Path = MF.FLOWS_FILE) -> tuple[list[str], dict[str, list[float | None]]]:
    """확정치(check=='ok') 줄만, 날짜순 — 값이 빈 칸이면 None."""
    rows = [r for _, r in sorted(MF.load_rows(path).items()) if r.get("check") == "ok"]
    out: dict[str, list[float | None]] = {}
    for k, col in COLS.items():
        out[k] = [float(r[col]) if r.get(col) not in (None, "") else None for r in rows]
    return [r["date"] for r in rows], out


def zscores(xs: list[float | None], win: int = Z_WIN) -> list[float | None]:
    """직전 win 개(오늘 제외) 평균·표준편차로 표준화 — 그날까지의 값만. 창에 빈 값이 있으면 None."""
    out: list[float | None] = []
    for k, x in enumerate(xs):
        prev = xs[k - win:k] if k >= win else None
        if x is None or not prev or any(v is None for v in prev):
            out.append(None)
            continue
        sd = statistics.stdev(prev)
        out.append(None if sd == 0 else (x - statistics.fmean(prev)) / sd)
    return out


def fires(name: str, z: dict[str, float | None]) -> bool:
    f, i, p = z.get("f"), z.get("i"), z.get("p")
    if name == "S1":
        return f is not None and f <= -Z_EXTREME
    if name == "S2":
        return f is not None and f >= Z_EXTREME
    if name == "S3":
        return f is not None and i is not None and f >= Z_JOINT and i >= Z_JOINT
    if name == "S4":
        return f is not None and i is not None and f <= -Z_JOINT and i <= -Z_JOINT
    if name == "S5":
        return p is not None and p <= -Z_EXTREME
    raise KeyError(name)


def forward(days: list[str], opens: dict[str, float], h: int) -> dict[str, float]:
    """d → (d 다음 거래일 시가 → 그 h 거래일 뒤 시가) 수익. 미래 자료가 없으면 없음."""
    out = {}
    for k, d in enumerate(days):
        if k + 1 + h < len(days):
            a, b = opens.get(days[k + 1]), opens.get(days[k + 1 + h])
            if a and b:
                out[d] = b / a - 1
    return out


def trades(signal_days: list[str], days: list[str], fwd: dict[str, float], direction: int, h: int,
           cost: float) -> list[float]:
    """겹치지 않게: 보유 중(진입 다음 날 ~ 청산 시가 전)에 난 신호는 건너뛴다. 거래당 순수익(가설 방향, 왕복 비용 뺌)."""
    pos = {d: k for k, d in enumerate(days)}
    out, free_from = [], -1
    for d in signal_days:
        k = pos[d]
        if k + 1 < free_from or d not in fwd:
            continue
        out.append(direction * fwd[d] - 2 * cost)
        free_from = k + 1 + h
    return out


def judge(sig_days: list[str], all_days: list[str], fwd: dict[str, float], direction: int, h: int,
          cost: float) -> dict:
    """한 구간·한 보유 기간의 판정 재료와 P1~P4."""
    sig = [d for d in sig_days if d in fwd]
    base = [direction * fwd[d] for d in all_days if d in fwd]
    got = [direction * fwd[d] for d in sig]
    tr = trades(sig, all_days, fwd, direction, h, cost)
    if not got or not base:
        return {"n": len(got), "pass": False, "checks": {}}
    hit, base_hit = sum(x > 0 for x in got) / len(got), sum(x > 0 for x in base) / len(base)
    excess = (statistics.fmean(got) - statistics.fmean(base)) * 100
    checks = {"P1": len(got) >= MIN_EVENTS, "P2": (hit - base_hit) * 100 >= HIT_GAIN_PP,
              "P3": excess >= EXCESS_MIN_PCT, "P4": bool(tr) and statistics.fmean(tr) > 0 and sum(tr) > 0}
    return {"n": len(got), "hit": hit, "base_hit": base_hit, "excess_pct": excess, "trades": len(tr),
            "trade_mean_pct": statistics.fmean(tr) * 100 if tr else float("nan"),
            "trade_sum_pct": sum(tr) * 100, "checks": checks, "pass": all(checks.values())}


def measure(days: list[str], flows: dict[str, list[float | None]], opens: dict[str, float]) -> dict:
    zs = {k: zscores(v) for k, v in flows.items()}
    fired = {s: [d for k, d in enumerate(days) if fires(s, {c: zs[c][k] for c in zs})] for s in SIGNALS}
    fwds = {h: forward(days, opens, h) for h in (H, *H_REPORT)}
    out = {}
    for s, (_, direction) in SIGNALS.items():
        out[s] = {}
        for pname, (a, b) in PERIODS.items():
            in_p = [d for d in days if a <= d <= b]
            sd = [d for d in fired[s] if a <= d <= b]
            out[s][pname] = {h: judge(sd, in_p, fwds[h], direction, h, side_cost()) for h in fwds}
            out[s][pname]["reverse"] = judge(sd, in_p, fwds[H], -direction, H, side_cost())
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    days, flows = load()
    ks = L.load_bars("^KS11", "2009-01-01", "2026-11-16")
    opens = {d: ks[d]["open"] for d in ks if ks[d].get("open")}
    keep = [k for k, d in enumerate(days) if d in opens]           # 지수 시가가 있는 날만(대부분 같다)
    days, flows = [days[k] for k in keep], {c: [v[k] for k in keep] for c, v in flows.items()}
    res = measure(days, flows, opens)
    print("=" * 112)
    print(f"수급 판정대 — 확정 수급 {len(days)}일 · z 창 {Z_WIN} · 다음 날 시가 진입 {H}일 보유 · 편도 {side_cost() * 1e4:.1f}bp")
    print(f"  {'':4}{'신호':22}{'구간':4}{'날':>5}{'적중':>7}{'기저':>7}{'초과(%p)':>9}{'매매':>5}{'거래당':>8}{'합계':>8}  "
          f"P1 P2 P3 P4   │ 1일 초과 · 20일 초과 · 반대(되돌림) 초과")
    passed = []
    for s, (desc, _) in SIGNALS.items():
        ok_all = True
        for pname in PERIODS:
            r, r1, r20, rv = (res[s][pname][H], res[s][pname][1], res[s][pname][20], res[s][pname]["reverse"])
            ok_all &= r["pass"]
            ch = " ".join("O " if r["checks"].get(k) else "X " for k in ("P1", "P2", "P3", "P4"))
            print(f"  {s:4}{desc:22}{pname:4}{r['n']:>5}{r.get('hit', 0) * 100:>6.1f}%{r.get('base_hit', 0) * 100:>6.1f}%"
                  f"{r.get('excess_pct', float('nan')):>+9.2f}{r.get('trades', 0):>5}{r.get('trade_mean_pct', float('nan')):>+7.2f}%"
                  f"{r.get('trade_sum_pct', float('nan')):>+7.1f}%  {ch}  │ {r1.get('excess_pct', float('nan')):+.2f} · "
                  f"{r20.get('excess_pct', float('nan')):+.2f} · {rv.get('excess_pct', float('nan')):+.2f}")
        if ok_all:
            passed.append(s)
    print("=" * 112)
    print(f"통과(앞·뒤 구간 모두 P1~P4): {', '.join(passed) if passed else '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
