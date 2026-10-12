"""응답 불명 매도의 체결 확인 회귀 — 2026-09-30.

사고: 15:20 삼성E&A 3주 MA120 청산 주문의 응답이 10초를 넘겼다. 봇은 이중매도를 막으려 재전송하지
않고 '매도 거부'로 처리했는데, 실제로는 봇이 포기한 3초 뒤(15:20:32) 증권사에 등록돼 15:30 종가
동시호가에 47,700원으로 체결됐다. state 에 유령 3주가 남았고 텔레그램엔 '🚨 매도 거부 → HTS 수동매도
검토'가 갔다 — 실제로 팔린 주식을 또 팔라고 권한 셈이다.

매수엔 응답 불명을 잔고로 확인하는 회수 경로(_confirm_unknown_buy)가 있었는데 매도엔 없었다.

여기서 잠그는 것:
  ① 재전송은 여전히 안 한다 — 증권사 **주문·체결내역**으로 사실만 확인한다
  ② 체결 확인 → 실제 체결가로 청산 · 접수 확인(동시호가 대기) → 정상 매도와 같게 청산
  ③ 주문 없음/조회 실패 → 보유 유지. 알림이 '수동매도'를 권하지 않는다(이미 팔렸을 수 있다)
  ④ 등록 지연(오늘 +3초)을 기다린다 · 이번 주문 전의 다른 주문을 이번 것으로 오인하지 않는다
  ⑤ 잔고는 근거로 쓰지 않는다 — 조회 실패도 빈 리스트라 '팔림'과 구분이 안 되고,
     동시호가 중엔 체결 전이라 잔고가 그대로다

가짜는 네트워크 끝(증권사 응답)에만 둔다. _manage·state·매매기록은 실제 함수를 지난다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

POS = {"symbol": "000001", "name": "테스트", "mode": "largecap", "qty": 3, "entry_price": 100.0,
       "stop_price": 90.0, "target": 130.0, "peak_price": 100.0, "atr": 2.0, "score": 50.0,
       "buy_date": "2026-09-28", "partial_done": False, "journal_id": "j1"}
CUR = 95.0          # 15:20 판정가

# 시계는 고정한다 — 실제 시각에 따라 동시호가 경로로 갈렸다 말았다 하면 테스트가 흔들린다.
BASE = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)     # 연속매매 시간
AUCTION = BASE.replace(hour=15, minute=20, second=20)                          # 종가 동시호가 중
# 실제 증권사처럼 동작하는 가짜 시장 상태 — 15:30 체결 전에는 체결내역에 동시호가 주문이 없다.
MARKET = {"after_close": False}


def _now_tm(offset_sec: int = 0, base: datetime = BASE) -> str:
    return (base + timedelta(seconds=offset_sec)).strftime("%H%M%S")


def _row(sym="000001", side="-매도", oq="3", cq="3", px="94", tm=None, stt="체결") -> dict:
    return {"ord_no": "0492535", "stk_cd": sym, "io_tp_nm": side, "ord_qty": oq, "cntr_qty": cq,
            "cntr_pric": px, "oso_qty": str(int(oq) - int(cq)), "ord_stt": stt,
            "ord_tm": tm or _now_tm(3), "trde_tp": "시장가"}


def _execs(*rows) -> str:
    return json.dumps({"success": True, "data": {"cntr": list(rows), "return_code": 0,
                                                 "return_msg": "조회완료"}}, ensure_ascii=False)


class _Broker:
    """MCPManager 대역 — 매도 주문 응답과 체결내역 응답을 시나리오대로 돌려준다."""

    def __init__(self, exec_replies, place="timeout"):
        self.exec_replies = list(exec_replies)     # 각 원소: 응답 문자열 · 예외 · 호출 시점에 평가할 함수
        self.place = place                         # 문자열(전 종목 공통) 또는 {종목: 모드}
        self.tools = [{"name": "place_sell_order"}, {"name": "get_order_executions"}]
        self.sells = 0
        self.exec_calls = 0
        self.log: list[str] = []                   # 호출 순서 — '다른 종목 매도를 기다리게 하지 않는다' 검증용

    def __call__(self, *_a, **_k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def call_tool(self, name, args):
        if name == "place_sell_order":
            self.sells += 1
            self.log.append(f"sell:{args.get('stock_code')}")
            mode = self.place.get(args.get("stock_code"), "ok") if isinstance(self.place, dict) else self.place
            if mode == "timeout":
                raise asyncio.TimeoutError()             # 응답 불명 — _place 가 unknown 으로 바꾼다
            if mode == "reject":
                return json.dumps({"success": True, "data": {"return_code": 20, "return_msg": "잔고부족"}})
            return json.dumps({"success": True, "data": {"return_code": 0, "ord_no": "1"}})
        if name == "get_order_executions":
            self.exec_calls += 1
            self.log.append("executions")
            r = self.exec_replies[min(self.exec_calls, len(self.exec_replies)) - 1]
            if callable(r):
                r = r()
            if isinstance(r, Exception):
                raise r
            return r
        raise AssertionError(f"예상 밖 도구 호출: {name}")


@pytest.fixture
def env(monkeypatch, tmp_path):
    """state·매매기록을 임시로 돌린 trend_follow + 알림·이벤트 수집."""
    import trend_runtime as RT
    for name, fn in (("STATE_FILE", "state.json"), ("STATE_BAK", "state.json.bak"),
                     ("STATE_TMP", "state.json.tmp"), ("JOURNAL_FILE", "journal.json")):
        monkeypatch.setattr(RT, name, tmp_path / fn)
    import trend_follow as TF

    notes: list[tuple[bool, str]] = []

    async def _notify(msg, critical=False):
        notes.append((critical, msg))

    async def _price(_sym):
        return CUR

    async def _signals(_pos, _cur):
        return {"ma_exit": 100.0, "ma_ref": 90.0}         # 완성 종가 90 < MA120 100 → 청산 신호

    real_sleep = asyncio.sleep
    MARKET["after_close"] = False
    MARKET["sleeps"] = []

    async def _fast_sleep(sec, *a, **k):
        MARKET["sleeps"].append(sec)
        if sec >= 300:                     # 15:30 이후까지 기다렸다 = 동시호가 체결이 끝났다
            MARKET["after_close"] = True
        await real_sleep(0)

    monkeypatch.setattr(TF, "_clock", lambda: BASE)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(TF, "notify", _notify)
    monkeypatch.setattr(TF, "log_event", lambda ev, p=None: events.append((ev, p)))
    monkeypatch.setattr(TF, "_realtime_price", _price)
    monkeypatch.setattr(TF, "_exit_signals", _signals)
    monkeypatch.setattr(TF, "EXITS", ("ma", "hold"))
    monkeypatch.setattr(TF.asyncio, "sleep", _fast_sleep)
    TF.save_state("positions", [dict(POS)])
    return TF, notes, events


def _run(TF, broker, monkeypatch):
    monkeypatch.setattr(TF, "MCPManager", broker)
    asyncio.run(TF._manage(do_exit_signals=True, when="exit"))


def _exits(TF):
    return [r for r in TF.read_journal() if r.get("type") == "exit"]


def _critical(notes):
    return [m for c, m in notes if c]


# ─── ② 체결·접수가 확인되면 청산 처리 ───────────────────────────────────────
def test_unknown_sell_confirmed_filled_is_closed_at_actual_fill(env, monkeypatch):
    """★ 증권사 내역에 체결이 보이면 실제 체결가로 청산 기록 — 유령을 만들지 않는다."""
    TF, notes, _ev = env
    broker = _Broker([_execs(_row(px="94"))])
    _run(TF, broker, monkeypatch)
    assert TF.get_state("positions") == [], "팔린 종목이 state 에 남았다 — 09-30 유령 재현"
    ex = _exits(TF)
    assert len(ex) == 1 and ex[0]["exit_price"] == 94.0, "실제 체결가로 기록하지 않았다"
    assert "응답 불명" in ex[0]["reason"], "응답 불명을 확인해 청산했다는 사실이 기록에 없다"
    assert broker.sells == 1, "응답 불명 매도를 재전송했다 — 이중매도 경로"
    assert not any("매도 거부" in m for m in _critical(notes)), "팔렸는데 '매도 거부'로 알렸다"


def test_unknown_sell_accepted_in_closing_auction_is_closed(env, monkeypatch):
    """★ 15:20~15:30 동시호가엔 접수만 되고 체결 전이다 — 접수 확인이면 정상 매도와 같게 청산."""
    TF, notes, _ev = env
    broker = _Broker([_execs(_row(cq="0", px="0", stt="접수"))])
    _run(TF, broker, monkeypatch)
    assert TF.get_state("positions") == []
    ex = _exits(TF)
    assert len(ex) == 1 and ex[0]["exit_price"] == CUR, "체결 전이면 정상 경로처럼 판정가로 기록해야 한다"
    assert broker.sells == 1


def test_late_registration_is_waited_for(env, monkeypatch):
    """★ 09-30 실제 패턴 — 봇이 포기한 뒤에야 증권사에 등록됐다. 첫 조회에 없어도 다시 본다."""
    TF, _notes, _ev = env
    broker = _Broker([_execs(), _execs(_row(cq="0", px="0", stt="접수"))])
    _run(TF, broker, monkeypatch)
    assert TF.get_state("positions") == []
    assert broker.exec_calls == 2 and broker.sells == 1


# ─── ③ 확인 안 되면 보유 유지 — 수동매도를 권하지 않는다 ───────────────────
def test_absent_order_keeps_position(env, monkeypatch):
    """조회는 되는데 주문이 끝까지 없으면 미접수 — 보유 유지, 다음 cycle 재판정."""
    TF, notes, _ev = env
    broker = _Broker([_execs()])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]
    assert _exits(TF) == []
    assert broker.exec_calls == TF.UNKNOWN_SELL_POLLS and broker.sells == 1
    crit = " ".join(_critical(notes))
    assert "주문 없음" in crit


def test_unverified_does_not_advise_manual_sell(env, monkeypatch):
    """★ 조회도 실패하면 모른다 — '수동매도 검토'는 이미 팔린 주식을 또 팔게 만든다."""
    TF, notes, _ev = env
    broker = _Broker([RuntimeError("체결내역 조회 실패")])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]
    crit = " ".join(_critical(notes))
    assert "HTS 수동매도" not in crit, "팔렸을 수 있는데 수동매도를 권했다"
    assert "주문내역" in crit, "HTS 주문내역부터 확인하라는 안내가 없다"


# ─── ④ 오인 방지 ────────────────────────────────────────────────────────────
def test_earlier_order_is_not_mistaken_for_this_one(env, monkeypatch):
    """이번 주문보다 훨씬 앞선 같은 종목 매도(다른 주문)는 증거가 아니다."""
    TF, _notes, _ev = env
    broker = _Broker([_execs(_row(tm="090000"))])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"], "오전 주문을 이번 체결로 오인했다"


def test_buy_rows_and_other_symbols_are_ignored(env, monkeypatch):
    TF, _notes, _ev = env
    broker = _Broker([_execs(_row(side="+매수"), _row(sym="000002"))])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]


# ─── 명시적 거부 경로는 그대로 ──────────────────────────────────────────────
def test_explicit_reject_path_unchanged(env, monkeypatch):
    """거부(rc≠0)는 접수 안 됨이 확실 — 기존대로 1회 재시도, 체결내역은 보지 않는다."""
    TF, _notes, _ev = env
    broker = _Broker([_execs()], place="reject")
    _run(TF, broker, monkeypatch)
    assert broker.sells == 2 and broker.exec_calls == 0
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]


# ─── 체결내역 파싱 ──────────────────────────────────────────────────────────
def test_parse_sell_orders_handles_kiwoom_formats():
    import trend_kiwoom_io as IO
    rows = [_row(sym="A000001", oq="+3", cq="2", px="-94", tm="152032"),
            _row(oq="1", cq="1", px="96", tm="152040"),
            _row(side="-매도취소", tm="152050"),
            _row(stt="거부", tm="152055")]
    got = IO._parse_sell_orders(_execs(*rows), "000001", "152000")
    assert got is not None
    ordered, filled, avg = got
    assert ordered == 4 and filled == 3
    assert avg == pytest.approx((2 * 94 + 1 * 96) / 3)


def test_parse_sell_orders_rejects_bad_payload():
    import trend_kiwoom_io as IO
    assert IO._parse_sell_orders("not json", "000001") is None
    assert IO._parse_sell_orders(json.dumps({"success": False, "error": "x"}), "000001") is None
    bad_rc = json.dumps({"success": True, "data": {"cntr": [], "return_code": 3, "return_msg": "8050"}})
    assert IO._parse_sell_orders(bad_rc, "000001") is None, "8050 같은 오류 응답을 '주문 없음'으로 읽었다"


# ═══════════════════════════════════════════════════════════════════════════
# 종가 동시호가(15:20~15:30) 응답 불명 매도 — 2026-10-12
#
# 하나금융 3주: 15:20:31 접수 → 15:30 체결 @124,400. 위 확인 로직이 15:20:30~15:21:24 동안
# 체결내역을 4번 봤지만 **체결 전 동시호가 주문은 체결내역에 나오지 않아** '미접수'로 오판했다
# (09-30 유령 재발). 가짜 증권사도 실제처럼 만든다 — 15:30 이전엔 비어 있고 이후에 나타난다.
# ═══════════════════════════════════════════════════════════════════════════
AUCTION_ROW_TM = _now_tm(11, AUCTION)          # 봇 발송 11초 뒤 접수(15:20:31)


def _auction_execs(sym="000001", qty="3", px="94"):
    """호출 시점의 가짜 시장 상태에 따라 — 체결 전엔 빈 내역, 15:30 이후엔 체결 행."""
    return lambda: _execs(_row(sym=sym, oq=qty, cq=qty, px=px, tm=AUCTION_ROW_TM)) \
        if MARKET["after_close"] else _execs()


@pytest.fixture
def auction(env, monkeypatch):
    TF, notes, events = env
    monkeypatch.setattr(TF, "_clock", lambda: AUCTION)
    return TF, notes, events


def test_auction_unknown_sell_settles_after_close(auction, monkeypatch):
    """★ 10-12 재현 — 동시호가 중 응답 불명 매도는 15:30 체결 이후에 확정해야 한다."""
    TF, notes, _ev = auction
    broker = _Broker([_auction_execs(px="124400")])
    _run(TF, broker, monkeypatch)
    assert TF.get_state("positions") == [], "체결된 종목이 장부에 남았다 — 10-12 유령 재현"
    ex = _exits(TF)
    assert len(ex) == 1 and ex[0]["exit_price"] == 124400.0, "15:30 실제 체결가로 기록하지 않았다"
    assert "15:30" in ex[0]["reason"]
    assert broker.sells == 1, "응답 불명 매도를 재전송했다"
    assert not _critical(notes), f"체결됐는데 경고를 보냈다: {_critical(notes)}"


def test_auction_settle_waits_until_after_close(auction, monkeypatch):
    """확정 조회는 15:30 체결 이후에 시작한다 — 15:20:20 발송이면 약 10분 기다린다."""
    TF, _notes, _ev = auction
    _run(TF, _Broker([_auction_execs()]), monkeypatch)
    long_waits = [s for s in MARKET["sleeps"] if s >= 300]
    assert long_waits and long_waits[0] == pytest.approx(610, abs=1)


def test_auction_wait_does_not_delay_other_sells(auction, monkeypatch):
    """★ 확정을 기다리느라 다른 종목 매도가 15:30 마감 뒤로 밀리면 전량 거부된다(rc 505217)."""
    TF, _notes, _ev = auction
    TF.save_state("positions", [dict(POS), {**POS, "symbol": "000002", "journal_id": "j2"}])
    broker = _Broker([_auction_execs()], place={"000001": "timeout", "000002": "ok"})
    _run(TF, broker, monkeypatch)
    first_exec = broker.log.index("executions")
    assert broker.log.index("sell:000002") < first_exec, "다른 종목 매도가 확정 대기 뒤로 밀렸다"
    assert TF.get_state("positions") == []


def test_auction_unfilled_keeps_position_and_alerts(auction, monkeypatch):
    """15:30 이후에도 체결이 없으면 그때 미체결로 판단 — 보유 유지 + 알림."""
    TF, notes, _ev = auction
    broker = _Broker([_execs()])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]
    assert broker.exec_calls == TF.AUCTION_SETTLE_POLLS
    crit = " ".join(_critical(notes))
    assert "15:30 이후에도" in crit


def test_auction_partial_fill_is_not_booked_as_full(auction, monkeypatch):
    """일부만 체결되면 전량 청산으로 기록하지 않는다 — 장부 수량은 사람이 정정."""
    TF, notes, _ev = auction
    broker = _Broker([lambda: _execs(_row(oq="3", cq="1", px="124400", tm=AUCTION_ROW_TM))
                      if MARKET["after_close"] else _execs()])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]
    assert _exits(TF) == []
    assert "일부만 체결" in " ".join(_critical(notes))


def test_auction_query_failure_does_not_advise_manual_sell(auction, monkeypatch):
    TF, notes, _ev = auction
    broker = _Broker([RuntimeError("체결내역 조회 실패")])
    _run(TF, broker, monkeypatch)
    assert [p["symbol"] for p in TF.get_state("positions")] == ["000001"]
    crit = " ".join(_critical(notes))
    assert "HTS 수동매도" not in crit and "주문" in crit


def test_intraday_sell_never_waits_for_auction(auction, monkeypatch):
    """★ 장중(intraday) 경로가 15:30 까지 기다리면 그 뒤 15:20 청산 phase 가 마감 뒤로 밀린다."""
    TF, _notes, _ev = auction

    async def _boom(*_a, **_k):
        raise AssertionError("장중 경로가 동시호가 확정 대기에 들어갔다")

    async def _crash(_sym):
        return 85.0                                       # -15% → 하드손절(장중에도 판정)
    monkeypatch.setattr(TF, "_settle_auction_sells", _boom)
    monkeypatch.setattr(TF, "_realtime_price", _crash)
    monkeypatch.setattr(TF, "MCPManager", _Broker([_execs()]))
    asyncio.run(TF._manage(do_exit_signals=False, when="intraday"))
