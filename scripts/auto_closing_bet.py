"""
종가매매(종가배팅) 자동화 스크립트

사용법:
  python scripts/auto_closing_bet.py --phase selection   # 14:50 후보 선별
  python scripts/auto_closing_bet.py --phase buy         # 15:20 모의 매수
  python scripts/auto_closing_bet.py --phase sell        # 09:00 시초가 매도
  python scripts/auto_closing_bet.py --test              # 즉시 테스트 (선별+매수)
  python scripts/auto_closing_bet.py --daemon            # 스케줄러 데몬
  python scripts/auto_closing_bet.py --status            # 상태 확인

타임라인:
  14:50 KST  ─→ selection: 후보 선별 + AnalysisAgent 검증
  15:20 KST  ─→ buy:       종가 시장가 모의 매수
  다음날
  09:00 KST  ─→ sell:      시초가 청산 신호 확인 → 매도

상태 파일:  %TEMP%/closing_bet_state.json
로그:       %TEMP%/mcp_logs/auto_closing_bet.log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ─── 프로젝트 루트를 sys.path에 추가 ───────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.a2a_integration.a2a_lg_client_utils_v2 import A2AClientManagerV2  # noqa: E402

# ─── 설정 ──────────────────────────────────────────────────────────────────
SUPERVISOR_URL = os.getenv("SUPERVISOR_URL", "http://localhost:8000")
_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
STATE_FILE = _TEMP / "closing_bet_state.json"
LOG_DIR = _TEMP / "mcp_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 스케줄 (hour, minute, phase)  ─ KST 기준, 로컬 시스템이 KST임을 가정
SCHEDULE: list[tuple[int, int, str]] = [
    (14, 50, "selection"),
    (15, 20, "buy"),
    (9,   0, "sell"),   # 다음날
]

# ─── 로거 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "auto_closing_bet.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─── 상태 파일 ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(key: str, content: str) -> None:
    state = load_state()
    state[key] = {
        "timestamp": datetime.now().isoformat(),
        "content": content,
    }
    state["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("[STATE] %s 저장 → %s", key, STATE_FILE)


def get_state(key: str) -> str:
    return load_state().get(key, {}).get("content", "")


# ─── Supervisor 호출 ────────────────────────────────────────────────────────

async def ask_supervisor(query: str, timeout: int = 600) -> str:
    """Supervisor A2A 에이전트에 쿼리를 보내고 텍스트 응답을 반환합니다."""
    logger.info("[→ Supervisor] %s", query[:120].replace("\n", " "))
    print("=" * 70)

    try:
        async with A2AClientManagerV2(base_url=SUPERVISOR_URL) as client:
            resp = await asyncio.wait_for(
                client.text_client.send(query),
                timeout=timeout,
            )
        text = resp.text if hasattr(resp, "text") else str(resp)
    except asyncio.TimeoutError:
        text = f"[TIMEOUT] Supervisor 응답 대기 {timeout}초 초과"
        logger.error(text)
    except Exception as e:
        text = f"[ERROR] Supervisor 호출 실패: {e}"
        logger.error(text, exc_info=True)

    print(text)
    print("=" * 70)
    return text


# ─── 헬스체크 ──────────────────────────────────────────────────────────────

async def check_services() -> bool:
    """Supervisor 접근 가능 여부를 확인합니다."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{SUPERVISOR_URL}/.well-known/agent.json")
        if r.status_code < 500:
            logger.info("[HEALTH] Supervisor UP (%s)", SUPERVISOR_URL)
            return True
        logger.error("[HEALTH] Supervisor 응답 이상: HTTP %s", r.status_code)
        return False
    except Exception as e:
        logger.error("[HEALTH] Supervisor 접근 불가: %s", e)
        return False


# ─── 3단계 핵심 함수 ────────────────────────────────────────────────────────

