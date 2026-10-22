"""5세대(방어 현금 자리) — 슬리브에 주식이 없고, 결합이 4세대 G4a 와 같은 규칙인지."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lab_gen4 as G4  # noqa: E402
import lab_gen5 as G5  # noqa: E402


def test_defensive_sleeve_has_no_equity():
    assert set(G5.DEF3) == {"148070", "132030", "138230"} and not (set(G5.DEF3) & {"069500", "133690"})


def test_static_defensive_is_equal_weight_at_month_ends():
    t = G5.static_defensive({"m"})
    assert t(0, "x") == {a: pytest.approx(1 / 3) for a in G5.DEF3}
    assert t(5, "x") is None and t(5, "m") == {a: pytest.approx(1 / 3) for a in G5.DEF3}


def test_combine_matches_gen4_rule_on_synthetic_data():
    """같은 슬리브(TSMOM 4자산)를 넣으면 combine == lab_gen4.g4a_target — 결합 규칙을 다시 구현하지 않았는지."""
    import lab_classics as C
    days = [f"{2010 + i // 336}-{1 + (i % 336) // 28:02d}-{1 + i % 28:02d}" for i in range(300)]
    up = {d: {"open": 100 + i, "close": 100 + i} for i, d in enumerate(days)}
    dn = {d: {"open": 500 - i, "close": 500 - i} for i, d in enumerate(days)}
    kodex = {d: {"open": 200.0 if i <= 250 else 74.0, "close": 200.0 if i <= 250 else 74.0} for i, d in enumerate(days)}
    ks = {d: {"open": 1000.0, "close": 1000.0} for d in days}
    px = {"133690": up, "148070": up, "132030": dn, "138230": dn}
    a = G4.g4a_target(kodex, ks, px, set(days))
    b = G5.combine(kodex, ks, C.tsmom(px, set(days)))
    for i, d in enumerate(days):
        assert a(i, d, 1_000_000.0) == b(i, d, 1_000_000.0)
