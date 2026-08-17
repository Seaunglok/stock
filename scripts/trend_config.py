"""추세추종 데몬 공유 설정 — .env 로드 + 상수 + 로거 (scripts/trend_config.py).

trend_follow.py / trend_kiwoom_io.py / 백테스트 / 대시보드가 공유한다.

**부작용 정책**(2026-08-17): import 만으로 프로세스 전역을 바꾸는 것은
`setup_daemon_runtime()` 안으로 모았다 — 소켓 기본 타임아웃, 루트 로거 점유, stdout 재설정.
데몬 진입점만 이 함수를 부른다.

이유: 대시보드가 이 모듈을 import 하지 않으려고 경로 상수·journal 파싱·state 로딩을
통째로 복사해 두고 있었다(trend_dashboard.py 주석 "config.py 와 동일 파일명"). 부작용이
부담스러우면 재사용 대신 복붙이 일어나고, 그러면 파일 포맷이 바뀔 때 한쪽만 조용히 어긋난다.
상수·경로는 부작용 없이 import 가능해야 한다.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # scripts/trend_config.py → repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))            # src.* 절대 import 부트스트랩(불가피)

from src.mcp_servers.trend_mcp import costs as _costs  # noqa: E402
from src.mcp_servers.trend_mcp.signals import TrendConfig  # noqa: E402


ENV_LOADED = False   # .env 를 실제로 읽었는가 — LIVE-GUARD 가 최우선으로 확인한다


def _load_env() -> None:
    """.env 로드. TREND_ENV_FILE 로 경로를 바꿀 수 있다(테스트/다중 구성용).

    테스트가 '설정 파일 없음' 상태를 재현할 때 실제 .env 를 rename 하면, pytest 가 중간에 죽는
    순간 .env 가 사라진 채 남는다 — 다음 기동이 전부 코드 기본값으로 도는, 이 테스트가 막으려는
    바로 그 사고다. 그래서 파일을 건드리지 않고 경로만 돌릴 수 있게 한다.
    """
    global ENV_LOADED
    env = Path(os.environ["TREND_ENV_FILE"]) if os.environ.get("TREND_ENV_FILE") else _ROOT / ".env"
    if not env.exists():
        return                    # ENV_LOADED=False 유지 → 기동 시 경고(아래 LIVE-GUARD)
    ENV_LOADED = True
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()   # 상수 계산에 필요하므로 이건 import 시점에 수행(파일 읽기 외 전역 변경 없음)

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

# ─────────────────────────────────────────────────────────────────────────────
# ★ 기본값 = **현재 채택된 운용값**. .env 는 override 전용이다.
#   2026-08-17 이전엔 A/B 검증 '이전' 값이 기본값이고 채택값은 .env 에만 있었다 → .env 유실 시
#   하드손절·서킷·breadth 게이트가 전부 꺼지고 ADOPT_MODE=all 로 HTS 수동매수분까지 청산되는
#   구성으로 조용히 돌아갔다. 더 나쁘게는 PRODUCTION_MODE 도 .env 에서 오므로 LIVE-GUARD 자체가
#   건너뛰어져, 주문은 실제로 나가면서 알림 라벨만 MOCK 이 된다.
#   → 기본값을 채택값으로 승격해 "설정 파일이 없으면 검증된 전략이 돈다" 를 보장한다.
#   기본값 변경 시 tests/test_trend_config.py 스냅샷도 함께 갱신할 것.
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSE_MODE = os.getenv("TREND_UNIVERSE", "largecap")    # 채택: largecap (watchdog 과 동일 기본값)
WATCHLIST = [c.strip() for c in os.getenv("TREND_WATCHLIST", "005930,000660").split(",") if c.strip()]
TOP_N = int(os.getenv("TREND_TOP_N") or (30 if UNIVERSE_MODE == "gainers" else 100))
MIN_VALUE_KRW = float(os.getenv("TREND_MIN_VALUE_KRW", "100000000000"))
MAX_POS = int(os.getenv("TREND_MAX_POS", "5"))
INVEST_PER_TRADE = float(os.getenv("TREND_INVEST_PER_TRADE", "500000"))
# 포지션 사이징: risk=예탁 RISK_PCT% ÷ 손절폭(거래별 리스크 균등·터틀식, 백테스트 MAR 0.87→2.34 검증)
#   / pct_equity=예탁 POSITION_PCT% notional / fixed=INVEST_PER_TRADE 고정.
SIZING_MODE = os.getenv("TREND_SIZING_MODE", "risk")        # 채택(2026-07-13 포트폴리오 A/B)
POSITION_PCT = float(os.getenv("TREND_POSITION_PCT", "15"))  # risk 폴백용 notional %
# risk 모드: 종목당 감수 리스크(예탁 대비 %). 1.0=보수(MDD~7%)·1.5=현 15% notional 노출 근사(MDD~11%).
RISK_PCT = float(os.getenv("TREND_RISK_PCT", "1.5"))
# risk 모드 notional 상한(예탁 대비 %) — 손절폭 극소 종목이 과대편입되는 것 방지.
MAX_NOTIONAL_PCT = float(os.getenv("TREND_MAX_NOTIONAL_PCT", "25"))
USE_FOREIGN_EXIT = os.getenv("TREND_USE_FOREIGN_EXIT", "true").lower() == "true"
# 외인 청산 신호 규모 임계값: |5일 순매수합| ≥ 이 값 × 20일 평균거래량 이어야 유효 신호(0=부호만).
# 2026-07-15 삼성생명 노이즈 오발동(0.001% 규모) 재발 방지. 백테스트: backtest_trend --foreignexit.
FOREIGN_MIN_RATIO = float(os.getenv("TREND_FOREIGN_MIN_RATIO", "0.2") or 0)
# 외인 청산 추세 확인 이평선(기본 60): 외인 순매도 **AND** 현재가<MA60 일 때만 청산. 0=off(수급만, 구 동작).
# 2026-07-31: KOSPI +17.9% 반등일에 4종 동시 외인청산 신호 — 전부 MA120 위 정상추세였음(외인 5일합은
# 직전 폭락기 포함이라 반등 초입에도 음수 = 늦은 신호). 추세 확인으로 수급 단독 청산 차단.
# ※ MA120 은 이미 단독 청산조건이라 AND 로 쓰면 외인룰 영구 미발동 → MA60 사용.
FOREIGN_TREND_MA = int(os.getenv("TREND_FOREIGN_TREND_MA", "60") or 0)
# 시장 레짐 필터(2026-08-03): KOSPI 가 자기 MA(N) 아래면 하락장 → 그날 신규진입 전면 차단. 0=off.
# 근거: 실전 6전6패 진단 — 검증구간(일간변동성 2.16%·+136% 상승장) vs 실전구간(5.71%·-20.5% 하락장)
# 레짐 불일치가 주원인. 이 전략은 원래 '시장필터 없음'이 설계 선택이었으나 하락장 방어가 부재했다.
# 실전 진입 11건 중 10건이 KOSPI<MA60 일에 발생(차단 시 실현손실 -33.3%p 회피). 추세추종 대가 표준
# (Weinstein Stage·O'Neil 'M'). ※breadth 게이트는 '당일 상승종목 비율'이라 지수 추세를 못 본다 — 상호보완.
REGIME_MA = int(os.getenv("TREND_REGIME_MA", "60") or 0)
NEWS_VETO = os.getenv("TREND_NEWS_VETO", "true").lower() == "true"
INTRADAY_POLL_MIN = int(os.getenv("TREND_INTRADAY_POLL_MIN", "10"))
# 프리장(장전 동시호가) 갭다운 소프트veto: >0 이면 예상체결가가 기준가 대비 그 %p 초과 하락 시 후보 제외. 기본 0=off(표시만).
PREMARKET_GAPDOWN_VETO = float(os.getenv("TREND_PREMARKET_GAPDOWN_VETO", "0") or 0)
# 09:30 진입 시 하락 중(현재가<시가)인 후보는 보류 → 장중 반등(시가 회복) 시 진입, 끝까지 안 돌면 그날 스킵.
ENTRY_WAIT_FALLING = os.getenv("TREND_ENTRY_WAIT_FALLING", "true").lower() == "true"
# 신규 진입 허용 마감 시각. 이후 보류분은 그날 스킵. "HH:MM". 진입시각(11:00)보다 뒤여야 한다.
ENTRY_CUTOFF = os.getenv("TREND_ENTRY_CUTOFF", "14:00")
# 하드 손절(PDF 절대원칙): 진입가 대비 손실이 이 %p 초과 시 ATR 트레일과 무관하게 즉시 시장가 청산. 0=off.
HARD_STOP_PCT = float(os.getenv("TREND_HARD_STOP_PCT", "10") or 0)
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
# 거래비용 (편도 bps) — 기본값은 trend_mcp.costs 단일 소스(백테스트와 동일 숫자).
# 2026-08-17: 과거엔 CLOSING_BET_* 를 공용으로 읽어 ① 종가매매 비용을 바꾸면 추세추종 손익이
# 같이 움직였고 ② 백테스트 기본값(18bps)과 달라 매매일지 net_pct 와 검증 기대값이 비교 불가였다.
TAX_BPS = float(os.getenv("TREND_TAX_BPS") or _costs.TAX_BPS)
FEE_BPS = float(os.getenv("TREND_FEE_BPS") or _costs.FEE_BPS)
SLIPPAGE_BPS = float(os.getenv("TREND_SLIPPAGE_BPS") or _costs.SLIPPAGE_BPS)
ROUNDTRIP_COST_PCT = _costs.roundtrip_pct(TAX_BPS, FEE_BPS, SLIPPAGE_BPS)
FORCE_PHASE = os.getenv("TREND_FORCE_PHASE", "false").lower() == "true"
# 일일 최대손실 서킷브레이커: 당일 실현손실(net)이 예탁자산의 이 %p 초과 시 신규 진입 중단. 0=off.
DAILY_LOSS_LIMIT_PCT = float(os.getenv("TREND_DAILY_LOSS_LIMIT_PCT", "2") or 0)
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
BREADTH_MIN_PCT = float(os.getenv("TREND_BREADTH_MIN_PCT", "0.4") or 0)
# Reconcile(어댑트) 모드: all=모든 broker 보유분 편입, watchlist=WATCHLIST 종목만, off=어댑트 안 함.
# 기본 off — 실전에서 HTS 수동매수/장기보유분이 trend 룰(MA120 이탈)로 강제청산되면 되돌릴 수 없다.
ADOPT_MODE = os.getenv("TREND_ADOPT_MODE", "off").lower()

CFG = TrendConfig(
    mode=("largecap" if UNIVERSE_MODE in ("largecap", "watchlist") else "gainers"),
    stop_pct=float(os.getenv("TREND_STOP_PCT", "7")),
    atr_k=float(os.getenv("TREND_ATR_K", "2.0")),
    rr=float(os.getenv("TREND_RR", "3.0")),
    partial_pct=float(os.getenv("TREND_PARTIAL_PCT", "30")),
    # 눌림목 게이트 폭(현재가 ≤ MA20×(1+X%)). A/B 검증(2026-06-26)으로 12 채택.
    # 양극화/멜트업 장에서 3%는 과도하게 좁아 후보 0 빈발 → 12%가 largecap +2.61%/watchlist +8.90% 기대값 정점.
    pullback_pct=float(os.getenv("TREND_PULLBACK_PCT", "12")),
)

DATA_DIR = _ROOT / "data" / "trend_follow"
DATA_DIR.mkdir(parents=True, exist_ok=True)   # 경로만 쓰는 쪽도 쓰기 가능해야 함(무해·멱등)
STATE_FILE = DATA_DIR / "state.json"
LOCK_FILE = DATA_DIR / "daemon.lock"
HEARTBEAT_FILE = DATA_DIR / "daemon.heartbeat"   # 데몬 진행 heartbeat — watchdog hang 감지용
# heartbeat 기록 주기 ↔ watchdog stale 판정 임계는 **한 쌍**이다(임계 = 주기 × 10).
# 2026-08-17 이전엔 60 이 trend_follow 에, 600 이 trend_watchdog 에 따로 있어서, 기록 주기를
# 늘리면 watchdog 이 정상 데몬을 hung 으로 오판해 taskkill 하는 구조였다.
HEARTBEAT_INTERVAL_SEC = 60
HEARTBEAT_STALE_SEC = HEARTBEAT_INTERVAL_SEC * 10   # 정상 screen 은 <2~3분
JOURNAL_FILE = DATA_DIR / "journal.json"
LOG_DIR = _ROOT / "logs" / "trend_follow"
LOG_FILE = LOG_DIR / "trend_follow.log"

logger = logging.getLogger("trend")
_RUNTIME_READY = False


def setup_daemon_runtime() -> None:
    """데몬/장기 실행 진입점 전용 초기화 — **프로세스 전역을 바꾸는 것만** 여기 모았다.

    상수만 필요한 쪽(대시보드·백테스트·테스트)은 이 함수를 부르지 않고 import 만 하면 된다.
    멱등 — 여러 번 불러도 안전하다.

    하는 일:
      · 소켓 기본 타임아웃 30s — pykrx/DART 동기 호출이 무한 hang 되면 async 데몬 전체가
        얼어붙는다(2026-07-02 08:50 screen hang → entry 누락). 예외로 바뀌면 기존 try/except 가
        graceful skip 한다. async httpx(MCP)는 자체 타임아웃이라 영향 없음.
      · 로그 디렉터리/파일 핸들러(자정 회전·30일 보관) + 루트 로거 basicConfig
      · stdout UTF-8 재설정 — Windows cp949 콘솔에서 이모지 출력 시 UnicodeEncodeError 로
        데몬이 죽는 것 방지
    """
    global _RUNTIME_READY
    if _RUNTIME_READY:
        return
    _RUNTIME_READY = True
    socket.setdefaulttimeout(30)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _fh = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1,
                                   backupCount=30, encoding="utf-8")
    _fh.suffix = "%Y-%m-%d"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), _fh])

# 진입 시각(HH:MM). 2026-08 09:30→11:00: 09~10시는 갭·시초 물량으로 일중 변동성이 가장 커
# 슬리피지·휩소가 크다. 오전 변동성이 가라앉은 뒤 진입해 체결 품질을 높인다.
# ※ 백테스트는 '신호일 익일 **시가**' 진입으로 검증됨 — 일봉 데이터엔 장중 시각 가격이 없어
#   11시 진입은 백테스트 재현 불가(미검증 변경). 논리적 근거만 있는 상태이므로 journal 로 추적.
# 보류(하락중) 후보 재시도 마감은 TREND_ENTRY_CUTOFF(14:00) — 진입시각보다 뒤여야 의미가 있다.
ENTRY_TIME = os.getenv("TREND_ENTRY_TIME", "11:00")


def _hhmm(s: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in s.split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except Exception:
        pass
    logger.warning("[CONFIG] 시각 파싱 실패 '%s' → 기본 %02d:%02d", s, *default)
    return default


_ENTRY_H, _ENTRY_M = _hhmm(ENTRY_TIME, (11, 0))
SCHEDULE = [(8, 50, "screen"), (_ENTRY_H, _ENTRY_M, "entry"), (15, 20, "exit")]
# 정합성: 보류(하락중) 재시도 마감이 진입시각보다 이르면 보류분이 즉시 스킵돼 무의미해진다.
_CUT_H, _CUT_M = _hhmm(ENTRY_CUTOFF, (14, 0))
if (_CUT_H, _CUT_M) <= (_ENTRY_H, _ENTRY_M):
    logger.warning("[CONFIG] ⚠️ TREND_ENTRY_CUTOFF(%s) ≤ TREND_ENTRY_TIME(%s) — 하락보류 후보가 "
                   "즉시 스킵됩니다. 컷오프를 진입시각보다 뒤로 설정하세요.", ENTRY_CUTOFF, ENTRY_TIME)
