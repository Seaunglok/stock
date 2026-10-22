"""분봉 수집 — 응답 파싱과 '줄어드는 덮어쓰기 금지' 합치기."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import collect_i3_minutes as M  # noqa: E402


def test_parse_rows_groups_by_day_ascending():
    rows = [{"cntr_tm": "20261022090200", "cur_prc": "+101", "open_pric": "100", "high_pric": "102",
             "low_pric": "-99", "trde_qty": "5"},
            {"cntr_tm": "20261022090100", "cur_prc": "100", "open_pric": "", "high_pric": "", "low_pric": "", "trde_qty": "1"},
            {"cntr_tm": "20261021153000", "cur_prc": "98"}, {"cntr_tm": "bad"}]
    out = M.parse_rows(rows)
    assert list(out) == ["2026-10-22", "2026-10-21"] or set(out) == {"2026-10-22", "2026-10-21"}
    assert [b["t"] for b in out["2026-10-22"]] == ["0901", "0902"]
    assert out["2026-10-22"][1] == {"t": "0902", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 5.0}
    assert out["2026-10-22"][0]["o"] == 100.0                      # 빈 시가 → 종가로


def test_merge_never_shrinks(tmp_path):
    full = [{"t": f"09{m:02d}", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for m in range(10)]
    assert M.merge_save("X", "2026-10-21", full, tmp_path) == (0, 10)
    part = full[5:]                                                 # 다음 날 응답엔 앞부분이 잘려 있다
    assert M.merge_save("X", "2026-10-21", part, tmp_path) == (10, 10)
    saved = json.loads((tmp_path / "X" / "2026-10-21.json").read_text(encoding="utf-8"))
    assert len(saved) == 10 and saved[0]["t"] == "0900"
