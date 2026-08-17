"""추세추종 거래비용 — 라이브·백테스트 **단일 소스**.

2026-08-17 이전엔 같은 비용이 세 곳에 서로 다른 기본값으로 흩어져 있었다:
  trend_config.py      CLOSING_BET_TAX_BPS 기본 20.0  → 왕복 0.43%  (라이브 net 손익)
  backtest_trend.py    --tax-bps 기본 18.0            → 왕복 0.41%  (검증 기대값)
  backtest_walkforward 별도 구현

즉 매매일지의 net_pct 와 백테스트 기대값이 **애초에 비교 불가능한 수치**였다. 실전 성과를
"검증 기대값 대비 미달"로 판단해 온 근거 자체가 어긋나 있었다는 뜻이다.

또 하나: 추세추종이 `CLOSING_BET_*` 환경변수를 읽고 있어서, 종가매매 비용을 조정하면 추세추종
손익이 같이 움직였다. 트랙이 분리돼 있다는 전제와 어긋난다 → `TREND_*` 로 독립.

값 근거(2026 기준, 보수적):
  TAX      매도 시 거래세 0.20% (코스피·코스닥 동일). 정부 정책 가변이라 보수적으로 잡는다.
  FEE      키움 비대면 위탁수수료 0.015% 편도.
  SLIPPAGE 대형주 시장가 0.10% 편도 (실전 첫주 체결가 대조로 보정).

여긴 순수 상수만 둔다(.env 읽기 없음) — 데몬은 trend_config 가, 백테스트는 CLI 가 override 한다.
"""
from __future__ import annotations

TAX_BPS = 20.0        # 매도세 (편도, 매도에만 부과)
FEE_BPS = 1.5         # 위탁수수료 (편도)
SLIPPAGE_BPS = 10.0   # 슬리피지 (편도)


def roundtrip_pct(tax_bps: float = TAX_BPS, fee_bps: float = FEE_BPS,
                  slippage_bps: float = SLIPPAGE_BPS) -> float:
    """왕복 거래비용(%) = 매도세 + 2×수수료 + 2×슬리피지.

    매도세는 매도에만 붙으므로 1회, 수수료·슬리피지는 매수/매도 양쪽이라 2회.
    """
    return (tax_bps + 2 * fee_bps + 2 * slippage_bps) / 100.0
