"""direct_closing_bet 순수 헬퍼 + 청산 원장 회귀 테스트 (#11).

direct_closing_bet 모듈은 import 시 .env/pykrx 를 로드하므로 무겁지만 네트워크는 불필요.
STATE_FILE 을 tmp 로 바꿔 원장 집계를 격리 테스트한다.
"""
import importlib.util
import json
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


# ── 정보 수집·분석 (뉴스/DART 공시) — 악재 veto ──────────────────────────────
import asyncio
from datetime import date


def test_info_negative_disclosure_veto(dcb, monkeypatch):
    today = date.today().isoformat()
    monkeypatch.setattr(dcb, "_load_disclosures",
                        lambda sym, days=5: [{"date": today, "report_nm": "유상증자결정", "rcept_no": "1"}])
    info = asyncio.run(dcb.analyze_candidate_info(None, None, "000001", "TST", 1, 1, today))
    assert info["has_negative"] is True
    assert any("유상증자" in e["keyword"] for e in info["negative_events"])


def test_info_positive_disclosure_no_veto(dcb, monkeypatch):
    today = date.today().isoformat()
    monkeypatch.setattr(dcb, "_load_disclosures",
                        lambda sym, days=5: [{"date": today, "report_nm": "단일판매ㆍ공급계약체결", "rcept_no": "1"}])
    info = asyncio.run(dcb.analyze_candidate_info(None, None, "000001", "TST", 1, 1, today))
    assert info["has_negative"] is False
    assert info["positive_events"]


def test_info_negative_news_veto(dcb, monkeypatch):
    today = date.today().isoformat()
    async def fake_news(mgr, tool, name):
        return [{"title": "OO전자 횡령 혐의 압수수색", "description": ""}]
    monkeypatch.setattr(dcb, "_fetch_news_items_via", fake_news)
    monkeypatch.setattr(dcb, "_load_disclosures", lambda sym, days=5: [])
    info = asyncio.run(dcb.analyze_candidate_info(object(), "news_tool", "000001", "TST", None, None, today))
    assert info["has_negative"] is True
    assert any(e["src"] == "뉴스" for e in info["negative_events"])


# ── 동적 테마(트렌드) 자동 도출 ──────────────────────────────────────────────

def test_tokenize_news_strips_html_entities(dcb):
    toks = dcb._tokenize_news("삼성전자 &quot;HBM&quot; 반도체 호재")
    assert "반도체" in toks and "HBM" in toks and "quot" not in toks


def test_looks_like_theme(dcb):
    assert dcb._looks_like_theme("원전", set()) is True
    assert dcb._looks_like_theme("HBM", set()) is True       # 대문자 약어
    assert dcb._looks_like_theme("있다", set()) is False      # 불용어
    assert dcb._looks_like_theme("삼성전자와", {"삼성전자"}) is False  # 종목명 접두


def test_load_active_trends_uses_recent_file(dcb, tmp_path, monkeypatch):
    f = tmp_path / "mt.json"
    f.write_text(json.dumps({"date": date.today().isoformat(),
                             "themes": {"원전/전력": ["원전", "SMR"]}}), encoding="utf-8")
    monkeypatch.setattr(dcb, "TRENDS_FILE", f)
    assert dcb.load_active_trends() == {"원전/전력": ["원전", "SMR"]}


def test_load_active_trends_stale_falls_back_static(dcb, tmp_path, monkeypatch):
    f = tmp_path / "mt.json"
    f.write_text(json.dumps({"date": "2020-01-01", "themes": {"원전/전력": ["원전"]}}), encoding="utf-8")
    monkeypatch.setattr(dcb, "TRENDS_FILE", f)
    assert dcb.load_active_trends() is dcb.TREND_KEYWORDS   # 오래됨 → 정적
