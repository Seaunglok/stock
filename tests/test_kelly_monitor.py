"""켈리 감시 기준 회귀 — 2026-09-09.

이 파일이 지키는 것은 계산의 정확성만이 아니라 **기준을 표본 보기 전에 정했다는 사실**이다.
상수를 바꾸면 여기서 깨지고, git 이력이 '언제 무엇을 근거로 바꿨는지'를 남긴다.
(워크포워드 MDD_RATIO 와 같은 패턴 — 2026-08-28.)
"""
from __future__ import annotations

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
