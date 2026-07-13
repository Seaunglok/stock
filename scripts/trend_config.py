"""추세추종 데몬 공유 설정 — .env 로드 + 상수 + 로거 (scripts/trend_config.py).

trend_follow.py / trend_kiwoom_io.py 가 공유. import 시 .env 로드 + 로깅 설정 1회.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 네트워크 stall 방어(2026-07-02 08:50 screen hang → entry 누락 재발방지):
# pykrx/DART 등 동기 네트워크 호출이 무한 hang 되면 async 데몬 전체가 얼어붙는다.
# 소켓 read 30s 초과 시 예외 → 기존 try/except 가 graceful skip(종목 스킵/폴백). async httpx(MCP)는 자체 타임아웃 사용해 영향 없음.
socket.setdefaulttimeout(30)

_ROOT = Path(__file__).resolve().parents[1]   # scripts/trend_config.py → repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.mcp_servers.trend_mcp.signals import TrendConfig  # noqa: E402


def _load_env() -> None:
    env = _ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()

# 외부 라이브러리 로그 억제
logging.Handler.handleError = lambda self, record: None  # noqa: E731
for _n in ("pykrx", "pykrx.website", "FinanceDataReader", "requests", "urllib3", "httpx"):
    logging.getLogger(_n).setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.WARNING)

# ─── 설정 ──────────────────────────────────────────────────────────────────
ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "")
# 라벨은 MCP 서버의 KIWOOM_PRODUCTION_MODE 와 단일 소스. MCP 서버가 paper 면 MOCK, production 이면 REAL.
# 과거에 별도 MOCK_MODE env 를 받았으나 주문경로(MCP)와 라벨(데몬) 불일치 footgun 으로 제거(2026-06-19).
PRODUCTION_MODE = os.getenv("KIWOOM_PRODUCTION_MODE", "false").lower() == "true"
MOCK_MODE = not PRODUCTION_MODE
TRADING_URL = "http://localhost:8030/mcp/"
MARKET_URL = "http://localhost:8031/mcp/"
INFO_URL = "http://localhost:8032/mcp/"
INVESTOR_URL = "http://localhost:8033/mcp/"
PORTFOLIO_URL = "http://localhost:8034/mcp/"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Critical 알림 별도 채팅(미설정 시 기본 채팅 사용). 매도거부/누적실패/긴급 등에만 전송.
TELEGRAM_CRITICAL_CHAT_ID = os.getenv("TELEGRAM_CRITICAL_CHAT_ID", "") or TELEGRAM_CHAT_ID

UNIVERSE_MODE = os.getenv("TREND_UNIVERSE", "watchlist")   # 기본 watchlist (검증 최고)
WATCHLIST = [c.strip() for c in os.getenv("TREND_WATCHLIST", "005930,000660").split(",") if c.strip()]
TOP_N = int(os.getenv("TREND_TOP_N") or (30 if UNIVERSE_MODE == "gainers" else 100))
MIN_VALUE_KRW = float(os.getenv("TREND_MIN_VALUE_KRW", "100000000000"))
MAX_POS = int(os.getenv("TREND_MAX_POS", "5"))
INVEST_PER_TRADE = float(os.getenv("TREND_INVEST_PER_TRADE", "500000"))
# 포지션 사이징: risk=예탁 RISK_PCT% ÷ 손절폭(거래별 리스크 균등·터틀식, 백테스트 MAR 0.87→2.34 검증)
#   / pct_equity=예탁 POSITION_PCT% notional / fixed=INVEST_PER_TRADE 고정.
SIZING_MODE = os.getenv("TREND_SIZING_MODE", "pct_equity")
POSITION_PCT = float(os.getenv("TREND_POSITION_PCT", "8"))
# risk 모드: 종목당 감수 리스크(예탁 대비 %). 1.0=보수(MDD~7%)·1.5=현 15% notional 노출 근사(MDD~11%).
RISK_PCT = float(os.getenv("TREND_RISK_PCT", "1.5"))
# risk 모드 notional 상한(예탁 대비 %) — 손절폭 극소 종목이 과대편입되는 것 방지.
MAX_NOTIONAL_PCT = float(os.getenv("TREND_MAX_NOTIONAL_PCT", "25"))
USE_FOREIGN_EXIT = os.getenv("TREND_USE_FOREIGN_EXIT", "true").lower() == "true"
NEWS_VETO = os.getenv("TREND_NEWS_VETO", "true").lower() == "true"
INTRADAY_POLL_MIN = int(os.getenv("TREND_INTRADAY_POLL_MIN", "10"))
# 프리장(장전 동시호가) 갭다운 소프트veto: >0 이면 예상체결가가 기준가 대비 그 %p 초과 하락 시 후보 제외. 기본 0=off(표시만).
PREMARKET_GAPDOWN_VETO = float(os.getenv("TREND_PREMARKET_GAPDOWN_VETO", "0") or 0)
# 09:30 진입 시 하락 중(현재가<시가)인 후보는 보류 → 장중 반등(시가 회복) 시 진입, 끝까지 안 돌면 그날 스킵.
ENTRY_WAIT_FALLING = os.getenv("TREND_ENTRY_WAIT_FALLING", "true").lower() == "true"
# 신규 진입 허용 마감 시각(PDF: 09:30~10:30만 진입). 이후 보류분은 그날 스킵. "HH:MM".
ENTRY_CUTOFF = os.getenv("TREND_ENTRY_CUTOFF", "10:30")
# 하드 손절(PDF 절대원칙): 진입가 대비 손실이 이 %p 초과 시 ATR 트레일과 무관하게 즉시 시장가 청산. 0=off.
HARD_STOP_PCT = float(os.getenv("TREND_HARD_STOP_PCT", "0") or 0)
# 청산 이평선(하방돌파 시 청산). A/B 검증(2026-06-12): MA120 >> MA50(기대값·누적 2~4배, 추세 끝까지 탑승).
EXIT_MA = int(os.getenv("TREND_EXIT_MA", "120"))
# 최대 보유 영업일(시간청산, 0=off). 백테스트가 cfg.max_hold=60 강제 마감으로 기대값을 산출했으므로
# 라이브도 동일 조건 유지 — MA120 위 횡보 종목의 무기한 자본 점유 방지. 15:20 exit phase 에서만 평가.
MAX_HOLD_DAYS = int(os.getenv("TREND_MAX_HOLD", "60") or 0)
# 실적(재무) 자동 가점(차수재시실 '실적'): 매출·영업이익 YoY 동반증가 +N점, 영업이익만 +N/2 — 순위 가점만. 0=off.
FUND_BONUS = float(os.getenv("TREND_FUND_BONUS", "5") or 0)
# 주도섹터 집단상승(차수재시실 '시황'): 당일 섹터 평균등락·상승비율로 주도섹터 판정 → 소속 후보 가점. 0=off.
SECTOR_BONUS = float(os.getenv("TREND_SECTOR_BONUS", "5") or 0)
# true 면 주도섹터 소속 후보만 진입(하드 게이트). 기본 false(가점만) — 검증된 게이트 엣지 보존.
SECTOR_GATE = os.getenv("TREND_SECTOR_GATE", "false").lower() == "true"
SECTOR_MIN_AVG = float(os.getenv("TREND_SECTOR_MIN_AVG", "1.0"))     # 주도 판정: 섹터 평균 등락률 하한 %
SECTOR_BREADTH = float(os.getenv("TREND_SECTOR_BREADTH", "0.6"))    # 주도 판정: 상승종목 비율 하한 (집단상승)
SECTOR_TOP_K = int(os.getenv("TREND_SECTOR_TOP_K", "3"))
# 거래비용 (편도 bps). 거래세는 정부 정책 가변 → 보수 20bps(코스피 0.20%·코스닥 0.20%, 2026 기준).
# 키움 비대면 위탁수수료 0.015% 편도, 대형주 시장가 슬리피지 0.10% 편도 (실전 첫주 후 보정).
# 환경변수 prefix CLOSING_BET_* 공용(과거 잔존, 변경하면 closing-bet 도 영향). 실전에선 .env 로 override.
TAX_BPS = float(os.getenv("CLOSING_BET_TAX_BPS", "20.0"))
FEE_BPS = float(os.getenv("CLOSING_BET_FEE_BPS", "1.5"))
SLIPPAGE_BPS = float(os.getenv("CLOSING_BET_SLIPPAGE_BPS", "10.0"))
ROUNDTRIP_COST_PCT = (TAX_BPS + 2 * FEE_BPS + 2 * SLIPPAGE_BPS) / 100.0  # 매도세 + 2×수수료 + 2×슬리피지
FORCE_PHASE = os.getenv("TREND_FORCE_PHASE", "false").lower() == "true"
# 일일 최대손실 서킷브레이커: 당일 실현손실(net)이 예탁자산의 이 %p 초과 시 신규 진입 중단. 0=off.
DAILY_LOSS_LIMIT_PCT = float(os.getenv("TREND_DAILY_LOSS_LIMIT_PCT", "0") or 0)
# 피라미딩(승자 불타기, 검증=backtest equity게이트): 보유 종목이 진입+ k×STEP_R×R 도달 시 1유닛 추가.
# equity-curve 게이트(최근 LOOKBACK 청산 net 평균>MIN_NET 일 때만)로 횡보장 증폭손실 차단. 0=off(기본).
PYRAMID_ADDS = int(os.getenv("TREND_PYRAMID_ADDS", "0") or 0)          # 종목당 최대 추가 유닛 수(0=off)
PYRAMID_STEP_R = float(os.getenv("TREND_PYRAMID_STEP_R", "1.0"))       # 추가 트리거 간격(R배수)
PYRAMID_LOOKBACK = int(os.getenv("TREND_PYRAMID_LOOKBACK", "20"))      # equity 게이트 청산거래 표본 수
PYRAMID_MIN_NET = float(os.getenv("TREND_PYRAMID_MIN_NET", "0") or 0)  # 게이트 임계(최근 평균 net% >)
# Equity-curve 게이트 우회(MOCK 파일럿/테스트용). true 시 청산이력 무관 즉시 OPEN — 횡보장 증폭손실 위험.
# 실전 전환 시 반드시 false 복귀. PRODUCTION 모드 + 이 값 true 면 LIVE-GUARD 경고 발화.
PYRAMID_BYPASS_GATE = os.getenv("TREND_PYRAMID_BYPASS_GATE", "false").lower() == "true"
# 시장 breadth 게이트(2026-06-24): KOSPI 업종지수 universe 양봉비율 < 이 값 일 때 신규진입 차단.
# 06-23 사고(9종 동시 hard stop) 재발 방지. 백테스트(largecap): 0.4=P10-7.99%·PF1.52, 0.5=P10-7.07%·PF1.65. 0=off.
BREADTH_MIN_PCT = float(os.getenv("TREND_BREADTH_MIN_PCT", "0") or 0)
# Reconcile(어댑트) 모드: all=모든 broker 보유분 편입(기본·기존 동작), watchlist=WATCHLIST 종목만, off=어댑트 안 함.
# 실전에서 HTS 수동매수/장기보유분이 trend 룰(MA120 이탈)로 강제청산되는 위험 차단용.
ADOPT_MODE = os.getenv("TREND_ADOPT_MODE", "all").lower()

CFG = TrendConfig(
    mode=("largecap" if UNIVERSE_MODE in ("largecap", "watchlist") else "gainers"),
    stop_pct=float(os.getenv("TREND_STOP_PCT", "7")),
    atr_k=float(os.getenv("TREND_ATR_K", "2.0")),
    rr=float(os.getenv("TREND_RR", "3.0")),
    partial_pct=float(os.getenv("TREND_PARTIAL_PCT", "30")),
    # 눌림목 게이트 폭(현재가 ≤ MA20×(1+X%)). 기본 3 → A/B 검증(2026-06-26)으로 12 채택.
    # 양극화/멜트업 장에서 3%는 과도하게 좁아 후보 0 빈발 → 12%가 largecap +2.61%/watchlist +8.90% 기대값 정점.
    pullback_pct=float(os.getenv("TREND_PULLBACK_PCT", "3")),
)

DATA_DIR = _ROOT / "data" / "trend_follow"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOCK_FILE = DATA_DIR / "daemon.lock"
HEARTBEAT_FILE = DATA_DIR / "daemon.heartbeat"   # 데몬 진행 heartbeat — watchdog hang 감지용
JOURNAL_FILE = DATA_DIR / "journal.json"
LOG_DIR = _ROOT / "logs" / "trend_follow"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "trend_follow.log"

_fh = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8")
_fh.suffix = "%Y-%m-%d"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout), _fh])
logger = logging.getLogger("trend")

SCHEDULE = [(8, 50, "screen"), (9, 30, "entry"), (15, 20, "exit")]
