"""라이브 청산 사다리 ↔ 백테스트 청산 사다리 **일치 검증** — 2026-08-17.

배경: 청산 판정이 두 곳에 각각 구현돼 있다.
  라이브     signals.exit_decision           — 하드손절→부분익절→트레일→MA→외인→만기
  백테스트   backtest_trend.simulate_trade   — 같은 순서를 일봉 OHLC 위에 손으로 구현

`backtest_trend.py:159` 에 "라이브 exit_decision 우선순위와 동일" 이라는 **주석으로만**
보증돼 있었다. 사람이 눈으로 맞춰야 하는 불변식은 언젠가 깨진다.

구현을 하나로 합치는 방법도 검토했으나, 일봉 백테스트는 한 봉에서 저가/고가/종가로 각각
다른 신호를 봐야 해서 exit_decision 을 세 번 부르며 stop=0·target=0 같은 **센티널 인자로
서로를 비활성화**해야 한다. 그 방식은 지금의 명시적 비교문보다 읽기 어렵고, exit_decision
인자 의미가 바뀌면 백테스트 뜻이 조용히 달라진다 — 막으려던 것과 같은 종류의 결합이다.

그래서 구현은 둘로 두되, **동치성을 테스트로 잠근다.** 한쪽만 고치면 여기서 깨진다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from src.mcp_servers.trend_mcp.signals import TrendConfig, exit_decision  # noqa: E402

CFG = TrendConfig()
QTY = 100          # 백테스트는 비율 계산 — 부분익절 30% 가 정수로 떨어지는 가상 수량


def _live(cur, *, entry=10000.0, stop=9300.0, target=12100.0, partial_done=False,
          hard=0.0, ma_exit=None, foreign=None, use_foreign=False, ma_trend=None, aged=False):
    return exit_decision(entry=entry, cur=cur, qty=QTY, target=target, stop=stop,
                         partial_done=partial_done, hard_stop_pct=hard,
                         partial_pct=CFG.partial_pct, ma_exit=ma_exit, exit_ma_label=120,
                         foreign_net=foreign, use_foreign=use_foreign,
                         ma_trend=ma_trend, trend_ma_label=60, aged_out=aged)


# ─── 우선순위: 라이브 사다리의 순서가 백테스트 평가 순서와 같아야 한다 ──────────
def test_partial_precedes_trail():
    """백테스트는 고가(부분익절)를 저가(트레일)보다 먼저 본다 — 라이브도 같은 순서여야."""
    act, _, _ = _live(12100.0, stop=12000.0)      # 목표·트레일 동시 충족
    assert act == "PARTIAL"


def test_hard_stop_precedes_partial():
    """하드손절이 최우선 — 같은 봉에서 둘 다 걸리면 손실 차단이 먼저다."""
    act, reason, _ = _live(8500.0, hard=10.0, target=8000.0)
    assert act == "EXIT" and "하드" in reason


def test_trail_precedes_ma():
    act, reason, _ = _live(9200.0, stop=9300.0, ma_exit=9500.0)
    assert act == "EXIT" and "트레일" in reason


def test_ma_precedes_foreign():
    act, reason, _ = _live(9400.0, stop=9000.0, ma_exit=9500.0,
                           foreign=-5000.0, use_foreign=True)
    assert act == "EXIT" and "MA120" in reason


def test_aged_is_last():
    """시간청산은 맨 뒤 — 다른 신호가 없을 때만. 백테스트의 max_hold 종가청산과 같은 의미."""
    act, reason, _ = _live(10500.0, stop=9000.0, aged=True)
    assert act == "EXIT" and "보유기간" in reason


# ─── 하드손절 발동 조건: 백테스트의 hard_floor 와 같은 가격에서 걸려야 한다 ─────
@pytest.mark.parametrize("hard_pct", [5.0, 7.0, 10.0, 15.0])
def test_hard_stop_triggers_at_same_price_as_backtest_floor(hard_pct):
    """백테스트: eff_stop = max(stop, entry*(1-h/100)), low <= eff_stop 이면 청산.
    라이브:   pnl(cur) <= -h 이면 청산. 두 임계가 같은 가격이어야 한다."""
    entry = 10000.0
    floor = entry * (1 - hard_pct / 100.0)        # 백테스트 hard_floor
    assert _live(floor - 1, entry=entry, stop=0.0, hard=hard_pct)[0] == "EXIT"
    assert _live(floor + 1, entry=entry, stop=0.0, hard=hard_pct)[0] is None


def test_hard_floor_below_trail_uses_trail():
    """트레일이 하드손절보다 위면 트레일이 먼저 — 백테스트 max(stop, floor) 와 동치."""
    act, reason, _ = _live(9400.0, entry=10000.0, stop=9500.0, hard=10.0)
    assert act == "EXIT" and "트레일" in reason


# ─── 부분익절 수량: 백테스트의 rem 감소분과 일치 ───────────────────────────────
def test_partial_qty_matches_cfg_pct():
    _, _, part = _live(12100.0)
    assert part / QTY == pytest.approx(CFG.partial_pct / 100.0)


def test_partial_only_once():
    """이미 익절했으면 다시 안 된다 — 백테스트의 partial 플래그와 같은 동작."""
    assert _live(13000.0, partial_done=True)[0] is None


# ─── 외인 청산: 백테스트 _foreign_exit_today 가 True 를 준 경우와 동치 ─────────
def test_foreign_exit_when_flagged():
    act, reason, _ = _live(10500.0, stop=9000.0, foreign=-5000.0, use_foreign=True)
    assert act == "EXIT" and "외국인" in reason


def test_foreign_ignored_when_off():
    """백테스트 V_FOREIGN_MIN_RATIO=None 이면 외인룰 미적용 — 라이브 use_foreign=False 와 동치."""
    assert _live(10500.0, stop=9000.0, foreign=-5000.0, use_foreign=False)[0] is None


def test_foreign_needs_trend_break_when_ma_given():
    """MA60 위면 수급만으로 팔지 않는다(2026-07-31 4종 오청산 방지).
    백테스트 V_FOREIGN_TREND_MA 의 `close >= ma → False` 와 같은 뜻."""
    assert _live(10500.0, stop=9000.0, foreign=-5000.0, use_foreign=True,
                 ma_trend=10000.0)[0] is None
    assert _live(9900.0, stop=9000.0, foreign=-5000.0, use_foreign=True,
                 ma_trend=10000.0)[0] == "EXIT"


# ─── 홀드: 아무 신호도 없으면 계속 보유 ────────────────────────────────────────
def test_hold_when_nothing_triggers():
    assert _live(10500.0, stop=9000.0, ma_exit=9800.0)[0] is None


def test_disabling_sentinels_behave_as_backtest_expects():
    """백테스트가 각 pass 에서 신호를 끄는 방식(stop=0 / target=0)이 실제로 꺼지는지.
    이 동치가 깨지면 3-pass 어댑터를 쓰는 어떤 통합도 조용히 틀린다."""
    assert _live(1.0, stop=0.0, target=0.0, hard=0.0)[0] is None        # 전부 off → 홀드
    assert _live(99999.0, target=0.0)[0] is None                        # target=0 → 부분익절 off


# ─── ma_ref: MA 조건만 완성 종가로 판정 (2026-08-25 KB금융) ────────────────────
def test_ma_ref_separates_ma_conditions_from_intraday_price():
    """★ MA 조건은 완성 종가로, 트레일·하드손절은 장중가로 — 서로 다른 가격을 쓴다.

    KB금융 실제: 15:20 장중 164,900 / MA60 165,813 → 청산. 종가는 166,400(>MA)이었다.
    ma_ref 에 종가를 넘기면 MA 판정만 종가 기준이 되고, 트레일은 장중가를 계속 본다.
    """
    common = dict(entry=167_500.0, qty=2, target=229_814.0, stop=146_728.0,
                  partial_done=True, hard_stop_pct=10.0,
                  foreign_net=-278_177.0, use_foreign=True, ma_trend=165_813.0)
    # 장중가만 쓰던 과거 동작 — 청산
    act, reason, _ = exit_decision(cur=164_900.0, **common)
    assert act == "EXIT" and "외국인" in reason
    # 완성 종가를 MA 기준으로 넘기면 — 홀드
    act2, _, _ = exit_decision(cur=164_900.0, ma_ref=166_400.0, **common)
    assert act2 is None, "종가 166,400 은 MA 165,813 위 → 외인룰 미발동"


def test_ma_ref_does_not_weaken_trail_or_hard_stop():
    """ma_ref 는 이평선 전용이다 — 트레일/하드손절은 장중가로 계속 판정해야 한다."""
    # 장중가가 트레일 아래로 뚫렸다면 종가가 위여도 청산
    act, reason, _ = exit_decision(entry=100.0, cur=89.0, qty=10, target=130.0, stop=90.0,
                                   partial_done=True, ma_ref=105.0)
    assert act == "EXIT" and "트레일" in reason
    # 하드손절도 마찬가지
    act2, reason2, _ = exit_decision(entry=100.0, cur=88.0, qty=10, target=130.0, stop=0.0,
                                     partial_done=True, hard_stop_pct=10.0, ma_ref=105.0)
    assert act2 == "EXIT" and "하드" in reason2


def test_ma_ref_defaults_to_cur():
    """미지정이면 기존 동작(cur 로 MA 비교) — 백테스트는 이미 종가를 cur 로 넘긴다."""
    kw = dict(entry=100.0, qty=10, target=130.0, stop=80.0, partial_done=True, ma_exit=95.0)
    assert exit_decision(cur=94.0, **kw)[0] == exit_decision(cur=94.0, ma_ref=94.0, **kw)[0]


def test_ma120_exit_also_uses_ma_ref():
    """MA120 단독 청산도 같은 기준을 쓴다(외인룰만이 아니다)."""
    kw = dict(entry=100.0, qty=10, target=130.0, stop=80.0, partial_done=True, ma_exit=95.0)
    assert exit_decision(cur=94.0, **kw)[0] == "EXIT"              # 장중 이탈
    assert exit_decision(cur=94.0, ma_ref=96.0, **kw)[0] is None   # 종가는 MA 위


# ─── EXITS 스위치 동치 (2026-08-28) ───────────────────────────────────────────
# 라이브(signals.exit_decision)와 백테스트(backtest_trend_portfolio.simulate)가 **같은
# 문자열 규약**으로 사다리를 켜고 끈다. 한쪽만 바뀌면 여기서 깨진다.
ADOPTED_EXITS = ("ma", "hold")


def _ex(cur, exits, **kw):
    base = dict(entry=10000.0, qty=100, target=12100.0, stop=9300.0,
                partial_done=False, hard_stop_pct=10.0, partial_pct=CFG.partial_pct,
                exit_ma_label=120, exits=exits)
    base.update(kw)
    return exit_decision(cur=cur, **base)


def test_adopted_config_ignores_trail():
    """★ 채택 구성에서 트레일 이탈은 청산 사유가 아니다."""
    assert _ex(9200.0, ADOPTED_EXITS)[0] is None, "트레일이 꺼졌는데 청산됐다"
    assert _ex(9200.0, ("partial", "trail", "ma", "hold"))[0] == "EXIT"   # 구 구성은 청산


def test_adopted_config_ignores_partial():
    """부분익절도 꺼진다 — 목표 도달해도 전량 보유(우측꼬리 유지)."""
    assert _ex(12100.0, ADOPTED_EXITS)[0] is None
    assert _ex(12100.0, ("partial", "trail", "ma", "hold"))[0] == "PARTIAL"


def test_adopted_config_keeps_ma_exit():
    act, reason, _ = _ex(9400.0, ADOPTED_EXITS, ma_exit=9500.0)
    assert act == "EXIT" and "MA120" in reason


def test_adopted_config_keeps_time_exit():
    act, reason, _ = _ex(10500.0, ADOPTED_EXITS, aged_out=True)
    assert act == "EXIT" and "보유기간" in reason


def test_hard_stop_survives_every_exits_combo():
    """★ 하드손절은 어떤 조합에서도 살아 있어야 한다 — 위험 바닥이므로."""
    for exits in ((), ("ma",), ("hold",), ADOPTED_EXITS, ("partial", "trail", "ma", "hold")):
        act, reason, _ = _ex(8900.0, exits, stop=0.0, target=0.0)
        assert act == "EXIT" and "하드" in reason, f"exits={exits} 에서 하드손절이 죽었다"


def test_empty_exits_holds_unless_hard_stop():
    """전부 끄면 하드손절 외엔 아무것도 팔지 않는다."""
    assert _ex(9200.0, (), ma_exit=9500.0, aged_out=True)[0] is None
    assert _ex(8000.0, ())[0] == "EXIT"


def test_live_and_backtest_share_exit_token_vocabulary():
    """★ 라이브와 백테스트가 같은 토큰을 쓰는지 — 오타 하나로 규칙이 조용히 꺼진다."""
    import inspect
    import sys
    sys.path.insert(0, str(_ROOT / "scripts"))
    import backtest_trend_portfolio as P
    bt = inspect.signature(P.simulate).parameters["exits"].default
    live = inspect.signature(exit_decision).parameters["exits"].default
    assert set(bt) == set(live) == {"partial", "trail", "ma", "hold"}, \
        "두 하니스의 사다리 토큰이 갈렸다 — 한쪽에서만 켜지는 규칙이 생긴다"


def test_config_exits_are_valid_tokens():
    """설정에 오타가 있으면 그 규칙은 조용히 꺼진다 — 기동 전에 잡는다."""
    import sys
    sys.path.insert(0, str(_ROOT / "scripts"))
    from trend_config import EXITS
    assert set(EXITS) <= {"partial", "trail", "ma", "hold"}, f"알 수 없는 토큰: {EXITS}"
    assert EXITS, "EXITS 가 비었다 — 하드손절 외 청산이 없다"
