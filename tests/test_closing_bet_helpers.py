"""direct_closing_bet 순수 헬퍼 + 청산 원장 회귀 테스트 (#11).

direct_closing_bet 모듈은 import 시 .env/pykrx 를 로드하므로 무겁지만 네트워크는 불필요.
STATE_FILE 을 tmp 로 바꿔 원장 집계를 격리 테스트한다.
"""
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def dcb():
    spec = importlib.util.spec_from_file_location("dcb", _ROOT / "scripts" / "direct_closing_bet.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_compute_atr(dcb):
    ohlcv = [{"high": 10 + i, "low": 8 + i, "close": 9 + i} for i in range(20)]
    assert dcb._compute_atr(ohlcv, period=14) == pytest.approx(2.0, abs=0.5)


def test_add_business_days_skips_weekend(dcb):
    # 2026-06-05 는 금요일 → +1 영업일 = 월요일 06-08
    assert dcb._add_business_days("2026-06-05", 1) == "2026-06-08"


def test_order_accepted_return_code(dcb):
    assert dcb._order_accepted({"data": {"return_code": 0}})[0] is True
    assert dcb._order_accepted({"data": {"return_code": 3, "return_msg": "8005"}})[0] is False
    assert dcb._order_accepted({"success": False, "error": "x"})[0] is False


def test_extract_fill_price(dcb):
    assert dcb._extract_fill_price({"data": {"cntr_pric": "+12,345"}}) == 12345.0
    assert dcb._extract_fill_price({"data": {"ord_no": "0001"}}) is None


def test_aggregate_exits_weighted_net(dcb, tmp_path, monkeypatch):
    monkeypatch.setattr(dcb, "STATE_FILE", tmp_path / "state.json")
    ed = "2026-06-03"
    dcb._reset_exit_ledger(ed)
    # 3주: 1주 @1030(+3%), 2주 @990(-1%) → gross = (30 - 20)/3000 = +0.33%
    dcb._append_exit(ed, {"symbol": "A", "company_name": "AA", "entry_price": 1000,
                          "qty": 1, "exit_price": 1030, "when": "09:00"})
    dcb._append_exit(ed, {"symbol": "A", "company_name": "AA", "entry_price": 1000,
                          "qty": 2, "exit_price": 990, "when": "15:10"})
    r = dcb._aggregate_exits(ed)[0]
    assert r["sell_qty"] == 3
    assert r["pnl_pct_gross"] == pytest.approx(0.33, abs=0.01)
    # net = gross - 왕복비용
    assert r["pnl_pct"] == pytest.approx(0.33 - dcb.ROUNDTRIP_COST_PCT, abs=0.01)
    assert r["action"] == "REALIZED"
