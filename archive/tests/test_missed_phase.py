"""놓친 phase 복구 회귀 — 2026-09-09 도입, 2026-09-14 판정 기준 교정.

■ 09-09 도입 배경
watchdog 이 08:50:22 에 데몬을 재기동했고 새 데몬이 08:50:27 에 떴다.
`_next_run(8,50)` 이 **27초 차이로** 슬롯을 내일로 넘겨 그날 스크린이 통째로 사라졌다.

■ 09-14 오탐 — 이 파일이 원래 잡았어야 했던 결함
11:00:08 entry 가 후보 0건으로 정상 종료 → 2초 뒤 "entry 미실행 감지 → 복구" 로 **한 번 더**
돌았고, 15:20 에 "🚨 entry 오늘 미실행" critical 알림이 나갔다.
원인: entry 의 done 표식은 원래 **'주문/게이트 판정이 났다'**(매수·보류·레짐·breadth 때만)는
뜻인데, 복구 로직이 그걸 **'실행됐다'**로 읽었다. 후보 0·슬롯 만석·서킷·진입정지 날마다 오탐.
더 나쁜 경로: 시장가 주문 응답 불명(브로커는 접수) → 포지션 미기록·표식 없음 → 2초 뒤 복구가
**같은 매수를 다시 보낸다.** 08-17 에 없앤 재전송이 phase 단위로 되살아난 것이다.

이전 테스트는 `_phase_done_today` 를 목으로 바꿔 끼워, 실제 phase 가 표식을 남기는지를
한 번도 보지 않았다. 그래서 여기서는 **실제 state 파일(임시 경로)** 로 검증한다.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))


@pytest.fixture
def tf(monkeypatch, tmp_path):
    """state 경로 3종을 **전부** 임시로 돌린 trend_follow.

    ⚠️ STATE_FILE 만 바꾸면 save_state 가 STATE_TMP·STATE_BAK(운영 경로)에 쓴다 —
    테스트가 라이브 state.json.bak 을 덮어쓴다. 셋 다 바꿔야 한다.
    """
    import trend_runtime as RT
    monkeypatch.setattr(RT, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(RT, "STATE_BAK", tmp_path / "state.json.bak")
    monkeypatch.setattr(RT, "STATE_TMP", tmp_path / "state.json.tmp")
    import trend_follow as TF
    monkeypatch.setattr(TF, "FORCE_PHASE", False)
    return TF


def _at(h, m, s=0):
    """오늘 날짜의 시각 — 표식이 datetime.now() 날짜로 저장되므로 날짜를 맞춘다."""
    return datetime.now().replace(hour=h, minute=m, second=s, microsecond=0)


def _missed(tf, h, m, s=0):
    return [p for p, _slot, _g in tf._missed_phases(_at(h, m, s))]


def _run(tf, label, fn):
    asyncio.run(tf._run_phase(label, fn))


def test_fixture_isolates_all_state_paths(tf):
    """★ 이 fixture 가 운영 state 를 가리키면 테스트가 실계좌 보유 추적을 망가뜨린다."""
    import trend_runtime as RT
    live = (_ROOT / "data").resolve()
    for p in (RT.STATE_FILE, RT.STATE_BAK, RT.STATE_TMP):
        assert live not in Path(p).resolve().parents, f"운영 경로를 가리킨다: {p}"


# ─── 09-09 동작 유지 ────────────────────────────────────────────────────────
def test_before_slot_is_not_missed(tf):
    assert tf._missed_phases(_at(8, 30)) == []


def test_screen_missed_by_seconds_is_detected(tf):
    """★ 2026-09-09 재현 — 08:50:27 기동, 오늘 아무 표식 없음 → screen 놓침."""
    missed = tf._missed_phases(_at(8, 50, 27))
    assert [p for p, _s, _g in missed] == ["screen"], missed
    _phase, slot, in_grace = missed[0]
    assert slot == _at(8, 50), "슬롯 시각이 어긋난다"
    assert in_grace is True, "진입(11:00) 전이므로 복구 유예 안이어야 한다"


def test_completion_marker_is_honored(tf):
    """phase 가 스스로 남긴 완료 표식(구 데몬·수동 --phase 실행 포함)은 실행으로 친다."""
    tf._mark_done("screen")
    assert _missed(tf, 9, 0) == []


def test_missed_marker_stops_repeat_alerts(tf):
    """포기 표식(!missed)이 찍히면 다시 보고하지 않는다 — 매 루프 알림 폭탄 방지."""
    tf._mark_done("screen" + tf._MISSED_SUFFIX)
    assert _missed(tf, 9, 0) == []


# ─── ★ 09-14 오탐 ───────────────────────────────────────────────────────────
def test_entry_that_returned_early_is_not_missed(tf):
    """★ 2026-09-14 재현 — 후보 0건 entry 는 표식을 안 남기고 끝난다. 그래도 '실행'이다."""
    tf._mark_done("screen")

    async def entry_no_candidates():
        return None                       # phase_entry: "후보 0 슬롯 19 — 진입 없음"
    _run(tf, "entry", entry_no_candidates)
    assert "entry" not in _missed(tf, 11, 0, 10), \
        "정상 종료한 entry 를 놓침으로 오판 — 2초 뒤 재실행된다"


def test_ran_marker_persists_in_state(tf):
    """표식은 state.json 에 남아 **데몬 재기동 뒤에도** 유효해야 한다(watchdog 이 매일 재기동)."""
    assert tf._RAN_SUFFIX == "@ran", "state.json 에 저장되는 형식 — 바꾸면 이미 찍힌 표식이 무효가 된다"
    tf._mark_done("screen")
    tf._mark_done("entry@ran")
    assert "entry" not in _missed(tf, 11, 30)


def test_failed_entry_is_not_retried(tf):
    """★ 도중에 실패한 entry 를 재실행하지 않는다 — 응답 불명 주문의 재전송 경로.

    시장가 주문이 타임아웃 났는데 브로커는 접수했고 잔고엔 아직 안 잡힌 경우 포지션은
    기록되지 않는다. 여기서 복구가 entry 를 다시 돌리면 같은 매수가 또 나간다.
    """
    tf._mark_done("screen")

    async def entry_blows_up():
        raise RuntimeError("주문 응답 불명")
    with pytest.raises(RuntimeError):
        _run(tf, "entry", entry_blows_up)
    assert "entry" not in _missed(tf, 11, 0, 5), "실패한 entry 를 재실행하려 한다(재전송 위험)"


def test_failed_exit_is_not_retried(tf):
    """청산도 주문 phase 다 — 실패 후 자동 재실행은 검증된 흐름에 없던 동작이다."""
    tf._mark_done("screen")
    tf._mark_done("entry")

    async def exit_blows_up():
        raise RuntimeError("trading-domain 연결 실패")
    with pytest.raises(RuntimeError):
        _run(tf, "exit", exit_blows_up)
    assert "exit" not in _missed(tf, 15, 21)


def test_interrupted_screen_is_still_recovered(tf):
    """screen 은 주문이 없어 재실행이 안전하다 → **완료**해야 실행으로 친다.

    hang 으로 watchdog 이 죽인 screen 을 재기동 뒤 복구하던 09-09 동작을 유지한다.
    """
    tf._mark_done("screen" + tf._RAN_SUFFIX)          # 시작만 하고 완료 표식이 없다
    missed = tf._missed_phases(_at(9, 0))
    assert [p for p, _s, _g in missed] == ["screen"]
    assert missed[0][2] is True


def test_run_phase_marks_before_invoking(tf):
    """★ 표식은 **호출 전에** 찍혀야 한다 — phase 도중 강제종료돼도 주문 phase 가 재실행되지 않도록."""
    seen = {}

    async def probe():
        seen["marked"] = tf._marked_today("entry" + tf._RAN_SUFFIX)
    _run(tf, "entry", probe)
    assert seen["marked"] is True, "phase 가 끝난 뒤에 표식을 찍는다 — 중단 시 재실행된다"


def test_force_phase_does_not_blind_missed_check(tf, monkeypatch):
    """TREND_FORCE_PHASE 는 phase 내부 중복 가드를 끄는 스위치다.

    스케줄러의 실행 장부까지 못 보게 되면 지난 phase 를 루프마다 다시 돌린다.
    """
    monkeypatch.setattr(tf, "FORCE_PHASE", True)
    tf._mark_done("screen")
    tf._mark_done("entry" + tf._RAN_SUFFIX)
    assert _missed(tf, 11, 30) == []


# ─── 스케줄러 배선 ──────────────────────────────────────────────────────────
def test_scheduler_invokes_phases_only_through_run_phase(tf):
    """★ phase 를 직접 await 하는 경로가 하나라도 남으면 그 경로는 표식을 안 남긴다 → 오탐 재발."""
    src = inspect.getsource(tf.scheduler_daemon)
    assert "await funcs[" not in src, "표식 없이 phase 를 호출하는 경로가 남아 있다"
    assert src.count("_run_phase(") >= 2, "정규 실행·복구 실행 모두 _run_phase 를 거쳐야 한다"


def test_retry_safe_phases_place_no_orders(tf):
    """★ 재실행 허용 phase 는 주문 경로가 없어야 한다 — entry/exit 가 여기 들어오면 재전송이 된다."""
    assert tf._RETRY_SAFE, "비어 있으면 hang 난 screen 이 복구되지 않는다"
    for phase in tf._RETRY_SAFE:
        src = inspect.getsource(getattr(tf, f"phase_{phase}"))
        for banned in ("_place(", "_execute_buys(", "_buy_one(", "_manage(", "_sell"):
            assert banned not in src, f"{phase} 에 주문 경로({banned})가 있는데 재실행 허용이다"


# ─── 유예 경계 — 늦게 하는 게 더 위험한 지점 ────────────────────────────────
def test_screen_grace_ends_at_entry_time(tf):
    """screen 후보는 entry 가 소비한다 — 진입 시각을 넘기면 복구할 이유가 없다."""
    before = dict((p, g) for p, _s, g in tf._missed_phases(_at(10, 59)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(_at(11, 1)))
    assert before["screen"] is True
    assert after["screen"] is False, "진입 시각 이후에도 screen 을 복구하려 한다"


def test_entry_grace_ends_at_cutoff(tf):
    """★ 진입 복구는 기존 '보류→반등' 마감(ENTRY_CUTOFF)과 같은 선에서 끝나야 한다.

    그보다 늦은 진입은 검증된 조건 밖이다 — 실계좌에 검증 안 된 시각의 주문이 나간다.
    """
    h, m = (int(x) for x in tf.ENTRY_CUTOFF.split(":"))
    cut = _at(h, m)
    before = dict((p, g) for p, _s, g in tf._missed_phases(cut - timedelta(minutes=1)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(cut + timedelta(minutes=1)))
    assert before["entry"] is True
    assert after["entry"] is False, "마감 뒤에도 진입을 복구하려 한다"


def test_exit_grace_ends_before_market_close(tf):
    """★ 장 마감(15:30) 뒤 매도는 rc 505217 로 전량 거부된다 — 그 전에 끊어야 한다."""
    before = dict((p, g) for p, _s, g in tf._missed_phases(_at(15, 27)))
    after = dict((p, g) for p, _s, g in tf._missed_phases(_at(15, 29)))
    assert before["exit"] is True
    assert after["exit"] is False, "장 마감 임박/경과인데 청산을 복구하려 한다"
    h, m = (int(x) for x in tf._CATCHUP_DEADLINE["exit"].split(":"))
    assert h * 60 + m < 15 * 60 + 30, "청산 유예선이 장 마감을 넘는다"


# ─── 설정 자체의 무결성 ─────────────────────────────────────────────────────
def test_every_scheduled_phase_has_a_deadline(tf):
    """★ SCHEDULE 에 phase 를 추가하고 유예를 안 넣으면 KeyError 로 데몬 루프가 죽는다."""
    for _h, _m, phase in tf.SCHEDULE:
        assert phase in tf._CATCHUP_DEADLINE, f"{phase} 의 복구 유예가 없다"


def test_deadlines_are_after_their_slots(tf):
    """유예선이 슬롯보다 이르면 복구가 영원히 불가능하다(조용히 항상 '포기')."""
    for h, m, phase in tf.SCHEDULE:
        dh, dm = (int(x) for x in tf._CATCHUP_DEADLINE[phase].split(":"))
        assert dh * 60 + dm > h * 60 + m, f"{phase}: 유예선이 슬롯보다 이르다"


def test_markers_do_not_collide(tf):
    """표식끼리·phase 이름과 섞이면 '완료'·'호출됨'·'포기'를 구분할 수 없다."""
    assert tf._RAN_SUFFIX != tf._MISSED_SUFFIX
    names = {p for _h, _m, p in tf.SCHEDULE}
    for n in names:
        assert n + tf._MISSED_SUFFIX not in names
        assert n + tf._RAN_SUFFIX not in names
