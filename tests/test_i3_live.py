"""I3 실전 — 판단 일치·주문 안전장치 회귀 (2026-10-22).

이 코드가 실계좌 주문을 낸다. 검증한 전략과 같은 판단을 하는지(실데이터 대조), 모의 모드에서 주문이
절대 안 나가는지, 응답 불명 주문을 재전송하지 않는지 — 안전장치는 **일부러 깨뜨려** 발동을 확인한다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import i3_live as LV  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ─── 판단 핵심 ────────────────────────────────────────────────────────────────
def test_declared_constants_come_from_validated_lab():
    """★ 실전 상수는 검증 선언값을 import 한다 — 따로 적으면 조용히 갈린다."""
    import lab_holdout as H
    assert (K.M, K.LOOKBACK) == H.I3_DEFAULT == (6, 252)
    assert K.FLOOR_DD == H.I3_FLOOR_DD == 18.0 and K.BAND == H.I3_BAND == 0.10
    assert (K.BASE, K.CASH, K.REPLAY_START) == ("069500", "153130", "2015-07-28")


def test_budget_exposure():
    assert K.budget_exposure([100.0]) == 1.0                         # 6 × 18% ≥ 1
    assert K.budget_exposure([100.0, 82.0]) == 0.0                   # 바닥
    assert K.budget_exposure([100.0, 91.0]) == pytest.approx(6 * 9 / 91)


@pytest.mark.parametrize("eng, navs, prev, exp_w, exp_need", [
    (K.EngineState(True, False, "d"), [100.0], None, 1.0, True),          # 첫 판단
    (K.EngineState(False, True, "d"), [100.0], 1.0, 0.0, True),           # 엔진 이탈 전환
    (K.EngineState(True, False, "d"), [100.0, 99.0], 1.0, 1.0, False),    # 변화 < 10%p → 유지
    (K.EngineState(True, False, "d"), [100.0, 91.0], 1.0, 6 * 9 / 91, True),  # 비중 0.59 → 매매
    (K.EngineState(True, False, "d"), [100.0, 82.0], 0.05, 0.0, True),    # 0 으로
])
def test_decide_rules(eng, navs, prev, exp_w, exp_need):
    w, need, _ = K.decide(eng, navs, prev)
    assert need is exp_need and w == pytest.approx(exp_w if need else prev)


def test_order_plan_sells_before_buys_and_floors_shares():
    tgt = K.target_shares(0.5, 1_000_000, {K.BASE: 90_000, K.CASH: 113_000})
    assert tgt == {K.BASE: 5, K.CASH: 4}                             # 495,000 // 90,000 = 5
    plan = K.order_plan({K.CASH: 8}, tgt)
    assert plan == [("sell", K.CASH, 4), ("buy", K.BASE, 5)]


def test_live_decisions_match_validated_backtest_on_real_data():
    """★ 같은 가격·같은 자산 이력이면 실전 판단 == 검증한 lab_holdout.i3 판단 (실데이터, 표본 날짜)."""
    import strategy_lab as L
    import lab_holdout as H
    cache = _ROOT / "docs_cache" / "lab"
    if not (cache / "069500_2026-08-24.json").exists() or not (cache / "IDX_KS11_2026-08-24.json").exists():
        pytest.skip("검증 캐시 없음")
    kodex = L.load_bars("069500", "2014-01-01", L.FULL[1])
    cash = L.load_bars("153130", "2014-01-01", L.FULL[1])
    ks = L.load_bars("^KS11", "1996-01-01", L.FULL[1])
    dates = L.calendar(kodex, *L.FULL)
    lab_t = H.i3(kodex, ks, K.BASE, K.CASH, *H.I3_DEFAULT)
    seen = []

    def probe(i, d, nav):
        w = lab_t(i, d, nav)
        seen.append((d, nav, None if w is None else w.get(K.BASE, 0.0)))
        return w
    L.simulate({K.BASE: L.Asset(K.BASE, kodex), K.CASH: L.Asset(K.CASH, cash)}, dates, probe,
               3_852_844.0, pass_nav=True)
    navs, prev = [], None
    sample = set(range(0, len(seen), 37)) | {k for k, (_, _, w) in enumerate(seen) if w is not None}
    checked = 0
    for k, (d, nav, lab_w) in enumerate(seen):
        navs.append(nav)
        if k in sample:                     # 매매가 일어난 모든 날(178) + 37일 간격 표본
            eng = K.engine_state(kodex, ks, d)
            w, need, _ = K.decide(eng, navs, prev)
            assert need == (lab_w is not None), f"{d} 매매 여부 불일치"
            if need:
                assert w == pytest.approx(lab_w), f"{d} 비중 불일치"
            checked += 1
        if lab_w is not None:
            prev = lab_w
    assert checked >= 200, f"대조한 날이 {checked}일뿐 — 검증이 비어 있다"


# ─── 가짜 외부 의존 ──────────────────────────────────────────────────────────
def _bars(days, start=100.0, step=0.1):
    return {d: {"open": start + i * step, "close": start + i * step} for i, d in enumerate(days)}


class FakeMarket:
    def __init__(self, days, today, drift=0.0):
        self.days = days
        self.base = _bars(days)
        self.kospi = _bars(days, 2000.0, 1.0)
        self.today = today
        self.drift = drift

    async def base_bars(self):
        return {d: v for d, v in self.base.items() if d < self.today}

    async def kospi_bars(self):
        return {d: v for d, v in self.kospi.items() if d < self.today}

    async def recent(self, code):
        src = self.kospi if code == "KOSPI" else self.base
        out = {d: dict(v) for d, v in list(src.items())[-60:]}
        if self.drift:
            for v in out.values():
                v["close"] *= 1 + self.drift
        return out


class FakeBroker:
    def __init__(self, holdings=None, equity=(3_800_000.0, 3_600_000.0), allow_orders=True,
                 responses=None, after=None):
        self._h = holdings if holdings is not None else []
        self._eq = equity
        self.allow = allow_orders
        self.placed = []
        self.responses = responses or {}
        self.after = after
        self.calls = 0

    async def holdings(self):
        self.calls += 1
        if self.after is not None and self.placed:
            return self.after
        return self._h

    async def equity(self):
        return self._eq

    async def place(self, side, code, qty):
        if not self.allow:
            raise AssertionError("모의 모드에서 주문이 나갔다")
        self.placed.append((side, code, qty))
        return self.responses.get((side, code), {"success": True, "data": {"return_code": 0}})


class Notes:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg, critical=False):
        self.msgs.append((critical, msg))


def _days(n=3000):
    from datetime import date, timedelta
    d0 = date(2015, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "state.json", tmp_path / "events.jsonl"


# ─── 판단 단계 ────────────────────────────────────────────────────────────────
def test_decide_refuses_before_close(paths):
    days = _days()
    today = days[-1]
    now = datetime.fromisoformat(today + "T14:00:00")
    r = run(LV.phase_decide(FakeMarket(days, today), FakeBroker(), Notes(), now, *paths))
    assert "skip" in r and not paths[0].exists()


def test_decide_skips_when_today_bar_missing(paths):
    """휴장·미갱신 — 오늘 일봉이 없으면 판단하지 않는다."""
    days = _days()
    m = FakeMarket(days[:-1], days[-1])
    now = datetime.fromisoformat(days[-1] + "T15:50:00")
    r = run(LV.phase_decide(m, FakeBroker(), Notes(), now, *paths))
    assert "skip" in r and not paths[0].exists()


def test_decide_aborts_on_source_mismatch(paths):
    """★ 키움 최근 일봉이 장기 이력과 0.5% 넘게 다르면 판단 중단 + critical."""
    days = _days()
    notes = Notes()
    now = datetime.fromisoformat(days[-1] + "T15:50:00")
    r = run(LV.phase_decide(FakeMarket(days, days[-1], drift=0.02), FakeBroker(), notes, now, *paths))
    assert "abort" in r and any(c for c, _ in notes.msgs) and not paths[0].exists()


def test_decide_aborts_when_holdings_unknown(paths):
    """★ 계좌 조회 실패를 '보유 0' 으로 믿지 않는다."""
    days = _days()
    b = FakeBroker()

    async def none():
        return None
    b.holdings = none
    now = datetime.fromisoformat(days[-1] + "T15:50:00")
    r = run(LV.phase_decide(FakeMarket(days, days[-1]), b, Notes(), now, *paths))
    assert "abort" in r and not paths[0].exists()


def test_decide_writes_pending_and_is_idempotent_same_day(paths):
    days = _days()
    now = datetime.fromisoformat(days[-1] + "T15:50:00")
    hold = [{"symbol": "096770", "name": "SK이노베이션", "qty": 1, "avg": 152700, "cur": 142200}]
    b = FakeBroker(holdings=hold, equity=(3_790_000.0, 3_640_000.0))
    r = run(LV.phase_decide(FakeMarket(days, days[-1]), b, Notes(), now, *paths))
    st = json.loads(paths[0].read_text(encoding="utf-8"))
    assert r["nav"] == 3_790_000 - 142_200                          # I3 외 보유분 제외
    assert st["pending"]["decided_on"] == days[-1] and st["pending"]["w"] == pytest.approx(1.0)
    run(LV.phase_decide(FakeMarket(days, days[-1]), b, Notes(), now, *paths))
    st2 = json.loads(paths[0].read_text(encoding="utf-8"))
    assert len(st2["navs"]) == 1, "같은 날 재실행이 자산 이력을 중복 기록했다"


# ─── 매매 단계 ────────────────────────────────────────────────────────────────
def _seed(path, w=1.0, decided="2026-10-21", **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    st = {"pending": {"decided_on": decided, "w": w, "reason": "t"}, "w": w, **extra}
    path.write_text(json.dumps(st), encoding="utf-8")


NOW = datetime(2026, 10, 22, 8, 50)
PRICES = {K.BASE: 90_000.0, K.CASH: 113_000.0}


def test_dry_run_never_places_orders(paths):
    """★ 모의 모드 — 주문 도구가 불리면 FakeBroker 가 AssertionError 를 낸다(일부러 깨뜨리기)."""
    _seed(paths[0])
    b = FakeBroker(holdings=[{"symbol": K.CASH, "qty": 30, "cur": 113000, "name": "x", "avg": 0}],
                   allow_orders=False)
    r = run(LV.phase_trade(b, Notes(), NOW, PRICES, *paths, dry_run=True))
    assert r["orders"] and r["note"].startswith("모의")
    st = json.loads(paths[0].read_text(encoding="utf-8"))
    assert st["traded_on"] == "2026-10-22" and "pending" not in st


def test_real_trade_sells_first_then_waits_then_buys(paths):
    _seed(paths[0])
    hold = [{"symbol": K.CASH, "qty": 30, "cur": 113000, "name": "x", "avg": 0}]
    b = FakeBroker(holdings=hold, equity=(3_400_000.0, 10_000.0))
    order = []

    async def waited():
        order.append(("wait",))
    r = run(LV.phase_trade(b, Notes(), NOW, PRICES, *paths, dry_run=False, wait_after_open=waited))
    seq = [p[0] for p in b.placed]
    assert seq and seq[0] == "sell" and seq[-1] == "buy"
    assert r["target"][K.BASE] == int(3_400_000 * 0.99 // 90_000)


def test_unknown_order_is_not_resent_and_alerts(paths):
    """★ 응답 불명 주문은 한 번만 — 재전송 없음, critical 알림."""
    _seed(paths[0])
    hold = [{"symbol": K.CASH, "qty": 30, "cur": 113000, "name": "x", "avg": 0}]
    b = FakeBroker(holdings=hold, equity=(3_400_000.0, 0.0),
                   responses={("sell", K.CASH): {"success": False, "unknown": True}})
    notes = Notes()
    run(LV.phase_trade(b, notes, NOW, PRICES, *paths, dry_run=False))
    assert sum(1 for s, c, _ in b.placed if (s, c) == ("sell", K.CASH)) == 1
    assert any(c and "응답 불명" in m for c, m in notes.msgs)


def test_post_trade_mismatch_alerts(paths):
    _seed(paths[0])
    hold = [{"symbol": K.CASH, "qty": 30, "cur": 113000, "name": "x", "avg": 0}]
    b = FakeBroker(holdings=hold, equity=(3_400_000.0, 0.0), after=hold)   # 체결 안 된 것처럼
    notes = Notes()
    run(LV.phase_trade(b, notes, NOW, PRICES, *paths, dry_run=False))
    assert any(c and "목표와 다름" in m for c, m in notes.msgs)


@pytest.mark.parametrize("kw, seed_extra, now, reason", [
    ({"halt": True}, {}, NOW, "I3_HALT"),
    ({}, {"traded_on": "2026-10-22"}, NOW, "이미"),
    ({}, {}, datetime(2026, 10, 22, 10, 30), "시간대"),
])
def test_trade_guards(paths, kw, seed_extra, now, reason):
    _seed(paths[0], **seed_extra)
    b = FakeBroker(allow_orders=False)
    r = run(LV.phase_trade(b, Notes(), now, PRICES, *paths, dry_run=False, **kw))
    assert reason in r.get("skip", "")


def test_stale_plan_is_dropped(paths):
    _seed(paths[0], decided="2026-10-10")
    b = FakeBroker(allow_orders=False)
    notes = Notes()
    r = run(LV.phase_trade(b, notes, NOW, PRICES, *paths, dry_run=False))
    assert "오래된" in r["skip"] and any(c for c, _ in notes.msgs)
    assert "pending" not in json.loads(paths[0].read_text(encoding="utf-8"))


def test_trade_aborts_when_holdings_unknown(paths):
    _seed(paths[0])
    b = FakeBroker(allow_orders=False)

    async def none():
        return None
    b.holdings = none
    r = run(LV.phase_trade(b, Notes(), NOW, PRICES, *paths, dry_run=False))
    assert "abort" in r


def test_dry_run_is_default():
    """★ 환경변수가 없으면 모의 — 실주문은 운용자가 명시적으로 켠다."""
    import os
    old = os.environ.pop("I3_DRY_RUN", None)
    try:
        assert LV._env_bool("I3_DRY_RUN", True) is True
    finally:
        if old is not None:
            os.environ["I3_DRY_RUN"] = old
