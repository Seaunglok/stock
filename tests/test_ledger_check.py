"""장부↔계좌 대조 알림 회귀 — 2026-09-30.

사고: 응답 불명 매도가 실제로 체결됐는데 state 에 삼성E&A 3주가 남았다(유령). reconcile 은
ADOPT_MODE=off 라 계좌를 보지도 않았다 — 그대로 두면 다음 날 없는 주식을 또 팔려 했을 것이다.

여기서 잠그는 것:
  ① 유령(장부에만 있음 / 계좌 수량 < 장부 수량)과 고아(최근 봇이 청산 기록했는데 계좌에 남음)를 알린다
  ② **알림만** 한다 — 장부를 자동으로 고치지 않는다
  ③ 조회 실패는 '보유 0' 이 아니다 — 판단을 건너뛴다(8050 장애일 오판 방지)
  ④ 같은 날 같은 불일치는 한 번만 알린다(reconcile 은 하루 두 번 돈다)
  ⑤ HTS 수동 보유분(봇 기록 없음)은 알리지 않는다 — ADOPT_MODE=off 의 존재 이유
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))


def _pos(sym: str, qty: int) -> dict:
    return {"symbol": sym, "name": f"종목{sym}", "qty": qty, "entry_price": 100.0,
            "stop_price": 90.0, "target": 130.0, "buy_date": "2026-09-28", "journal_id": f"j{sym}"}


def _hold(sym: str, qty: int) -> dict:
    return {"symbol": sym, "name": f"종목{sym}", "qty": qty, "avg": 100, "cur": 100}


@pytest.fixture
def env(monkeypatch, tmp_path):
    import trend_runtime as RT
    for name, fn in (("STATE_FILE", "state.json"), ("STATE_BAK", "state.json.bak"),
                     ("STATE_TMP", "state.json.tmp"), ("JOURNAL_FILE", "journal.json")):
        monkeypatch.setattr(RT, name, tmp_path / fn)
    import trend_follow as TF
    notes: list[tuple[bool, str]] = []
    broker = {"holdings": []}

    async def _notify(msg, critical=False):
        notes.append((critical, msg))

    async def _holdings():
        h = broker["holdings"]
        if isinstance(h, Exception):
            raise h
        return h

    monkeypatch.setattr(TF, "notify", _notify)
    monkeypatch.setattr(TF, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(TF, "_broker_holdings_checked", _holdings)
    monkeypatch.setattr(TF, "FORCE_PHASE", False)
    return TF, notes, broker, tmp_path


def _check(TF):
    asyncio.run(TF._check_ledger_vs_broker())


def _crit(notes):
    return [m for c, m in notes if c]


# ─── ① 유령 ─────────────────────────────────────────────────────────────────
def test_ghost_is_alerted_and_ledger_untouched(env):
    """★ 09-30 재현 — 장부엔 있는데 계좌에 없다. 알리되 장부는 건드리지 않는다."""
    TF, notes, broker, _tmp = env
    TF.save_state("positions", [_pos("028050", 3), _pos("003490", 6)])
    broker["holdings"] = [_hold("003490", 6)]
    _check(TF)
    crit = _crit(notes)
    assert len(crit) == 1 and "028050" in crit[0] and "계좌에 없음" in crit[0]
    assert [p["symbol"] for p in TF.get_state("positions")] == ["028050", "003490"], "장부를 자동 수정했다"


def test_quantity_shortfall_is_a_ghost(env):
    TF, notes, broker, _tmp = env
    TF.save_state("positions", [_pos("003490", 6)])
    broker["holdings"] = [_hold("003490", 2)]
    _check(TF)
    assert len(_crit(notes)) == 1


def test_same_mismatch_alerted_once_per_day(env):
    """reconcile 은 기동·청산 때 하루 두 번 돈다 — 같은 불일치로 두 번 울리면 무시하게 된다."""
    TF, notes, broker, _tmp = env
    TF.save_state("positions", [_pos("028050", 3)])
    broker["holdings"] = [_hold("003490", 6)]
    _check(TF)
    _check(TF)
    assert len(_crit(notes)) == 1


# ─── ① 고아 ─────────────────────────────────────────────────────────────────
def _write_exit(tmp: Path, sym: str, days_ago: int):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    with (tmp / "journal.json").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "type": "exit", "id": f"j{sym}", "symbol": sym, "qty": 3,
                            "net_pct": -1.0}, ensure_ascii=False) + "\n")


def test_orphan_after_recorded_exit_is_alerted(env):
    """★ 반대 방향 — 청산으로 기록했는데 실제로는 안 팔렸다. 이 보유분은 손절 관리 밖이다."""
    TF, notes, broker, tmp = env
    TF.save_state("positions", [])
    _write_exit(tmp, "028050", days_ago=0)
    broker["holdings"] = [_hold("028050", 3)]
    _check(TF)
    crit = _crit(notes)
    assert len(crit) == 1 and "028050" in crit[0] and "계좌에 남" in crit[0]


def test_manual_holding_is_not_alerted(env):
    """★ 봇 기록이 없는 보유분은 HTS 수동 매수다 — ADOPT_MODE=off 가 일부러 두는 것."""
    TF, notes, broker, _tmp = env
    TF.save_state("positions", [])
    broker["holdings"] = [_hold("005930", 10)]
    _check(TF)
    assert _crit(notes) == []


def test_old_exit_is_not_treated_as_orphan(env):
    """오래전에 청산한 종목을 나중에 수동으로 산 경우까지 매일 울리면 안 된다."""
    TF, notes, broker, tmp = env
    TF.save_state("positions", [])
    _write_exit(tmp, "028050", days_ago=TF.LEDGER_ORPHAN_LOOKBACK_DAYS + 3)
    broker["holdings"] = [_hold("028050", 3)]
    _check(TF)
    assert _crit(notes) == []


# ─── ③ 조회 실패는 '보유 0' 이 아니다 ───────────────────────────────────────
def test_query_failure_skips_judgement(env):
    """★ 조회 실패를 빈 계좌로 믿으면 모든 보유를 유령으로 오판한다(8050 IP 장애일)."""
    TF, notes, broker, _tmp = env
    TF.save_state("positions", [_pos("003490", 6)])
    broker["holdings"] = None
    _check(TF)
    assert _crit(notes) == []


def test_check_failure_does_not_break_reconcile(env, monkeypatch):
    """대조가 예외를 내도 reconcile(→청산 phase)은 계속 돈다 — 알림 기능이 청산을 막으면 안 된다."""
    TF, _notes, broker, _tmp = env
    broker["holdings"] = RuntimeError("조회 폭발")
    monkeypatch.setattr(TF, "ADOPT_MODE", "off")
    asyncio.run(TF.phase_reconcile())


def test_reconcile_runs_check_even_when_adopt_off(env, monkeypatch):
    """★ 09-30 엔 ADOPT_MODE=off 라 reconcile 이 계좌를 보지도 않았다."""
    TF, notes, broker, _tmp = env
    monkeypatch.setattr(TF, "ADOPT_MODE", "off")
    TF.save_state("positions", [_pos("028050", 3)])
    broker["holdings"] = [_hold("003490", 6)]
    asyncio.run(TF.phase_reconcile())
    assert any("028050" in m for m in _crit(notes)), "ADOPT_MODE=off 에서 대조가 돌지 않았다"


# ─── 조회 실패/성공 구분 ────────────────────────────────────────────────────
@pytest.mark.parametrize("resp, expected", [
    ({}, None),                                                        # _kiwoom_call 실패
    ({"return_code": 3, "return_msg": "8050", "stk_acnt_evlt_prst": []}, None),
    ({"return_code": 0}, None),                                        # 보유목록 키 없음 = 불완전
    ({"return_code": 0, "stk_acnt_evlt_prst": []}, []),               # 보유 0 이 확인됨
    ({"return_code": 0, "stk_acnt_evlt_prst": [{"stk_cd": "A003490", "stk_nm": "대한항공",
                                                "rmnd_qty": "000006", "avg_prc": "31450",
                                                "cur_prc": "32000"}]},
     [{"symbol": "003490", "name": "대한항공", "qty": 6, "avg": 31450, "cur": 32000}]),
])
def test_holdings_checked_distinguishes_failure_from_empty(monkeypatch, resp, expected):
    import trend_kiwoom_io as IO

    async def _call(*_a, **_k):
        return resp
    monkeypatch.setattr(IO, "_kiwoom_call", _call)
    assert asyncio.run(IO._broker_holdings_checked()) == expected
