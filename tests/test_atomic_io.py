"""원자적 쓰기 한 곳(atomic_io) — 실패해도 원본이 남고, I3 상태 파일이 사라지지 않는다(11-18).

일부러 깨뜨리기: 교체(os.replace)를 PermissionError 로 막고 · tmp 쓰기를 인코딩 오류로 막고 · state.json 을 지운 채 .bak 만 남겨
본다. 읽기는 실제 reader(i3_live.load_state · csv.DictReader)로 확인한다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import atomic_io as A  # noqa: E402

_REAL_REPLACE = A.os.replace


@pytest.fixture
def no_wait(monkeypatch):
    slept = []
    monkeypatch.setattr(A.time, "sleep", lambda s: slept.append(s))
    return slept


def _block_replace(monkeypatch, times: int | None):
    """새 파일(.tmp)을 본파일로 바꾸는 os.replace 만 times 번 PermissionError 로 막는다(None = 계속).
    백신·색인이 갓 쓴 파일을 잡고 있는 모양 — 본파일을 .bak 으로 옮기는 교체는 막지 않는다."""
    n = {"left": times}

    def fake(src, dst):
        if str(src).endswith(".tmp") and (n["left"] is None or n["left"] > 0):
            if n["left"] is not None:
                n["left"] -= 1
            raise PermissionError(13, "다른 프로세스가 파일을 사용 중", str(dst))
        return _REAL_REPLACE(src, dst)
    monkeypatch.setattr(A.os, "replace", fake)


def test_write_text_new_and_overwrite(tmp_path):
    p = tmp_path / "sub" / "a.json"                      # 폴더가 없어도 만든다
    A.write_text(p, "첫째")
    A.write_text(p, "둘째")
    assert p.read_text(encoding="utf-8") == "둘째"
    assert not A.tmp_of(p).exists() and not A.bak_of(p).exists()


def test_keep_bak_copies_previous(tmp_path):
    p = tmp_path / "state.json"
    A.write_text(p, "v1", keep_bak=True)
    assert not A.bak_of(p).exists()                      # 처음엔 직전 본이 없다
    A.write_text(p, "v2", keep_bak=True)
    assert p.read_text(encoding="utf-8") == "v2"
    assert A.bak_of(p).read_text(encoding="utf-8") == "v1"


@pytest.mark.parametrize("keep_bak", [False, True])
def test_replace_blocked_keeps_original(tmp_path, monkeypatch, no_wait, keep_bak):
    """깨뜨리기: 교체가 계속 막히면 예외 — 원본은 그대로(파일이 사라지지 않는다), tmp 는 남지 않는다."""
    p = tmp_path / "state.json"
    A.write_text(p, "원본", keep_bak=keep_bak)
    _block_replace(monkeypatch, None)
    with pytest.raises(PermissionError):
        A.write_text(p, "새것", keep_bak=keep_bak)
    assert p.read_text(encoding="utf-8") == "원본"
    assert not A.tmp_of(p).exists()
    assert len(no_wait) == A.REPLACE_RETRIES


def test_replace_retried_then_ok(tmp_path, monkeypatch, no_wait):
    p = tmp_path / "a.csv"
    A.write_text(p, "원본")
    _block_replace(monkeypatch, 2)                       # 백신이 두 번 잡았다 놓는 경우
    A.write_text(p, "새것")
    assert p.read_text(encoding="utf-8") == "새것"
    assert no_wait == [A.RETRY_GAP_S] * 2


def test_tmp_write_failure_keeps_original(tmp_path):
    """깨뜨리기: tmp 쓰기 도중 실패(인코딩 불가 문자) — 원본 그대로 · tmp 지움 · 예외 그대로."""
    p = tmp_path / "a.json"
    A.write_text(p, "원본")
    with pytest.raises(UnicodeEncodeError):
        A.write_text(p, "깨진 \ud800 문자")
    assert p.read_text(encoding="utf-8") == "원본"
    assert not A.tmp_of(p).exists()


def test_write_csv_reader_roundtrip_and_same_bytes(tmp_path):
    """실제 reader 로 읽고, 바꾸기 전 코드(인라인 DictWriter)와 바이트가 같은지."""
    cols = ["date", "nav", "w"]
    rows = [{"date": "2026-11-17", "nav": 3655282, "w": 0.0, "extra": "버림"}, {"date": "2026-11-18", "nav": 1}]
    p = tmp_path / "h.csv"
    A.write_csv(p, cols, rows)
    with p.open(encoding="utf-8", newline="") as f:
        back = list(csv.DictReader(f))
    assert back == [{"date": "2026-11-17", "nav": "3655282", "w": "0.0"}, {"date": "2026-11-18", "nav": "1", "w": ""}]
    old = tmp_path / "old.csv"
    with old.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    assert p.read_bytes() == old.read_bytes()


def test_write_csv_failure_keeps_original(tmp_path):
    p = tmp_path / "h.csv"
    A.write_csv(p, ["a"], [{"a": 1}])
    with pytest.raises(UnicodeEncodeError):
        A.write_csv(p, ["a"], [{"a": "\ud800"}])
    assert p.read_text(encoding="utf-8").splitlines() == ["a", "1"]
    assert not A.tmp_of(p).exists()


# ── I3 상태 파일(실전) — writer(save_state) → reader(load_state) ─────────────────
def test_i3_state_survives_blocked_replace(tmp_path, monkeypatch, no_wait):
    """깨뜨리기: 11-18 전 save_state 는 state.json 을 .bak 으로 '옮긴' 뒤 교체 → 교체가 막히면 state.json 이 없어지고
    load_state 가 {} 를 돌려줬다. 이제는 원본이 그대로 남는다."""
    import i3_live as LV
    st = tmp_path / "state.json"
    LV.save_state({"w": 0.0, "navs": [["2026-11-17", 3655282.0]]}, st)
    LV.save_state({"w": 0.0, "navs": [["2026-11-17", 3655282.0], ["2026-11-18", 3655400.0]]}, st)
    assert json.loads(A.bak_of(st).read_text(encoding="utf-8"))["navs"] == [["2026-11-17", 3655282.0]]
    _block_replace(monkeypatch, None)
    with pytest.raises(PermissionError):
        LV.save_state({"w": 1.0, "navs": []}, st)
    back = LV.load_state(st)
    assert back["w"] == 0.0 and len(back["navs"]) == 2


def test_i3_load_state_refuses_missing_with_bak(tmp_path):
    """깨뜨리기: state.json 이 없는데 .bak 이 있으면 빈 상태로 시작하지 않고 멈춘다(처음 실행만 {})."""
    import i3_live as LV
    st = tmp_path / "state.json"
    assert LV.load_state(st) == {}                       # 둘 다 없음 = 처음 실행
    LV.save_state({"w": 0.0}, st)
    LV.save_state({"w": 0.0, "navs": []}, st)
    st.unlink()
    with pytest.raises(FileNotFoundError, match="bak"):
        LV.load_state(st)
