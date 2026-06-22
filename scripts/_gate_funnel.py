"""일회성 진단: largecap 게이트 퍼널 — 어느 게이트가 후보를 떨구는지 카운트.

핵심 분석 로직은 src/mcp_servers/trend_mcp/signals.py 의 analyze_gate_funnel 순수 함수.
이 스크립트는 데이터 로드(get_universe·get_ohlcv·get_kospi_closes·state.json) + 호출 + print.
"""
import json
import sys

sys.path.insert(0, ".")
from trend_config import CFG, UNIVERSE_MODE  # noqa: E402
from src.mcp_servers.trend_mcp.market_data import get_kospi_closes, get_ohlcv  # noqa: E402
from src.mcp_servers.trend_mcp.signals import analyze_gate_funnel  # noqa: E402
from trend_kiwoom_io import get_universe  # noqa: E402  (데몬용 config 주입 wrapper)

kospi = get_kospi_closes()
uni = get_universe()
held = set()
try:
    held = {p["symbol"] for p in json.load(open("data/trend_follow/state.json")).get("positions", [])}
except Exception:
    pass

result = analyze_gate_funnel(uni, kospi, CFG, held=held, ohlcv_loader=get_ohlcv)

total = result["total"]
print(f"모드={CFG.mode}  평가={total}종목(보유 {len(held)} 제외)")
print("게이트별 통과율:")
for k in ["price>MA60", "price>MA120", "RS>0", "pullback", "vol_up"]:
    if total and k in result["pass_counts"]:
        cnt = result["pass_counts"][k]
        print(f"  {k:12} {cnt:3}/{total}  ({100*cnt//total}%)")
print(f"전부 통과(후보)={result['all_pass']}   1개만 부족(near-miss)={len(result['near_miss'])}")
print("near-miss 상위(부족 게이트):")
for c in sorted(result["near_miss"], key=lambda x: -x[3])[:12]:
    print("   ", c)