async def phase_selection() -> str:
    """14:50 — 종가배팅 후보 선별 + AnalysisAgent 4차원 검증."""
    logger.info("=" * 60)
    logger.info("[PHASE 1] 종가배팅 후보 선별 시작  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)

    if not await check_services():
        msg = "[SKIP] Supervisor 서비스 미가동 — 선별 중단"
        logger.error(msg)
        return msg

    query = (
        "종가배팅 후보를 closing-bet-mcp로 선별해줘.\n"
        "실행 환경: MOCK_MODE=true (모의투자)\n\n"
        "워크플로우:\n"
        "1. DataCollector: KOSPI 등락률 조회 → check_market_filter\n"
        "2. DataCollector: 거래대금 상위 20종목 → 각 종목 OHLCV/뉴스/외인기관 수집\n"
        "3. DataCollector: score_stock_combined → rank_candidates (top 5, min_score=50)\n"
        "4. AnalysisAgent: PLAYBOOK A(레짐 판정) → D(전략 분기) → B(VCP 필터) → C(포지션 사이저)\n\n"
        "최종 출력 형식 (반드시 포함):\n"
        "- 종목코드, 종목명, composite 점수\n"
        "- PLAYBOOK C 권장 포지션 크기(%)\n"
        "- 손절가(%)\n"
        "- 익절 1차가(%)\n"
        "- 레짐(weak/neutral/strong)\n"
        "- 추천/보류/제외 판정 및 사유"
    )

    result = await ask_supervisor(query)
    save_state("selection", result)
    logger.info("[PHASE 1] 완료 — %d chars", len(result))
    return result


async def phase_buy(selection_result: str | None = None) -> str:
    """15:20 — 선별 결과 기반 종가 모의 매수."""
    logger.info("=" * 60)
    logger.info("[PHASE 2] 종가 모의 매수 시작  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)

    if not await check_services():
        msg = "[SKIP] Supervisor 서비스 미가동 — 매수 중단"
        logger.error(msg)
        return msg

    if selection_result is None:
        selection_result = get_state("selection")
        if not selection_result:
            msg = "[SKIP] 이전 선별 결과 없음 — selection 단계를 먼저 실행하세요"
            logger.error(msg)
            return msg

    query = (
        "다음 종가배팅 분석 결과를 바탕으로 MOCK_MODE(모의투자)로 종가 시장가 매수를 실행해줘.\n\n"
        f"=== 선별 결과 ===\n{selection_result}\n\n"
        "매수 조건:\n"
        "- MOCK_MODE=true (모의투자) — Human 승인 단계 자동 처리\n"
        "- 추천 판정 종목만 매수 (보류/제외 종목 제외)\n"
        "- 주문 타입: 시장가(order_type='03')\n"
        "- PLAYBOOK C 포지션 크기 적용 (composite 85+ → 8%, 70~85 → 5%, 70미만 → 2%)\n"
        "- 리스크 점수 초과 시에도 MOCK_MODE이므로 자동 승인 진행\n\n"
        "매수 후 반드시 포함할 정보:\n"
        "- 각 종목별: 주문번호(또는 모의 ID), 종목코드, 수량, 주문가격\n"
        "- 총 투자금액 합계\n"
        "- 손절가, 익절 1차가"
    )

    result = await ask_supervisor(query)
    save_state("buy", result)
    logger.info("[PHASE 2] 완료 — %d chars", len(result))
    return result


async def phase_sell(buy_result: str | None = None) -> str:
    """다음날 09:00 — 시초가 청산 신호 확인 → 모의 매도."""
    logger.info("=" * 60)
    logger.info("[PHASE 3] 시초가 청산 판단 시작  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)

    if not await check_services():
        msg = "[SKIP] Supervisor 서비스 미가동 — 매도 중단"
        logger.error(msg)
        return msg

    if buy_result is None:
        buy_result = get_state("buy")
        if not buy_result:
            msg = "[SKIP] 이전 매수 결과 없음 — buy 단계를 먼저 실행하세요"
            logger.error(msg)
            return msg

    query = (
        "다음 종가배팅 매수 결과를 바탕으로 시초가 청산을 MOCK_MODE로 실행해줘.\n\n"
        f"=== 매수 결과 ===\n{buy_result}\n\n"
        "청산 워크플로우:\n"
        "1. DataCollector: 각 보유 종목 현재가(시초가) 조회\n"
        "2. DataCollector: closing-bet-mcp의 check_exit_signal(entry_price, current_price) 호출\n"
        "3. TradingAgent: 신호에 따라 MOCK_MODE 매도 실행\n"
        "   - SELL_ALL or STOP_LOSS → 전량 시장가 매도\n"
        "   - PARTIAL_SELL → suggested_qty_pct 비율만큼 매도\n"
        "   - HOLD → 보유 유지 (사유 명시)\n\n"
        "매도 후 반드시 포함할 정보:\n"
        "- 각 종목별: 청산 신호, 매도 수량, 수익률(%)\n"
        "- 보유 유지 종목(HOLD) 목록 및 사유\n"
        "- 총 실현 손익 요약\n"
        "MOCK_MODE=true — Human 승인 자동 처리"
    )

    result = await ask_supervisor(query)
    save_state("sell", result)
    logger.info("[PHASE 3] 완료 — %d chars", len(result))
    return result


# ─── 테스트 모드 ────────────────────────────────────────────────────────────

def _is_error_result(text: str) -> bool:
    """에러 응답 여부를 판단합니다 (Supervisor 내부 오류 포함)."""
    prefixes = ("[SKIP]", "[ERROR]", "[TIMEOUT]", "오류가 발생했습니다")
    return any(text.startswith(p) for p in prefixes)


async def run_test() -> None:
    """즉시 실행 테스트: 선별 + 매수 순차 실행."""
    print("\n" + "=" * 60)
    print("[TEST MODE] 종가매매 자동화 즉시 테스트")
    print("주의: 장 시간 외 실행 — 시장 데이터가 전일 기준일 수 있습니다.")
    print("=" * 60 + "\n")

    sel = await phase_selection()

    if _is_error_result(sel):
        logger.error("선별 실패 — 매수 단계 중단")
        return

    logger.info("선별 완료. 3초 후 매수 단계 시작...")
    await asyncio.sleep(3)

    await phase_buy(sel)

    print("\n" + "=" * 60)
    print("[TEST] 선별 + 매수 완료")
    print(f"상태 파일: {STATE_FILE}")
    print("매도 테스트: python scripts/auto_closing_bet.py --phase sell")
    print("=" * 60)


# ─── 스케줄러 데몬 ─────────────────────────────────────────────────────────

def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # 0=월 ~ 4=금


def _next_run_time(hour: int, minute: int, base: datetime | None = None) -> datetime:
    """지정 시각의 다음 실행 시간을 계산합니다 (주말 스킵)."""
    now = base or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while not _is_weekday(target):
        target += timedelta(days=1)
    return target


async def scheduler_daemon() -> None:
    """14:50 선별 → 15:20 매수 → 다음날 09:00 매도를 매일 자동 반복합니다."""
    logger.info("=" * 60)
    logger.info("[DAEMON] 종가매매 스케줄러 시작")
    logger.info("  14:50 선별 / 15:20 매수 / 09:00(다음날) 매도")
    logger.info("  Ctrl+C 로 종료")
    logger.info("=" * 60)

    phase_funcs: dict[str, Any] = {
        "selection": phase_selection,
        "buy": phase_buy,
        "sell": phase_sell,
    }

    while True:
        now = datetime.now()

        if not _is_weekday(now):
            # 주말이면 월요일 09:00까지 대기
            monday = now
            while not _is_weekday(monday):
                monday = (monday + timedelta(days=1)).replace(
                    hour=9, minute=0, second=0, microsecond=0
                )
            wait = (monday - now).total_seconds()
            logger.info("[DAEMON] 주말 — 월요일 %s까지 대기 (%.0f분)", monday.strftime("%m/%d %H:%M"), wait / 60)
            await asyncio.sleep(min(wait, 1800))
            continue

        # 가장 가까운 다음 실행 시간 찾기
        candidates = [
            (_next_run_time(h, m), phase)
            for h, m, phase in SCHEDULE
        ]
        candidates.sort(key=lambda x: x[0])
        next_dt, next_phase = candidates[0]
        wait = (next_dt - now).total_seconds()

        logger.info(
            "[DAEMON] 다음: %s @ %s (%.0f분 후)",
            next_phase, next_dt.strftime("%m/%d %H:%M:%S"), wait / 60,
        )

        # 대기 (최대 1시간마다 wake)
        while wait > 0:
            sleep = min(wait, 1800)
            await asyncio.sleep(sleep)
            wait -= sleep
            if wait > 60:
                logger.info("[DAEMON] %s까지 %.0f분 남음", next_phase, wait / 60)

        if _is_weekday(datetime.now()):
            logger.info("[DAEMON] %s 실행", next_phase)
            try:
                await phase_funcs[next_phase]()
            except Exception as e:
                logger.error("[DAEMON] %s 오류: %s", next_phase, e, exc_info=True)
        else:
            logger.info("[DAEMON] %s 스킵 (거래일 아님)", next_phase)


# ─── 상태 출력 ─────────────────────────────────────────────────────────────

def print_status() -> None:
    state = load_state()
    if not state:
        print("상태 파일 없음 (아직 실행 전)")
        return

    print(f"\n=== 종가매매 상태 [최근 업데이트: {state.get('last_updated', '?')}] ===")
    for key in ("selection", "buy", "sell"):
        entry = state.get(key)
        if not entry:
            print(f"  [{key.upper():10}] -")
            continue
        ts = entry.get("timestamp", "?")
        preview = entry.get("content", "")[:80].replace("\n", " ")
        print(f"  [{key.upper():10}] {ts}  {preview}...")

    print(f"\n상태 파일: {STATE_FILE}")

    # 다음 실행 시간
    now = datetime.now()
    print("\n다음 예정 실행:")
    for h, m, phase in SCHEDULE:
        nt = _next_run_time(h, m)
        diff = nt - now
        hrs, rem = divmod(int(diff.total_seconds()), 3600)
        mins = rem // 60
        print(f"  {phase:10} → {nt.strftime('%m/%d %H:%M')} ({hrs}시간 {mins}분 후)")


# ─── 진입점 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="종가매매 자동화 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--phase",
        choices=["selection", "buy", "sell"],
        help="단발 실행할 단계",
    )
    group.add_argument("--test",   action="store_true", help="즉시 테스트 (선별+매수)")
    group.add_argument("--daemon", action="store_true", help="스케줄러 데몬 시작")
    group.add_argument("--status", action="store_true", help="상태 확인")

    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.test:
        asyncio.run(run_test())
    elif args.daemon:
        try:
            asyncio.run(scheduler_daemon())
        except KeyboardInterrupt:
            logger.info("[DAEMON] 종료")
    elif args.phase == "selection":
        asyncio.run(phase_selection())
    elif args.phase == "buy":
        asyncio.run(phase_buy())
    elif args.phase == "sell":
        asyncio.run(phase_sell())
