"""미정의 전역 이름 검사 — 2026-08-21.

계기: 스타 임포트를 명시 import 로 바꾼 뒤(08-17) 새 상수를 쓰면서 import 목록에 추가하지
않아 `MIN_VALUE_KRW` NameError 가 커밋됐다. phase_screen 을 실행하는 테스트가 없어서
전체 테스트가 통과했고, **다음 08:50 스크리닝에서야 터졌을** 상황이었다.

`import` 만으로는 못 잡는다 — 함수 본문의 이름은 호출될 때 평가되기 때문이다.
ruff(F821)가 있으면 그걸 쓰는 게 낫지만 현재 미설치라 ast 로 같은 검사를 한다.
"""
from __future__ import annotations

import ast
import builtins
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# 실거래·분석 경로. 여기 없는 파일은 검사되지 않는다는 뜻이니 새 모듈은 추가할 것.
TARGETS = [
    "scripts/trend_follow.py",
    "scripts/trend_runtime.py",
    "scripts/trend_journal.py",
    "scripts/trend_kiwoom_io.py",
    "scripts/trend_config.py",
    "scripts/trend_lock.py",
    "scripts/trend_watchdog.py",
    "scripts/trend_dashboard.py",
    "scripts/shadow_ledger.py",
    "scripts/collect_minute_bars.py",
    "scripts/backtest_trend.py",
    "scripts/backtest_trend_portfolio.py",
    "src/mcp_servers/trend_mcp/signals.py",
    "src/mcp_servers/trend_mcp/market_data.py",
]

# 인터프리터가 주입하는 모듈 전역 — ast 로는 정의를 볼 수 없다.
_IMPLICIT = {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__"}


def _bound_names(tree: ast.AST) -> set[str]:
    out = set(dir(builtins)) | _IMPLICIT
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Global):
            out.update(n.names)
        elif isinstance(n, ast.comprehension):
            for t in ast.walk(n.target):
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


@pytest.mark.parametrize("rel", TARGETS, ids=[p.split("/")[-1] for p in TARGETS])
def test_no_undefined_names(rel):
    """참조하는 이름이 전부 정의/import 돼 있어야 한다.

    보수적 검사다 — 스코프를 구분하지 않고 파일 전체의 바인딩을 합쳐서 본다.
    따라서 오탐은 없고(정의된 걸 미정의라 하지 않음), 놓치는 경우는 있다
    (다른 함수에서 정의된 지역명을 쓰는 경우). NameError 커밋 방지가 목적이다.
    """
    path = _ROOT / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    missing = sorted(used - _bound_names(tree))
    assert not missing, f"{rel}: 미정의 이름 {missing}"
