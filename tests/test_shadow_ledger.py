"""그림자 원장 회귀 — 2026-08-05 코드리뷰로 수정한 결함 D1~D6 이 되돌아오지 않게.

이 모듈은 게이트 판정 숫자를 만드는 측정 코드다. 여기가 조용히 틀리면 전략 결정이 틀린다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import shadow_ledger as sl  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """실제 원장/분봉을 건드리지 않도록 경로를 tmp 로 격리."""
    monkeypatch.setattr(sl, "SHADOW_FILE", tmp_path / "shadow.jsonl")
    monkeypatch.setattr(sl, "MINUTE_DIR", tmp_path / "minute")
    return tmp_path


def _bars(start: str, closes, highs=None, lows=None) -> list[dict]:
    d0 = datetime.strptime(start, "%Y-%m-%d")
    out = []
    for i, c in enumerate(closes):
        out.append({"date": (d0 + timedelta(days=i)).strftime("%Y-%m-%d"),
                    "open": c, "close": c,
                    "high": (highs[i] if highs else c), "low": (lows[i] if lows else c),
                    "volume": 1000})
    return out


# 추적 중인 레코드는 '최근'이어야 한다 — 오래된 레코드는 D4 포기 규칙에 걸린다.
RECENT = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")


def _rec(**kw) -> dict:
    base = {"date": RECENT, "symbol": "005930", "name": "삼성전자",
            "reason": "no_slot", "ref_price": 100.0, "stop": 90.0, "target": 130.0}
    base.update(kw)
    return base


# ─── D1: taken 은 실체결가로 평가해야 R 이 성립 ────────────────────────────
def test_entry_actual_takes_precedence_over_proxy():
    r = _rec(reason="taken", entry_actual=100.0)
    bars = _bars(RECENT, [111.0] + [111.0] * 25)      # 그날 종가는 111 (프록시라면 이 값)
    sl._evaluate(r, bars)
    assert r["entry_ref"] == 100.0, "실체결가가 있으면 종가 프록시를 쓰면 안 된다"
    assert r["entry_src"] == "actual"


def test_taken_r_uses_actual_risk():
    """entry=100, stop=90 → risk 10. 손절 선행이면 정확히 -1R."""
    r = _rec(reason="taken", entry_actual=100.0)
    bars = _bars(RECENT, [100.0] + [95.0] * 25, lows=[100.0] + [89.0] * 25)
    sl._evaluate(r, bars)
    assert r["outcome"] == "stop"
    assert r["r"] == -1.0


# ─── D2: 손절/목표가 나도 추적 기간을 다 채울 때까지 확정하지 않는다 ──────────
def test_stop_hit_does_not_finalize_early():
    r = _rec()
    bars = _bars(RECENT, [100.0] + [95.0] * 3, lows=[100.0] + [89.0] * 3)
    done = sl._evaluate(r, bars)
    assert r["outcome"] == "stop"
    assert done is False, "3봉만 있는데 확정하면 D+5/D+20 이 영구 결측된다(생존편향)"


def test_finalizes_when_horizon_filled():
    r = _rec()
    bars = _bars(RECENT, [100.0] + [95.0] * sl.MAX_TRACK_DAYS,
                 lows=[100.0] + [89.0] * sl.MAX_TRACK_DAYS)
    assert sl._evaluate(r, bars) is True
    assert r["tracked"] == sl.MAX_TRACK_DAYS


def test_fwd_keeps_filling_after_stop():
    """손절 후에도 D+N 지표는 계속 채워져야 한다 — 표본에서 패자만 빠지면 안 된다."""
    r = _rec()
    bars = _bars(RECENT, [100.0] + [95.0] * sl.MAX_TRACK_DAYS,
                 lows=[100.0] + [89.0] * sl.MAX_TRACK_DAYS)
    sl._evaluate(r, bars)
    assert r["outcome"] == "stop"
    assert set(r["fwd"]) == {str(h) for h in sl.HORIZONS}


def test_outcome_frozen_at_first_hit():
    """첫 도달 이후 반대 신호가 나와도 outcome/hit_day 는 안 바뀐다."""
    closes = [100.0] + [95.0] * sl.MAX_TRACK_DAYS
    lows = [100.0, 89.0] + [95.0] * (sl.MAX_TRACK_DAYS - 1)
    highs = [100.0, 95.0] + [140.0] * (sl.MAX_TRACK_DAYS - 1)     # 나중에 목표 돌파
    r = _rec()
    sl._evaluate(r, _bars(RECENT, closes, highs=highs, lows=lows))
    assert (r["outcome"], r["hit_day"]) == ("stop", 1)


def test_stop_wins_when_both_hit_same_day():
    r = _rec()
    bars = _bars(RECENT, [100.0, 100.0], highs=[100.0, 140.0], lows=[100.0, 80.0])
    sl._evaluate(r, bars)
    assert r["outcome"] == "stop", "같은 날 양쪽 도달은 보수적으로 손절 선행"


# ─── D3: 과거 레코드는 그 당시 진입 시각으로 평가 ──────────────────────────
@pytest.mark.parametrize("date,expected", [
    ("2026-07-22", "09:30"),      # 진입시각 변경 전
    ("2026-07-31", "09:30"),
    ("2026-08-03", "11:00"),      # 변경 시행일
    ("2026-08-05", "11:00"),
])
def test_historic_entry_time_mapping(date, expected):
    assert sl._entry_time_for(date) == expected


def test_record_stamp_beats_history_table():
    """설정이 또 바뀌어도 스탬프된 레코드는 자기 시각을 유지한다."""
    assert sl._entry_time_for("2026-08-05", {"entry_time": "13:00"}) == "13:00"


def test_minute_proxy_uses_record_entry_time(_isolate):
    d = _isolate / "minute" / "2026-07-22"
    d.mkdir(parents=True)
    (d / "005930.json").write_text(json.dumps([
        {"ts": "202607220930", "open": 900.0, "high": 900.0, "low": 900.0, "close": 900.0},
        {"ts": "202607221100", "open": 1100.0, "high": 1100.0, "low": 1100.0, "close": 1100.0},
    ]), encoding="utf-8")
    price, src = sl._entry_proxy("005930", "2026-07-22", {"close": 5.0})
    assert (price, src) == (900.0, "minute"), "07-22 는 09:30 진입이었다"


# ─── D4: 해소 불가 레코드는 포기 ───────────────────────────────────────────
def test_missing_bar_retries_while_recent():
    r = _rec(date=datetime.now().strftime("%Y-%m-%d"))
    assert sl._evaluate(r, _bars("2020-01-01", [100.0])) is False
    assert "outcome" not in r


def test_missing_bar_gives_up_when_stale():
    old = (datetime.now() - timedelta(days=sl.GIVEUP_AFTER_DAYS + 5)).strftime("%Y-%m-%d")
    r = _rec(date=old)
    assert sl._evaluate(r, _bars("2020-01-01", [100.0])) is True
    assert r["outcome"] == "unknown", "상장폐지/조회범위 초과분이 매일 재시도되면 안 된다"


# ─── D5: taken 은 기존 차단 레코드를 교체 ──────────────────────────────────
def test_duplicate_block_reason_is_ignored():
    sl.record("size_zero", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    sl.record("no_slot", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    recs = sl._load()
    assert len(recs) == 1 and recs[0]["reason"] == "size_zero", "먼저 걸린 사유를 보존"


def test_taken_replaces_earlier_block():
    sl.record("size_zero", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    sl.record("taken", [{"symbol": "005930", "name": "삼성전자", "price": 100,
                         "entry_actual": 101.0}])
    recs = sl._load()
    assert len(recs) == 1, "중복 기록이 아니라 교체여야 한다"
    assert recs[0]["reason"] == "taken" and recs[0]["entry_actual"] == 101.0


def test_taken_replacement_keeps_other_symbols():
    sl.record("no_slot", [{"symbol": "000660", "name": "SK하이닉스", "price": 200}])
    sl.record("size_zero", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    sl.record("taken", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    syms = sorted(r["symbol"] for r in sl._load())
    assert syms == ["000660", "005930"]


# ─── D6: 저장 중 동시 기록 병합 ────────────────────────────────────────────
def test_save_merges_concurrent_append():
    sl.record("no_slot", [{"symbol": "005930", "name": "삼성전자", "price": 100}])
    snapshot = sl._load()                       # update() 가 읽어간 시점
    sl.record("regime", [{"symbol": "000660", "name": "SK하이닉스", "price": 200}])   # 그 사이 데몬이 append
    snapshot[0]["done"] = True
    sl._save(snapshot)
    syms = sorted(r["symbol"] for r in sl._load())
    assert syms == ["000660", "005930"], "스냅샷 덮어쓰기로 동시 기록이 유실되면 안 된다"


# ─── 기록 자체가 매매를 막지 않는다 ────────────────────────────────────────
def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(sl, "_load", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sl.record("no_slot", [{"symbol": "005930"}]) == 0


def test_record_empty_is_noop():
    assert sl.record("no_slot", []) == 0
    assert sl._load() == []
