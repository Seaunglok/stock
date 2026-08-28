"""유니버스 broad 캐시 무효화 회귀 — 2026-08-28.

방어 대상: 캐시가 `version` 만 보고 스냅샷 날짜를 보지 않아, `_universe_kiwoom.py` 로
새 스냅샷을 받아도 **옛 목록을 영구히 물고 있던** 상태. stale 경고는 뜨는데 그 경고가
안내하는 갱신 절차가 실제로는 아무 효과가 없었다 — 경고만 보고 고쳤다고 믿게 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.mcp_servers.trend_mcp import market_data as MD  # noqa: E402


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    """docs_cache 를 임시 디렉터리로 돌린다 — 실제 캐시를 건드리지 않는다."""
    monkeypatch.setattr(MD, "_ROOT", tmp_path)
    (tmp_path / "docs_cache").mkdir()
    monkeypatch.setattr(MD, "_BROAD_CACHE", tmp_path / "docs_cache" / "broad_universe.json")
    return tmp_path / "docs_cache"


def _snapshot(d: Path, date: str, names: list[str]) -> None:
    rows = [{"code": f"{i:06d}", "name": n, "market": "거래소",
             "market_cap": (len(names) - i) * 1e12, "list_count": 1000}
            for i, n in enumerate(names)]
    (d / f"universe_kiwoom_{date}.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _write_cache(d: Path, snapshot: str, codes: list[str]) -> None:
    (d / "broad_universe.json").write_text(json.dumps(
        {"version": MD._BROAD_VERSION, "snapshot": snapshot, "codes": codes}), encoding="utf-8")


def test_newer_snapshot_invalidates_cache(fake_cache):
    """★ 새 스냅샷이 있으면 캐시를 버리고 새 목록을 만든다."""
    _snapshot(fake_cache, "20260430", ["구A", "구B"])
    _write_cache(fake_cache, "20260430", ["999999"])          # 옛 목록
    _snapshot(fake_cache, "20260828", ["신A", "신B", "신C"])   # 더 새 스냅샷 도착
    codes = MD._broad_codes()
    assert "999999" not in codes, "새 스냅샷이 있는데 옛 캐시를 그대로 돌려줬다"
    assert len(codes) == 3


def test_same_snapshot_uses_cache(fake_cache):
    """같은 스냅샷이면 캐시를 그대로 쓴다(불필요한 재생성 방지)."""
    _snapshot(fake_cache, "20260828", ["A", "B", "C"])
    _write_cache(fake_cache, "20260828", ["000042"])
    assert MD._broad_codes() == ["000042"]


def test_older_snapshot_does_not_invalidate(fake_cache):
    """과거 스냅샷 파일이 남아 있어도 최신 캐시는 유지된다."""
    _snapshot(fake_cache, "20260101", ["옛A"])
    _snapshot(fake_cache, "20260828", ["A", "B"])
    _write_cache(fake_cache, "20260828", ["000042"])
    assert MD._broad_codes() == ["000042"]


def test_newest_snapshot_date_picks_latest(fake_cache):
    _snapshot(fake_cache, "20260101", ["a"])
    _snapshot(fake_cache, "20260828", ["b"])
    _snapshot(fake_cache, "20260430", ["c"])
    assert MD._newest_snapshot_date() == "20260828"


def test_no_snapshot_returns_empty(fake_cache):
    """스냅샷이 하나도 없으면 빈 문자열 — 캐시 무효화 조건이 오작동하지 않아야."""
    assert MD._newest_snapshot_date() == ""
