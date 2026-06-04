"""
종가매매 자동화 (직접 실행 버전) — Claude Agent / Anthropic API 불필요

pykrx로 OHLCV·종목 목록을 수집하고, closing_bet_mcp Python 함수를
직접 임포트하여 채점합니다. 주문 실행만 trading-domain MCP(:8030)를 사용합니다.

사용법:
  python scripts/direct_closing_bet.py --test              # 즉시 테스트 (선별만, 주문 없음)
  python scripts/direct_closing_bet.py --daemon            # 스케줄러 데몬
  python scripts/direct_closing_bet.py --status            # 상태 확인
  python scripts/direct_closing_bet.py --phase selection   # 14:50 후보 선별
  python scripts/direct_closing_bet.py --phase buy         # 15:20 모의 매수
  python scripts/direct_closing_bet.py --phase sell        # 09:00 시초가 매도

필수 서비스:
  trading-domain  :8030  — 주문 실행 (MOCK_MODE 지원)

선택 서비스 (없어도 동작, 있으면 채점 정밀도 향상):
  naver-news-mcp  :8050  — 카탈리스트 점수용 뉴스
  investor-domain :8033  — 외인·기관 순매수 데이터

환경 변수 (.env):
  KIWOOM_ACCOUNT_NO      — 계좌번호 (필수)
  INVESTMENT_PER_TRADE   — 1종목 기준 투자금 (기본: 500000원)
  MOCK_MODE              — true/false (기본: true)
  TELEGRAM_BOT_TOKEN     — 텔레그램 봇 토큰 (선택)
  TELEGRAM_CHAT_ID       — 텔레그램 채팅 ID (선택)
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

# ─── 프로젝트 루트 ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# pykrx의 logging.info(args, kwargs) 잘못된 포맷 호출로 인한 "--- Logging error ---" 억제
logging.Handler.handleError = lambda self, record: None  # noqa: E731

# pykrx / FinanceDataReader 내부 INFO 노이즈 억제
for _noisy in ("pykrx", "pykrx.website", "pykrx.stock", "FinanceDataReader",
               "FinanceDataReader.krx", "requests", "urllib3", "httpx"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)
# pykrx가 root logger에 출력하는 노이즈 차단 — 우리 로거만 WARNING+ 허용
logging.getLogger().setLevel(logging.WARNING)


def _load_env() -> None:
    """python-dotenv 없이 .env 파일 로드."""
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

# pykrx — import 시 "KRX 로그인 실패" stdout 메시지 억제
import contextlib as _ctx, io as _io  # noqa: E402
with _ctx.redirect_stdout(_io.StringIO()):
    from pykrx import stock as krx  # noqa: E402
del _ctx, _io

# closing_bet_mcp 스코어링 함수 직접 임포트 (MCP 서버 불필요)
from src.mcp_servers.closing_bet_mcp.catalyst import score_catalyst  # noqa: E402
from src.mcp_servers.closing_bet_mcp.exit_rules import (  # noqa: E402
    classify_regime,
    evaluate_exit,
    evaluate_hold_exit,
    evaluate_market_filter,
    init_stop_price,
    ratchet_stop,
)
from src.mcp_servers.closing_bet_mcp.scorer import compute_technical_scores  # noqa: E402

# MCPManager — trading-domain 주문 실행 전용
from src.claude_agents.base.mcp_client import MCPManager  # noqa: E402

# ─── 설정 ──────────────────────────────────────────────────────────────────
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "")
INVESTMENT_PER_TRADE = float(os.getenv("INVESTMENT_PER_TRADE", "500000"))
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"

TRADING_URL = "http://localhost:8030/mcp/"
MARKET_URL  = "http://localhost:8031/mcp/"
NEWS_URL = "http://localhost:8050/mcp"
INVESTOR_URL = "http://localhost:8033/mcp/"
PORTFOLIO_URL = "http://localhost:8034/mcp/"   # 실계좌 보유분 조회 (reconciliation)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_TEMP = Path(os.environ.get("TEMP", "C:/Windows/Temp"))

# 로그: 프로젝트 내 logs/closing_bet/ 폴더에 일자별로 회전 (자정에 자동 회전)
LOG_DIR = _ROOT / "logs" / "closing_bet"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "closing_bet.log"  # 활성 로그 (자정에 closing_bet.log.YYYY-MM-DD로 회전)

DATA_DIR = _ROOT / "data" / "closing_bet"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# #2: 상태 파일을 프로젝트 영속 경로로 (구버전 %TEMP% 는 OS 정리/재부팅 시 유실 → 다일 보유 중 고아 포지션 위험).
STATE_FILE = DATA_DIR / "state.json"
_OLD_STATE_FILE = _TEMP / "closing_bet_state_direct.json"
if not STATE_FILE.exists() and _OLD_STATE_FILE.exists():
    try:
        STATE_FILE.write_text(_OLD_STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass

TOP_N_STOCKS = 50       # 거래대금 상위 N종목 분석 (확장: 전고점 셋업 발굴 확률 향상)
# "최고 확률 높은 종목만 1~5개" — composite >= 60 인 셋업만 후보로 인정.
# 임계치 미달이면 0개도 가능 (강제로 5개 채우지 않음).
MIN_SCORE = float(os.getenv("CLOSING_BET_MIN_SCORE", "55.0"))
TOP_CANDIDATES = int(os.getenv("CLOSING_BET_TOP_CANDIDATES", "3"))  # 상한 (백테스트 결과 3개가 5개보다 우수)
# 거래대금 절대 임계 (외부 베스트 프랙티스 — 1,000억원 이상)
MIN_VALUE_KRW = float(os.getenv("CLOSING_BET_MIN_VALUE_KRW", "100000000000"))  # 1,000억원
# 손절 % (외부 권장 -1~-2%, 기본 -2.0)
STOP_LOSS_PCT = float(os.getenv("CLOSING_BET_STOP_LOSS_PCT", "-2.0"))
# P0: catalyst 가중 — 검증 백테스트(compute_technical_scores)엔 catalyst가 없었다.
#     기본 0.0(= technical-only, 백테스트 채점식과 동일). 실거래 검증 후 0.3 등으로 상향 가능.
CATALYST_WEIGHT = float(os.getenv("CLOSING_BET_CATALYST_WEIGHT", "0.0"))
# P0: 점수 차등(확신) 사이징 — 백테스트에서 70+ 구간이 오히려 부진(50%/-0.13%, n=10)해
#     기본 off(전 구간 1.0x). CLOSING_BET_CONVICTION_SIZING=true 일 때만 ≥70 1.5x / ≥85 2.0x.
CONVICTION_SIZING = os.getenv("CLOSING_BET_CONVICTION_SIZING", "false").lower() == "true"
# P2: 거래비용(편도 bps, 1bp=0.01%) — 청산 손익을 net 으로 보고하기 위한 차감.
#     왕복 ≈ 매도세 + 수수료×2 + 슬리피지×2. 백테스트(backtest_walkforward.py)와 동일 가정.
TAX_BPS       = float(os.getenv("CLOSING_BET_TAX_BPS", "18.0"))       # 매도세 (매도 1회)
FEE_BPS       = float(os.getenv("CLOSING_BET_FEE_BPS", "1.5"))        # 위탁수수료 (편도)
SLIPPAGE_BPS  = float(os.getenv("CLOSING_BET_SLIPPAGE_BPS", "10.0"))  # 시장가 슬리피지 (편도)
ROUNDTRIP_COST_PCT = (TAX_BPS + 2 * FEE_BPS + 2 * SLIPPAGE_BPS) / 100.0
# (a) 보유기간 + (c) ATR 트레일링 손절 — 백테스트(atr2_h3)에서 p1 대비 OOS 우위 검증.
#   기존 1영업일 강제청산(p1) 대신 최대 N영업일 보유 + ATR 트레일로 우측꼬리를 잡는다.
HOLD_DAYS  = int(os.getenv("CLOSING_BET_HOLD_DAYS", "3"))       # 최대 보유 영업일 (시간청산)
ATR_K      = float(os.getenv("CLOSING_BET_ATR_K", "2.0"))       # 트레일 밴드 = ATR_K × ATR
ATR_PERIOD = int(os.getenv("CLOSING_BET_ATR_PERIOD", "14"))     # ATR 평균 기간(봉)
# #1 장중 트레일 점검 주기(분). 백테스트는 일중 저가로 손절 이탈을 잡지만 라이브는 관측 시점에만
#    볼 수 있으므로, 보유분이 있는 장중에는 이 주기로 폴링해 트레일 스톱을 갱신·이탈 청산한다.
INTRADAY_POLL_MIN = int(os.getenv("CLOSING_BET_INTRADAY_POLL_MIN", "10"))
# #2(reconciliation): 청산 phase 에서 실계좌 보유분을 조회해 state 와 대조.
#   봇 매수이력에 있는데 state 가 잊은 종목(고아) → 청산. 매수이력에 없는 보유분 → 알림만(수동 확인).
RECONCILE = os.getenv("CLOSING_BET_RECONCILE", "true").lower() == "true"
OHLCV_DAYS = 120        # 일봉 조회 일수 (consolidation 90봉 + 여유 30봉)
MAX_PER_SECTOR = 2      # 섹터당 최대 선정 종목 수 (집중 리스크 방지)
US_MARKET_WEAK_THR = -1.5  # S&P500 AND NASDAQ 모두 이 값 이하 시 종베 중단

SCHEDULE: list[tuple[int, int, str]] = [
    (14, 50, "selection"),
    (15, 15, "buy_first"),    # E: 분할 매수 — 첫 50% (외부 권장 15:10~15:19)
    (15, 19, "buy_second"),   # E: 분할 매수 — 나머지 50% (마감 직전)
    (18,  5, "after_hours"),  # 시간외 단일가로 트레일링 스톱 갱신
    (9,   0, "sell"),         # 매일 — 트레일/손절 청산만 (시간청산 X)
    (15, 10, "force_close"),  # 매일 — 트레일 이탈 + 보유기간(HOLD_DAYS) 만기 시간청산
]

# ─── 로거 ──────────────────────────────────────────────────────────────────
# TimedRotatingFileHandler: 매일 자정 회전, 30일치 보관.
# 활성 파일은 LOG_FILE, 회전된 파일은 closing_bet.log.YYYY-MM-DD 형식.
from logging.handlers import TimedRotatingFileHandler  # noqa: E402

_file_handler = TimedRotatingFileHandler(
    filename=LOG_FILE,
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
    delay=False,
    utc=False,
)
_file_handler.suffix = "%Y-%m-%d"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        _file_handler,
    ],
)
logger = logging.getLogger(__name__)


# ─── Telegram 알림 ─────────────────────────────────────────────────────────

async def notify(msg: str) -> None:
    """Telegram 알림 전송. 토큰/채팅 ID 미설정 시 로그만 출력."""
    logger.info("[NOTIFY] %s", msg[:200].replace("\n", " "))
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import httpx
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML",
            })
    except Exception as e:
        logger.warning("[TELEGRAM] 전송 실패: %s", e)


# ─── 상태 파일 ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(key: str, content: Any) -> None:
    state = load_state()
    state[key] = {"timestamp": datetime.now().isoformat(), "content": content}
    state["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("[STATE] %s 저장", key)


def get_state(key: str) -> Any:
    return load_state().get(key, {}).get("content")


# ─── #6 멱등성: 단일 인스턴스 락 + phase 일일 중복실행 가드 ──────────────────────

LOCK_FILE = DATA_DIR / "daemon.lock"
FORCE_PHASE = os.getenv("CLOSING_BET_FORCE_PHASE", "false").lower() == "true"


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # noqa: PLC0415
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return True   # 판단 불가 → 살아있다고 가정(보수적)


def acquire_daemon_lock() -> bool:
    """데몬 단일 인스턴스 보장. 다른 살아있는 데몬이 락을 쥐고 있으면 False."""
    if LOCK_FILE.exists():
        try:
            old = int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            logger.error("[LOCK] 이미 데몬 실행 중 (PID=%d) — 중복 기동 차단", old)
            return False
        logger.warning("[LOCK] 스테일 락 발견 (PID=%s) — 회수", old)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_daemon_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except Exception:
        pass


def _phase_done_today(label: str) -> bool:
    """오늘 해당 phase 가 이미 실행 완료됐는지 (이중 주문 방지). FORCE_PHASE 면 항상 False."""
    if FORCE_PHASE:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    done = get_state("completed_phases") or {}
    return label in (done.get(today) or [])


def _mark_phase_done(label: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    done = get_state("completed_phases") or {}
    # 오늘 기록만 유지 (과거 날짜 정리)
    done = {today: list(set((done.get(today) or []) + [label]))}
    save_state("completed_phases", done)


# ─── 청산 원장 ──────────────────────────────────────────────────────────────
# 1영업일 보장: 09:00 부분청산(러닝) + 15:10 잔량 강제청산을 종목별로 합산해
# "포지션 1건당 가중 실현손익"을 만든다. HOLD가 남지 않으므로 승률 측정 편향이 사라진다.

def _reset_exit_ledger(exit_date: str) -> None:
    save_state("exit_ledger", {"exit_date": exit_date, "exits": []})


def _ensure_exit_ledger(exit_date: str) -> None:
    """exit_date가 바뀌었으면 원장 초기화 (새 청산일 첫 phase에서 호출)."""
    led = get_state("exit_ledger") or {}
    if led.get("exit_date") != exit_date:
        _reset_exit_ledger(exit_date)


def _append_exit(exit_date: str, rec: dict) -> None:
    """종목별 부분 청산 1건(09:00 또는 15:10)을 원장에 누적."""
    led = get_state("exit_ledger") or {}
    if led.get("exit_date") != exit_date:
        led = {"exit_date": exit_date, "exits": []}
    led.setdefault("exits", []).append(rec)
    save_state("exit_ledger", led)


def _aggregate_exits(exit_date: str) -> list[dict]:
    """원장을 종목별 가중 실현손익으로 합산 (부분 매도 + 강제 청산 모두 반영).

    반환 레코드는 sell.json `results` 스키마와 호환:
      symbol/company_name/entry_price/exit_price/pnl_pct/pnl_amount/composite/sector/action
    action 은 항상 "REALIZED" — 모든 포지션이 1영업일 내 실현되므로 HOLD 미발생.
    """
    led = get_state("exit_ledger") or {}
    if led.get("exit_date") != exit_date:
        return []
    by_sym: dict[str, dict] = {}
    for e in led.get("exits", []):
        s = by_sym.setdefault(e["symbol"], {
            "symbol":       e["symbol"],
            "company_name": e.get("company_name", e["symbol"]),
            "entry_price":  float(e.get("entry_price", 0) or 0),
            "composite":    e.get("composite", 0.0),
            "sector":       e.get("sector", "기타"),
            "action":       "REALIZED",
            "sell_qty":     0,
            "pnl_amount":   0.0,
            "exits":        [],
        })
        qty = int(e.get("qty", 0) or 0)
        s["sell_qty"]   += qty
        s["pnl_amount"] += (float(e.get("exit_price", 0) or 0) - s["entry_price"]) * qty
        s["exits"].append({
            "qty": qty, "exit_price": e.get("exit_price"),
            "reason": e.get("reason", ""), "when": e.get("when", ""),
        })
    results: list[dict] = []
    for s in by_sym.values():
        invested   = s["entry_price"] * s["sell_qty"]
        gross_amt  = s["pnl_amount"]
        gross_pct  = round(gross_amt / invested * 100, 2) if invested > 0 else 0.0
        # P2: 거래비용(왕복) 차감 — pnl_pct/pnl_amount 는 net 을 기본으로 보고한다.
        cost_amt   = invested * ROUNDTRIP_COST_PCT / 100.0
        s["exit_price"]       = round(s["entry_price"] + gross_amt / s["sell_qty"], 2) if s["sell_qty"] > 0 else s["entry_price"]
        s["pnl_pct_gross"]    = gross_pct
        s["pnl_amount_gross"] = round(gross_amt)
        s["cost_pct"]         = round(ROUNDTRIP_COST_PCT, 3)
        s["pnl_pct"]          = round(gross_pct - ROUNDTRIP_COST_PCT, 2)   # net
        s["pnl_amount"]       = round(gross_amt - cost_amt)               # net
        results.append(s)
    return results


def _finalize_sell_log(entry_date: str, exit_date: str) -> list[dict]:
    """원장을 합산해 sell.json 을 (재)작성. 09:00·15:10 어느 쪽에서 호출해도 idempotent."""
    results = _aggregate_exits(exit_date)
    _data_logger.log_sell(entry_date, exit_date, results, MOCK_MODE)
    return results


# ─── 데이터 로거 ──────────────────────────────────────────────────────────────

class DataLogger:
    """일별 종가배팅 데이터를 data/closing_bet/YYYY-MM-DD/ 에 JSON으로 저장합니다.

    저장 구조:
      data/closing_bet/
        2026-05-09/
          selection.json  — 전체 채점 종목 + 최종 후보 + 시장 상태
          buy.json        — 매수 주문 내역
        2026-05-10/
          sell.json       — 청산 결과 + P&L
    """

    def __init__(self, data_dir: Path = DATA_DIR):
        self._dir = data_dir

    def _day_dir(self, date: str) -> Path:
        d = self._dir / date
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_event(self, event_type: str, payload: dict | None = None) -> None:
        """append-only 이벤트 라인로그 (data/closing_bet/YYYY-MM-DD/events.jsonl).

        대시보드/백테스트가 시계열로 phase 진행과 결정 근거를 재구성할 수 있도록
        한 줄 = 한 이벤트(JSON) 형태로 누적 저장한다.
        """
        date = datetime.now().strftime("%Y-%m-%d")
        line = {
            "ts":         datetime.now().isoformat(timespec="seconds"),
            "event":      event_type,
            "payload":    payload or {},
        }
        path = self._day_dir(date) / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def log_selection(
        self,
        date: str,
        market: dict,
        all_scored: list[dict],
        candidates: list[dict],
    ) -> None:
        composites = [s["composite"] for s in all_scored] if all_scored else [0]
        data = {
            "date":       date,
            "timestamp":  datetime.now().isoformat(),
            "market":     market,
            "candidates": candidates,
            "all_scored": all_scored,
            "stats": {
                "analyzed_count":  len(all_scored),
                "qualified_count": len([s for s in all_scored if s["composite"] >= MIN_SCORE]),
                "min_composite":   round(min(composites), 1),
                "max_composite":   round(max(composites), 1),
                "avg_composite":   round(sum(composites) / len(composites), 1),
            },
        }
        path = self._day_dir(date) / "selection.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[DATA_LOG] 선별 저장 → %s (%d종목 전체, 후보 %d)", path, len(all_scored), len(candidates))

    def log_buy(self, date: str, orders: list[dict], mock_mode: bool) -> None:
        data = {
            "date":           date,
            "timestamp":      datetime.now().isoformat(),
            "mock_mode":      mock_mode,
            "orders":         orders,
            "total_invested": sum(o["quantity"] * o["entry_price"] for o in orders),
        }
        path = self._day_dir(date) / "buy.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[DATA_LOG] 매수 저장 → %s (%d종목)", path, len(orders))

    def log_sell(
        self,
        entry_date: str,
        exit_date: str,
        results: list[dict],
        mock_mode: bool,
    ) -> None:
        sold = [r for r in results if r.get("action") != "HOLD"]
        wins = [r for r in sold if r.get("pnl_pct", 0) > 0]
        data = {
            "entry_date": entry_date,
            "exit_date":  exit_date,
            "timestamp":  datetime.now().isoformat(),
            "mock_mode":  mock_mode,
            "results":    results,
            "summary": {
                "total_trades": len(sold),
                "wins":         len(wins),
                "losses":       len(sold) - len(wins),
                "win_rate":     round(len(wins) / len(sold) * 100, 1) if sold else 0.0,
                "avg_pnl_pct":  round(
                    sum(r.get("pnl_pct", 0) for r in sold) / len(sold), 2
                ) if sold else 0.0,
                "total_pnl_pct": round(sum(r.get("pnl_pct", 0) for r in sold), 2),
            },
        }
        path = self._day_dir(exit_date) / "sell.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[DATA_LOG] 청산 저장 → %s (%d거래)", path, len(sold))

    def analyze(self, days: int = 30) -> str:
        """최근 N일 데이터로 점수 구간별 승률 분석 리포트를 반환."""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        trade_records: list[dict] = []
        for day_dir in sorted(self._dir.glob("????-??-??")):
            if day_dir.name < since:
                continue
            sell_file = day_dir / "sell.json"
            if not sell_file.exists():
                continue
            try:
                sell_data = json.loads(sell_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            entry_date = sell_data.get("entry_date", "")
            score_map: dict[str, float] = {}
            if entry_date:
                sel_file = self._dir / entry_date / "selection.json"
                if sel_file.exists():
                    try:
                        sel_data = json.loads(sel_file.read_text(encoding="utf-8"))
                        for c in sel_data.get("candidates", []):
                            score_map[c["symbol"]] = c["composite"]
                    except Exception:
                        pass
            for r in sell_data.get("results", []):
                if r.get("action") == "HOLD":
                    continue
                symbol = r.get("symbol", "")
                composite = r.get("composite") or score_map.get(symbol, 0.0)
                trade_records.append({
                    "date":      sell_data.get("exit_date", day_dir.name),
                    "symbol":    symbol,
                    "name":      r.get("company_name", ""),
                    "composite": composite,
                    "pnl_pct":   r.get("pnl_pct", 0.0),
                    "win":       r.get("pnl_pct", 0.0) > 0,
                })

        if not trade_records:
            return f"최근 {days}일 거래 기록 없음\n데이터 디렉토리: {self._dir}"

        brackets = [
            ("80+",   lambda c: c >= 80),
            ("70~80", lambda c: 70 <= c < 80),
            ("60~70", lambda c: 60 <= c < 70),
            ("50~60", lambda c: 50 <= c < 60),
            ("~50",   lambda c: c < 50),
        ]
        lines = [
            f"=== 종가배팅 성과 분석 (최근 {days}일) ===",
            f"전체 거래: {len(trade_records)}건",
            "",
            "── 점수 구간별 승률 ──",
        ]
        for bracket_name, fn in brackets:
            br = [t for t in trade_records if fn(t["composite"])]
            if not br:
                continue
            wins = sum(1 for t in br if t["win"])
            avg_pnl = round(sum(t["pnl_pct"] for t in br) / len(br), 2)
            lines.append(
                f"  [{bracket_name:6s}]  {len(br):2d}건  "
                f"승률:{wins/len(br)*100:5.1f}%  "
                f"평균P&L:{avg_pnl:+.2f}%"
            )

        total_wins = sum(1 for t in trade_records if t["win"])
        avg_all = round(sum(t["pnl_pct"] for t in trade_records) / len(trade_records), 2)
        lines += [
            "",
            "── 전체 ──",
            f"  승률: {total_wins/len(trade_records)*100:.1f}%  평균P&L: {avg_all:+.2f}%",
            "",
            "── 날짜별 결과 (최근 10일) ──",
        ]
        from collections import defaultdict
        daily: dict[str, list[dict]] = defaultdict(list)
        for t in trade_records:
            daily[t["date"]].append(t)
        for date in sorted(daily.keys(), reverse=True)[:10]:
            trades = daily[date]
            dw = sum(1 for t in trades if t["win"])
            dpnl = round(sum(t["pnl_pct"] for t in trades), 2)
            lines.append(
                f"  {date}  {len(trades)}건  "
                f"승:{dw}/패:{len(trades)-dw}  "
                f"합계P&L:{dpnl:+.2f}%"
            )
        lines.append(f"\n데이터 위치: {self._dir}")
        return "\n".join(lines)


_data_logger = DataLogger()


# ─── pykrx 데이터 헬퍼 ────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y%m%d")


def _suppress_pykrx_noise():
    """pykrx util.py의 print(stdout) + logging.info(root) 노이즈 억제.

    pykrx dataframe_empty_handler가 오류 시 print()와 logging.info()를 동시에 호출함.
    stdout redirect + root logger 임시 레벨 상향으로 양쪽 억제.
    """
    import contextlib, io

    class _Combined:
        def __enter__(self):
            self._stdout_ctx = contextlib.redirect_stdout(io.StringIO())
            self._stdout_ctx.__enter__()
            self._root = logging.getLogger()
            self._prev_level = self._root.level
            self._root.setLevel(logging.WARNING)
            return self

        def __exit__(self, *args):
            self._stdout_ctx.__exit__(*args)
            self._root.setLevel(self._prev_level)

    return _Combined()


def get_kospi_change_pct() -> tuple[float, float]:
    """(오늘 등락률%, 5일 누적 등락률%) 반환.

    데이터 소스 우선순위:
      1) Naver Finance 모바일 API — 장중 실시간 (오늘 등락률만)
      2) pykrx — 영업일 마감 후
      3) FinanceDataReader ^KS11 — Yahoo Finance (1일 lag 가능)

    Naver 성공 시 5일 등락률은 FDR로 보완.
    """
    today_pct: float | None = None
    five_d_pct: float | None = None

    # 1차: Naver Finance 실시간 (장중에도 정확)
    try:
        import httpx  # noqa: PLC0415
        r = httpx.get("https://m.stock.naver.com/api/index/KOSPI/basic", timeout=5.0)
        if r.status_code == 200:
            d = r.json()
            ratio = d.get("fluctuationsRatio")
            if ratio is not None:
                today_pct = round(float(ratio), 2)
                logger.debug("[KOSPI] naver 실시간 today=%.2f%%", today_pct)
    except Exception as e:
        logger.debug("[KOSPI] naver 실패: %s", e)

    # 5일 등락률은 FDR로 보완 (Naver API는 단일 값만)
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        df = fdr.DataReader("^KS11", _days_ago(20), _today())
        if not df.empty and len(df) >= 2:
            closes = df["Close"].values
            fdr_today = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
            ref_idx = max(-6, -len(closes))
            five_d_pct = round((closes[-1] - closes[ref_idx]) / closes[ref_idx] * 100, 2)
            if today_pct is None:
                today_pct = fdr_today
                logger.debug("[KOSPI] fdr ^KS11 today=%.2f%% 5d=%.2f%%", today_pct, five_d_pct)
    except Exception as e:
        logger.debug("[KOSPI] fdr 실패: %s", e)

    # 마지막 fallback: pykrx
    if today_pct is None:
        try:
            with _suppress_pykrx_noise():
                df = krx.get_index_ohlcv_by_date(_days_ago(20), _today(), "1001")
            if not df.empty and len(df) >= 2:
                closes = df["종가"].values
                today_pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                if five_d_pct is None:
                    ref_idx = max(-6, -len(closes))
                    five_d_pct = round((closes[-1] - closes[ref_idx]) / closes[ref_idx] * 100, 2)
        except Exception as e:
            logger.warning("[KOSPI] 모든 소스 실패 — 0.0 사용: %s", e)

    return today_pct or 0.0, five_d_pct or 0.0


def _fallback_top_stocks(n: int) -> list[tuple[str, str, float]]:
    """pykrx KRX 엔드포인트 불가 시 캐시된 Kiwoom universe로 대체."""
    try:
        cache_files = sorted(_ROOT.glob("docs_cache/universe_kiwoom_*.json"), reverse=True)
        if not cache_files:
            return []
        data = json.loads(cache_files[0].read_text(encoding="utf-8"))
        kospi = [
            r for r in data
            if r.get("market") in ("거래소",) and r.get("warn", "0") == "0"
        ]
        kospi.sort(key=lambda r: r.get("market_cap", 0), reverse=True)
        # fallback은 거래대금 데이터 없음 → MIN_VALUE_KRW 이상으로 가정해 필터 통과
        result = [(r["code"], r["name"], MIN_VALUE_KRW) for r in kospi[:n]]
        logger.info("[DATA] fallback universe %d종목 (캐시: %s)", len(result), cache_files[0].name)
        return result
    except Exception as e:
        logger.error("[DATA] fallback universe 실패: %s", e)
        return []


def get_top_stocks_by_value(n: int = TOP_N_STOCKS) -> list[tuple[str, str, float]]:
    """거래대금 상위 N 종목 [(ticker, name, value_krw), ...] 반환."""
    for offset in range(8):
        try:
            date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
            with _suppress_pykrx_noise():
                df = krx.get_market_ohlcv_by_ticker(date, market="KOSPI")
            if df.empty:
                continue
            df = df[df["거래대금"] > 0].sort_values("거래대금", ascending=False)
            result: list[tuple[str, str, float]] = []
            for ticker in df.head(n).index:
                try:
                    name = krx.get_market_ticker_name(ticker)
                except Exception:
                    name = ticker
                value = float(df.loc[ticker, "거래대금"])
                result.append((ticker, name, value))
            logger.info("[DATA] 거래대금 상위 %d종목 (기준일: %s)", len(result), date)
            return result
        except Exception:
            continue
    logger.warning("[DATA] pykrx KRX 엔드포인트 불응답 — universe 캐시로 대체")
    return _fallback_top_stocks(n)


def get_ohlcv(symbol: str, days: int = OHLCV_DAYS) -> list[dict]:
    """일봉 데이터 [{open,high,low,close,volume,value}, ...] 반환 (최대 days개)."""
    try:
        df = krx.get_market_ohlcv_by_date(_days_ago(days + 20), _today(), symbol)
        if df.empty:
            return []
        records = []
        for _, row in df.tail(days).iterrows():
            records.append({
                "open":   float(row.get("시가", 0)),
                "high":   float(row.get("고가", 0)),
                "low":    float(row.get("저가", 0)),
                "close":  float(row.get("종가", 0)),
                "volume": float(row.get("거래량", 0)),
                "value":  float(row.get("거래대금", 0)),
            })
        return records
    except Exception as e:
        logger.debug("[OHLCV] %s 오류: %s", symbol, e)
        return []


def get_current_price(symbol: str) -> float | None:
    """최신 종가 반환. 장중 실시간 가격이 필요하면 kiwoom-market-mcp 사용 권장."""
    try:
        df = krx.get_market_ohlcv_by_date(_days_ago(10), _today(), symbol)
        if df.empty:
            return None
        return float(df["종가"].iloc[-1])
    except Exception:
        return None


def get_advance_ratio() -> float:
    """KOSPI 전 종목 중 등락률 > 0 비율 (0.0~1.0). 오류 시 중립값 0.5 반환."""
    for offset in range(3):
        try:
            date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
            with _suppress_pykrx_noise():
                df = krx.get_market_ohlcv_by_ticker(date, market="KOSPI")
            if df.empty:
                continue
            active = df[df["거래량"] > 0]
            if active.empty:
                continue
            if "등락률" in active.columns:
                rising = int((active["등락률"] > 0).sum())
            else:
                rising = int((active["종가"] >= active["시가"]).sum())
            return round(rising / len(active), 3)
        except Exception:
            pass
    logger.debug("[DATA] 양봉비율 조회 실패 — 중립값 0.5 사용")
    return 0.5


def _above_ma20(ohlcv: list[dict]) -> bool:
    """현재가가 20일 단순이동평균 이상인지 확인. 데이터 부족(< 20봉) 시 True."""
    if len(ohlcv) < 20:
        return True
    closes = [c["close"] for c in ohlcv[-20:]]
    ma20 = sum(closes) / 20
    return ohlcv[-1]["close"] >= ma20


def _compute_atr(ohlcv: list[dict], period: int = ATR_PERIOD) -> float:
    """평균 True Range (절대값). 데이터 부족 시 0.0 → 호출자가 고정손절로 폴백."""
    if len(ohlcv) < 2:
        return 0.0
    trs = []
    for i in range(1, len(ohlcv)):
        h = ohlcv[i].get("high", 0.0)
        l = ohlcv[i].get("low", 0.0)
        pc = ohlcv[i - 1].get("close", 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    k = trs[-period:]
    return sum(k) / len(k) if k else 0.0


def _add_business_days(start_date_str: str, n: int) -> str:
    """YYYY-MM-DD 에 영업일(주말만 스킵) n일을 더한 날짜. 시간청산 기한 계산용.

    공휴일은 미반영 — 기존 스케줄러의 주말-only 규약과 동일.
    """
    d = datetime.strptime(start_date_str, "%Y-%m-%d")
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.strftime("%Y-%m-%d")


def _today_gap_pct(ohlcv: list[dict]) -> float:
    """오늘 종가가 전일 대비 몇 % 상승했는지 반환."""
    if len(ohlcv) < 2:
        return 0.0
    prev = ohlcv[-2]["close"]
    curr = ohlcv[-1]["close"]
    if prev <= 0:
        return 0.0
    return (curr - prev) / prev * 100


# 갭 임계값 — 백테스트 결과:
#  -2~0% 갭: 80% 승률 / +1.28%
#   0~+2% 갭: 76% 승률 / +1.17%
#  +2~+4% 갭: 57.9% 승률 / +0.61% (가장 약한 구간)
#  +4%+: 차익실현 압력 ↑
# → +2% 이상 갭 종목은 익일 시초 약세 가능성 높아 제외
_GAP_LIMIT = 2.0


def _merge_split_orders(first: list[dict], second: list[dict]) -> list[dict]:
    """분할 매수 1차+2차 결과를 종목별 평단/총 수량으로 합산."""
    by_symbol: dict[str, dict] = {}
    for o in first + second:
        sym = o["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {**o, "split": "merged"}
        else:
            existing = by_symbol[sym]
            total_qty = existing["quantity"] + o["quantity"]
            # 가중 평단가
            avg_price = (
                existing["entry_price"] * existing["quantity"]
                + o["entry_price"] * o["quantity"]
            ) / total_qty if total_qty > 0 else existing["entry_price"]
            existing["quantity"] = total_qty
            existing["entry_price"] = round(avg_price, 2)
    return list(by_symbol.values())


def _has_min_value(ohlcv: list[dict], min_value_krw: float = MIN_VALUE_KRW) -> bool:
    """오늘 거래대금이 min_value_krw 이상인지 확인.

    외부 베스트 프랙티스: 종가매매는 1,000억원 이상 거래대금에서 안정적.
    pykrx의 '거래대금'은 원 단위.
    """
    if not ohlcv:
        return False
    today_value = ohlcv[-1].get("value") or 0
    return today_value >= min_value_krw


def get_overnight_us_change() -> tuple[float, float]:
    """(S&P 500 선물 등락률%, NASDAQ 선물 등락률%). 실패 시 (0.0, 0.0).

    외부 권장: KOSPI 14:50 시점에 미국 현물(전일 종가)보다 **야간 선물 실시간**이 신호 정확.
    티커: ES=F (S&P500 선물), NQ=F (NASDAQ 100 선물).
    선물 조회 실패 시 현물(US500/IXIC)로 폴백.
    """
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        end = datetime.now()
        start = (end - timedelta(days=10)).strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        # 1순위: 선물 (ES=F, NQ=F)
        try:
            es = fdr.DataReader("ES=F", start, end_str)
            nq = fdr.DataReader("NQ=F", start, end_str)
            if len(es) >= 2 and len(nq) >= 2:
                es_pct = round((es["Close"].iloc[-1] - es["Close"].iloc[-2]) / es["Close"].iloc[-2] * 100, 2)
                nq_pct = round((nq["Close"].iloc[-1] - nq["Close"].iloc[-2]) / nq["Close"].iloc[-2] * 100, 2)
                logger.debug("[US_FUTURES] ES=F %+.2f%%  NQ=F %+.2f%%", es_pct, nq_pct)
                return es_pct, nq_pct
        except Exception as e:
            logger.warning("[US_FUTURES] ES=F/NQ=F 조회 실패 — 현물 폴백: %s", str(e)[:80])

        # 폴백: 현물 (US500, IXIC)
        sp = fdr.DataReader("US500", start, end_str)
        nq = fdr.DataReader("IXIC", start, end_str)
        sp_pct = round(float(sp["Close"].iloc[-1] / sp["Close"].iloc[-2] - 1) * 100, 2) if len(sp) >= 2 else 0.0
        nq_pct = round(float(nq["Close"].iloc[-1] / nq["Close"].iloc[-2] - 1) * 100, 2) if len(nq) >= 2 else 0.0
        return sp_pct, nq_pct
    except Exception as e:
        logger.warning("[US_MARKET] 조회 실패: %s", e)
        return 0.0, 0.0


def _load_sector_map() -> dict[str, str]:
    """FinanceDataReader로 KOSPI 종목별 업종 매핑 로드. 일별 캐시 사용."""
    cache_path = DATA_DIR / f"_sector_map_{datetime.now().strftime('%Y%m%d')}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        import FinanceDataReader as fdr  # noqa: PLC0415
        df = fdr.StockListing("KOSPI")
        if not df.empty:
            sector_col = next((c for c in ["Sector", "업종", "Industry"] if c in df.columns), None)
            code_col   = next((c for c in ["Symbol", "Code", "종목코드"] if c in df.columns), None)
            if sector_col and code_col:
                result = {str(row[code_col]): str(row[sector_col]) for _, row in df.iterrows() if row.get(code_col)}
                cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                logger.info("[SECTOR] 업종 맵 로드 완료 (%d종목)", len(result))
                return result
    except Exception as e:
        logger.debug("[SECTOR] fdr 업종 맵 실패 → Kiwoom 캐시 사용: %s", e)
    # fdr 실패 시 Kiwoom universe 캐시에서 섹터 정보 로드
    try:
        cache_files = sorted(_ROOT.glob("docs_cache/universe_kiwoom_*.json"), reverse=True)
        if cache_files:
            data = json.loads(cache_files[0].read_text(encoding="utf-8"))
            result = {r["code"]: r.get("sector", "기타") for r in data if r.get("code")}
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            logger.info("[SECTOR] Kiwoom 캐시에서 업종 맵 로드 (%d종목)", len(result))
            return result
    except Exception as e2:
        logger.warning("[SECTOR] Kiwoom 캐시도 실패: %s — 섹터 제한 비활성", e2)
    return {}


def apply_sector_limit(
    candidates_pool: list[dict],
    sector_map: dict[str, str],
    max_per_sector: int = MAX_PER_SECTOR,
) -> list[dict]:
    """점수 내림차순 후보 풀에서 섹터당 max_per_sector개만 선택 (그리디)."""
    if not sector_map:
        return candidates_pool[:TOP_CANDIDATES]
    sector_count: dict[str, int] = {}
    selected: list[dict] = []
    for c in candidates_pool:
        sector = sector_map.get(c["symbol"], "기타")
        if sector_count.get(sector, 0) < max_per_sector:
            selected.append({**c, "sector": sector})
            sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(selected) >= TOP_CANDIDATES:
            break
    return selected


# ─── 선택적 MCP 데이터 (#7: 종목 루프 전체에서 1회 연결 재사용) ──────────────────

async def _enter_optional_mcp(key: str, url: str):
    """선택적 MCP 를 1회 연결해 진입된 MCPManager 반환 (도구 없으면 정리 후 None).

    실패/미가동 시 None — 호출자는 종목 루프 전체에서 이 연결을 재사용한다.
    기존엔 종목마다 새로 connect 해 서버 down 시 타임아웃이 누적됐다.
    """
    try:
        mgr = MCPManager({key: url})
        await mgr.__aenter__()
        if not mgr.tools:
            await mgr.__aexit__(None, None, None)
            return None
        return mgr
    except Exception:
        return None


def _find_mcp_tool(mgr, keywords: tuple[str, ...]) -> str | None:
    return next((t["name"] for t in (mgr.tools or [])
                 if any(kw in t["name"].lower() for kw in keywords)), None)


async def _fetch_news_via(mgr, tool: str, company_name: str) -> list[str]:
    """이미 연결된 naver-news mgr 로 뉴스 제목 수집."""
    try:
        raw = await mgr.call_tool(tool, {"query": company_name, "display": 10})
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        items: Any = parsed
        if isinstance(parsed, dict):
            items = parsed.get("data", parsed.get("items", []))
            if isinstance(items, dict):
                items = items.get("items", [])
        titles = []
        for item in (items or [])[:10]:
            if isinstance(item, dict):
                t = item.get("title", item.get("제목", ""))
                if t:
                    titles.append(str(t))
        return titles
    except Exception:
        return []


async def _fetch_investor_via(mgr, tool: str, symbol: str) -> tuple[float | None, float | None]:
    """이미 연결된 investor-domain mgr 로 외인·기관 5일 순매수 수집."""
    try:
        raw = await mgr.call_tool(tool, {"stock_code": symbol})
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            d = parsed.get("data", parsed)
            if isinstance(d, dict):
                foreign = d.get("foreign_net_5d") or d.get("외국인_5일_순매수")
                inst = d.get("institutional_net_5d") or d.get("기관_5일_순매수")
                return (float(foreign) if foreign is not None else None,
                        float(inst) if inst is not None else None)
    except Exception:
        pass
    return None, None


async def _try_get_realtime_price(symbol: str) -> float | None:
    """kiwoom-market-mcp → trading-domain 순으로 실시간 현재가 조회. 실패 시 None.

    장 시간 중 kiwoom-market-mcp(:8031)에서 실시간 현재가를 조회한다.
    서버 미가동 또는 툴 없을 시 trading-domain(:8030)으로 재시도.
    둘 다 실패하면 호출자가 pykrx 전일종가로 폴백.
    """
    _PRICE_KEYS = ("current_price", "현재가", "stck_prpr", "price", "close")
    _PRICE_TOOL_KW = ("current_price", "현재가", "quote", "get_price", "market_price")

    for url_key, url in [
        ("kiwoom-market-mcp", MARKET_URL),
        ("trading-domain", TRADING_URL),
    ]:
        try:
            async with MCPManager({url_key: url}) as mcp:
                if not mcp.tools:
                    continue
                tool = next(
                    (t["name"] for t in mcp.tools
                     if any(kw in t["name"].lower() for kw in _PRICE_TOOL_KW)),
                    None,
                )
                if not tool:
                    continue
                raw = await mcp.call_tool(tool, {"stock_code": symbol})
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                d = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
                for key in _PRICE_KEYS:
                    val = d.get(key) if isinstance(d, dict) else None
                    if val:
                        return float(str(val).replace(",", ""))
        except Exception:
            continue
    return None


def _order_accepted(parsed: Any) -> tuple[bool, str]:
    """주문 응답이 실제 수락됐는지 판정 (#3 reconciliation).

    키움은 MCP 레벨 success:true 라도 data.return_code != 0 이면 거부다
    (예: 8005 토큰무효 → return_code 3). 이 경우 포지션을 state 에 기록하면 안 된다
    (유령 포지션 → 익일 보유하지 않은 종목 청산 시도).
    """
    if not isinstance(parsed, dict):
        return False, "응답 형식 오류"
    if parsed.get("success") is False:
        return False, str(parsed.get("error", "주문 실패"))
    d = parsed.get("data", parsed)
    rc = d.get("return_code") if isinstance(d, dict) else None
    if rc in (0, "0", None):   # return_code 없으면(=구형/성공) 수락으로 간주
        return True, ""
    msg = d.get("return_msg", "") if isinstance(d, dict) else ""
    return False, f"return_code={rc} {str(msg)[:80]}"


# 주문 거부 원인 분류 — return_msg 키워드 매칭 (장중 시장가 거부 원인 추적용).
_REJECT_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("8005", "토큰", "token"),                                  "TOKEN_INVALID(토큰무효·#5자동복구대상)"),
    (("rc4058", "거래시간", "장운영", "운영시간", "주문가능시간",
      "장개시", "장종료", "동시호가", "장시작", "장마감"),         "NOT_TRADING_HOURS(장운영시간외)"),
    (("증거금", "예수금", "잔고", "현금", "매수가능", "주문가능금액"), "INSUFFICIENT_FUNDS(증거금/잔고부족)"),
    (("호가단위", "단위상위", "단위하위"),                          "PRICE_TICK(호가단위오류)"),
    (("상한", "하한", "가격제한"),                                  "PRICE_LIMIT(상하한가)"),
    (("종목", "정리매매", "거래정지", "관리종목"),                   "SYMBOL_RESTRICTED(종목제한)"),
]


def _classify_rejection(msg: str) -> str:
    m = (msg or "").lower()
    for kws, label in _REJECT_PATTERNS:
        if any(k.lower() in m for k in kws):
            return label
    return "UNKNOWN(미분류 — raw 응답 확인)"


def _rejection_detail(parsed: Any) -> tuple[Any, str, str]:
    """(return_code, return_msg, 분류라벨) 추출."""
    d = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
    code = d.get("return_code") if isinstance(d, dict) else None
    msg = str(d.get("return_msg", "")) if isinstance(d, dict) else ""
    return code, msg, _classify_rejection(msg)


def _log_order_reject(phase: str, symbol: str, params: dict, parsed: Any) -> tuple[str, str]:
    """주문 거부를 원인분류·전체 코드/메시지·파라미터·raw 응답까지 기록.

    closing_bet.log(ERROR) + events.jsonl(order_reject)에 동시 기록해 사후 원인분석을 가능케 한다.
    Returns: (분류라벨, return_msg)
    """
    code, msg, label = _rejection_detail(parsed)
    try:
        raw_str = json.dumps(parsed, ensure_ascii=False)[:600]
    except Exception:
        raw_str = str(parsed)[:600]
    logger.error(
        "[REJECT] %s %s  분류=%s  rc=%s  msg=%s  params=%s  raw=%s",
        phase, symbol, label, code, msg, params, raw_str,
    )
    _data_logger.log_event("order_reject", {
        "phase": phase, "symbol": symbol, "label": label,
        "return_code": code, "return_msg": msg, "params": params,
        "raw": parsed if isinstance(parsed, dict) else str(parsed),
        "ts": datetime.now().isoformat(timespec="seconds"),
    })
    return label, msg


def _extract_fill_price(parsed: Any) -> float | None:
    """주문 응답에서 실체결가를 찾는다 (있으면). 키움 kt10000/kt10001 은 보통 주문번호만
    동기 반환하므로 대개 None — 호출자는 매수 직전 실시간가로 폴백한다.
    어댑터/모의서버가 체결가를 echo 하면 그 값을 entry 로 쓴다.
    """
    _FILL_KEYS = ("ord_uv", "체결단가", "체결가", "executed_price", "fill_price",
                  "avg_price", "prc", "cntr_pric", "stck_prpr")
    if not isinstance(parsed, dict):
        return None
    d = parsed.get("data", parsed)
    if not isinstance(d, dict):
        return None
    for key in _FILL_KEYS:
        val = d.get(key)
        if val in (None, "", "0", 0):
            continue
        try:
            price = float(str(val).lstrip("+-").replace(",", ""))
            if price > 0:
                return price
        except (TypeError, ValueError):
            continue
    return None


async def _try_get_after_hours_price(symbol: str) -> float | None:
    """시간외 단일가 조회.

    1) 전용 after_hours/시간외 툴이 있으면 우선 사용.
    2) 없으면 get_stock_basic_info → cur_prc 필드 fallback.
       (키움 API는 장 마감 후에도 cur_prc에 시간외 최신가 반영)
    """
    _AH_TOOL_KW = ("after_hours", "overtime", "시간외", "extended")
    _AH_PRICE_KEYS = ("after_hours_price", "시간외현재가", "overtime_price", "extended_price")
    try:
        async with MCPManager({"kiwoom-market-mcp": MARKET_URL}) as mcp:
            if not mcp.tools:
                return None

            # 1) 전용 시간외 툴 탐색
            ah_tool = next(
                (t["name"] for t in mcp.tools
                 if any(kw in t["name"].lower() for kw in _AH_TOOL_KW)),
                None,
            )
            if ah_tool:
                raw = await mcp.call_tool(ah_tool, {"stock_code": symbol})
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                d = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
                for key in _AH_PRICE_KEYS:
                    val = d.get(key) if isinstance(d, dict) else None
                    if val:
                        return float(str(val).replace(",", ""))

            # 2) Fallback: get_stock_basic_info → cur_prc (장 마감 후 시간외 가격 반영)
            info_tool = next(
                (t["name"] for t in mcp.tools if "basic_info" in t["name"] or "basic" in t["name"]),
                None,
            )
            if info_tool:
                raw = await mcp.call_tool(info_tool, {"stock_code": symbol})
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                d = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
                cur = d.get("cur_prc") if isinstance(d, dict) else None
                if cur:
                    # cur_prc는 "+126600" / "-126600" 형식 — 부호 제거 후 숫자만
                    price = float(str(cur).lstrip("+-").replace(",", ""))
                    if price > 0:
                        logger.debug("[AH] %s 전용툴 없음 → cur_prc fallback: %.0f원", symbol, price)
                        return price
    except Exception:
        pass
    return None


# ─── 스코어링 ───────────────────────────────────────────────────────────────

def score_one_stock(
    symbol: str,
    company_name: str,
    ohlcv: list[dict],
    news_titles: list[str] | None = None,
    foreign_net: float | None = None,
    inst_net: float | None = None,
) -> dict | None:
    """closing_bet_mcp Python 함수를 직접 호출해 composite 점수 계산."""
    if not ohlcv or len(ohlcv) < 21:
        return None
    try:
        cat = score_catalyst(
            news_titles=news_titles or [],
            news_descriptions=[],
            disclosure_titles=[],
        )
        # P0: 라이브 채점식을 검증 백테스트(compute_technical_scores, candle v1, catalyst 미반영)와 일치.
        #     기존 hybrid는 candle v2(위꼬리 클수록 高)로 백테스트 결론(위꼬리 작을수록 승률↑)과 부호가 반대였음.
        tech = compute_technical_scores(
            ohlcv=ohlcv,
            foreign_net_5d=foreign_net,
            institutional_net_5d=inst_net,
        )
        # catalyst 가중은 CLOSING_BET_CATALYST_WEIGHT(기본 0.0)로만 블렌딩.
        # 0.0이면 composite = technical-only로 백테스트와 동일. 뉴스 없는 종목은 페널티하지 않음.
        cat_weight = CATALYST_WEIGHT if cat.has_catalyst else 0.0
        composite = cat.score * cat_weight + tech.composite() * (1.0 - cat_weight)
        return {
            "symbol":              symbol,
            "company_name":        company_name,
            "composite":           round(composite, 1),
            "catalyst_score":      round(cat.score, 1),
            "has_catalyst":        cat.has_catalyst,
            "catalyst_weighted":   cat.has_catalyst,
            "technical_composite": round(tech.composite(), 1),
            "current_price":       float(ohlcv[-1]["close"]) if ohlcv else 0.0,
            "atr":                 round(_compute_atr(ohlcv), 2),   # (c) 트레일 손절 밴드용
        }
    except Exception as e:
        logger.debug("[SCORE] %s 오류: %s", symbol, e)
        return None


def calc_position_qty(composite: float, current_price: float) -> int:
    """composite 점수 기반 투자 수량 산출.

    P0: 확신 사이징(≥70 1.5x / ≥85 2.0x)은 백테스트에서 70+ 구간이 오히려 부진
    (승률 50.0% / 평균 -0.13%, n=10)해 근거가 약하다. 기본은 전 구간 1.0x(평탄).
    근거가 쌓이면 CLOSING_BET_CONVICTION_SIZING=true 로 점수 차등을 다시 켤 수 있다.
    """
    if current_price <= 0:
        return 0
    if CONVICTION_SIZING and composite >= 85:
        invest = INVESTMENT_PER_TRADE * 2.0
    elif CONVICTION_SIZING and composite >= 70:
        invest = INVESTMENT_PER_TRADE * 1.5
    else:
        invest = INVESTMENT_PER_TRADE
    return max(1, int(invest / current_price))


# ─── Phase 1: 후보 선별 ────────────────────────────────────────────────────

async def phase_selection() -> list[dict]:
    """14:50 — pykrx + closing_bet_mcp 직접 스코어링으로 종가배팅 후보 선별."""
    logger.info("=" * 60)
    logger.info("[PHASE 1] 후보 선별 시작  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)
    _data_logger.log_event("phase_start", {"phase": "selection"})

    # 1) 시장 필터
    today_pct, five_d_pct = get_kospi_change_pct()
    mf = evaluate_market_filter(kospi_today_pct=today_pct, kospi_5d_pct=five_d_pct)
    logger.info(
        "[MARKET] KOSPI 오늘 %+.2f%%  5일 %+.2f%%  OK=%s",
        today_pct, five_d_pct, mf["ok"],
    )
    _data_logger.log_event("market_filter", {
        "kospi_today_pct": today_pct, "kospi_5d_pct": five_d_pct,
        "ok": mf["ok"], "reason": mf.get("reason", ""),
    })

    if not mf["ok"]:
        msg = (
            f"⚠️ 시장 필터 — 종베 중단\n"
            f"KOSPI {today_pct:+.2f}%\n"
            f"사유: {mf['reason']}"
        )
        await notify(msg)
        save_state("selection", [])
        _data_logger.log_event("skip", {"reason": "market_filter", "detail": mf.get("reason")})
        return []

    # 1-b) 시장 레짐 (양봉비율 + 추세 복합 판단)
    advance_ratio = get_advance_ratio()
    regime = classify_regime(kospi_today_pct=today_pct, advance_ratio=advance_ratio)
    logger.info(
        "[MARKET] 양봉비율 %.1f%%  레짐=%s",
        advance_ratio * 100, regime,
    )
    _data_logger.log_event("regime", {
        "kospi_today_pct": today_pct, "advance_ratio": advance_ratio, "regime": regime,
    })

    if regime == "weak":
        msg = (
            f"⚠️ 시장 레짐 WEAK — 종베 중단\n"
            f"KOSPI {today_pct:+.2f}%  양봉비율 {advance_ratio*100:.1f}%\n"
            f"(KOSPI < -1.0% 또는 양봉비율 < 35%)"
        )
        await notify(msg)
        save_state("selection", [])
        _data_logger.log_event("skip", {"reason": "regime_weak", "kospi": today_pct, "advance_ratio": advance_ratio})
        return []

    # 1-c) 미국 시장 오버나잇 게이트 (Fix 4)
    sp_pct, nq_pct = get_overnight_us_change()
    logger.info("[US_MARKET] S&P500 %+.2f%%  NASDAQ %+.2f%%", sp_pct, nq_pct)
    _data_logger.log_event("us_market", {"sp500_pct": sp_pct, "nasdaq_pct": nq_pct})
    if sp_pct <= US_MARKET_WEAK_THR and nq_pct <= US_MARKET_WEAK_THR:
        msg = (
            f"⚠️ 미국 시장 약세 — 종베 중단\n"
            f"S&P500 {sp_pct:+.2f}%  NASDAQ {nq_pct:+.2f}%\n"
            f"(둘 다 {US_MARKET_WEAK_THR}% 이하)"
        )
        await notify(msg)
        save_state("selection", [])
        _data_logger.log_event("skip", {"reason": "us_weak", "sp500": sp_pct, "nasdaq": nq_pct})
        return []

    # 2) 거래대금 상위 종목 수집
    stocks = get_top_stocks_by_value(TOP_N_STOCKS)
    if not stocks:
        await notify("❌ 종목 데이터 수집 실패")
        save_state("selection", [])
        return []

    # 3) 각 종목 채점
    # #7: 선택적 MCP(news/investor)를 종목 루프 전체에서 1회 연결로 재사용.
    #     catalyst 가중이 0이면 뉴스는 composite 에 영향 없으므로 아예 연결하지 않는다.
    news_mgr = await _enter_optional_mcp("naver-news-mcp", NEWS_URL) if CATALYST_WEIGHT > 0 else None
    news_tool = _find_mcp_tool(news_mgr, ("news", "search")) if news_mgr else None
    inv_mgr = await _enter_optional_mcp("investor-domain", INVESTOR_URL)
    inv_tool = _find_mcp_tool(inv_mgr, ("foreign", "investor", "trading")) if inv_mgr else None
    logger.info("[SELECT] 보조데이터 연결 — news=%s investor=%s (catalyst_w=%.2f)",
                bool(news_tool), bool(inv_tool), CATALYST_WEIGHT)

    scored: list[dict] = []
    ma20_filtered = 0
    gap_filtered  = 0
    value_filtered = 0
    try:
        for idx, (symbol, name, stock_value) in enumerate(stocks, 1):
            if stock_value < MIN_VALUE_KRW:    # B: 거래대금 1,000억원 미만 제외
                value_filtered += 1
                logger.debug("[FILTER] %s %s — 거래대금 %.0f억원 < %.0f억원", symbol, name, stock_value / 1e8, MIN_VALUE_KRW / 1e8)
                continue
            ohlcv = get_ohlcv(symbol)
            if not ohlcv:
                continue
            if not _above_ma20(ohlcv):
                ma20_filtered += 1
                logger.debug("[FILTER] %s %s — MA20 이하 제외", symbol, name)
                continue
            gap_pct = _today_gap_pct(ohlcv)
            if gap_pct >= _GAP_LIMIT:   # +2% 이상 갭은 익일 시초 약세 가능성 높음
                gap_filtered += 1
                logger.debug("[FILTER] %s %s — 당일 갭 %.1f%% 제외", symbol, name, gap_pct)
                continue
            news = await _fetch_news_via(news_mgr, news_tool, name) if news_tool else []
            foreign, inst = await _fetch_investor_via(inv_mgr, inv_tool, symbol) if inv_tool else (None, None)
            result = score_one_stock(symbol, name, ohlcv, news, foreign, inst)
            if result:
                scored.append(result)
                logger.info(
                    "[%2d/%d] %s %-10s → %5.1f점",
                    idx, len(stocks), symbol, name[:10], result["composite"],
                )
    finally:
        if inv_mgr:
            await inv_mgr.__aexit__(None, None, None)
        if news_mgr:
            await news_mgr.__aexit__(None, None, None)

    # 4) 최종 후보 선별 — 섹터당 최대 MAX_PER_SECTOR종목 제한 (Fix 1)
    sector_map = _load_sector_map()
    qualified_pool = sorted(
        [s for s in scored if s["composite"] >= MIN_SCORE],
        key=lambda x: -x["composite"],
    )
    candidates = apply_sector_limit(qualified_pool, sector_map)
    save_state("selection", candidates)

    # 일별 데이터 저장 (전체 채점 결과 + 예비 후보 포함)
    today_str = datetime.now().strftime("%Y-%m-%d")
    market_info = {
        "kospi_today_pct": today_pct,
        "kospi_5d_pct":    five_d_pct,
        "filter_ok":       mf["ok"],
        "filter_reason":   mf.get("reason", ""),
        "advance_ratio":   advance_ratio,
        "regime":          regime,
        "sp500_pct":       sp_pct,
        "nasdaq_pct":      nq_pct,
        "ma20_filtered":   ma20_filtered,
        "gap_filtered":    gap_filtered,
        "value_filtered":  value_filtered,
    }
    _data_logger.log_selection(today_str, market_info, scored, candidates)
    _data_logger.log_event("selection_done", {
        "analyzed": len(scored), "qualified": len(qualified_pool), "candidates": len(candidates),
        "ma20_filtered": ma20_filtered, "gap_filtered": gap_filtered, "value_filtered": value_filtered,
        "regime": regime, "candidate_symbols": [c["symbol"] for c in candidates],
    })

    # 5) 알림 — 섹터 정보 + 채점 분포 통합 포맷
    filter_summary = (
        f"분석:{len(scored)}  거래대금제외:{value_filtered}  "
        f"MA20제외:{ma20_filtered}  갭제외:{gap_filtered}  "
        f"US ES{sp_pct:+.1f}%/NQ{nq_pct:+.1f}%"
    )
    if not candidates:
        msg = (
            f"📊 선별 완료 — 후보 없음\n"
            f"KOSPI {today_pct:+.2f}%  레짐:{regime}  양봉:{advance_ratio*100:.0f}%\n"
            f"({filter_summary}  기준 {MIN_SCORE}점 이상 없음)"
        )
        logger.info("[PHASE 1] 후보 없음")
    else:
        lines = [
            f"📊 종가배팅 후보 [{datetime.now().strftime('%m/%d %H:%M')}]",
            f"KOSPI {today_pct:+.2f}%  레짐:{regime}  양봉:{advance_ratio*100:.0f}%",
            f"{filter_summary}",
        ]
        for i, c in enumerate(candidates, 1):
            qty = calc_position_qty(c["composite"], c["current_price"])
            sector = c.get("sector", "기타")
            cat_tag = "📰" if c.get("has_catalyst") else "—"
            lines.append(
                f"{i}. {c['company_name']}({c['symbol']}) [{sector}] {cat_tag}\n"
                f"   점수 {c['composite']}  "
                f"가 {c['current_price']:,.0f}원  "
                f"수량 {qty}주"
            )
        msg = "\n".join(lines)
        logger.info("[PHASE 1] 완료 — 후보 %d종목", len(candidates))

    await notify(msg)
    return candidates


# ─── Phase 2: 매수 ──────────────────────────────────────────────────────────

async def phase_buy(
    candidates: list[dict] | None = None,
    split_pct: int = 100,
    split_label: str = "full",
) -> list[dict]:
    """trading-domain MCP로 종가 시장가 매수.

    Args:
        candidates: 매수 후보. None이면 state['selection']에서 로드.
        split_pct: 이번 회차에서 매수할 수량 비율 (1~100).
                   분할 매수 시 첫 번째는 50, 두 번째는 100 - 첫번째 실수량.
        split_label: 'full' / 'first' / 'second' — 로깅/state 키 분리용.
    """
    logger.info("=" * 60)
    logger.info("[PHASE 2:%s] 매수 시작 (split=%d%%)  %s",
                split_label, split_pct, datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)
    _data_logger.log_event("phase_start", {"phase": f"buy_{split_label}", "split_pct": split_pct})

    # #6 멱등성: 오늘 같은 매수 회차가 이미 실행됐으면 중복 주문 방지 (수동+스케줄 충돌 등).
    if _phase_done_today(f"buy_{split_label}"):
        logger.warning("[PHASE 2:%s] 오늘 이미 실행됨 — 중복 매수 차단 (CLOSING_BET_FORCE_PHASE=true 로 강제)", split_label)
        _data_logger.log_event("skip", {"reason": "already_done", "phase": f"buy_{split_label}"})
        return []

    if candidates is None:
        candidates = get_state("selection") or []
    if not candidates:
        await notify(f"⚠️ 매수 중단({split_label}): 선별된 후보 없음")
        _data_logger.log_event("skip", {"reason": "no_candidates", "phase": f"buy_{split_label}"})
        return []

    # 분할 매수: 두 번째 회차는 첫 번째에서 매수한 수량을 빼고 나머지만
    first_orders_by_symbol: dict[str, dict] = {}
    if split_label == "second":
        prev = get_state("buy_first") or []
        first_orders_by_symbol = {o["symbol"]: o for o in prev}

    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    today_str = datetime.now().strftime("%Y-%m-%d")
    orders: list[dict] = []

    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain :8030 연결 실패 — 매수 중단")
                return []

            for c in candidates:
                symbol = c["symbol"]
                # P2: 매수 직전가 — kiwoom-market 실시간가 우선(장중 정확) → pykrx 전일종가 → 선별가.
                #     pykrx 일봉은 장중 stale 라 entry_price 가 실제 체결가와 크게 어긋났음.
                live_price = await _try_get_realtime_price(symbol)
                if not (live_price and live_price > 0):
                    live_price = get_current_price(symbol)
                price = live_price if live_price and live_price > 0 else c.get("current_price", 0.0)
                if live_price and live_price != c.get("current_price", 0.0):
                    logger.info("[BUY] %s 가격 갱신: %.0f → %.0f원", symbol, c.get("current_price", 0.0), price)
                full_qty = calc_position_qty(c["composite"], price)
                if full_qty < 1:
                    continue

                # 이 회차의 매수 수량 계산
                if split_label == "first":
                    qty = max(1, int(full_qty * split_pct / 100))
                elif split_label == "second":
                    prev_qty = first_orders_by_symbol.get(symbol, {}).get("quantity", 0)
                    qty = max(0, full_qty - prev_qty)
                    if qty == 0:
                        logger.info("[BUY:second] %s 잔여 수량 없음 — 스킵", symbol)
                        continue
                else:  # full
                    qty = full_qty

                try:
                    raw = await mcp.call_tool("place_buy_order", {
                        "stock_code": symbol,
                        "quantity":   qty,
                        "price":      None,
                        "order_type": "03",   # 시장가
                        "account_no": ACCOUNT_NO,
                    })
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    # #3: 주문 수락(return_code 0) 확인 — 거부 시 유령 포지션 방지.
                    ok, _ = _order_accepted(parsed)
                    if not ok:
                        label, msg = _log_order_reject(
                            f"buy_{split_label}", symbol,
                            {"qty": qty, "order_type": "03(시장가)", "price": price, "account": ACCOUNT_NO[:4] + "****"},
                            parsed,
                        )
                        await notify(f"❌ 매수 거부 {c['company_name']}({symbol})\n[{label}]\n{msg[:100]}")
                        continue
                    # P2: 응답에 실체결가가 있으면 entry 로 사용 (없으면 매수 직전 실시간가 유지).
                    fill_price = _extract_fill_price(parsed)
                    entry_price = fill_price if fill_price and fill_price > 0 else price
                    if fill_price and abs(fill_price - price) > 0.01:
                        logger.info("[BUY] %s 체결가 반영: %.0f → %.0f원", symbol, price, entry_price)
                    # (a)+(c) 트레일 손절·보유기간 상태 초기화
                    atr = float(c.get("atr", 0.0) or 0.0)
                    stop0 = init_stop_price(entry_price, atr, ATR_K, STOP_LOSS_PCT)
                    orders.append({
                        "symbol":       symbol,
                        "company_name": c["company_name"],
                        "quantity":     qty,
                        "entry_price":  entry_price,
                        "composite":    c["composite"],
                        "sector":       c.get("sector", "기타"),
                        "buy_date":     today_str,
                        "split":        split_label,
                        "atr":          atr,
                        "stop_price":   round(stop0, 2),
                        "peak_price":   entry_price,
                        "sell_after":   _add_business_days(today_str, HOLD_DAYS),
                        "order_result": parsed,
                    })
                    logger.info(
                        "[BUY:%s] %s %-10s  %d주 @ %s원  %s",
                        split_label, symbol, c["company_name"][:10], qty, entry_price, mode_tag,
                    )
                    _data_logger.log_event("buy", {
                        "symbol": symbol, "name": c["company_name"], "qty": qty,
                        "price": entry_price, "composite": c["composite"],
                        "sector": c.get("sector", "기타"), "mock": MOCK_MODE,
                        "split": split_label,
                    })
                except Exception as e:
                    logger.error("[BUY:%s] %s 주문 실패: %s", split_label, symbol, e)
                    _data_logger.log_event("error", {
                        "phase": f"buy_{split_label}", "symbol": symbol, "error": str(e)[:200],
                    })

    except Exception as e:
        logger.error("[BUY:%s] trading-domain 연결 오류: %s", split_label, e)
        await notify(f"❌ 매수 오류({split_label}): {e}")
        return []

    # state 누적: positions = 평단·총 수량 통합 (first + second)
    if split_label == "second":
        prev = get_state("buy_first") or []
        merged = _merge_split_orders(prev, orders)
        save_state("positions", merged)
        save_state("buy", merged)
    elif split_label == "first":
        save_state("buy_first", orders)
        save_state("positions", orders)  # 임시 (second가 덮어씀)
    else:  # full
        save_state("positions", orders)
        save_state("buy", orders)

    save_state("buy_date", today_str)
    if orders:
        _mark_phase_done(f"buy_{split_label}")   # #6: 실주문 발생 시에만 완료 표시 (0건이면 재시도 허용)
    _data_logger.log_buy(today_str, orders if split_label != "second" else (get_state("buy") or orders), MOCK_MODE)

    if orders:
        total = sum(o["quantity"] * o["entry_price"] for o in orders)
        lines = [f"✅ 종가매수 완료 {mode_tag} [{datetime.now().strftime('%m/%d %H:%M')}]"]
        for o in orders:
            sector = o.get("sector", "기타")
            lines.append(
                f"• {o['company_name']}({o['symbol']}) [{sector}]\n"
                f"   {o['quantity']}주 @ {o['entry_price']:,.0f}원  점수 {o['composite']}"
            )
        lines.append(f"총 투자금액 {total:,.0f}원")
        await notify("\n".join(lines))
    else:
        await notify(f"⚠️ 매수된 종목 없음 {mode_tag}")

    logger.info("[PHASE 2] 완료 — %d건 주문", len(orders))
    return orders


# ─── Phase 2-b: 시간외 확인 ────────────────────────────────────────────────

async def phase_after_hours(positions: list[dict] | None = None) -> None:
    """18:05 — 시간외 단일가로 트레일링 스톱을 갱신(상방만)하고 현황 알림.

    (a)+(c) 모델에서 실제 매도는 09:00/15:10 phase 가 담당한다. 여기선 시간외 고가를
    반영해 trailing stop 을 끌어올리고(peak/stop 갱신) 상태를 저장만 한다.
    """
    logger.info("=" * 60)
    logger.info("[PHASE AH] 시간외 확인  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)
    _data_logger.log_event("phase_start", {"phase": "after_hours"})

    if positions is None:
        positions = get_state("positions") or []
    if not positions:
        logger.info("[PHASE AH] 보유 포지션 없음 — 스킵")
        return

    updated: list[dict] = []
    lines = [f"🌙 시간외 확인 [{datetime.now().strftime('%m/%d %H:%M')}]"]
    for pos in positions:
        symbol      = pos["symbol"]
        entry_price = float(pos.get("entry_price", 0))
        name        = pos.get("company_name", symbol)
        atr         = float(pos.get("atr", 0.0) or 0.0)
        peak        = float(pos.get("peak_price", entry_price) or entry_price)
        stop        = float(pos.get("stop_price", 0.0) or 0.0)

        ah_price = await _try_get_after_hours_price(symbol)
        if ah_price is None:
            updated.append(pos)
            continue

        new_peak, new_stop = ratchet_stop(entry_price, peak, stop, ah_price, atr, ATR_K, STOP_LOSS_PCT)
        pos = {**pos, "peak_price": round(new_peak, 2), "stop_price": round(new_stop, 2)}
        updated.append(pos)
        pnl_pct = round((ah_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0
        icon = "🟢" if pnl_pct > 0 else ("🔴" if ah_price <= new_stop else "⚪")
        lines.append(f"{icon} {name}({symbol})  시간외:{ah_price:,.0f}  {pnl_pct:+.2f}%  stop:{new_stop:,.0f}")
        _data_logger.log_event("after_hours", {
            "symbol": symbol, "name": name, "ah_price": ah_price,
            "entry_price": entry_price, "pnl_pct": pnl_pct, "stop_price": round(new_stop, 2),
        })

    save_state("positions", updated)   # 갱신된 trailing stop 저장
    await notify("\n".join(lines))
    logger.info("[PHASE AH] 완료 — %d종목 트레일 갱신", len(updated))


# ─── Phase 3: 매도 (다일 보유 + ATR 트레일) ─────────────────────────────────────

async def _sell_market(mcp: Any, symbol: str, sell_qty: int) -> Any:
    """trading-domain 시장가 매도 1건. 파싱된 응답 반환. 예외는 호출자에 전파."""
    raw = await mcp.call_tool("place_sell_order", {
        "stock_code": symbol,
        "quantity":   sell_qty,
        "price":      None,
        "order_type": "03",   # 시장가
        "account_no": ACCOUNT_NO,
    })
    return json.loads(raw) if isinstance(raw, str) else raw


async def _manage_position(
    mcp: Any, pos: dict, exit_date: str, today: str, allow_time_exit: bool, when_label: str,
) -> tuple[str, Any]:
    """포지션 1건 평가: 트레일 갱신 → 손절/시간청산이면 전량 매도(원장 기록), 아니면 갱신본 유지.

    Returns:
      ("sold", pnl_pct)     — 전량 청산 완료 (원장/이벤트 기록됨)
      ("keep", updated_pos) — 보유 지속 (갱신된 peak/stop)
    """
    symbol      = pos["symbol"]
    entry_price = float(pos.get("entry_price", 0))
    qty         = int(pos.get("quantity", 0))
    name        = pos.get("company_name", symbol)
    atr         = float(pos.get("atr", 0.0) or 0.0)
    peak        = float(pos.get("peak_price", entry_price) or entry_price)
    stop        = float(pos.get("stop_price", 0.0) or 0.0)

    current = await _try_get_realtime_price(symbol)
    if current is None:
        current = get_current_price(symbol) or entry_price

    new_peak, new_stop = ratchet_stop(entry_price, peak, stop, current, atr, ATR_K, STOP_LOSS_PCT)
    # sell_after 누락(레거시 포지션) 시 15:10 에 즉시 만기 처리 — 무한 이월 방지.
    aged = allow_time_exit and (not pos.get("sell_after") or today >= pos["sell_after"])
    dec = evaluate_hold_exit(entry_price, current, new_stop, aged)
    pnl_pct = round((current - entry_price) / entry_price * 100, 2) if entry_price else 0.0

    if dec.action == "HOLD":
        logger.info("[%s] %s %-10s  HOLD  손익=%+.2f%%  stop=%.0f",
                    when_label, symbol, name[:10], pnl_pct, new_stop)
        return ("keep", {**pos, "peak_price": round(new_peak, 2), "stop_price": round(new_stop, 2)})

    if qty < 1:
        return ("sold", pnl_pct)
    try:
        resp = await _sell_market(mcp, symbol, qty)
        # #3: 매도 수락(return_code 0) 확인 — 거부 시 포지션 유지(미실현), 다음 기회 재시도.
        ok, _ = _order_accepted(resp)
        if not ok:
            label, msg = _log_order_reject(
                f"sell_{when_label}", symbol,
                {"qty": qty, "order_type": "03(시장가)", "side": "sell", "account": ACCOUNT_NO[:4] + "****"},
                resp,
            )
            await notify(f"❌ 매도 거부 {name}({symbol})\n[{label}]\n{msg[:100]} (보유 유지·재시도)")
            return ("keep", {**pos, "peak_price": round(new_peak, 2), "stop_price": round(new_stop, 2)})
        _append_exit(exit_date, {
            "symbol": symbol, "company_name": name, "entry_price": entry_price,
            "qty": qty, "exit_price": current,
            "composite": pos.get("composite", 0.0), "sector": pos.get("sector", "기타"),
            "reason": dec.reason, "when": when_label,
        })
        _data_logger.log_event("sell", {
            "symbol": symbol, "name": name, "action": dec.action,
            "qty": qty, "entry_price": entry_price, "exit_price": current,
            "pnl_pct": pnl_pct, "reason": dec.reason,
            "composite": pos.get("composite", 0.0), "mock": MOCK_MODE,
        })
        logger.info("[%s] %s %-10s  SELL_ALL  손익=%+.2f%%  (%s)",
                    when_label, symbol, name[:10], pnl_pct, dec.reason)
        return ("sold", pnl_pct)
    except Exception as e:
        logger.error("[%s] %s 매도 실패: %s", when_label, symbol, e)
        _data_logger.log_event("error", {"phase": when_label, "symbol": symbol, "error": str(e)[:200]})
        return ("keep", {**pos, "peak_price": round(new_peak, 2), "stop_price": round(new_stop, 2)})


def _entry_date_label(positions: list[dict]) -> str:
    """보유 포지션들의 최소 buy_date (다일 보유라 진입일이 섞일 수 있음)."""
    dates = [p.get("buy_date") for p in positions if p.get("buy_date")]
    return min(dates) if dates else (get_state("buy_date") or
                                     (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))


async def phase_sell(positions: list[dict] | None = None) -> None:
    """매 영업일 09:00 — 보유 전 종목의 트레일/손절 청산만 평가 (시간청산은 15:10).

    (a)+(c): 우측꼬리를 잡기 위해 부분 익절 없이 트레일링 스톱 이탈 시에만 전량 청산하고,
    그렇지 않으면 보유를 지속한다(최대 HOLD_DAYS 영업일). 보유분은 갱신된 stop 으로 유지.
    """
    logger.info("=" * 60)
    logger.info("[PHASE 3] 청산 판단(09:00) 시작  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)
    _data_logger.log_event("phase_start", {"phase": "sell"})

    if positions is None:
        positions = get_state("positions") or []
    if not positions:
        await notify("ℹ️ 청산: 보유 포지션 없음")
        _data_logger.log_event("skip", {"reason": "no_positions", "phase": "sell"})
        return

    mode_tag   = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    today      = datetime.now().strftime("%Y-%m-%d")
    exit_date  = today
    entry_date = _entry_date_label(positions)
    _ensure_exit_ledger(exit_date)
    remaining: list[dict] = []
    sold = 0

    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain :8030 연결 실패 — 청산 중단")
                return
            for pos in positions:
                status, payload = await _manage_position(
                    mcp, pos, exit_date, today, allow_time_exit=False, when_label="09:00",
                )
                if status == "keep":
                    remaining.append(payload)
                else:
                    sold += 1
    except Exception as e:
        logger.error("[SELL] 오류: %s", e)
        await notify(f"❌ 청산 오류: {e}")
        return

    save_state("positions", remaining)
    results = _finalize_sell_log(entry_date, exit_date) if sold else _aggregate_exits(exit_date)
    if sold:
        save_state("sell", results)

    lines = [f"📤 청산(09:00) {mode_tag} [{datetime.now().strftime('%m/%d %H:%M')}]"]
    if sold:
        for r in results:
            icon = "🟢" if r["pnl_pct"] > 0 else "🔴"
            lines.append(f"{icon} {r['company_name']}({r['symbol']})  실현 {r['pnl_pct']:+.2f}%")
    else:
        lines.append("트레일 이탈 없음 — 전량 보유 지속")
    if remaining:
        lines.append(f"\n⏳ 보유 {len(remaining)}종목 (트레일 유지, 만기 15:10 시간청산): "
                     f"{', '.join(p['symbol'] for p in remaining)}")
    await notify("\n".join(lines))
    logger.info("[PHASE 3] 완료 — 청산:%d종목  보유지속:%d종목", sold, len(remaining))


# ─── Phase 3-b: 시간청산 + 트레일 (매 영업일 15:10) ──────────────────────────────

async def phase_force_close(positions: list[dict] | None = None) -> None:
    """매 영업일 15:10 — 트레일 이탈분 청산 + 보유기간(HOLD_DAYS) 만기분 시간청산.

    (a): 만기에 도달하지 않은 포지션은 청산하지 않고 다음 영업일로 이월(트레일 유지).
    따라서 force_close 는 더 이상 '전량 청산'이 아니라 'aged-out + 트레일 이탈'만 정리한다.
    """
    logger.info("=" * 60)
    logger.info("[PHASE FC] 시간청산/트레일(15:10)  %s", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 60)
    _data_logger.log_event("phase_start", {"phase": "force_close"})

    if positions is None:
        positions = get_state("positions") or []

    today      = datetime.now().strftime("%Y-%m-%d")
    exit_date  = today
    entry_date = _entry_date_label(positions) if positions else \
        (get_state("buy_date") or today)

    if not positions:
        logger.info("[PHASE FC] 보유 포지션 없음")
        _finalize_sell_log(entry_date, exit_date)
        return

    _ensure_exit_ledger(exit_date)
    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    remaining: list[dict] = []
    sold = 0

    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain :8030 연결 실패 — 청산 중단")
                return
            for pos in positions:
                status, payload = await _manage_position(
                    mcp, pos, exit_date, today, allow_time_exit=True, when_label="15:10",
                )
                if status == "keep":
                    remaining.append(payload)
                else:
                    sold += 1
    except Exception as e:
        logger.error("[FC] 오류: %s", e)
        await notify(f"❌ 청산 오류: {e}")
        return

    save_state("positions", remaining)   # 만기 미도달분만 이월
    results = _finalize_sell_log(entry_date, exit_date)
    save_state("sell", results)

    lines = [f"🧹 시간청산/트레일(15:10) {mode_tag} [{datetime.now().strftime('%m/%d %H:%M')}]  청산 {sold}종목"]
    for r in results:
        icon = "🟢" if r["pnl_pct"] > 0 else "🔴"
        lines.append(f"{icon} {r['company_name']}({r['symbol']})  실현 {r['pnl_pct']:+.2f}%")
    if results:
        wins = sum(1 for r in results if r["pnl_pct"] > 0)
        lines.append(f"\n📊 당일 실현 {len(results)}종목  승률(net) {wins/len(results)*100:.0f}%")
    if remaining:
        lines.append(f"⏭ 이월 {len(remaining)}종목 (보유기간 미만기): {', '.join(p['symbol'] for p in remaining)}")
    await notify("\n".join(lines))
    logger.info("[PHASE FC] 완료 — 청산:%d  이월:%d  실현합산:%d종목", sold, len(remaining), len(results))

    # #2: 실계좌 보유분 대조 — state 가 잊은 고아 포지션 회수 (15:10 청산 직후)
    await phase_reconcile()


# ─── Phase 3-c: 장중 트레일 점검 (#1 — 일중 손절 이탈 포착) ──────────────────────

async def phase_intraday_stop() -> None:
    """정규장 중 주기적으로 보유분의 트레일 스톱을 갱신하고 이탈 시 청산.

    백테스트는 일중 저가로 손절 이탈을 잡는데 라이브는 관측 시점에만 가격을 보므로,
    데몬이 장중 INTRADAY_POLL_MIN 주기로 이 함수를 호출해 간극을 줄인다.
    시간청산은 하지 않는다(15:10 force_close 담당). 매도가 발생할 때만 알림/기록한다.
    """
    positions = get_state("positions") or []
    if not positions:
        return

    today      = datetime.now().strftime("%Y-%m-%d")
    exit_date  = today
    entry_date = _entry_date_label(positions)
    _ensure_exit_ledger(exit_date)
    remaining: list[dict] = []
    sold = 0

    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                logger.warning("[INTRADAY] trading-domain 연결 실패 — 점검 스킵")
                return
            for pos in positions:
                status, payload = await _manage_position(
                    mcp, pos, exit_date, today, allow_time_exit=False, when_label="intraday",
                )
                if status == "keep":
                    remaining.append(payload)
                else:
                    sold += 1
    except Exception as e:
        logger.error("[INTRADAY] 오류: %s", e)
        return

    # 갱신된 트레일 스톱(remaining)은 항상 저장 — 매도 없어도 stop 래칫 보존
    save_state("positions", remaining)
    if sold:
        results = _finalize_sell_log(entry_date, exit_date)
        save_state("sell", results)
        lines = [f"📉 장중 트레일 청산 [{datetime.now().strftime('%m/%d %H:%M')}]  {sold}종목"]
        for r in results:
            icon = "🟢" if r["pnl_pct"] > 0 else "🔴"
            lines.append(f"{icon} {r['company_name']}({r['symbol']})  실현 {r['pnl_pct']:+.2f}%")
        await notify("\n".join(lines))
        logger.info("[INTRADAY] 트레일 청산 %d종목, 보유 %d종목", sold, len(remaining))


# ─── #2 Reconciliation: 실계좌 보유분 ↔ 봇 state 대조 ──────────────────────────

async def _get_broker_holdings() -> list[dict] | None:
    """portfolio-domain(get_account_evaluation, kt00004)로 실계좌 보유종목 조회.

    Returns: [{symbol(6자리), name, qty, avg_price}] / 조회 실패 시 None(=대조 스킵, 안전).
    """
    try:
        async with MCPManager({"portfolio-domain": PORTFOLIO_URL}) as mcp:
            if not mcp.tools:
                return None
            tool = next((t["name"] for t in mcp.tools if "evaluation" in t["name"].lower()), None)
            if not tool:
                return None
            raw = await mcp.call_tool(tool, {})
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            d = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
            if not isinstance(d, dict) or d.get("return_code") not in (0, "0", None):
                return None
            rows = d.get("stk_acnt_evlt_prst") or []
            holdings = []
            for r in rows:
                code = str(r.get("stk_cd", "")).lstrip("A").strip()
                try:
                    qty = int(str(r.get("rmnd_qty", "0")).lstrip("0") or "0")
                except ValueError:
                    qty = 0
                if not code or qty <= 0:
                    continue
                try:
                    avg = float(str(r.get("avg_prc", "0")).lstrip("0") or "0")
                except ValueError:
                    avg = 0.0
                holdings.append({"symbol": code, "name": r.get("stk_nm", code), "qty": qty, "avg_price": avg})
            return holdings
    except Exception as e:
        logger.warning("[RECONCILE] 보유분 조회 실패 — 대조 스킵: %s", str(e)[:120])
        return None


def _bot_history_symbols() -> set[str]:
    """봇이 과거에 매수한 적 있는 종목코드 집합 (data/closing_bet/*/buy.json)."""
    syms: set[str] = set()
    for buy_file in DATA_DIR.glob("????-??-??/buy.json"):
        try:
            d = json.loads(buy_file.read_text(encoding="utf-8"))
            for o in d.get("orders", []):
                if o.get("symbol"):
                    syms.add(str(o["symbol"]))
        except Exception:
            continue
    return syms


async def phase_reconcile() -> None:
    """실계좌 보유분을 state 와 대조 — 봇이 잊은 고아 포지션을 청산, 미지 보유분은 알림.

    state 가 유실되거나(과거 %TEMP%) 청산 누락으로 봇이 추적 못 하는 보유분을 잡는다.
    안전장치: 자동 청산은 '봇 매수이력에 있는' 종목만. 그 외 보유분은 절대 건드리지 않고 알림만.
    """
    if not RECONCILE:
        return
    holdings = await _get_broker_holdings()
    if holdings is None:
        return  # 조회 실패 → 안전하게 스킵

    tracked = {p["symbol"] for p in (get_state("positions") or [])}
    bot_syms = _bot_history_symbols()
    orphans = [h for h in holdings if h["symbol"] not in tracked and h["symbol"] in bot_syms]
    unknown = [h for h in holdings if h["symbol"] not in tracked and h["symbol"] not in bot_syms]

    if not orphans and not unknown:
        return
    logger.info("[RECONCILE] 보유 %d  추적 %d  고아 %d  미지 %d",
                len(holdings), len(tracked), len(orphans), len(unknown))

    # 미지 보유분 — 봇 소관 아님(수동 매수 등). 절대 자동 청산하지 않고 알림만.
    if unknown:
        await notify("ℹ️ 미추적 보유분(봇 매수이력 없음 — 수동 확인):\n" +
                     "\n".join(f"• {h['name']}({h['symbol']}) {h['qty']}주" for h in unknown))

    if not orphans:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    _ensure_exit_ledger(today)
    mode_tag = "🧪 MOCK" if MOCK_MODE else "💰 REAL"
    closed = 0
    try:
        async with MCPManager({"trading-domain": TRADING_URL}) as mcp:
            if not mcp.tools:
                await notify("❌ trading-domain 연결 실패 — 고아 청산 보류")
                return
            for h in orphans:
                symbol, qty, entry = h["symbol"], h["qty"], h["avg_price"]
                cur = await _try_get_realtime_price(symbol) or get_current_price(symbol) or entry
                try:
                    resp = await _sell_market(mcp, symbol, qty)
                    ok, _ = _order_accepted(resp)
                    if not ok:
                        _log_order_reject("reconcile", symbol,
                                          {"qty": qty, "side": "sell", "reason": "orphan"}, resp)
                        continue
                    _append_exit(today, {
                        "symbol": symbol, "company_name": h["name"], "entry_price": entry,
                        "qty": qty, "exit_price": cur, "composite": 0.0, "sector": "기타",
                        "reason": "고아 포지션 청산 (state 미추적 보유분)", "when": "reconcile",
                    })
                    _data_logger.log_event("reconcile_close", {
                        "symbol": symbol, "name": h["name"], "qty": qty,
                        "entry_price": entry, "exit_price": cur, "mock": MOCK_MODE,
                    })
                    closed += 1
                    logger.info("[RECONCILE] 고아 청산 %s %s %d주 (평단 %.0f)", symbol, h["name"], qty, entry)
                except Exception as e:
                    logger.error("[RECONCILE] %s 청산 오류: %s", symbol, e)
    except Exception as e:
        logger.error("[RECONCILE] 오류: %s", e)
        return

    if closed:
        results = _finalize_sell_log(_entry_date_label(get_state("positions") or []) or today, today)
        save_state("sell", results)
        await notify(f"🧹 고아 포지션 청산 {mode_tag} — {closed}종목 (state 미추적분 회수)")


# ─── 즉시 테스트 (선별만) ───────────────────────────────────────────────────

async def run_test() -> None:
    """선별 단계만 즉시 실행 (주문 없음). 종목 데이터와 채점 결과를 검증합니다."""
    print("\n" + "=" * 60)
    print("[TEST] 종가배팅 선별 즉시 테스트 (주문 없음)")
    print("주의: 장 시간 외 실행 — 전일 기준 데이터가 사용됩니다.")
    print("=" * 60 + "\n")

    candidates = await phase_selection()

    print("\n" + "=" * 60)
    if candidates:
        print(f"[TEST] 선별 완료 — 후보 {len(candidates)}종목")
        for c in candidates:
            qty = calc_position_qty(c["composite"], c["current_price"])
            print(
                f"  {c['symbol']} {c['company_name']:<12} "
                f"점수:{c['composite']:5.1f}  "
                f"현재가:{c['current_price']:>8,.0f}원  "
                f"예상수량:{qty}주"
            )
    else:
        print("[TEST] 선별 완료 — 후보 없음")
    print(f"상태 파일: {STATE_FILE}")
    print("매수 테스트: python scripts/direct_closing_bet.py --phase buy")
    print("=" * 60)


# ─── 스케줄러 데몬 ─────────────────────────────────────────────────────────

def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5  # 0=월 ~ 4=금


def _is_market_hours(dt: datetime) -> bool:
    """정규장 트레일 점검 구간 (영업일 09:00~15:10). 15:10 이후는 force_close가 담당."""
    if not _is_weekday(dt):
        return False
    minutes = dt.hour * 60 + dt.minute
    return 9 * 60 <= minutes <= 15 * 60 + 10


def _next_run_time(hour: int, minute: int, base: datetime | None = None) -> datetime:
    """지정 시각의 다음 실행 시간 (주말 스킵)."""
    now = base or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while not _is_weekday(target):
        target += timedelta(days=1)
    return target


async def scheduler_daemon() -> None:
    """14:50 선별 → 15:20 매수 → 다음날 09:00 청산을 매 거래일 자동 반복."""
    logger.info("=" * 60)
    logger.info("[DAEMON] 종가매매 스케줄러 시작")
    logger.info("  14:50 선별 / 15:15·15:19 매수 / 18:05 시간외 / 09:00 청산 / 15:10 잔량 강제청산 (다음날)")
    logger.info("  Ctrl+C 로 종료  |  MOCK_MODE=%s", MOCK_MODE)
    logger.info("=" * 60)

    # #6: 단일 인스턴스 보장 — 이미 다른 데몬이 돌고 있으면 즉시 종료 (이중 주문 방지).
    if not acquire_daemon_lock():
        await notify("⚠️ 데몬 중복 기동 차단 — 이미 실행 중인 인스턴스가 있습니다.")
        return

    await notify(
        f"🚀 종가매매 데몬 시작\n"
        f"{'🧪 MOCK 모의투자' if MOCK_MODE else '💰 실거래'}\n"
        f"14:50 선별 / 15:15 매수1차 / 15:19 매수2차 / 18:05 시간외 / 09:00 청산 / 15:10 잔량 강제청산"
    )

    phase_funcs = {
        "selection":   lambda: phase_selection(),
        "buy":         lambda: phase_buy(),
        "buy_first":   lambda: phase_buy(split_pct=50, split_label="first"),
        "buy_second":  lambda: phase_buy(split_pct=100, split_label="second"),
        "after_hours": lambda: phase_after_hours(),
        "sell":        lambda: phase_sell(),
        "force_close": lambda: phase_force_close(),
    }

    while True:
        now = datetime.now()

        if not _is_weekday(now):
            monday = now
            while not _is_weekday(monday):
                monday = (monday + timedelta(days=1)).replace(
                    hour=9, minute=0, second=0, microsecond=0
                )
            wait_sec = (monday - now).total_seconds()
            logger.info(
                "[DAEMON] 주말 — 월요일 %s까지 대기 (%.0f분)",
                monday.strftime("%m/%d %H:%M"), wait_sec / 60,
            )
            await asyncio.sleep(min(wait_sec, 1800))
            continue

        schedule_items = [
            (_next_run_time(h, m), phase) for h, m, phase in SCHEDULE
        ]
        schedule_items.sort(key=lambda x: x[0])
        next_dt, next_phase = schedule_items[0]
        wait_sec = (next_dt - now).total_seconds()

        logger.info(
            "[DAEMON] 다음: %-10s @ %s (%.0f분 후)",
            next_phase, next_dt.strftime("%m/%d %H:%M"), wait_sec / 60,
        )

        while wait_sec > 0:
            # #1: 보유분이 있고 정규장 시간이면 INTRADAY_POLL_MIN 주기로 트레일 점검.
            has_positions = bool(get_state("positions"))
            poll_cap = INTRADAY_POLL_MIN * 60 if (has_positions and _is_market_hours(datetime.now())) else 1800
            sleep_time = min(wait_sec, poll_cap)
            await asyncio.sleep(sleep_time)
            wait_sec -= sleep_time
            now2 = datetime.now()
            if get_state("positions") and _is_market_hours(now2) and now2 < next_dt:
                try:
                    await phase_intraday_stop()
                except Exception as e:
                    logger.error("[DAEMON] 장중 트레일 점검 오류: %s", e)
            if wait_sec > 60:
                logger.info("[DAEMON] %s까지 %.0f분 남음", next_phase, wait_sec / 60)

        if _is_weekday(datetime.now()):
            logger.info("[DAEMON] %s 실행", next_phase)
            try:
                await phase_funcs[next_phase]()
            except Exception as e:
                logger.error("[DAEMON] %s 오류: %s", next_phase, e, exc_info=True)
                await notify(f"❌ {next_phase} 실행 오류: {e}")
        else:
            logger.info("[DAEMON] %s 스킵 (거래일 아님)", next_phase)


# ─── 상태 출력 ─────────────────────────────────────────────────────────────

def print_status() -> None:
    state = load_state()
    if not state:
        print("상태 파일 없음 (아직 실행 전)")
        return

    print(f"\n=== 종가매매 상태 [업데이트: {state.get('last_updated', '?')}] ===")
    print(f"상태 파일: {STATE_FILE}")

    sel_entry = state.get("selection", {})
    candidates: list = sel_entry.get("content", []) if sel_entry else []
    if candidates:
        print(f"\n  [선별  {sel_entry.get('timestamp', '')[:16]}]  {len(candidates)}종목")
        for c in candidates:
            print(f"    • {c.get('company_name', '')}({c.get('symbol', '')})  점수:{c.get('composite', 0)}")
    else:
        print("\n  [선별] 없음")

    pos_entry = state.get("positions", {})
    positions: list = pos_entry.get("content", []) if pos_entry else []
    if positions:
        print(f"\n  [포지션  {pos_entry.get('timestamp', '')[:16]}]  {len(positions)}개 보유")
        for p in positions:
            print(
                f"    • {p.get('company_name', '')}({p.get('symbol', '')})  "
                f"{p.get('quantity', 0)}주 @ {p.get('entry_price', 0):,.0f}원"
            )
    else:
        print("\n  [포지션] 없음")

    now = datetime.now()
    print("\n  다음 예정 실행:")
    for h, m, phase in SCHEDULE:
        nt = _next_run_time(h, m)
        diff = nt - now
        hrs, rem = divmod(int(diff.total_seconds()), 3600)
        mins = rem // 60
        print(f"    {phase:10} → {nt.strftime('%m/%d %H:%M')} ({hrs}시간 {mins}분 후)")


# ─── 내역 조회 ─────────────────────────────────────────────────────────────

def print_history(days: int = 7) -> None:
    """최근 N일 선별·매수·청산 내역 출력."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"\n=== 최근 {days}일 종가배팅 내역 ===")
    found = False
    for day_dir in sorted(DATA_DIR.glob("????-??-??"), reverse=True):
        if day_dir.name < since:
            continue
        print(f"\n── {day_dir.name} ──")
        sel_file = day_dir / "selection.json"
        if sel_file.exists():
            try:
                d = json.loads(sel_file.read_text(encoding="utf-8"))
                mkt   = d.get("market", {})
                stats = d.get("stats", {})
                print(
                    f"  [선별] KOSPI {mkt.get('kospi_today_pct', 0):+.2f}%  "
                    f"필터:{'OK' if mkt.get('filter_ok') else 'NG'}  "
                    f"분석:{stats.get('analyzed_count', 0)}종목  "
                    f"후보:{len(d.get('candidates', []))}종목"
                )
                for c in d.get("candidates", []):
                    print(
                        f"    → {c.get('company_name', '')}"
                        f"({c.get('symbol', '')})  "
                        f"점수:{c.get('composite', 0):.1f}  "
                        f"기술:{c.get('technical_composite', 0):.1f}  "
                        f"카탈:{c.get('catalyst_score', 0):.1f}"
                    )
                # 예비 후보 (후보 선정에서 탈락한 종목)
                reserves = [
                    s for s in d.get("all_scored", [])
                    if s.get("composite", 0) >= MIN_SCORE
                    and s["symbol"] not in {c["symbol"] for c in d.get("candidates", [])}
                ]
                if reserves:
                    print(f"  [예비] {len(reserves)}종목 (기준 통과, 순위 탈락)")
                    for s in reserves[:5]:
                        print(f"    ·  {s.get('company_name', '')}({s.get('symbol', '')})  점수:{s.get('composite', 0):.1f}")
                found = True
            except Exception:
                pass
        buy_file = day_dir / "buy.json"
        if buy_file.exists():
            try:
                d = json.loads(buy_file.read_text(encoding="utf-8"))
                mode = "MOCK" if d.get("mock_mode") else "REAL"
                print(
                    f"  [매수] {mode}  {len(d.get('orders', []))}종목  "
                    f"투자금:{d.get('total_invested', 0):,.0f}원"
                )
                found = True
            except Exception:
                pass
        sell_file = day_dir / "sell.json"
        if sell_file.exists():
            try:
                d = json.loads(sell_file.read_text(encoding="utf-8"))
                s    = d.get("summary", {})
                mode = "MOCK" if d.get("mock_mode") else "REAL"
                print(
                    f"  [청산] {mode}  {s.get('total_trades', 0)}건  "
                    f"승률:{s.get('win_rate', 0):.1f}%  "
                    f"평균P&L:{s.get('avg_pnl_pct', 0):+.2f}%"
                )
                for r in d.get("results", []):
                    if r.get("action") == "HOLD":
                        continue
                    icon = "🟢" if r.get("pnl_pct", 0) > 0 else "🔴"
                    print(
                        f"    {icon} {r.get('company_name', '')}({r.get('symbol', '')})  "
                        f"{r.get('action', '')}  {r.get('pnl_pct', 0):+.2f}%"
                        + (f"  {r.get('pnl_amount', 0):+,.0f}원" if "pnl_amount" in r else "")
                    )
                found = True
            except Exception:
                pass
    if not found:
        print(f"  기록 없음 (데이터 디렉토리: {DATA_DIR})")
    print()


# ─── 진입점 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="종가매매 자동화 — Claude Agent / Anthropic API 불필요",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--phase",
        choices=["selection", "buy", "buy_first", "buy_second", "sell", "after_hours", "force_close", "intraday_stop", "reconcile"],
        help="단발 실행 단계",
    )
    group.add_argument("--test",    action="store_true", help="즉시 테스트 (선별만, 주문 없음)")
    group.add_argument("--daemon",  action="store_true", help="스케줄러 데몬")
    group.add_argument("--status",  action="store_true", help="상태 확인")
    group.add_argument("--analyze", nargs="?", const=30, type=int, metavar="DAYS",
                       help="최근 N일 성과 분석 (기본: 30일)")
    group.add_argument("--history", nargs="?", const=7,  type=int, metavar="DAYS",
                       help="최근 N일 거래 내역 조회 (기본: 7일)")

    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.analyze is not None:
        print(_data_logger.analyze(args.analyze))
    elif args.history is not None:
        print_history(args.history)
    elif args.test:
        asyncio.run(run_test())
    elif args.daemon:
        try:
            asyncio.run(scheduler_daemon())
        except KeyboardInterrupt:
            logger.info("[DAEMON] 종료")
        finally:
            release_daemon_lock()   # #6: 자기 PID 락만 해제
    elif args.phase == "selection":
        asyncio.run(phase_selection())
    elif args.phase == "buy":
        asyncio.run(phase_buy())
    elif args.phase == "buy_first":
        asyncio.run(phase_buy(split_pct=50, split_label="first"))
    elif args.phase == "buy_second":
        asyncio.run(phase_buy(split_pct=100, split_label="second"))
    elif args.phase == "sell":
        asyncio.run(phase_sell())
    elif args.phase == "after_hours":
        asyncio.run(phase_after_hours())
    elif args.phase == "force_close":
        asyncio.run(phase_force_close())
    elif args.phase == "intraday_stop":
        asyncio.run(phase_intraday_stop())
    elif args.phase == "reconcile":
        asyncio.run(phase_reconcile())
