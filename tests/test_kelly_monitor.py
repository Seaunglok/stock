"""켈리 감시 기준 회귀 — 2026-09-09.

이 파일이 지키는 것은 계산의 정확성만이 아니라 **기준을 표본 보기 전에 정했다는 사실**이다.
상수를 바꾸면 여기서 깨지고, git 이력이 '언제 무엇을 근거로 바꿨는지'를 남긴다.
(워크포워드 MDD_RATIO 와 같은 패턴 — 2026-08-28.)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import kelly_monitor as K  # noqa: E402


# ─── 선언된 기준이 그대로인가 ────────────────────────────────────────────────
def test_criteria_are_frozen_constants():
    """★ 표본을 보기 전에 정한 값들 — 바꾸려면 문서에 근거를 남길 것."""
    assert K.MIN_TRADES == 50
    assert K.PERSIST_N == 2
    assert K.STRESS_CUT_PCT == 5.0
    assert K.ABANDON_AFTER == 12 and K.ABANDON_SWING == 5.0
    assert K.ADOPTED_SINCE == "2026-08-28"


def test_persistence_required_so_single_crossing_is_ignored():
    """f* 는 구간마다 10배 흔들린다(12년 4분할 29%~285%) — 단발 교차로 움직이면 안 된다."""
    assert K.PERSIST_N >= 2


# ─── 계산 정확성 ────────────────────────────────────────────────────────────
def test_kelly_matches_textbook_on_binary_bet():
    """★ 이항 베팅에선 일반화 켈리가 교과서 f*=(bp-q)/b 와 일치해야 한다.

    이기면 +1(2배), 지면 -1(전액). p=0.6 → f* = (1*0.6-0.4)/1 = 0.2
    """
    R = [1.0] * 600 + [-1.0] * 400
    assert K.kelly_fraction(R) == pytest.approx(0.2, abs=0.01)


def test_kelly_is_zero_when_no_edge():
    """기대값이 0 이하면 걸 이유가 없다."""
    R = [1.0] * 500 + [-1.0] * 500
    assert K.kelly_fraction(R) == pytest.approx(0.0, abs=0.01)


def test_kelly_exceeds_one_when_loss_is_capped():
    """★ 최악 손실이 -100% 가 아니면 f* 는 1 을 넘을 수 있다(레버리지 권고).

    우리 실제 상황이다 — 하드손절이 -10% 에서 자른다. 이걸 모르면 133% 를
    '계산 오류'로 오해하게 된다.
    """
    R = [0.5] * 300 + [-0.10] * 700          # 최악 -10%
    assert K.kelly_fraction(R) > 1.0


def test_growth_is_maximized_at_f_star():
    """f* 양옆에서 로그성장률이 더 낮아야 한다 — 최적화가 실제로 최적을 찾았는지."""
    R = [0.5] * 300 + [-0.10] * 700
    f = K.kelly_fraction(R)

    def g(x):
        return sum(math.log(1 + x * r) for r in R) / len(R)
    assert g(f) > g(f * 0.8)
    assert g(f) > g(f * 1.2)


def test_empty_sample_is_zero_not_crash():
    assert K.kelly_fraction([]) == 0.0
    assert K.kelly_stress([]) == 0.0


# ─── 스트레스 절단 ──────────────────────────────────────────────────────────
def test_stress_cut_lowers_f_star_for_fat_tail():
    """꼬리를 지우면 f* 가 내려간다 — 실측 133% → 27.9% 였다."""
    R = [3.0] * 50 + [0.2] * 250 + [-0.10] * 700      # 상위에 큰 승자
    assert K.kelly_stress(R, 5.0) < K.kelly_fraction(R)


def test_stress_is_not_used_for_verdict():
    """★ 판정은 **전체 분포**로 한다 — 꼬리를 지우면 추세추종의 엣지 자체를 지운다.

    상위 5% 절단본으로 판정하면 '큰 승자가 없다면'이라는 틀린 전제로 판정하게 된다.
    실측: 절단 f* 27.9% < 노출 100% → 켜자마자 상시 경보가 된다.
    """
    R = [3.0] * 50 + [0.2] * 250 + [-0.10] * 700
    a = K.assess(R, exposure=0.5)
    assert a["f_star"] > a["f_stress"], "표본 전제가 깨졌다"
    # 전체 f* 로 판정했으면 정상, 절단본으로 판정했으면 과베팅이 나올 구성
    assert a["verdict"] == "정상"


# ─── 표본 요건 ──────────────────────────────────────────────────────────────
def test_no_verdict_below_minimum_sample():
    """★ 표본이 모자라면 어떤 판정도 하지 않는다 — 숫자를 보고 기준을 맞추게 되는 걸 막는다."""
    a = K.assess([0.1] * (K.MIN_TRADES - 1), exposure=1.0)
    assert a["verdict"] == "표본부족"
    assert a["f_star"] is None, "표본 부족인데 f* 를 계산해 보여주면 그걸 보고 판단하게 된다"


def test_verdict_appears_at_minimum_sample():
    a = K.assess([0.5] * 20 + [-0.1] * 30, exposure=1.0)   # 정확히 50건
    assert a["verdict"] in ("정상", "과베팅")
    assert a["f_star"] is not None


def test_overbet_verdict_when_f_star_below_exposure():
    """★ f* 가 노출보다 낮으면 과베팅으로 판정한다 — 이 지표의 존재 이유.

    손실 폭이 클수록 f* 가 작아진다: 승 +40%/패 -40%, 승률 60% → f* = 50%.
    (손실이 -5% 처럼 얕으면 f* 가 500% 를 넘어 과베팅 판정 자체가 안 나온다 —
     우리 실제 분포가 그쪽이라, 하드손절이 f* 를 크게 만든다는 뜻이기도 하다.)
    """
    R = [0.4] * 60 + [-0.4] * 40          # f* ≈ 50%
    assert K.kelly_fraction(R) == pytest.approx(0.5, abs=0.02)
    assert K.assess(R, exposure=1.0)["verdict"] == "과베팅"
    assert K.assess(R, exposure=0.3)["verdict"] == "정상"


# ─── 주문 경로 무관 ─────────────────────────────────────────────────────────
def test_monitor_never_touches_orders():
    """★ 이 모듈은 주문·사이징에 관여하지 않는다.

    자동 사이징으로 바뀌면 워크포워드 재검증 없이 실계좌 거래가 달라진다.
    """
    src = (_ROOT / "scripts" / "kelly_monitor.py").read_text(encoding="utf-8")
    for banned in ("_place", "place_buy", "place_sell", "save_state", "trend_kiwoom_io"):
        assert banned not in src, f"주문/상태 경로({banned})를 건드린다"


def test_monitor_is_not_imported_by_daemon():
    """★ 데몬이 이 모듈을 부르면 그 순간 매매 경로에 들어온다."""
    src = (_ROOT / "scripts" / "trend_follow.py").read_text(encoding="utf-8")
    assert "kelly_monitor" not in src


# ─── 채택 구성 이후만 센다 ──────────────────────────────────────────────────
def test_adopted_since_matches_exit_ladder_change():
    """★ 08-28 이전 거래는 청산 사다리가 다르다(트레일·부분익절 포함).

    섞으면 지금 안 쓰는 규칙의 f* 를 감시하게 된다.
    """
    assert K.ADOPTED_SINCE == "2026-08-28"
    doc = (_ROOT / "docs" / "2026-08-28-adoption.md").read_text(encoding="utf-8")
    assert "ma,hold" in doc, "채택일 근거 문서가 사라졌다"


# ═══════════════════════════════════════════════════════════════════════════
# 저장 형식 경계 (2026-09-29)
#
# 09-09 판독 로직은 `closed`·`exit_date` 필드를 찾았는데, 데몬이 쓰는 청산 기록엔 둘 다 없다
# (`type: "exit"` + `ts`). 운영 저널의 청산 22건 중 **0건**을 읽었다 — 첫 청산이 나와도 "0/50"
# 으로 남았을 것이다. 위 테스트들은 가짜 리스트로 계산만 검증해 경계를 한 번도 지나지 않았다.
# 여기서는 데몬과 같은 쓰기 함수(journal_append)로 기록하고 같은 읽기 함수로 읽는다.
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def journal(monkeypatch, tmp_path):
    """저널을 임시 파일로 — 운영 journal.json 을 건드리지 않는다."""
    import trend_runtime as RT
    f = tmp_path / "journal.json"
    monkeypatch.setattr(RT, "JOURNAL_FILE", f)
    return f


def _exit_rec(jid: str, net: float, qty: int = 3) -> dict:
    """trend_follow 의 청산 journal_append 와 같은 모양(ts 는 journal_append 가 붙인다)."""
    return {"type": "exit", "id": jid, "symbol": "000000", "name": "테스트", "qty": qty,
            "entry_price": 10000.0, "exit_price": round(10000.0 * (1 + net / 100), 2),
            "decided_at": 0.0, "pnl_pct": net, "net_pct": net, "pnl_amount": 0,
            "rr_realized": None, "reason": "MA120 이평선 하방돌파", "hold_days": 2}


def _write_at(f: Path, ts: str, rec: dict) -> None:
    """과거 시각의 기록 — journal_append 는 ts 를 현재로 찍으므로 날짜 필터 검증용으로 직접 쓴다."""
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, **rec}, ensure_ascii=False) + "\n")


def test_reads_exit_written_by_daemon_writer(journal):
    """★ 데몬의 쓰기 함수로 남긴 청산을 켈리 감시가 읽어야 한다 — 09-29 결함의 직접 재현."""
    import trend_runtime as RT
    RT.journal_append(_exit_rec("a1", -4.21))
    assert K.adopted_returns(since="2000-01-01") == pytest.approx([-0.0421])


def test_ignores_non_exit_records(journal):
    """진입·피라미딩·메모는 청산이 아니다."""
    for rec in ({"type": "entry", "id": "a1", "qty": 3, "entry_price": 10000.0},
                {"type": "pyramid", "id": "a1", "qty": 1},
                {"type": "note", "id": "a1", "psych": "조급함"}):
        _write_at(journal, "2026-09-28T11:00:00", rec)
    assert K.adopted_returns(since="2000-01-01") == []


def test_partial_exits_are_one_trade_qty_weighted(journal):
    """한 거래를 나눠 팔았으면(구 사다리의 부분익절) 켈리 표본은 **1건** — 수량 가중 수익률.

    켈리의 베팅 단위는 거래다. 청산 기록 단위로 세면 부분익절한 승자가 표본을 두 번 차지한다.
    """
    _write_at(journal, "2026-09-30T10:00:00", _exit_rec("t1", 30.0, qty=1))
    _write_at(journal, "2026-10-02T15:20:00", _exit_rec("t1", -10.0, qty=2))
    assert K.adopted_returns(since="2000-01-01") == pytest.approx([(30.0 * 1 - 10.0 * 2) / 3 / 100])


def test_exits_before_adoption_are_excluded(journal):
    """채택일 이전 청산은 다른 사다리의 분포다 — 날짜는 청산 시각(ts) 기준."""
    _write_at(journal, "2026-08-25T15:20:26", _exit_rec("old", -1.09))
    _write_at(journal, "2026-09-30T15:20:00", _exit_rec("new", -4.0))
    assert K.adopted_returns() == pytest.approx([-0.04])


def test_writer_schema_still_has_fields_reader_needs():
    """★ 데몬의 청산 기록 형식이 바뀌면 여기서 깨진다 — 읽는 쪽이 조용히 0건이 되는 것을 막는다."""
    src = (_ROOT / "scripts" / "trend_follow.py").read_text(encoding="utf-8")
    i = src.index('journal_append({"type": "exit"')
    call = src[i:src.index("})", i)]
    for key in ('"id"', '"qty"', '"net_pct"'):
        assert key in call, f"청산 기록에 {key} 가 없다 — 켈리 감시가 읽을 수 없다"
    rt = (_ROOT / "scripts" / "trend_runtime.py").read_text(encoding="utf-8")
    assert '{"ts": datetime.now()' in rt, "journal_append 가 ts 를 붙이지 않는다 — 날짜 필터가 무력화된다"


def test_live_journal_exits_are_readable():
    """★ 운영 저널에 청산 기록이 있으면 판독 결과도 0 이 아니어야 한다.

    2026-09-29: 청산 22건이 있는데 0건으로 읽혔다. 운영 데이터가 없는 환경에선 건너뛴다.
    """
    import trend_runtime as RT
    if not RT.JOURNAL_FILE.exists():
        pytest.skip("운영 저널 없음")
    n_exit = sum(1 for r in RT.read_journal() if r.get("type") == "exit")
    if n_exit == 0:
        pytest.skip("운영 저널에 청산 기록 없음")
    assert K.adopted_returns(since="2000-01-01"), f"청산 기록 {n_exit}건이 있는데 하나도 못 읽는다"
