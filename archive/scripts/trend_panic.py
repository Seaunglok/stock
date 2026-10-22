"""추세추종 데몬 긴급정지 + (옵션) 전량청산 — 사고/연속손실/시스템장애 시 1명령.

사용:
  python scripts/trend_panic.py --kill        # 데몬 정지 + watchdog 비활성화만
  python scripts/trend_panic.py --flatten     # 보유분 전량 시장가 청산만 (데몬 살아있어도 호출 가능)
  python scripts/trend_panic.py --full        # 정지 → 청산 → state 백업 (기본 권장)
  python scripts/trend_panic.py --status      # 현재 trend 데몬/보유분/락 상태만 보고
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

WATCHDOG_TASKS = ["KiwoomTrendWatchdog", "TrendJournalNotion"]   # 자동복구/일지 차단


def _trend_pids() -> list[int]:
    pids: list[int] = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "trend_follow.py" in cmd and "--daemon" in cmd:
                pids.append(p.info["pid"])
        except Exception:
            pass
    return pids


def _kill_daemon() -> tuple[int, int]:
    """trend_follow 데몬 강제종료. (killed, remaining) 반환."""
    pids = _trend_pids()
    print(f"[KILL] trend_follow --daemon 대상: {len(pids)}개 → {pids}")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
            print(f"  taskkill /F /T /PID {pid}")
        except Exception as e:
            print(f"  PID {pid} 실패: {e}")
    time.sleep(3)
    remaining = _trend_pids()
    print(f"[KILL] 남은 daemon: {remaining}")
    # 단일락 해제(혹시 모를 잔존)
    lock = _ROOT / "data" / "trend_follow" / "daemon.lock"
    if lock.exists():
        try:
            lock.unlink()
            print(f"[KILL] {lock} 삭제 (재기동 가능 상태)")
        except Exception as e:
            print(f"[KILL] lock 삭제 실패: {e}")
    return len(pids) - len(remaining), len(remaining)


def _disable_watchdog() -> None:
    for task in WATCHDOG_TASKS:
        try:
            r = subprocess.run(["schtasks", "/Change", "/TN", task, "/Disable"],
                               capture_output=True, text=True, check=False)
            if r.returncode == 0:
                print(f"[WATCHDOG] {task} 비활성화")
            else:
                print(f"[WATCHDOG] {task} 비활성화 실패(없거나 권한): {r.stderr.strip()[:80]}")
        except Exception as e:
            print(f"[WATCHDOG] {task} 실패: {e}")


def _backup_state() -> None:
    state = _ROOT / "data" / "trend_follow" / "state.json"
    if not state.exists():
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = state.with_name(f"state.panic.{ts}.json")
    try:
        shutil.copy(state, backup)
        print(f"[BACKUP] state → {backup.name}")
    except Exception as e:
        print(f"[BACKUP] 실패: {e}")


async def _flatten_all() -> None:
    """trend 데몬이 추적하던 모든 보유분을 시장가 즉시 청산. broker_holdings 기준(state 신뢰X)."""
    from src.claude_agents.base.mcp_client import MCPManager
    from trend_config import ACCOUNT_NO, PORTFOLIO_URL, TRADING_URL
    from trend_kiwoom_io import _broker_holdings, _order_accepted, _place

    held = await _broker_holdings()
    if not held:
        print("[FLATTEN] 보유분 없음 — 청산 대상 0")
        return
    print(f"[FLATTEN] broker 보유 {len(held)}종 — 시장가 매도 시도:")
    for h in held:
        print(f"  - {h['symbol']} {h['name']} {h['qty']}주 평단{h['avg']:,.0f}")
    confirm = input("→ 위 전량 시장가 청산 진행? (yes 입력 시 실행): ").strip().lower()
    if confirm != "yes":
        print("[FLATTEN] 취소")
        return
    if not ACCOUNT_NO:
        print("[FLATTEN] KIWOOM_ACCOUNT_NO 없음 — 중단")
        return
    sold, failed = [], []
    async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
        if not mcp.tools:
            print("[FLATTEN] trading-domain 연결 실패")
            return
        for h in held:
            try:
                resp = await _place(mcp, "sell", h["symbol"], h["qty"])
                ok, why = _order_accepted(resp)
                if ok:
                    sold.append(h)
                    print(f"  ✓ {h['symbol']} {h['qty']}주 청산 접수")
                else:
                    failed.append((h, why))
                    print(f"  ✗ {h['symbol']} 거부: {why}")
            except Exception as e:
                failed.append((h, str(e)))
                print(f"  ✗ {h['symbol']} 예외: {e}")
    print(f"\n[FLATTEN] 접수 {len(sold)} / 실패 {len(failed)}")
    if failed:
        print("⚠️ 실패분은 키움HTS 에서 수동 매도 권장:")
        for h, why in failed:
            print(f"  - {h['symbol']} {h['name']} {h['qty']}주 ({why})")


def _status() -> None:
    pids = _trend_pids()
    lock = _ROOT / "data" / "trend_follow" / "daemon.lock"
    state_path = _ROOT / "data" / "trend_follow" / "state.json"
    print(f"[STATUS] trend_follow --daemon PID: {pids if pids else '(없음)'}")
    print(f"[STATUS] lock: {'존재' if lock.exists() else '없음'} ({lock})")
    positions: list = []
    if state_path.exists():
        try:
            st = json.loads(state_path.read_text(encoding="utf-8"))
            positions = st.get("positions", [])
        except Exception:
            pass
    print(f"[STATUS] state.positions: {len(positions)}종")
    for p in positions:
        print(f"  - {p.get('symbol')} {p.get('name')} {p.get('qty')}주 평단{p.get('entry_price', 0):,.0f}")
    for task in WATCHDOG_TASKS:
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", task, "/FO", "LIST"],
                               capture_output=True, text=True, check=False)
            if r.returncode == 0:
                state_line = next((l for l in r.stdout.splitlines() if "Status" in l or "상태" in l), "")
                print(f"[STATUS] {task}: {state_line.strip()}")
            else:
                print(f"[STATUS] {task}: (등록 없음 또는 조회 실패)")
        except Exception as e:
            print(f"[STATUS] {task}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="추세추종 긴급정지 + 전량청산")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--kill", action="store_true", help="데몬 정지 + watchdog 비활성화")
    g.add_argument("--flatten", action="store_true", help="보유분 전량 시장가 청산만")
    g.add_argument("--full", action="store_true", help="정지+청산+state 백업 (권장)")
    g.add_argument("--status", action="store_true", help="현재 상태 보고만")
    args = ap.parse_args()

    if args.status:
        _status(); return
    if args.kill:
        _disable_watchdog(); _kill_daemon(); return
    if args.flatten:
        asyncio.run(_flatten_all()); return
    if args.full:
        print("=== PANIC FULL: watchdog off → daemon kill → state backup → flatten ===")
        _disable_watchdog()
        _kill_daemon()
        _backup_state()
        asyncio.run(_flatten_all())
        print("=== PANIC FULL 완료 ===")


if __name__ == "__main__":
    main()
