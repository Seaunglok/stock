"""AQR 계열 팩터 2종 — 저베타(BAB)·퀄리티(QMJ), 원 출처 규칙의 롱온리판 (2026-10-22, 사전 선언).

운용자(10-22): "펀드회사의 알고리즘, 논문·GitHub 에서 많이 쓰는 알고리즘도 가져와라" · "남은 일 진행해줘"(외부 2차).

원칙: 출처 규칙 그대로, 개인 계좌로 불가능한 부분만 뺀다(공매도·레버리지). 파라미터를 우리 데이터로 고르지 않는다.

선언 (측정 전)
-------------
  BAB  Frazzini·Pedersen(2014) 'Betting Against Beta' — 월말, 대형주 유니버스 중 이력 252일 이상 종목의 252일 일간 수익
       KOSPI 베타를 구해 **하위 20%(20종목) 동일가중**. 원 논문의 레버리지(베타 1 로 맞추기)·고베타 공매도는 뺀다(롱온리).
  QMJ  Asness·Frazzini·Pedersen(2019) 'Quality Minus Junk' — 월말, 유니버스 ∩ DART, **공시 다음 날부터**의 연간 재무로
       퀄리티 = 평균(수익성 백분위[ROE·영업이익/자산], 안전성 백분위[−부채/자본]). 원 논문의 성장·배당 항목은 데이터가
       없어 뺀다. **상위 20%(20종목) 동일가중**, 정크 공매도는 뺀다(롱온리).
  공통: 유니버스 = 리그 '추세추종' 멤버와 같은 KOSPI 대형주 100(backtest_trend_portfolio._load — 리그에서 추가 비용 0).
        주식이라 매도세 포함 비용, 정수 주식수(예탁 364만원 → 종목당 약 18만원, 그보다 비싼 1주는 못 산다 — 실계좌 조건),
        다음 날 시가 체결, 남는 돈은 현금(연구 153130 / 리그 머니마켓).
  ⚠️ 유니버스가 '현재' 시총 상위 100 이라 과거 백테스트엔 생존편향이 있다(수치가 부풀려진다 — 추세추종 08-28 사고와 같은
     종류). 리그(앞으로의 데이터)엔 이 편향이 없다. 그래서 백테스트는 참고, 판정은 리그.
  리그 입장: 원 출처 규칙의 롱온리판 + 운용 가능 → 입장(리그 정책 ①). 2026-10-23 등록.
"""
from __future__ import annotations

import contextlib
import io
import json
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import strategy_lab as L  # noqa: E402

N_PICK = 20
BETA_LOOK = 252
EQUITY = 3_640_000.0
END = L.HOLDOUT[1]
CASH = "153130"
EPISODE = ("2026-05-29", "2026-06-30")


def _series(bars: dict[str, dict]) -> tuple[list[str], dict[str, int], list[float]]:
    days = sorted(bars)
    return days, {d: k for k, d in enumerate(days)}, [bars[d]["close"] for d in days]


def beta(rs: list[float], rm: list[float]) -> float | None:
    if len(rs) < 20 or len(rs) != len(rm):
        return None
    vm = statistics.pvariance(rm)
    if vm <= 0:
        return None
    ms, mm = statistics.fmean(rs), statistics.fmean(rm)
    return sum((a - ms) * (b - mm) for a, b in zip(rs, rm)) / len(rs) / vm


def bab_target(bars: dict[str, dict], kospi: dict, ends: set[str], n_pick: int = N_PICK, look: int = BETA_LOOK):
    """월말 저베타 하위 n_pick 동일가중. target(i, d) — 월말이 아니면 None(유지), 첫날은 현금."""
    ser = {c: _series(b) for c, b in bars.items()}
    kc = {d: v["close"] for d, v in kospi.items()}

    def t(i, d):
        if d not in ends:
            return {} if i == 0 else None
        betas = {}
        for code, (days, pos, cl) in ser.items():
            k = pos.get(d)
            if k is None or k < look:
                continue
            rs, rm = [], []
            for j in range(k - look + 1, k + 1):
                a, b = days[j - 1], days[j]
                if a in kc and b in kc and cl[j - 1] > 0 and kc[a] > 0:
                    rs.append(cl[j] / cl[j - 1] - 1)
                    rm.append(kc[b] / kc[a] - 1)
            bt = beta(rs, rm)
            if bt is not None:
                betas[code] = bt
        if len(betas) < n_pick:
            return {}
        picks = sorted(betas, key=lambda c: (betas[c], c))[:n_pick]
        return {c: 1.0 / n_pick for c in picks}
    return t


