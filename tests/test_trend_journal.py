"""매매일지 집계 회귀 — trend_follow.py 에서 분리(2026-08-06)하며 순수함수가 된 부분.

일지는 운영 판단의 1차 입력(마감 알림·회고)이라 집계가 틀리면 조용히 오판한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from trend_journal import _market_line, _safety_line, _safety_md, safety_event_counts  # noqa: E402


def _ev(name: str, **payload) -> dict:
    return {"ts": "2026-08-06T15:20:00", "event": name, "payload": payload}


# ─── 안전 이벤트 집계 ───────────────────────────────────────────────────────
def test_empty_events_all_zero():
    c = safety_event_counts([])
    assert set(c.values()) == {0}


def test_hard_stop_counted_only_for_hard_reason():
    events = [_ev("exit", reason="하드손절 -10.0%"),
              _ev("exit", reason="MA120 이탈"),
              _ev("exit", reason="트레일 이탈")]
    assert safety_event_counts(events)["hard_stop"] == 1


def test_sell_reject_counted_only_for_sell_phases():
    events = [_ev("order_reject", phase="exit"),
              _ev("order_reject", phase="intraday"),
              _ev("order_reject", phase="force_close"),
              _ev("order_reject", phase="entry")]        # 매수 거부는 별개
    assert safety_event_counts(events)["sell_reject"] == 3


def test_all_counters():
    events = [_ev("circuit_break", reason="일일손실"), _ev("reconcile_adopt", symbol="005930"),
              _ev("fill_partial", symbol="005930"), _ev("fill_missing", symbol="000660"),
              _ev("pyramid_add", symbol="005930")]
    c = safety_event_counts(events)
    assert (c["circuit_break"], c["adopted"], c["fill_partial"], c["fill_missing"], c["pyramid"]) \
        == (1, 1, 1, 1, 1)


def test_malformed_payload_does_not_crash():
    """payload 가 dict 가 아니거나 없어도 집계가 죽지 않아야 한다(일지 생성이 마감 전체를 막음)."""
    events = [{"event": "exit"}, {"event": "exit", "payload": None},
              {"event": "exit", "payload": "문자열"}, {}]
    assert safety_event_counts(events)["hard_stop"] == 0


def test_unknown_events_ignored():
    assert set(safety_event_counts([_ev("phase_start", phase="entry"),
                                    _ev("screen_done"), _ev("entry")]).values()) == {0}


# ─── 마감 요약 렌더링 ───────────────────────────────────────────────────────
def test_safety_md_empty_when_nothing_happened():
    assert _safety_md(safety_event_counts([])) == []


def test_safety_md_lists_only_nonzero():
    md = "\n".join(_safety_md(safety_event_counts([_ev("circuit_break")])))
    assert "서킷브레이커" in md and "하드손절" not in md


def test_safety_line_excludes_informational_counters():
    """편입·피라미딩은 즉시대응 대상이 아니므로 텔레그램 1줄 요약에서 뺀다."""
    c = safety_event_counts([_ev("reconcile_adopt"), _ev("pyramid_add")])
    assert _safety_line(c) == ""
    c2 = safety_event_counts([_ev("reconcile_adopt"), _ev("order_reject", phase="exit")])
    assert "매도거부 1" in _safety_line(c2) and "편입" not in _safety_line(c2)


# ─── 시장 라인 ─────────────────────────────────────────────────────────────
def test_market_line_needs_two_points():
    assert _market_line([]) == "N/A"
    assert _market_line([6000.0]) == "N/A"


def test_market_line_formats_change():
    out = _market_line([6598.3, 6274.7])
    assert "6,598.3" in out and "6,274.7" in out and "-4.90%" in out


def test_market_line_uses_last_two_only():
    assert _market_line([1.0, 2.0, 100.0, 110.0]) == _market_line([100.0, 110.0])
