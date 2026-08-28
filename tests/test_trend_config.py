"""설정 기본값 스냅샷 회귀 — 2026-08-17.

방어 대상: 검증(A/B)으로 **채택된 운용값이 .env 에만 있고 코드 기본값은 기각된 구값**이던 상태.
.env 가 유실되면 하드손절·일일손실서킷·breadth/레짐 게이트가 전부 꺼지고 ADOPT_MODE=all 로
HTS 수동매수분까지 청산되는 구성으로 조용히 돌아갔다. 더 나쁘게는 PRODUCTION_MODE 도 .env 에서
오므로 LIVE-GUARD 자체가 건너뛰어져, 주문은 실제로 나가면서 라벨만 MOCK 이 된다.

이 테스트는 **.env 없이 import 했을 때** 채택값이 나오는지를 잠근다.
전략 파라미터를 의도적으로 바꿀 땐 이 표도 같이 고칠 것 — 그게 요점이다(조용한 변경 방지).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))


# (속성명, 채택 기본값) — .env 없이 import 했을 때의 기대값
ADOPTED = [
    ("UNIVERSE_MODE",        "largecap"),
    ("SIZING_MODE",          "pct_equity"),  # = 하니스의 notional (동의어)
    ("RISK_PCT",             1.5),
    ("MAX_NOTIONAL_PCT",     25.0),
    ("POSITION_PCT",         5.0),    # 슬롯20 × 5% = 노출 100%(실계좌 385만 검증)
    ("MAX_POS",              20),     # 분산 — MDD 50.7%→35.1%
    ("HARD_STOP_PCT",        10.0),     # 0 이면 하드손절 없음
    ("DAILY_LOSS_LIMIT_PCT", 2.0),      # 0 이면 서킷 없음
    ("BREADTH_MIN_PCT",      0.4),      # 0 이면 breadth 게이트 없음
    ("REGIME_MA",            60),       # 0 이면 레짐 게이트 없음
    ("ADOPT_MODE",           "off"),    # all 이면 HTS 수동매수분 강제청산
    ("RANK_MODE",            "composite"),  # 2026-08-27: blend 철회(멜트업 구간 과적합)
    ("ENTRY_TIME",           "11:00"),
    ("ENTRY_CUTOFF",         "14:00"),  # ENTRY_TIME 보다 뒤여야 보류분이 의미를 가진다
    ("EXIT_MA",              120),
    ("MAX_HOLD_DAYS",        120),    # 워크포워드 채택 구성(ma,hold)
    ("USE_FOREIGN_EXIT",     False),  # 12년 검증 불가(ka10008 2026-05~) — 검증본에 없음
    ("FOREIGN_MIN_RATIO",    0.2),
    ("FOREIGN_TREND_MA",     20),   # 2026-08-25 A/B: MA60 은 룰을 무력화(변경 0건)
    ("EXITS",                ("ma", "hold")),  # 트레일·부분익절 제거(8폴드 중 0회 선택)
    ("PYRAMID_ADDS",         0),        # 피라미딩은 기본 off
    ("PYRAMID_BYPASS_GATE",  False),
]


@pytest.fixture(scope="module")
def cfg_no_env(tmp_path_factory):
    """'설정 파일 없음' 상태로 trend_config 재로딩.

    실제 .env 를 rename 하지 않는다 — pytest 가 중간에 죽으면 .env 가 사라진 채 남아,
    다음 기동이 전부 코드 기본값으로 도는 사고가 된다(이 테스트가 막으려는 바로 그것).
    대신 TREND_ENV_FILE 을 존재하지 않는 경로로 돌린다.
    """
    import os
    saved = {k: v for k, v in os.environ.items()
             if k.startswith(("TREND_", "KIWOOM_", "CLOSING_BET_"))}
    for k in saved:
        del os.environ[k]
    os.environ["TREND_ENV_FILE"] = str(tmp_path_factory.mktemp("noenv") / "absent.env")
    try:
        sys.modules.pop("trend_config", None)
        import trend_config
        yield importlib.reload(trend_config)
    finally:
        os.environ.pop("TREND_ENV_FILE", None)
        os.environ.update(saved)
        sys.modules.pop("trend_config", None)


@pytest.mark.parametrize("name,expected", ADOPTED, ids=[n for n, _ in ADOPTED])
def test_adopted_default(cfg_no_env, name, expected):
    """★ .env 가 없어도 검증된 전략값이 나와야 한다."""
    assert getattr(cfg_no_env, name) == expected


def test_env_missing_is_flagged(cfg_no_env):
    """.env 부재는 조용히 넘어가면 안 된다 — LIVE-GUARD 가 이 플래그를 읽는다."""
    assert cfg_no_env.ENV_LOADED is False


def test_pullback_default_is_adopted(cfg_no_env):
    """TrendConfig 안에 묻혀 있는 값 — A/B(2026-06-26)로 3 → 12 채택."""
    assert cfg_no_env.CFG.pullback_pct == 12.0


def test_pullback_lower_bound_is_adopted(cfg_no_env):
    """★ 0.0 = 'MA20 이상만'. None(하한 없음)과 반드시 구분돼야 한다 — 둘 다 falsy 라
    `if not x` 로 검사하면 채택값이 조용히 꺼진다(2026-08-25 A/B: +3.09→+3.62%)."""
    assert cfg_no_env.CFG.pullback_min_pct == 0.0
    assert cfg_no_env.CFG.pullback_min_pct is not None


def test_cutoff_after_entry_time(cfg_no_env):
    """컷오프가 진입시각보다 이르면 하락보류 후보가 즉시 스킵돼 무의미해진다."""
    entry = tuple(int(x) for x in cfg_no_env.ENTRY_TIME.split(":"))
    cut = tuple(int(x) for x in cfg_no_env.ENTRY_CUTOFF.split(":"))
    assert cut > entry


def test_schedule_uses_entry_time(cfg_no_env):
    phases = {p: (h, m) for h, m, p in cfg_no_env.SCHEDULE}
    assert phases["entry"] == (11, 0)
    assert phases["screen"] == (8, 50) and phases["exit"] == (15, 20)


def test_watchdog_universe_default_matches_config(cfg_no_env):
    """watchdog 은 .env 를 안 읽고 재기동 데몬에 env 를 주입한다 — 기본값이 갈리면
    수동 기동과 자동 기동이 서로 다른 유니버스로 돈다."""
    src = (_ROOT / "scripts" / "trend_watchdog.py").read_text(encoding="utf-8")
    assert f'os.environ.get("TREND_UNIVERSE", "{cfg_no_env.UNIVERSE_MODE}")' in src


def test_env_override_still_works(monkeypatch):
    """.env/환경변수는 여전히 기본값을 덮어쓸 수 있어야 한다(override 전용으로 격하됐을 뿐)."""
    monkeypatch.setenv("TREND_MAX_POS", "3")
    sys.modules.pop("trend_config", None)
    import trend_config
    assert importlib.reload(trend_config).MAX_POS == 3
    sys.modules.pop("trend_config", None)


# ─── .env 파서 (2026-08-25) ───────────────────────────────────────────────────
def test_env_parser_strips_inline_comments(tmp_path, monkeypatch):
    """★ .env.example 은 주석을 달아 배포한다 — 파서가 감당해야 한다.

    2026-08-25: `TREND_PULLBACK_MIN_PCT=0   # 설명` 을 넣자 값에 주석이 통째로 섞여
    float() 이 터졌다(데몬 기동 실패).
    """
    env = tmp_path / "t.env"
    env.write_text(
        "TREND_MAX_POS=7          # 슬롯 수\n"
        "TREND_RISK_PCT=1.5\t# 탭 앞에도\n"
        'TREND_WATCHLIST="005930,000660"   # 따옴표 값\n'
        "TREND_ADOPT_MODE=off\n", encoding="utf-8")
    import os
    saved = {k: v for k, v in os.environ.items() if k.startswith("TREND_")}
    for k in saved:
        del os.environ[k]
    os.environ["TREND_ENV_FILE"] = str(env)
    try:
        sys.modules.pop("trend_config", None)
        import trend_config
        m = importlib.reload(trend_config)
        assert m.MAX_POS == 7
        assert m.RISK_PCT == 1.5
        assert m.WATCHLIST == ["005930", "000660"]
        assert m.ADOPT_MODE == "off"
    finally:
        os.environ.pop("TREND_ENV_FILE", None)
        os.environ.update(saved)
        sys.modules.pop("trend_config", None)


def test_env_parser_keeps_hash_inside_quoted_value(tmp_path):
    """따옴표로 감싼 값 안의 # 는 살려야 한다(토큰 등)."""
    import os
    env = tmp_path / "t.env"
    env.write_text('TREND_WATCHLIST="a#b,c"\n', encoding="utf-8")
    saved = {k: v for k, v in os.environ.items() if k.startswith("TREND_")}
    for k in saved:
        del os.environ[k]
    os.environ["TREND_ENV_FILE"] = str(env)
    try:
        sys.modules.pop("trend_config", None)
        import trend_config
        assert importlib.reload(trend_config).WATCHLIST == ["a#b", "c"]
    finally:
        os.environ.pop("TREND_ENV_FILE", None)
        os.environ.update(saved)
        sys.modules.pop("trend_config", None)


