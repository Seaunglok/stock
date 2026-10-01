"""Notion 매매일지 동기화 보조 회귀 — 2026-10-01.

사고: 09-28 동기화가 Notion rate limit 에 걸려 결과 없이 끝났는데 예약작업 결과는 0x0 이었다.
규칙이 '오늘 거래만' 넣어서 다음 날에도 메워지지 않았다 → 09-28 매수 2건 누락, 9월 결산 매수 0.

여기서 잠그는 것:
  ① 행 값 규약이 기존 DB 행과 같다 — 실제 행 4건의 실현손익으로 잠근다(다르면 결산 합계가 어긋난다)
  ② 최근 N일을 다시 내보낸다 — 하루를 놓쳐도 다음 실행이 메운다. 지난달 보완이면 그 달 결산도 대상
  ③ 완료 판정은 **이번 실행분 로그만** 본다 — 누적 로그의 지난 결과 줄을 이번 성공으로 오인하지 않는다
  ④ prep 자신의 로그 줄이 결과 줄로 오인되지 않는다
  ⑤ 동기화 래퍼·작업 지시가 이 파일을 실제로 쓴다(배선)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import notion_sync as N  # noqa: E402


def _entry(sym="028050", name="삼성E&A", px=49850.0, qty=3, ts="2026-09-28T11:01:01", score=58.1):
    return {"ts": ts, "type": "entry", "id": "e" + sym, "symbol": sym, "name": name, "qty": qty,
            "entry_price": px, "score": score, "mode": "largecap"}


def _exit(entry_px, qty, net, ts="2026-09-30T15:20:32", sym="028050", name="삼성E&A", exit_px=47700.0,
          reason="MA120 이평선 하방돌파 (47,750 < 48,785)"):
    return {"ts": ts, "type": "exit", "id": "e" + sym, "symbol": sym, "name": name, "qty": qty,
            "entry_price": entry_px, "exit_price": exit_px, "net_pct": net, "reason": reason}


# ─── ① 값 규약 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("entry_px, qty, net, expected", [
    (49850.0, 3, -4.74, -7089),     # 삼성E&A 09-30 (DB 실측)
    (91200.0, 4, 25.78, 94045),     # GS 08-21
    (167500.0, 2, -1.09, -3652),    # KB금융 08-25 (체결가 정정 후)
    (127500.0, 5, -8.43, -53741),   # 메리츠금융지주 07-28
])
def test_realized_pnl_matches_existing_notion_rows(entry_px, qty, net, expected):
    """★ 실현손익 = 진입금액 × net% — 기존 DB 행과 같은 규약이어야 월 결산이 이어진다."""
    rows = N.notion_rows([_exit(entry_px, qty, net)], "2026-01-01")
    assert rows[0]["실현손익"] == expected


def test_entry_row_shape():
    row = N.notion_rows([_entry()], "2026-01-01")[0]
    assert row["종목명"] == "삼성E&A(028050)"
    assert row["매매구분"] == "매수" and row["매수일자"] == "2026-09-28"
    assert row["체결단가"] == 49850 and row["체결수량"] == 3 and row["총체결금액"] == 149550
    assert row["매매이유"].startswith("🤖 추세추종") and "58.1" in row["매매이유"]
    assert row["key"] == "028050|매수|2026-09-28"


def test_exit_row_shape():
    row = N.notion_rows([_exit(49850.0, 3, -4.74)], "2026-01-01")[0]
    assert row["매매구분"] == "매도" and row["매도일자"] == "2026-09-30"
    assert row["총체결금액"] == 143100 and row["수익률(%)"] == -4.74
    assert "MA120" in row["매매이유"]


def test_only_entries_and_exits_since_window():
    recs = [_entry(ts="2026-09-20T11:00:00"),                      # 창 밖
            _entry(sym="003490", name="대한항공", px=31400.0, qty=6),  # 창 안
            {"ts": "2026-09-29T10:00:00", "type": "note", "id": "x"},
            {"ts": "2026-09-29T10:00:00", "type": "pyramid", "id": "x", "symbol": "003490", "qty": 1},
            {"ts": "2026-09-29T10:00:00", "type": "partial", "id": "x", "symbol": "003490", "qty": 1}]
    rows = N.notion_rows(recs, "2026-09-24")
    assert [r["종목명"] for r in rows] == ["대한항공(003490)"]


# ─── ② 최근 N일 재대조 ──────────────────────────────────────────────────────
def test_missed_day_is_still_in_next_payload():
    """★ 09-28 거래를 놓쳐도 10-01 실행의 파일에 다시 들어 있어야 한다 — 자동 복구의 전제."""
    p = N.build_payload([_entry()], datetime(2026, 10, 1, 16, 10))
    assert p["since"] == "2026-09-24"
    assert [r["key"] for r in p["rows"]] == ["028050|매수|2026-09-28"]


def test_backfilled_month_is_aggregated_too():
    """지난달 거래를 보완한 날은 그 달 결산도 다시 계산해야 한다."""
    p = N.build_payload([_entry()], datetime(2026, 10, 1, 16, 10))
    assert p["months"] == ["2026-09", "2026-10"]


def test_window_covers_long_holiday():
    """추석(3일)+주말 뒤 첫 실행도 연휴 전날 거래를 다시 볼 수 있어야 한다."""
    assert N.LOOKBACK_DAYS >= 6


# ─── ③④ 완료 판정 ──────────────────────────────────────────────────────────
def test_missing_result_line_is_failure():
    ok, why = N.judge("Notion rate limit hit on the first query — waiting out the cooldown\n")
    assert not ok and "결과 줄 없음" in why


def test_auth_failure_result_is_failure():
    ok, _ = N.judge("결과: ❌ Notion 인증 만료 — 재인증 필요(반영 0건)\n")
    assert not ok


def test_normal_result_is_success():
    ok, why = N.judge("- A: ...\n`결과: DB 보완 2건 + 종합정리 갱신`\n")
    assert ok and why.startswith("결과:")


def test_only_this_runs_log_is_judged(tmp_path):
    """★ 로그는 누적된다 — 어제의 결과 줄을 오늘의 성공으로 읽으면 이 감시는 영원히 조용하다."""
    log = tmp_path / "notion_journal.log"
    old = "결과: 거래없음 — 종합정리 갱신\n".encode("utf-8")
    log.write_bytes(old + "Notion rate limit hit — waiting\n".encode("utf-8"))
    ok, _ = N.judge(N.read_new_log(log, len(old)))
    assert not ok, "지난 실행의 결과 줄을 이번 성공으로 오인했다"


def test_prep_line_is_not_a_result_line():
    """prep 이 로그에 남기는 줄을 check 가 에이전트 결과로 읽으면 실패가 묻힌다."""
    s = N.prep_summary(N.build_payload([_entry()], datetime(2026, 10, 1)))
    assert N.RESULT_TAG not in s
    assert not N.judge(s)[0]


def test_check_alerts_on_failure(tmp_path, monkeypatch):
    import trend_runtime as RT
    sent = []

    async def _notify(msg, critical=False):
        sent.append((critical, msg))
    monkeypatch.setattr(RT, "notify", _notify)
    log = tmp_path / "l.log"
    log.write_text("rate limit\n", encoding="utf-8")
    assert N.check(log, 0) == 1
    assert sent and sent[0][0] is True and "동기화 미완료" in sent[0][1]


def test_check_is_quiet_on_success(tmp_path, monkeypatch):
    import trend_runtime as RT

    async def _boom(*_a, **_k):
        raise AssertionError("성공인데 알렸다")
    monkeypatch.setattr(RT, "notify", _boom)
    log = tmp_path / "l.log"
    log.write_text("결과: 거래없음 — 종합정리 갱신\n", encoding="utf-8")
    assert N.check(log, 0) == 0


def test_dry_run_never_sends(tmp_path, monkeypatch):
    import trend_runtime as RT

    async def _boom(*_a, **_k):
        raise AssertionError("dry-run 인데 보냈다")
    monkeypatch.setattr(RT, "notify", _boom)
    log = tmp_path / "l.log"
    log.write_text("", encoding="utf-8")
    assert N.check(log, 0, dry_run=True) == 1


# ─── ⑤ 배선 ─────────────────────────────────────────────────────────────────
def test_wrapper_runs_prep_before_and_check_after_agent():
    src = (_ROOT / "scripts" / "notion_journal.cmd").read_text(encoding="ascii")   # ASCII 전용(cp949 안전)
    i_prep, i_agent, i_check = (src.index("notion_sync.py prep"), src.index("claude.exe"),
                                src.index("notion_sync.py check"))
    assert i_prep < i_agent < i_check, "prep → 에이전트 → check 순서가 아니다"
    assert "--offset" in src, "실행 전 로그 크기를 넘기지 않으면 지난 결과 줄을 오인한다"


def test_task_instructions_use_the_payload():
    md = (_ROOT / "scripts" / "notion_journal_task.md").read_text(encoding="utf-8")
    assert "notion_sync_trades.json" in md, "에이전트가 계산 파일을 읽지 않는다"
    assert "없는 행만" in md and "months" in md


def test_helper_is_off_the_order_path():
    src = (_ROOT / "scripts" / "notion_sync.py").read_text(encoding="utf-8")
    for banned in ("_place", "place_buy", "place_sell", "save_state", "trend_kiwoom_io"):
        assert banned not in src
