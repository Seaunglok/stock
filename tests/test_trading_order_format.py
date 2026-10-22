"""trading-domain 주문 파라미터 형식 — 2026-10-22 I3 지정가 실검증에서 드러난 두 결함의 회귀.

1) MCP 가 int 가격을 float 로 바꿔 넘겨 ord_uv 가 "106950.0" 이 됐다 → 정수 원 문자열로.
2) 서버 주문구분 '01'(지정가)을 키움 trde_tp 로 그대로 보내 [2000](407022:매매구분을 확인하십시요) 거부
   → 키움 지정가(보통)는 '0'. 시장가 '03' 은 실주문 체결 이력이 있는 값이라 그대로.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.mcp_servers.kiwoom_mcp.domains.trading_domain import _trde_tp, _won  # noqa: E402


def test_price_is_integer_won_string():
    assert _won(106950.0) == "106950" and _won(106950) == "106950"
    assert _won(None) is None and _won(0) is None


def test_limit_order_maps_to_kiwoom_code_zero():
    assert _trde_tp("01") == "0"
    assert _trde_tp("03") == "03"
