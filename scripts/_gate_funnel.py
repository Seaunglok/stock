"""일회성 진단: largecap 게이트 퍼널 — 어느 게이트가 후보를 떨구는지 카운트."""
import sys, json
from collections import Counter
sys.path.insert(0, ".")
from trend.config import CFG, UNIVERSE_MODE  # noqa: E402
from trend.market_data import get_kospi_closes, get_ohlcv, get_universe  # noqa: E402
from src.mcp_servers.trend_mcp.signals import entry_signal  # noqa: E402

kospi = get_kospi_closes()
uni = get_universe()
held = set()
try:
    held = {p["symbol"] for p in json.load(open("data/trend_follow/state.json")).get("positions", [])}
except Exception:
    pass

gp = Counter(); total = 0; allp = 0; near = []
for code, name in uni:
    if code in held:
        continue
    ohlcv = get_ohlcv(code)
    if not ohlcv:
        continue
    sig = entry_signal(ohlcv, kospi, CFG, None, None)
    if not sig.gates:
        continue
    total += 1
    for k, v in sig.gates.items():
        if v:
            gp[k] += 1
    fails = [k for k, v in sig.gates.items() if not v]
    if not fails:
        allp += 1
    elif len(fails) == 1:
        near.append((code, name[:10], fails[0], round(sig.score, 1)))

print(f"모드={CFG.mode}  평가={total}종목(보유 {len(held)} 제외)")
print("게이트별 통과율:")
for k in ["price>MA60", "price>MA120", "RS>0", "pullback", "vol_up"]:
    if total and k in gp:
        print(f"  {k:12} {gp[k]:3}/{total}  ({100*gp[k]//total}%)")
print(f"전부 통과(후보)={allp}   1개만 부족(near-miss)={len(near)}")
print("near-miss 상위(부족 게이트):")
for c in sorted(near, key=lambda x: -x[3])[:12]:
    print("   ", c)
