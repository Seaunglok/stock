"""키움 ka10099로 KOSPI+KOSDAQ 종목 리스트를 받아 사이즈별로 필터.

캐시: docs_cache/universe_kiwoom_<YYYYMMDD>.json — 같은 날 재호출 시 디스크에서 로드.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "docs_cache"
SIZE_RANK = {"대형주": 0, "중형주": 1, "소형주": 2, "": 3}


def _cache_path(date_str: str) -> Path:
    return CACHE_DIR / f"universe_kiwoom_{date_str}.json"


async def _fetch_from_kiwoom() -> list[dict]:
    """키움 ka10099로 KOSPI+KOSDAQ 전체 리스트 fetch."""
    from src.mcp_servers.kiwoom_mcp.common.client.kiwoom_restapi_client import (
        KiwoomRESTAPIClient,
    )
    from src.mcp_servers.kiwoom_mcp.common.constants import KiwoomAPIID

    client = KiwoomRESTAPIClient()
    out: list[dict] = []
    for mrkt_tp in ("0", "10"):
        resp = await client.call_api(
            api_id=KiwoomAPIID.STOCK_LIST, params={"mrkt_tp": mrkt_tp}
        )
        for s in resp.get("list", []):
            try:
                last_price = int(s.get("lastPrice", "0") or 0)
                list_count = int(s.get("listCount", "0") or 0)
            except ValueError:
                last_price, list_count = 0, 0
            out.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "market": s.get("marketName", ""),
                "size": s.get("upSizeName", ""),
                "sector": s.get("upName", ""),
                "kind": s.get("kind", ""),
                "last_price": last_price,
                "list_count": list_count,
                "market_cap": last_price * list_count,
                "state": s.get("state", ""),
                "warn": s.get("orderWarning", "0"),
            })
    return out


def _latest_cache() -> Path | None:
    if not CACHE_DIR.exists():
        return None
    files = sorted(CACHE_DIR.glob("universe_kiwoom_*.json"))
    return files[-1] if files else None


def load_universe(refresh: bool = False) -> list[dict]:
    """오늘자 universe를 디스크 캐시에서 로드.

    1. refresh=False & 오늘 캐시 있음 → 그대로 사용
    2. refresh=False & 오늘 캐시 없음 → 키움 호출 시도, 실패하면 최신 캐시로 폴백
    3. refresh=True → 키움 강제 재호출 (실패해도 폴백 안 함)
    """
    today = datetime.now().strftime("%Y%m%d")
    path = _cache_path(today)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    from dotenv import load_dotenv
    load_dotenv()

    try:
        data = asyncio.run(_fetch_from_kiwoom())
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    except Exception as e:
        if refresh:
            raise
        latest = _latest_cache()
        if latest is None:
            raise
        print(f"[universe] 키움 호출 실패 ({e}); 폴백 → {latest.name}")
        return json.loads(latest.read_text(encoding="utf-8"))


def select(
    universe: list[dict],
    sizes: Iterable[str] = ("대형주",),
    exclude_warnings: bool = True,
    exclude_etf_etn: bool = True,
    top_by_marketcap: int | None = None,
) -> list[dict]:
    """필터링 + 시총 정렬."""
    sizes_set = set(sizes)
    out = []
    for s in universe:
        if sizes_set and s["size"] not in sizes_set:
            continue
        if exclude_warnings and s.get("warn", "0") not in ("0", ""):
            continue
        if exclude_etf_etn and s.get("kind", "A") != "A":
            continue
        # 종목코드 6자리 보통주만
        code = s["code"]
        if not (len(code) == 6 and code.isdigit()):
            continue
        out.append(s)
    out.sort(key=lambda x: -x["market_cap"])
    if top_by_marketcap:
        out = out[:top_by_marketcap]
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    u = load_universe()
    print(f"전체: {len(u)}종목")
    by_size: dict[str, int] = {}
    for s in u:
        by_size[s["size"]] = by_size.get(s["size"], 0) + 1
    for k, v in sorted(by_size.items(), key=lambda x: SIZE_RANK.get(x[0], 9)):
        print(f"  {k or '(미분류)'}: {v}")

    large = select(u, sizes=("대형주",))
    print(f"\n대형주 필터: {len(large)}종목")
    print("시총 상위 10:")
    for s in large[:10]:
        cap = s["market_cap"] / 1e8
        print(f"  {s['code']} {s['name']:<14} {s['market']:<6} {cap:>15,.0f}억")