# ─── 신규진입 정지 (2026-08-28) ────────────────────────────────────────────────
def test_entry_halt_defaults_closed(cfg_no_env):
    """★ .env 유실 시에도 **정지 상태**여야 한다.

    12년 시점별 표본에서 거래당 -0.57%·PF 0.84 — 검증된 엣지가 없다는 판단으로 정지했다.
    이 값이 설정 유실 시 열리는 쪽으로 떨어지면, 근거 없는 규칙이 실계좌에 다시 돈다.
    08-17 원칙과 같다: 안전장치는 실패 시 닫힌다.
    """
    assert cfg_no_env.ENTRY_HALT is True


def test_entry_halt_can_be_lifted_by_env(monkeypatch):
    """해제는 명시적으로만 — 검증된 규칙을 찾으면 .env 로 연다."""
    monkeypatch.setenv("TREND_ENTRY_HALT", "false")
    sys.modules.pop("trend_config", None)
    import trend_config
    assert importlib.reload(trend_config).ENTRY_HALT is False
    sys.modules.pop("trend_config", None)


# ─── 워크포워드 채택 구성 (2026-08-28) ────────────────────────────────────────
def test_exit_ladder_excludes_trail_and_partial(cfg_no_env):
    """★ 트레일·부분익절이 기본 구성에 들어오면 안 된다.

    워크포워드 8폴드에서 현행 4단 사다리는 **한 번도 선택되지 않았다**. 같은 진입에
    청산만 바꿨을 때 거래당 -0.57% → +7.40% 였고, 범인은 ATR 트레일이었다
    (휩소마다 손실 확정 + 왕복비용 0.43% 부과, 거래 613 → 170).
    """
    assert "trail" not in cfg_no_env.EXITS
    assert "partial" not in cfg_no_env.EXITS
    assert set(cfg_no_env.EXITS) == {"ma", "hold"}


