"""4세대 G4a(I3 × TSMOM 현금 자리) — 결합 규칙이 적힌 대로인지(합성 데이터)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_gen4 as G  # noqa: E402


def _days(n):
    return [f"{2010 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def test_g4a_puts_i3_leftover_into_tsmom_basket_only():
    """I3 가 이탈(w=0)이면 KODEX200 은 0, 남는 돈은 TSMOM 4자산(12개월 수익 > 0 인 것만 1/4) — KODEX200 을 다시 사지 않는다."""
    n = 300
    days = _days(n)
    up = {d: {"open": 100 + i, "close": 100 + i} for i, d in enumerate(days)}
    dn = {d: {"open": 500 - i, "close": 500 - i} for i, d in enumerate(days)}
    kodex = {d: {"open": 200 - i * 0.5 if i > 250 else 200, "close": 200 - i * 0.5 if i > 250 else 200}
             for i, d in enumerate(days)}                                    # 끝에 급락 → I3 이탈
    ks = {d: {"open": 1000.0, "close": 1000.0} for d in days}
    px = {"133690": up, "148070": up, "132030": dn, "138230": dn}
    t = G.g4a_target(kodex, ks, px, set(days))
    last = None
    for i, d in enumerate(days):
        r = t(i, d, 1_000_000.0)
        if r is not None:
            last = r
    assert last.get(G.BASE, 0.0) == 0.0
    assert last["133690"] == pytest.approx(0.25) and last["148070"] == pytest.approx(0.25)
    assert "132030" not in last and last[G.CASH] == pytest.approx(0.5)
    assert sum(last.values()) == pytest.approx(1.0)
