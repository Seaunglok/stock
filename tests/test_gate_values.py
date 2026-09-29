"""게이트 통과값 기록 회귀 — 2026-09-29.

배경: 레짐·breadth 값은 **막힌 날만** events 에 남았다(regime_block / breadth_block).
통과한 날의 11:00 breadth 는 어디에도 없었다 — 장중 스냅샷(ka20003)이라 나중에 복원도 못 한다.
레짐 개방(09-21) 후 6거래일 중 4일을 breadth 가 막았는데, 임계 40% 가 맞는지 판정하려면
통과한 날의 값도 있어야 한다(막힌 날 값만으로는 분포의 한쪽뿐이다).

여기서 잠그는 것:
  ① 통과한 날 레짐·breadth 값이 `gates_pass` 로 남는다 (11:00 경로 · 장중 보류 재시도 경로)
  ② 막힌 날의 동작은 그대로다 — 기록 한 줄이 게이트 판정을 바꾸면 안 된다
  ③ 기록 실패가 진입을 막지 않는다 — 원격측정이 주문 경로를 끊으면 안 된다
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

CANDS = [{"symbol": "000001", "name": "테스트", "score": 50.0}]


@pytest.fixture
def env(monkeypatch, tmp_path):
    """state 경로 3종을 임시로 돌리고, 시장 조회·알림·원장을 가짜로 바꾼 trend_follow.

    반환 (TF, events, market) — market 을 고쳐 시장 상황을 바꾼다.
    """
    import trend_runtime as RT
    monkeypatch.setattr(RT, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(RT, "STATE_BAK", tmp_path / "state.json.bak")
    monkeypatch.setattr(RT, "STATE_TMP", tmp_path / "state.json.tmp")
    import trend_follow as TF

    events: list[tuple[str, dict]] = []
    market = {"above": True, "breadth": 0.55, "rows": True}

    async def _kospi():
        closes = [100.0] * 80
        closes[-1] = 110.0 if market["above"] else 90.0    # MA60 ≈ 100.2 / 99.8
        return closes

    async def _rows():
        return [{"sector": "가짜"}] if market["rows"] else None

    async def _no_circuit():
        return False, ""

    async def _quiet(*_a, **_k):
        return None

    monkeypatch.setattr(TF, "log_event", lambda ev, payload=None: events.append((ev, payload)))
    monkeypatch.setattr(TF, "shadow_record", lambda *a, **k: 0)
    monkeypatch.setattr(TF, "notify", _quiet)
    monkeypatch.setattr(TF, "_kospi_closes", _kospi)
    monkeypatch.setattr(TF, "_sector_index_rows", _rows)
    monkeypatch.setattr(TF, "market_breadth", lambda _r: market["breadth"])
    monkeypatch.setattr(TF, "_circuit_broken", _no_circuit)
    monkeypatch.setattr(TF, "REGIME_MA", 60)
    monkeypatch.setattr(TF, "BREADTH_MIN_PCT", 0.4)
    return TF, events, market


def _named(events, name):
    return [p for ev, p in events if ev == name]


# ─── ① 11:00 경로 — 통과한 날의 값이 남는다 ──────────────────────────────────
def test_pass_day_records_regime_and_breadth(env):
    """★ 통과한 날도 KOSPI·MA·breadth 가 남아야 한다 — 09-28 진입일엔 아무 값도 없었다."""
    TF, events, _m = env
    assert asyncio.run(TF._market_gates(CANDS)) == CANDS, "통과해야 할 날을 막았다"
    rec = _named(events, "gates_pass")
    assert len(rec) == 1, f"통과 기록이 {len(rec)}건"
    p = rec[0]
    assert p["kospi"] == 110.0 and p["ma_n"] == 60
    assert p["ma"] == pytest.approx(100.2, abs=0.05)
    assert p["breadth"] == 0.55 and p["breadth_min"] == 0.4
    assert p["candidates"] == 1


def test_missing_breadth_is_recorded_as_none(env):
    """업종지수를 못 받으면 breadth 는 fail-open 으로 통과한다 — 그 사실이 데이터에 보여야 한다.

    값이 없는 채로 통과한 날과, 40% 이상으로 통과한 날을 나중에 구분할 수 있어야 한다.
    """
    TF, events, m = env
    m["rows"] = False
    assert asyncio.run(TF._market_gates(CANDS)) == CANDS
    rec = _named(events, "gates_pass")
    assert rec and "breadth" in rec[0] and rec[0]["breadth"] is None


# ─── ② 막힌 날의 동작은 그대로 ──────────────────────────────────────────────
def test_regime_block_unchanged(env):
    TF, events, m = env
    m["above"] = False
    assert asyncio.run(TF._market_gates(CANDS)) is None
    assert _named(events, "regime_block"), "레짐 차단 기록이 사라졌다"
    assert not _named(events, "gates_pass"), "막힌 날을 통과로 기록했다"


def test_breadth_block_unchanged(env):
    TF, events, m = env
    m["breadth"] = 0.30
    assert asyncio.run(TF._market_gates(CANDS)) is None
    assert _named(events, "breadth_block"), "breadth 차단 기록이 사라졌다"
    assert not _named(events, "gates_pass")
    assert TF.get_state("pending_entries") == CANDS, "breadth 차단 후보가 보류로 남지 않았다"


# ─── ③ 기록 실패가 진입을 막지 않는다 ───────────────────────────────────────
def test_logging_failure_does_not_block_entry(env, monkeypatch):
    """★ 원격측정 한 줄이 디스크 오류로 예외를 내도 게이트 판정은 그대로 통과해야 한다."""
    TF, _events, _m = env

    def boom(ev, payload=None):
        if ev == "gates_pass":
            raise OSError("디스크 가득 참")
    monkeypatch.setattr(TF, "log_event", boom)
    assert asyncio.run(TF._market_gates(CANDS)) == CANDS


# ─── 장중 보류 재시도 경로 — 실제 진입 대부분이 여기서 난다(09-28 대한항공) ──
@pytest.fixture
def pending_env(env, monkeypatch):
    TF, events, market = env
    TF.save_state("pending_entries", CANDS)
    TF.save_state("pending_date", datetime.now().strftime("%Y-%m-%d"))
    TF.save_state("positions", [])
    monkeypatch.setattr(TF, "_past_entry_cutoff", lambda: False)

    class _MCP:
        tools = [{"name": "place_buy_order"}]

        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    async def _rising(_sym):
        return 110.0, 100.0

    async def _buy(_mcp, c, _tag):
        return {"symbol": c["symbol"], "name": c["name"], "qty": 1, "entry_price": 110.0,
                "stop_price": 99.0, "target": 140.0, "score": c["score"]}

    async def _verify(bought, positions):
        return bought, positions

    monkeypatch.setattr(TF, "MCPManager", _MCP)
    monkeypatch.setattr(TF, "_cur_and_open", _rising)
    monkeypatch.setattr(TF, "_buy_one", _buy)
    monkeypatch.setattr(TF, "_verify_buy_fills", _verify)
    return TF, events, market


def test_pending_entry_records_breadth_at_fill(pending_env):
    """★ 보류분이 실제로 체결된 순간의 breadth 가 남아야 한다."""
    TF, events, _m = pending_env
    asyncio.run(TF._try_pending())
    rec = _named(events, "gates_pass")
    assert len(rec) == 1, f"보류 체결 기록이 {len(rec)}건"
    assert rec[0]["phase"] == "pending" and rec[0]["breadth"] == 0.55
    assert rec[0]["symbols"] == ["000001"]
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"], "체결분이 저장되지 않았다"


def test_pending_poll_without_fill_logs_nothing(pending_env, monkeypatch):
    """반등하지 않아 안 산 폴링은 기록하지 않는다 — 10분마다 쌓이는 잡음 방지."""
    TF, events, _m = pending_env

    async def _falling(_sym):
        return 90.0, 100.0
    monkeypatch.setattr(TF, "_cur_and_open", _falling)
    asyncio.run(TF._try_pending())
    assert not _named(events, "gates_pass")
    assert TF.get_state("pending_entries") == CANDS, "안 산 보류분이 사라졌다"


def test_pending_logging_failure_keeps_fill_bookkeeping(pending_env, monkeypatch):
    """★ 기록 실패가 체결 확인·저장·보류해제 3줄을 건너뛰게 하면 안 된다.

    그 3줄이 빠지면 산 종목이 보류에 남아 다음 폴링이 재매수한다(07월 사고와 같은 경로).
    """
    TF, _events, _m = pending_env

    def boom(ev, payload=None):
        if ev == "gates_pass":
            raise OSError("디스크 가득 참")
    monkeypatch.setattr(TF, "log_event", boom)
    asyncio.run(TF._try_pending())
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"], "체결분 저장이 끊겼다"
    assert TF.get_state("pending_entries") == [], "산 종목이 보류에 남았다 — 재매수 경로"
