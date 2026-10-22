"""외인 수급 수집 회귀 — 2026-09-29.

배경: 외인 청산을 끈 08-28 이후 ka10008 수집이 조용히 멈췄다(유일한 호출이 스위치에 묶여 있었다).
ka10008 은 최근 ~50 완성일만 주므로 그보다 오래 비우면 중간 날짜가 영구히 사라진다.

여기서 잠그는 것:
  ① 잠정치(스냅샷 당일)는 이력에 넣지 않고, 같은 날짜는 나중 스냅샷이 이긴다
  ② 빈 응답·실패는 캐시에 남기지 않는다(장애일 `[]` 캐시가 재시도를 막던 백테스트 로더의 함정)
  ③ 저장 경로·형식이 백테스트 로더와 같다 — 쌓은 데이터를 백테스트가 그대로 읽어야 의미가 있다
  ④ 유니버스에서 빠진 종목도 계속 받는다 — 시점별 유니버스 재검증에 필요하다
  ⑤ 주문 경로와 무관하다
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import collect_foreign_flow as F  # noqa: E402


def _row(dt: str, chg: str = "100") -> dict:
    return {"dt": dt, "chg_qty": chg, "trde_qty": "1000"}


def _reply(rows: list[dict]) -> str:
    return json.dumps({"data": {"stk_frgnr": rows}}, ensure_ascii=False)


class _FakeMCP:
    """MCPManager 대역 — `MCPManager({...})` 호출이 자기 자신을 돌려준다."""

    def __init__(self, replies: dict):
        self.replies = replies
        self.tools = [{"name": F.TOOL}]
        self.calls: list[str] = []

    def __call__(self, *_a, **_k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def call_tool(self, _name, args):
        self.calls.append(args["stock_code"])
        r = self.replies[args["stock_code"]]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def snapdir(tmp_path, monkeypatch):
    """스냅샷 경로를 임시로 — 실제 docs_cache 를 건드리지 않는다."""
    monkeypatch.setattr(F, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(F, "CALL_GAP_SEC", 0)
    return tmp_path


# ─── ① 병합 규칙 ────────────────────────────────────────────────────────────
def test_merge_excludes_provisional_snapshot_day():
    """스냅샷 당일 값은 잠정치다 — 07-15 삼성생명 오발동의 원인이었다."""
    h: dict = {}
    F.merge_rows(h, [_row("20260929"), _row("20260926")], "20260929")
    assert list(h) == ["20260926"], "스냅샷 당일 잠정치가 이력에 들어갔다"


def test_later_snapshot_overwrites_earlier():
    """같은 날짜는 나중 스냅샷이 정정값이다."""
    h: dict = {}
    F.merge_rows(h, [_row("20260925", "100")], "20260926")
    F.merge_rows(h, [_row("20260925", "999")], "20260929")
    assert h["20260925"]["chg_qty"] == "999"


def test_rebuild_ignores_empty_snapshot_and_sorts(snapdir):
    (snapdir / "000001_20260926.json").write_text(json.dumps([_row("20260925", "1")]), encoding="utf-8")
    (snapdir / "000001_20260929.json").write_text(
        json.dumps([_row("20260926", "3"), _row("20260925", "2")]), encoding="utf-8")
    (snapdir / "000001_20260930.json").write_text("[]", encoding="utf-8")        # 장애일 빈 캐시
    h = F.rebuild_history(F.snapshots_by_code()["000001"])
    assert list(h) == ["20260925", "20260926"]
    assert h["20260925"]["chg_qty"] == "2", "나중 스냅샷의 정정값이 반영되지 않았다"


# ─── 연속성 점검 ────────────────────────────────────────────────────────────
def test_gap_is_detected_against_market_calendar():
    full = {"20260922": 1, "20260923": 1, "20260924": 1, "20260925": 1}
    hists = {"A": {"20260922": 1, "20260923": 1, "20260925": 1}, "B": dict(full), "C": dict(full)}
    cal = F.market_calendar(hists)
    assert cal == sorted(full)
    assert F.missing_days(set(hists["A"]), cal) == ["20260924"]
    assert F.missing_days(set(hists["B"]), cal) == []


def test_single_outlier_date_does_not_make_calendar():
    """한 종목에만 있는 날짜가 달력이 되면 나머지 전 종목이 공백으로 보인다."""
    hists = {"A": {"20260922": 1}, "B": {"20260922": 1}, "C": {"20260922": 1, "20260927": 1}}
    assert F.market_calendar(hists) == ["20260922"]


# ─── ② 실패는 캐시하지 않는다 ───────────────────────────────────────────────
def test_fetch_saves_loader_format(snapdir, monkeypatch):
    rows = [_row("20260926")]
    monkeypatch.setattr(F, "MCPManager", _FakeMCP({"000001": _reply(rows)}))
    ok, fail = asyncio.run(F.fetch(["000001"], "20260929"))
    assert ok == ["000001"] and fail == []
    saved = json.loads((snapdir / "000001_20260929.json").read_text(encoding="utf-8"))
    assert saved == rows, "백테스트 로더가 읽는 형식(행 리스트)이 아니다"


def test_failed_or_empty_response_is_not_cached(snapdir, monkeypatch):
    """★ 8050 IP 장애 같은 날 빈 응답을 `[]` 로 캐시하면 그날 재시도가 막힌다."""
    fake = _FakeMCP({"000001": json.dumps({"return_code": 3, "return_msg": "8050"}),
                     "000002": RuntimeError("timeout")})
    monkeypatch.setattr(F, "MCPManager", fake)
    ok, fail = asyncio.run(F.fetch(["000001", "000002"], "20260929"))
    assert ok == [] and sorted(fail) == ["000001", "000002"]
    assert not list(snapdir.glob("*.json")), "실패한 응답을 캐시에 남겼다"


def test_stale_empty_cache_is_retried(snapdir, monkeypatch):
    """그날 앞선 실패(또는 백테스트 로더)가 남긴 빈 파일이 있어도 다시 받는다."""
    (snapdir / "000001_20260929.json").write_text("[]", encoding="utf-8")
    fake = _FakeMCP({"000001": _reply([_row("20260926")])})
    monkeypatch.setattr(F, "MCPManager", fake)
    ok, _fail = asyncio.run(F.fetch(["000001"], "20260929"))
    assert ok == ["000001"] and fake.calls == ["000001"], "빈 캐시를 성공으로 보고 재조회하지 않았다"


def test_existing_snapshot_is_not_refetched(snapdir, monkeypatch):
    """같은 날 두 번 돌아도 API 를 다시 두드리지 않는다 — 재실행 안전·rate limit."""
    (snapdir / "000001_20260929.json").write_text(json.dumps([_row("20260926")]), encoding="utf-8")
    fake = _FakeMCP({})
    monkeypatch.setattr(F, "MCPManager", fake)
    ok, _fail = asyncio.run(F.fetch(["000001"], "20260929"))
    assert ok == ["000001"] and fake.calls == []


def test_unreachable_server_fails_every_code(snapdir, monkeypatch):
    fake = _FakeMCP({})
    fake.tools = []
    monkeypatch.setattr(F, "MCPManager", fake)
    ok, fail = asyncio.run(F.fetch(["000001", "000002"], "20260929"))
    assert ok == [] and fail == ["000001", "000002"]


# ─── ③ 백테스트 로더와 같은 규약 ────────────────────────────────────────────
def test_snapshot_location_and_name_match_backtest_loader():
    """★ 쌓은 데이터를 백테스트(_load_foreign_map)가 그대로 읽어야 한다."""
    src = (_ROOT / "scripts" / "backtest_trend.py").read_text(encoding="utf-8")
    assert '"docs_cache" / "foreign_ka10008"' in src, "백테스트 캐시 경로가 바뀌었다"
    assert 'f"{code}_{today}.json"' in src, "백테스트 캐시 파일명 규약이 바뀌었다"
    assert F.SNAP_DIR == _ROOT / "docs_cache" / "foreign_ka10008"
    assert F.snap_path("000001", "20260929").name == "000001_20260929.json"
    assert 'call_tool("get_foreign_trading_trend"' in src and F.TOOL == "get_foreign_trading_trend"


# ─── ④ 빠진 종목도 계속 받는다 ─────────────────────────────────────────────
def test_previously_collected_codes_are_kept(snapdir, monkeypatch):
    """★ 유니버스에서 빠진 종목도 계속 받는다 — 시점별 유니버스 재검증에 그 이력이 필요하다."""
    (snapdir / "999999_20260801.json").write_text(json.dumps([_row("20260731")]), encoding="utf-8")
    monkeypatch.setattr(F, "_universe_codes", lambda: {"000001"})
    codes = F.target_codes()
    assert "999999" in codes, "과거 수집 종목을 버렸다 — 이력이 끊긴다"
    assert "000001" in codes


# ─── ⑤ 주문 경로와 무관 ─────────────────────────────────────────────────────
def test_collector_is_off_the_order_path():
    src = (_ROOT / "scripts" / "collect_foreign_flow.py").read_text(encoding="utf-8")
    for banned in ("_place", "place_buy", "place_sell", "save_state", "trend_kiwoom_io", "trading-domain"):
        assert banned not in src, f"주문/상태 경로({banned})를 건드린다"
    daemon = next(p for p in (_ROOT / "scripts" / "trend_follow.py", _ROOT / "archive" / "scripts" / "trend_follow.py")
                  if p.exists())                     # 2026-10-22 추세추종 데몬은 archive/ 로 보관
    assert "collect_foreign_flow" not in daemon.read_text(encoding="utf-8")
