"""보관한 추세추종 데몬의 기동 순서 검사 — tests/test_trend_lock.py 에서 옮김(2026-10-22, 데몬과 함께 보관)."""
from pathlib import Path


def test_slow_startup_checks_run_after_lock():
    """★ 느린 기동 검사(_check_sizing_feasible, 시세 24회)가 락 획득 **뒤에** 있어야 한다.

    락 앞에 두면 검사가 도는 수십 초 동안 두 인스턴스가 나란히 통과해 중복 기동이 된다.
    2026-08-28 에 실제로 데몬이 3개 떠서 발견했다. 단일 인스턴스 보장은 락이 하는 일이고,
    락은 되도록 일찍 잡혀야 한다.
    """
    src = (Path(__file__).resolve().parents[1] / "scripts" / "trend_follow.py"
           ).read_text(encoding="utf-8")
    lock_at = src.index("if not acquire_lock():")
    check_at = src.index("await _check_sizing_feasible()")
    assert check_at > lock_at, "사이징 가드가 락 획득보다 먼저 실행된다 — 중복 기동 창이 열린다"