def quality_scores(bars: dict[str, dict], fund: dict, d: str) -> dict[str, float]:
    """그날 쓸 수 있는 재무(공시 다음 날부터)로 퀄리티 점수 — 평균(수익성 백분위, 안전성 백분위)."""
    from dart_fundamentals import latest_as_of
    from lab_buffett import pct_rank
    rows = {}
    for code, b in bars.items():
        if d not in b:
            continue
        f = latest_as_of(fund.get(code, {}), d)
        if not f:
            continue
        eq, ni, assets, op, liab = (f.get(x) for x in ("equity", "net_income", "assets", "op_income", "liabilities"))
        if None in (eq, ni, assets, op, liab) or eq <= 0 or assets <= 0:
            continue
        rows[code] = {"roe": ni / eq, "opa": op / assets, "lev": -liab / eq}
    if not rows:
        return {}
    r = {m: pct_rank({c: v[m] for c, v in rows.items()}) for m in ("roe", "opa", "lev")}
    return {c: ((r["roe"][c] + r["opa"][c]) / 2 + r["lev"][c]) / 2 for c in rows}


def qmj_target(bars: dict[str, dict], fund: dict, ends: set[str], n_pick: int = N_PICK):
    def t(i, d):
        if d not in ends:
            return {} if i == 0 else None
        sc = quality_scores(bars, fund, d)
        if len(sc) < n_pick:
            return {}
        picks = sorted(sc, key=lambda c: (-sc[c], c))[:n_pick]
        return {c: 1.0 / n_pick for c in picks}
    return t


def load_universe(end: str) -> dict[str, dict]:
    import backtest_trend_portfolio as P
    with contextlib.redirect_stdout(io.StringIO()):
        _dates, bars, _c, _o = P._load("2015-01-01", end, 100)
    return bars


def load_fund() -> dict:
    from dart_fundamentals import OUT
    return json.loads(OUT.read_text(encoding="utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import lab_classics as C
    import lab_holdout as H
    k = L.load_bars("069500", "2014-01-01", END)
    c = L.load_bars(CASH, "2014-01-01", END)
    ks = L.load_bars("^KS11", "1996-01-01", END)
    bars = load_universe(END)
    fund = load_fund()
    dates = [d for d in L.calendar(k, L.FULL[0], END) if d in c]
    ends = C.month_ends(sorted(k))
    stock_assets = {code: L.Asset(code, b, True) for code, b in bars.items()}

    def run(target):
        def tt(i, d):
            r = target(i, d)
            if r is None:
                return None
            out = dict(r)
            rest = 1.0 - sum(out.values())
            if rest > 1e-9:
                out[CASH] = rest
            return out
        return L.simulate({**stock_assets, CASH: L.Asset(CASH, c)}, dates, tt, EQUITY)

    res = {"KODEX200 보유": L.buy_and_hold("069500", dates, k, EQUITY),
           "I3": L.simulate({"069500": L.Asset("069500", k), CASH: L.Asset(CASH, c)}, dates,
                            H.i3(k, ks, "069500", CASH, *H.I3_DEFAULT), EQUITY, pass_nav=True),
           "BAB": run(bab_target(bars, ks, ends)),
           "QMJ": run(qmj_target(bars, fund, ends))}
    print("=" * 104)
    print(f"AQR 팩터(롱온리) — 대형주 100(⚠️ 현재 시총 기준 → 생존편향), 예탁 {EQUITY:,.0f}원, 2015-07~2026-08")
    print(f"  {'':14}{'연수익':>8}{'MDD':>7}{'최악':>7}{'박스권':>8}{'강세장':>8}{'미공개':>8}{'6월 사례':>9}{'매매':>6}  제1원칙")
    for n, r in res.items():
        s = {sp: L.slice_metrics(r, *rng) for sp, rng in
             (("전체", L.FULL), ("박스권", L.PERIODS["박스권"]), ("강세장", L.PERIODS["강세장"]),
              ("미공개", L.HOLDOUT), ("사례", EPISODE))}
        ok = s["전체"]["mdd"] <= L.MAX_MDD_PCT and s["전체"]["worst_year"] >= L.MIN_YEAR_RET_PCT
        print(f"  {n:14}{s['전체']['cagr']:>7.2f}%{s['전체']['mdd']:>6.1f}%{s['전체']['worst_year']:>+6.1f}%"
              f"{s['박스권']['cagr']:>7.1f}%{s['강세장']['cagr']:>7.1f}%{s['미공개']['total']:>+7.1f}%"
              f"{s['사례']['total']:>+8.1f}%{r.trades:>6}  {'O' if ok else 'x'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
