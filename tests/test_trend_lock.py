"""데몬 락 회귀 — 2026-08-11 PID 재사용 장애 재현 방지.

장애: 08-10 22:51 데몬(PID 6536) 사망 → 락 잔존 → 08-11 08:20 vmware-authd.exe 가
PID 6536 재할당 → `pid_exists` 가 True 라 신규 데몬이 매번 "이미 실행 중" 으로 거부됨.
거래일 내내 데몬 미기동(보유 5종 무관리). watchdog 은 그 PID 를 taskkill /F /T 하려 했다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import trend_lock as tl  # noqa: E402


@pytest.fixture
def lockfile(tmp_path) -> Path:
    return tmp_path / "daemon.lock"


# ─── 형식 ──────────────────────────────────────────────────────────────────
def test_write_then_read_roundtrip(lockfile):
    tl.write_lock(lockfile)
    rec = tl.read_lock(lockfile)
    assert rec["pid"] == os.getpid()
    assert rec["marker"] == tl.MARKER
    assert rec["created"] is not None, "기동시각이 없으면 PID 재사용을 못 걸러낸다"


def test_reads_legacy_bare_pid(lockfile):
    """구형식(숫자만) 락도 읽어야 한다 — 배포 시점에 이미 떠 있던 데몬 대비."""
    lockfile.write_text("6536", encoding="utf-8")
    rec = tl.read_lock(lockfile)
    assert rec == {"pid": 6536, "created": None, "legacy": True}


@pytest.mark.parametrize("body", ["", "   ", "쓰레기", "{}", '{"nope": 1}'])
def test_unparsable_lock_is_none(lockfile, body):
    lockfile.write_text(body, encoding="utf-8")
    assert tl.read_lock(lockfile) is None


def test_missing_file_is_none(lockfile):
    assert tl.read_lock(lockfile) is None


# ─── 소유권 판정 (핵심) ─────────────────────────────────────────────────────
def test_self_is_alive(lockfile):
    tl.write_lock(lockfile)
    assert tl.owner_alive(tl.read_lock(lockfile)) is True


def test_pid_reuse_is_rejected(lockfile):
    """★ 08-11 장애 재현: PID 는 살아있지만 기동시각이 다르면 남의 프로세스다."""
    tl.write_lock(lockfile)
    rec = json.loads(lockfile.read_text(encoding="utf-8"))
    rec["created"] = rec["created"] - 86400        # 하루 전에 뜬 프로세스였다고 가정
    assert tl.owner_alive(rec) is False, "PID 재사용을 살아있다고 보면 락이 영구 고착된다"


def test_dead_pid_is_not_alive():
    assert tl.owner_alive({"pid": 999_999_998, "created": 1.0}) is False


@pytest.mark.parametrize("rec", [None, {}, {"pid": 0}, {"pid": -1}, {"pid": None}])
def test_garbage_owner_is_not_alive(rec):
    assert tl.owner_alive(rec) is False


def test_legacy_lock_checked_by_cmdline():
    """구형식엔 기동시각이 없다 → 커맨드라인으로 판별. 현재 프로세스(pytest)는 데몬이 아니다."""
    assert tl.owner_alive({"pid": os.getpid(), "created": None, "legacy": True}) is False


def test_legacy_lock_accepts_marker_process(monkeypatch):
    class _P:
        def __init__(self, pid): pass
        def cmdline(self): return ["python", "scripts/trend_follow.py", "--daemon"]
    import psutil
    monkeypatch.setattr(psutil, "Process", _P)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    assert tl.owner_alive({"pid": os.getpid(), "created": None, "legacy": True}) is True


# ─── release 안전성 ────────────────────────────────────────────────────────
def test_owned_by_me_true_for_own_lock(lockfile):
    tl.write_lock(lockfile)
    assert tl.owned_by_me(tl.read_lock(lockfile)) is True


def test_owned_by_me_false_for_other_pid(lockfile):
    tl.write_lock(lockfile, pid=os.getpid())
    rec = tl.read_lock(lockfile)
    rec["pid"] = os.getpid() + 1
    assert tl.owned_by_me(rec) is False, "남이 인수한 락을 지우면 이중 기동이 된다"


def test_owned_by_me_false_after_pid_reuse(lockfile):
    tl.write_lock(lockfile)
    rec = tl.read_lock(lockfile)
    rec["created"] = rec["created"] - 86400
    assert tl.owned_by_me(rec) is False


# ─── 진단 출력 ─────────────────────────────────────────────────────────────
def test_describe_handles_missing_lock():
    assert tl.describe(None) == "(없음)"


def test_describe_mentions_pid(lockfile):
    tl.write_lock(lockfile)
    assert str(os.getpid()) in tl.describe(tl.read_lock(lockfile))


def test_describe_marks_legacy():
    assert "구형식" in tl.describe({"pid": 6536, "created": None, "legacy": True})
