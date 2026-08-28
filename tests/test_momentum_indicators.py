"""문헌 기반 모멘텀 지표 회귀 — 2026-08-21 추가.

전부 **아직 라이브 선정에 연결돼 있지 않다**. backtest_trend.py A/B 로 검증한 뒤에만 채택한다.
여기서 잠그는 건 "지표가 논문이 말하는 방향으로 움직이는가"다.
"""
from __future__ import annotations

import math
import random

import pytest

from src.mcp_servers.trend_mcp.signals import (
    information_discreteness,
    pct_of_52w_high,
    relative_strength,
    residual_momentum,
    trend_quality,
)


def _path(n=90, tot=0.20, noise=0.005, gap_at=None, gap=0.0, seed=0):
    """총수익률을 **정확히 tot 로 고정**한 가격 경로. 경로 모양만 비교하기 위한 통제.

    로그수익률 = 균등드리프트 + 노이즈이고, 노이즈 합을 0 으로 맞춰 끝값을 불변으로 만든다.
    ※ 계열 전체에 상수를 곱하는 방식은 안 된다 — 끝/시작 **비율**이 안 변해 총수익이 그대로다.
    """
    random.seed(seed)
    eps = [random.gauss(0, noise) for _ in range(n - 1)]
    if gap_at is not None:
        eps[gap_at] += gap
    mu = sum(eps) / len(eps)
    eps = [e - mu for e in eps]
    d = math.log(1 + tot) / (n - 1)
    p = [100.0]
    for e in eps:
        p.append(p[-1] * math.exp(d + e))
    return p


