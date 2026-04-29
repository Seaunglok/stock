"""closing_bet_mcp 순수 함수 테스트 (데이터 fetching 없음)"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
import random

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.mcp_servers.closing_bet_mcp.catalyst import score_catalyst, match_trends
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores
from src.mcp_servers.closing_bet_mcp.exit_rules import (
    evaluate_exit, evaluate_market_filter,
)


def synth_ohlcv(n=90, breakout=True):
    """가상 OHLCV — 큐레이션 없이 점수 검증용"""
    random.seed(42)
    rows = []
    price = 100.0
    base_vol = 1_000_000
    for i in range(n):
        # 60일 전 고점 형성 후 -10% 조정 후 회복
        if i == n - 60:
            price = 130.0
        if i == n - 40:
            price = 108.0
        change = random.uniform(-0.02, 0.025)
        price *= 1 + change
        o = price * (1 + random.uniform(-0.005, 0.005))
        c = price
        h = max(o, c) * (1 + random.uniform(0, 0.005))  # 위꼬리 짧음
        l = min(o, c) * (1 - random.uniform(0, 0.01))
        vol_mult = 5.0 if (breakout and i == n - 1) else 1.0
        rows.append({
            "open": o, "high": h, "low": l, "close": c,
            "volume": int(base_vol * vol_mult),
            "value": int(o * base_vol * vol_mult),
        })
    return rows


print("=== 1) match_trends ===")
trends, kws = match_trends([
    "삼성전자 HBM3E 양산 본격화",
    "엔비디아 신규 GPU 발주 확대",
])
print(f"trends={trends}, keywords={kws}")

print("\n=== 2) score_catalyst ===")
r = score_catalyst(
    news_titles=[
        "SK하이닉스 HBM 글로벌 점유율 1위 유지",
        "엔비디아향 AI 칩 공급 확대",
        "반도체 업황 회복 가시화",
    ],
    disclosure_titles=["주요사항보고서(자기주식취득결정)"],
)
print(r.to_dict())

print("\n=== 3) compute_technical_scores ===")
ohlcv = synth_ohlcv(n=90, breakout=True)
ts = compute_technical_scores(
    ohlcv=ohlcv,
    foreign_net_5d=15_000_000_000,
    institutional_net_5d=8_000_000_000,
)
for k, v in ts.to_dict().items():
    if k == "breakdown":
        continue
    print(f"  {k}: {v}")

print("\n=== 4) evaluate_market_filter ===")
print(evaluate_market_filter(kospi_today_pct=0.5, kospi_5d_pct=1.2))
print(evaluate_market_filter(kospi_today_pct=-2.1))
print(evaluate_market_filter(kospi_today_pct=-0.3, kospi_5d_pct=-3.5))

print("\n=== 5) evaluate_exit ===")
entry = 50000.0
cases = [
    ("시간외 -1%", entry * 0.99, entry * 0.985),
    ("정규장 -1.5%", entry * 0.985, None),
    ("시초가 +2%", entry * 1.02, None),
    ("정규장 +3.5%", entry * 1.035, None),
]
for label, cur, ah in cases:
    d = evaluate_exit(entry, cur, ah)
    print(f"  [{label}] {d.action} ({d.urgency}) — {d.reason}")

print("\n=== 6) 한국어 키 호환 테스트 ===")
ohlcv_kr = [
    {"시가": d["open"], "고가": d["high"], "저가": d["low"],
     "종가": d["close"], "거래량": d["volume"], "거래대금": d["value"]}
    for d in ohlcv
]
ts2 = compute_technical_scores(ohlcv=ohlcv_kr)
print(f"composite (한국어 키): {ts2.composite():.1f}")
print(f"composite (영어 키):   {ts.composite():.1f}")
print("→ 동일한지 검증:", abs(ts.composite() - ts2.composite()) < 0.01)
