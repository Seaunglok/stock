"""I3 도전자 리그(i3_shadow) — 챔피언 모델이 실전 판단과 같은지, 승격 규칙이 적힌 대로 판정하는지."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import i3_core as K  # noqa: E402
import i3_shadow as S  # noqa: E402

START, UPTO = "2024-09-02", "2026-08-24"     # 머니마켓(488770) 상장 뒤 — 실전 현금 자리 그대로


@pytest.fixture(scope="module")
def real():
    import strategy_lab as L
    cache = _ROOT / "docs_cache" / "lab"
    need = ("069500_2026-08-24.json", "IDX_KS11_2026-08-24.json", "488770_2026-10-21.json")
    if not all((cache / n).exists() for n in need):
        pytest.skip("검증 캐시 없음")
    k = L.load_bars("069500", "2014-01-01", "2026-08-24")
    ks = L.load_bars("^KS11", "1996-01-01", "2026-08-24")
    c = L.load_bars("488770", "2014-01-01", "2026-10-21")
    return k, ks, c, S.run_models(k, ks, c, START, 3_640_000.0, UPTO)


def test_champion_model_matches_live_decisions(real):
    """★ 챔피언 모델의 매매일·목표 비중 == 실전 판단 코드(i3_core) — 같은 자산 이력이면 같아야 한다.
    어긋나면 '모델 vs 실계좌'·'도전자 vs 챔피언' 비교가 전부 무의미해진다."""
    k, ks, _, res = real
    ch = res[S.CHAMPION]
    navs, prev, checked = [], None, 0
    for d, nav in ch["nav_hist"].items():
        if d >= UPTO:
            break
        navs.append(nav)
        eng = K.engine_state(k, ks, d)
        w, need, _ = K.decide(eng, navs, prev)
        assert need == (d in ch["trade_days"]), f"{d} 매매 여부 불일치"
        if need:
            assert w == pytest.approx(ch["w_hist"][d], abs=1e-6), f"{d} 비중 불일치"
            prev = w
        checked += 1
    assert checked > 400 and len(ch["trade_days"]) >= 10


def test_challenger_equals_champion_until_first_reentry(real):
    """R1 은 '손실 뒤 재진입'에서만 달라진다 — 그 전까지는 챔피언과 비중이 같아야 한다(다르면 구현 결함)."""
    k, ks, _, res = real
    flips = []
    prev_hold = None
    for d in sorted(res[S.CHAMPION]["w_hist"]):
        hold = K.engine_state(k, ks, d).holding
        if prev_hold is False and hold:
            flips.append(d)
        prev_hold = hold
    assert flips, "이 구간에 재진입이 없다 — 시험 구간을 바꿀 것"
    first = flips[0]
    for d, w in res[S.CHAMPION]["w_hist"].items():
        if d < first:
            assert res["R1"]["w_hist"][d] == pytest.approx(w)
    assert any(abs(res["R1"]["w_hist"][d] - res[S.CHAMPION]["w_hist"][d]) >= S.DIVERGE_PP
               for d in res[S.CHAMPION]["w_hist"] if d >= first)


def _curve(days, vals):
    return [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", v) for i, v in zip(range(days), vals)]


def _model(vals, ws):
    curve = _curve(len(vals), vals)
    return {"curve": curve, "w_hist": {d: w for (d, _), w in zip(curve, ws)}}


def test_promotion_rule_as_declared():
    """★ 일부러 깨뜨리기 — 조건 하나씩 빼면 승격되지 않는다."""
    n = S.PROMO_MIN_DAYS + 5
    champ = _model([100 + i * 0.01 for i in range(n)], [0.5] * n)
    good = _model([100 + i * 0.05 for i in range(n)], [1.0] * n)
    assert S.promotion(champ, good, "2026-01-01")["ok"]
    short = _model([100 + i * 0.05 for i in range(30)], [1.0] * 30)
    assert not S.promotion(champ, short, "2026-01-01")["ok"]                          # 기록 부족
    same = _model([100 + i * 0.05 for i in range(n)], [0.5] * n)
    assert not S.promotion(champ, same, "2026-01-01")["ok"]                           # 다르게 행동한 날 부족
    small = _model([100 + i * 0.0105 for i in range(n)], [1.0] * n)
    assert not S.promotion(champ, small, "2026-01-01")["ok"]                          # 수익 차 부족
    crash = _model([100 + i * 0.05 if i < n - 10 else 75 + i * 0.05 for i in range(n)], [1.0] * n)
    assert not S.promotion(champ, crash, "2026-01-01")["ok"]                          # MDD 초과


def test_history_is_one_row_per_day(tmp_path):
    p = tmp_path / "h.csv"
    S.append_history({"date": "2026-10-22", "i3_nav": 1}, p)
    S.append_history({"date": "2026-10-22", "i3_nav": 2}, p)
    S.append_history({"date": "2026-10-21", "i3_nav": 3}, p)
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert [r["date"] for r in rows] == ["2026-10-21", "2026-10-22"] and rows[1]["i3_nav"] == "2"


def test_decide_task_runs_league_after_decide_and_keeps_its_exit_code():
    """리그는 판단 뒤에 돌고, 작업 결과 코드는 판단의 것이어야 한다(리그 실패가 판단 실패로 보이면 안 된다)."""
    txt = (_ROOT / "scripts" / "i3_decide.cmd").read_text(encoding="utf-8")
    i_decide, i_rc, i_shadow = txt.index("--phase decide"), txt.index("set RC=%ERRORLEVEL%"), txt.index("i3_shadow.py")
    assert i_decide < i_rc < i_shadow and txt.rstrip().endswith("exit /b %RC%")