def _median_tq(**kw):
    vals = sorted(v for s in range(120) if (v := trend_quality(_path(seed=s, **kw))) is not None)
    return vals[len(vals) // 2]


def _bars(closes):
    return [{"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
             "volume": 1000, "value": c * 1000} for c in closes]


# ─── relative_strength(skip=) — Jegadeesh-Titman 12-1 ────────────────────────
def test_rs_skip_excludes_recent_window():
    """최근 skip 일을 빼고 측정한다. 마지막 구간만 급락시키면 skip 이 그걸 무시해야 한다."""
    stock = [100 + i for i in range(300)]          # 꾸준한 상승
    stock[-10:] = [200.0] * 10                     # 최근 10일 급락(399→200)
    kospi = [100.0] * 300
    assert relative_strength(stock, kospi, 60, skip=0) < 0, "스킵 없으면 급락에 오염"
    assert relative_strength(stock, kospi, 60, skip=21) > 0, "스킵하면 그 이전 추세를 본다"


def test_rs_skip_zero_is_legacy_behaviour():
    stock = [100 + i for i in range(200)]
    kospi = [100.0] * 200
    assert relative_strength(stock, kospi, 60) == relative_strength(stock, kospi, 60, skip=0)


def test_rs_insufficient_data_returns_zero():
    assert relative_strength([100.0] * 50, [100.0] * 50, 60, skip=21) == 0.0


# ─── pct_of_52w_high — George-Hwang 2004 ─────────────────────────────────────
def test_52w_high_at_new_high():
    v = pct_of_52w_high(_bars([100 + i for i in range(260)]))
    assert v is not None and v > 0.98


def test_52w_high_after_drawdown():
    closes = [100 + i for i in range(250)] + [250.0] * 10   # 349 고점 → 250
    v = pct_of_52w_high(_bars(closes))
    assert v is not None and 0.70 < v < 0.75


def test_52w_high_capped_at_one():
    """당일 고가가 최고가일 때 1.0 을 넘지 않는다."""
    v = pct_of_52w_high(_bars([100.0] * 100))
    assert v is not None and v <= 1.0


def test_52w_high_needs_minimum_history():
    assert pct_of_52w_high(_bars([100.0] * 30)) is None


# ─── information_discreteness — Da-Gurun-Warachka 2014 (FIP) ─────────────────
def test_fip_continuous_is_negative():
    """매일 조금씩 오른 종목 = 연속적 정보 = ID 음수(선호)."""
    closes = [100 * (1.3 ** (i / 299)) for i in range(300)]
    assert information_discreteness(closes) == pytest.approx(-1.0, abs=0.05)


def test_fip_discrete_is_higher_than_continuous():
    """★ 같은 총상승을 며칠 급등으로만 만든 종목은 ID 가 더 높다(=이산적, 비선호).

    논문: 연속적 +5.94% vs 이산적 −2.07% (형성기간 누적수익률 동일 조건).
    """
    smooth = [100 * (1.3 ** (i / 299)) for i in range(300)]
    jump = [100.0] * 250 + [130.0] * 50
    assert information_discreteness(jump) > information_discreteness(smooth)


def test_fip_sign_flips_for_decliners():
    """하락 종목은 부호가 뒤집힌다 — sign(PRET) 가 곱해지므로."""
    down = [130 * (0.77 ** (i / 299)) for i in range(300)]
    assert information_discreteness(down) == pytest.approx(-1.0, abs=0.05)


def test_fip_needs_history():
    assert information_discreteness([100.0] * 100) is None


# ─── trend_quality — Clenow 2015 ─────────────────────────────────────────────
def test_trend_quality_prefers_smooth_at_equal_return():
    """창 내 총수익률을 동일하게 고정하면 매끄러운 경로가 갭 경로보다 높다.

    변별력은 완만하다(중앙 약 0.65 vs 0.61) — 단발 갭에도 R² 가 비교적 높게 나오기 때문.
    급등주 구분은 FIP 가 훨씬 날카롭다(-1.0 vs -0.004). 두 지표는 상호보완.
    ※ 총수익률을 통제하지 않으면 연율화가 지배해 결과가 뒤집힌다.
    """
    assert _median_tq(noise=0.005) > _median_tq(noise=0.005, gap_at=60, gap=0.20)


def test_trend_quality_negative_for_downtrend():
    closes = [130 * (0.8 ** (i / 89)) for i in range(90)]
    v = trend_quality(closes)
    assert v is not None and v < 0


def test_trend_quality_near_zero_for_flat():
    v = trend_quality([100.0] * 90)
    assert v is not None and abs(v) < 1e-6


def test_trend_quality_penalises_noise():
    """★ Clenow 의 핵심 — 같은 총수익이라도 변동이 크면(R²↓) 점수가 깎인다.

    측정: 노이즈 0.5% → 0.648, 1.5% → 0.477, 3% → 0.260 (총수익 전부 +20% 고정).
    """
    smooth, mid, rough = _median_tq(noise=0.005), _median_tq(noise=0.015), _median_tq(noise=0.03)
    assert smooth > mid > rough
    assert rough < smooth / 2, "노이즈 6배면 점수가 절반 미만이어야 한다"


def test_trend_quality_needs_window():
    assert trend_quality([100.0] * 50) is None


# ─── residual_momentum — Blitz-Huij-Martens 2011 ─────────────────────────────
def _market(n=300, seed=1):
    random.seed(seed)
    m = [100.0]
    for _ in range(n - 1):
        m.append(m[-1] * (1 + random.gauss(0.0005, 0.01)))
    return m


def _long_market(n=1000, seed=3):
    import random
    random.seed(seed)
    m = [1000.0]
    for _ in range(n):
        m.append(m[-1] * (1 + random.gauss(0.0004, 0.01)))
    return m


def _stock(mkt, beta, alpha_recent=0.0, recent=252, seed=5):
    """베타는 전 구간 일정, 알파는 **마지막 recent 일에만** 준다."""
    import random
    random.seed(seed)
    out = [1000.0]
    start = len(mkt) - recent
    for i in range(1, len(mkt)):
        mr = (mkt[i] - mkt[i - 1]) / mkt[i - 1]
        a = alpha_recent if i >= start else 0.0
        out.append(out[-1] * (1 + beta * mr + a + random.gauss(0, 0.003)))
    return out


def test_residual_momentum_discounts_pure_beta():
    """★ 시장 상승에 편승한 고베타 종목(α=0)은 최근 초과성과 종목보다 낮다.

    현행 RS(단순 수익률 차이)는 β=1 을 가정해 고베타 편승 경로를 못 막는다.
    ※ 알파를 **전 구간 상수**로 주면 OLS 절편이 흡수해 잔차가 0 이 된다 — 이 지표가
       재는 것은 '자기 장기평균 대비 최근 초과분'이다(2026-08-28).
    """
    mkt = _long_market()
    hi_beta = _stock(mkt, beta=2.0)
    recent_alpha = _stock(mkt, beta=1.0, alpha_recent=0.002)
    assert residual_momentum(recent_alpha, mkt) > residual_momentum(hi_beta, mkt)


def test_residual_momentum_needs_history():
    assert residual_momentum([100.0] * 100, [100.0] * 100) is None


def test_residual_momentum_handles_flat_market():
    """시장이 완전 무변동이면 베타 추정이 불가 → None(0 으로 위장하지 않는다)."""
    assert residual_momentum([100 + i for i in range(300)], [100.0] * 300) is None


# ─── 랭킹 (assign_rank_scores) — 2026-08-21 blend 채택 ────────────────────────
def _c(sym, score, tq, hi):
    return {"symbol": sym, "score": score, "tq": tq, "hi": hi}


def test_blend_uses_rank_sum_not_raw_values():
    """★ tq 와 hi 는 스케일이 전혀 다르다(tq=연율화 배수 수준, hi=0~1 비율).

    값을 그대로 더하면 tq 가 지배해 hi 가 사실상 무시된다.
    A 는 tq 가 압도적(9.00)이라 **값 합산이면 1등**이지만, 순위합에서는 hi 꼴찌라 밀린다.
      순위(tq 내림차순): A=0, C=1, B=2      순위(hi 내림차순): C=0, B=1, A=2
      순위합:            A=2,  B=3,  C=1  → C 가 1등
    """
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = [_c("A", 50, 9.00, 0.70), _c("B", 50, 0.50, 0.95), _c("C", 50, 0.60, 0.99)]
    raw_best = max(cands, key=lambda c: c["tq"] + c["hi"])["symbol"]
    assert raw_best == "A", "전제 확인 — 값 합산이면 A 가 1등"
    assign_rank_scores(cands, "blend")
    order = [c["symbol"] for c in sorted(cands, key=lambda x: -x["rank_score"])]
    assert order == ["C", "A", "B"], f"순위합 결과가 다르다: {order}"


def test_rank_score_is_0_100_scale():
    """가점(+5)이 기존과 같은 의미를 갖도록 0~100 스케일을 유지한다."""
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = [_c(str(i), 50, i * 0.1, i * 0.01) for i in range(6)]
    assign_rank_scores(cands, "blend")
    vals = [c["rank_score"] for c in cands]
    assert min(vals) == 0.0 and max(vals) == 100.0


def test_composite_mode_preserves_existing_score():
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = [_c("A", 71.5, 1.0, 0.9), _c("B", 33.0, 2.0, 0.8)]
    assign_rank_scores(cands, "composite")
    assert [c["rank_score"] for c in cands] == [71.5, 33.0]


def test_missing_indicator_ranks_last():
    """지표 결측을 0 으로 취급하면 '데이터 없음'이 '최악'과 섞인다 → 최하위로 보내되 탈락은 아님."""
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = [_c("A", 50, None, None), _c("B", 50, 0.1, 0.5), _c("C", 50, 0.2, 0.6)]
    assign_rank_scores(cands, "blend")
    assert min(cands, key=lambda c: c["rank_score"])["symbol"] == "A"


def test_single_candidate_gets_full_score():
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = [_c("A", 42.0, None, None)]
    assign_rank_scores(cands, "blend")
    assert cands[0]["rank_score"] == 42.0


def test_empty_list_is_safe():
    from src.mcp_servers.trend_mcp.signals import assign_rank_scores
    cands = []
    assign_rank_scores(cands, "blend")
    assert cands == []


# ─── 잔차 모멘텀 퇴화 회귀 (2026-08-28) ───────────────────────────────────────
def test_residual_momentum_is_not_identically_zero():
    """★ 절편 있는 OLS 는 **적합 표본 위에서 잔차 합이 정확히 0** 이다.

    구 구현은 회귀 표본과 누적 구간이 같아 `sum(resid)/sd` 가 항상 0 이었다 —
    게이트로 쓰면 전 종목 탈락(백테스트 진입 0건). 값이 0 근처에 붙어 있으면 실패.
    """
    mkt = _long_market(seed=7)
    stk = _stock(mkt, beta=1.5, alpha_recent=0.0015, seed=9)
    v = residual_momentum(stk, mkt)
    assert v is not None
    assert abs(v) > 1.0, f"잔차 모멘텀이 0 으로 퇴화했다({v}) — 누적 구간이 회귀 표본과 같다"
    assert v > 0, f"최근 초과수익 종목인데 잔차 모멘텀이 양수가 아니다({v})"


def test_residual_momentum_negative_for_persistent_underperformer():
    """반대 방향도 잡아야 한다 — 베타 대비 꾸준히 밀리는 종목은 음수."""
    mkt = _long_market(seed=11)
    stk = _stock(mkt, beta=1.0, alpha_recent=-0.0015, seed=13)
    v = residual_momentum(stk, mkt)
    assert v is not None and v < -1.0, f"최근 열위 종목인데 {v}"


def test_residual_momentum_needs_estimation_window():
    """추정구간(기본 3년)이 안 차면 None — 부족한 데이터로 베타를 잡지 않는다."""
    short = [100.0 + i for i in range(300)]
    assert residual_momentum(short, short) is None
