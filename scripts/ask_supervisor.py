"""Supervisor에 일회성 질문 전송"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2


async def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "현재 한국에서 주목할 종목 알려줘"
    print(f"[질문] {question}\n")
    print("=" * 70)

    async with A2AClientManagerV2(base_url="http://localhost:8000") as client:
        resp = await client.text_client.send(question)

    text = resp.text if hasattr(resp, "text") else str(resp)
    print(text)
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