def test_hard_stop_is_not_a_strategy_switch(cfg_no_env):
    """하드손절은 EXITS 스위치에 없다 — 전략 선택지가 아니라 위험 바닥이다.

    백테스트는 항상 모델가 체결을 가정하지만 실거래엔 하한가·거래정지가 있다.
    MA120 이 살아있으면 거의 발동하지 않으므로(비용 0의 보험) 끌 이유가 없다.
    """
    assert "hard" not in cfg_no_env.EXITS
    assert cfg_no_env.HARD_STOP_PCT == 10.0


def test_total_exposure_is_the_validated_level(cfg_no_env):
    """★ 총 노출 = 슬롯 × 종목당 %. **실계좌 예탁(385만원)** 기준 워크포워드 채택값.

    1억 가정으로 검증한 50%(슬롯20×2.5%)는 실계좌에서 종목당 96,321원이 되어 유니버스의
    29%만 매수 가능했다 — 검증한 유니버스와 실제 매매 유니버스가 갈린다. 예탁금을 주입해
    재검증한 결과가 슬롯20×5%(노출 100%, MAR 0.96·MDD 18.4%)다.
    """
    assert cfg_no_env.SIZING_MODE in ("pct_equity", "notional")
    assert cfg_no_env.MAX_POS * cfg_no_env.POSITION_PCT == pytest.approx(100.0)
