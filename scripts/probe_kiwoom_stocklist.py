"""ka10099 (종목정보 리스트) probe — Kiwoom REST API로 KOSPI/KOSDAQ 전체 코드 가져오기."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from src.mcp_servers.kiwoom_mcp.common.client.kiwoom_restapi_client import (
    KiwoomRESTAPIClient,
)
from src.mcp_servers.kiwoom_mcp.common.constants import KiwoomAPIID


async def main():
    client = KiwoomRESTAPIClient()
    print(f"mode = {client.mode if hasattr(client, 'mode') else 'n/a'}")
    for label, mrkt_tp in [("KOSPI", "0"), ("KOSDAQ", "10")]:
        print(f"\n=== {label} (mrkt_tp={mrkt_tp}) ===")
        try:
            resp = await client.call_api(
                api_id=KiwoomAPIID.STOCK_LIST,
                params={"mrkt_tp": mrkt_tp},
            )
            keys = list(resp.keys())[:10]
            print("response keys:", keys)
            # 전형적으로 key 'list' 또는 'output' 안에 종목 리스트
            for k in keys:
                v = resp[k]
                if isinstance(v, list):
                    print(f"  -> list field '{k}' len={len(v)}")
                    if v:
                        print(f"     sample[0] keys: {list(v[0].keys())[:8]}")
                        print(f"     sample[0]: {v[0]}")
                    break
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
