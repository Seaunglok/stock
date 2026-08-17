"""상태 영속화 회귀 — 2026-08-17.

방어 대상: state.json 이 잘린 채 남으면 데몬이 '보유 0' 으로 착각해 실보유분에 손절·트레일이
안 걸리고, 다음 save_state 가 빈 dict 를 덮어써 손실이 확정된다.
발생 경로가 실재한다 — watchdog 은 hung 데몬을 `taskkill /F /T` 로 죽이는데(trend_watchdog.py),
save_state 는 청산 루프 안에서 **매 매도마다** 호출된다(trend_follow._manage).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import trend_runtime as rt  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    """STATE_FILE/.bak/.tmp 를 tmp_path 로 격리 — 실제 data/trend_follow 무접촉."""
    f = tmp_path / "state.json"
    monkeypatch.setattr(rt, "STATE_FILE", f)
    monkeypatch.setattr(rt, "STATE_BAK", f.with_suffix(".json.bak"))
    monkeypatch.setattr(rt, "STATE_TMP", f.with_suffix(".json.tmp"))
    return f


POS = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "entry_price": 70000}]


# ─── 기본 동작 ─────────────────────────────────────────────────────────────
def test_missing_file_is_empty(state):
    assert rt.load_state() == {}


def test_roundtrip(state):
    rt.save_state("positions", POS)
    assert rt.load_state()["positions"] == POS
    assert rt.get_state("positions") == POS


def test_get_state_default(state):
    assert rt.get_state("nope", "dflt") == "dflt"


def test_save_preserves_other_keys(state):
    rt.save_state("positions", POS)
    rt.save_state("candidates", [{"symbol": "000660"}])
    st = rt.load_state()
    assert st["positions"] == POS and len(st["candidates"]) == 1


def test_save_stamps_last_updated(state):
    rt.save_state("positions", POS)
    assert rt.load_state()["last_updated"]


# ─── ★ 손상 처리 (핵심) ────────────────────────────────────────────────────
def test_truncated_file_falls_back_to_bak(state):
    """잘린 쓰기 재현 → .bak 의 직전 정상본으로 복구. 절대 {} 가 아니다."""
    rt.save_state("positions", POS)
    rt.save_state("positions", POS + [{"symbol": "000660", "qty": 5}])   # .bak 생성
    state.write_text('{"positions": [{"symbol": "0059', encoding="utf-8")  # 중간에 끊김
    assert rt.load_state()["positions"] == POS, "손상 시 직전 정상본으로 돌아와야 한다"


def test_empty_file_falls_back_to_bak(state):
    rt.save_state("positions", POS)
    rt.save_state("positions", [])
    state.write_text("", encoding="utf-8")     # 빈 파일 = 잘린 쓰기의 전형
    assert rt.load_state()["positions"] == POS


def test_both_corrupt_raises_not_empty(state):
    """★ 본파일·백업 모두 깨지면 예외. {} 를 돌려주면 무방비로 거래를 계속하게 된다."""
    rt.save_state("positions", POS)
    rt.save_state("positions", POS)
    state.write_text("{{{", encoding="utf-8")
    rt.STATE_BAK.write_text("nonsense", encoding="utf-8")
    with pytest.raises(rt.StateCorrupted):
        rt.load_state()


def test_corrupt_state_is_not_overwritten(state):
    """★ 손상 상태에서 save 하면 예외로 멈춰야 한다 — 덮어쓰면 손실이 확정된다."""
    rt.save_state("positions", POS)
    rt.save_state("positions", POS)
    state.write_text("{{{", encoding="utf-8")
    rt.STATE_BAK.write_text("nonsense", encoding="utf-8")
    with pytest.raises(rt.StateCorrupted):
        rt.save_state("positions", [])
    assert state.read_text(encoding="utf-8") == "{{{", "손상 파일이 덮어써졌다"


def test_json_array_is_treated_as_corrupt(state):
    """dict 가 아닌 JSON(배열 등)도 손상으로 본다 — .get 호출에서 터지기 전에 잡는다."""
    rt.save_state("positions", POS)
    rt.save_state("positions", POS)
    state.write_text("[1,2,3]", encoding="utf-8")
    assert rt.load_state()["positions"] == POS


# ─── 원자성 ────────────────────────────────────────────────────────────────
def test_no_tmp_file_left_behind(state):
    rt.save_state("positions", POS)
    assert not rt.STATE_TMP.exists(), "tmp 잔존 = 치환 미완료"


def test_bak_created_on_second_save(state):
    rt.save_state("positions", POS)
    assert not rt.STATE_BAK.exists(), "최초 저장엔 백업 대상이 없다"
    rt.save_state("positions", [])
    assert json.loads(rt.STATE_BAK.read_text(encoding="utf-8"))["positions"] == POS


def test_state_survives_write_failure(state, monkeypatch):
    """tmp 쓰기가 실패해도 기존 state 는 온전해야 한다(부분 쓰기로 파괴 금지)."""
    rt.save_state("positions", POS)
    orig = state.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise OSError("디스크 가득참")
    monkeypatch.setattr(type(rt.STATE_TMP), "write_text", boom)
    with pytest.raises(OSError):
        rt.save_state("positions", [])
    assert state.read_text(encoding="utf-8") == orig
