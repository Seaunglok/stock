"""기존 task_id를 폴링해 결과 가져오기 (긴 타임아웃)"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2


async def main():
    task_id = sys.argv[1]
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    max_wait = int(sys.argv[3]) if len(sys.argv) > 3 else 600

    async with A2AClientManagerV2(base_url=base_url) as cm:
        elapsed = 0
        while elapsed < max_wait:
            task = await cm.engine._get_task_direct(task_id)
            if task is None:
                print(f"[{elapsed}s] task not found")
                break
            state = str(getattr(task.status, "state", "unknown"))
            print(f"[{elapsed}s] {state}")
            if "completed" in state.lower() or "failed" in state.lower():
                msg = task.status.message
                if msg and msg.parts:
                    text = msg.parts[0].root.text
                    print("=" * 70)
                    print(text)
                    print("=" * 70)
                # also dump artifacts
                for art in (task.artifacts or []):
                    for p in art.parts:
                        if hasattr(p.root, "text"):
                            print("[artifact]", p.root.text[:5000])
                break
            await asyncio.sleep(10)
            elapsed += 10


if __name__ == "__main__":
    asyncio.run(main())
