# 실전 매매 전환 절차 (추세추종 트랙)

**대상**: 2026-06-29(월) 추세추종 데몬 실전 전환.
**현행**: 2026-06-19 기준 MOCK(paper) 운영 중 (`KIWOOM_PRODUCTION_MODE=false`).

---

## 0. 단일 소스 (2026-06-19 수정)

이제 `MOCK_MODE` 환경변수는 **읽지 않습니다**. 단일 소스는 `KIWOOM_PRODUCTION_MODE`:

| `KIWOOM_PRODUCTION_MODE` | API 도메인 | 데몬 라벨 | 토큰 캐시 |
|--------------------------|-----------|----------|----------|
| `false`(기본) | `mockapi.kiwoom.com` | 🧪 MOCK | `token_paper_*.json` |
| `true` | `api.kiwoom.com` | 💰 REAL | `token_production_*.json` |

토큰 캐시는 모드별로 분리 저장되므로(`%TEMP%/kiwoom_token_cache/`) 모드 전환 시 토큰 충돌 없음.

---

## 1. 전환 전 체크리스트 (6/22 월 ~ 6/26 금)

### A. 사전 준비 (월 6/22)
- [ ] **실거래용 키움 API 키 발급/확인** — `KIWOOM_APP_KEY`/`KIWOOM_APP_SECRET` (모의용과 다름)
- [ ] **실거래 계좌번호 확인** — `KIWOOM_ACCOUNT_NO` (모의용과 다름)
- [ ] **계좌 예수금 입금** — 실전 첫주는 소액(예: 500만~1,000만) 권장
- [ ] **`.env.production` 별도 파일 작성** — 평시는 `.env`(MOCK), 전환 시 `.env.production` 복사
- [ ] **MCP 토큰 캐시 격리 확인** — `%TEMP%/kiwoom_token_cache/` 에 `token_paper_*` 와 `token_production_*` 가 따로 생성되는지

### B. 안전장치 강화 (화 6/23) — `[LIVE-GUARD]` 가 위반 시 경고+텔레그램 (2026-06-19 추가)
- [ ] **사이징 임시 축소** — `TREND_POSITION_PCT=2`~3 (현행 6→2), `TREND_MAX_POS=3`~5 (현행 10→3)
- [ ] **하드손절 상시 ON** — `TREND_HARD_STOP_PCT=7` 유지(이미 적용)
- [ ] **일일손실 서킷브레이커 ON** — `TREND_DAILY_LOSS_LIMIT_PCT=2`
- [ ] **피라미딩 OFF** — `TREND_PYRAMID_ADDS=0` (실전 첫달 검증 보류)
- [ ] **Reconcile 제한** — `TREND_ADOPT_MODE=watchlist` (또는 `off`) — HTS 수동매수가 trend 청산룰로 처분되지 않도록
- [ ] **거래비용 재확인** — `CLOSING_BET_TAX_BPS=20`(2025년 0.20% 매도세 보수), 정책 변경 시 .env 로 override
- [ ] **텔레그램 critical alert 분리** (선택) — 일반/사고 채널 구분

### C. 회귀/스모크 (수~목 6/24~25)
- [ ] **단위 테스트** — `python -m pytest tests/test_trend_signals.py -q` (30 PASS 확인)
- [ ] **실전 키 + paper 모드 1회 조회 스모크** — `KIWOOM_PRODUCTION_MODE=false` + 실거래 키로 `--phase reconcile` (계좌 평가 조회만 동작, 주문 없음). 응답 파싱 정상 확인.
- [ ] **실전 키 + production 모드 조회 스모크** — `KIWOOM_PRODUCTION_MODE=true` + 실거래 키로 `--phase reconcile`. `prsm_dpst_aset_amt`/`entr` 등 핵심 필드가 채워지는지 확인.
- [ ] **소량 실주문 1건 테스트** — 6/25(목) 장중 임의로 가장 저렴한 1주(예: 2~3만원대) **수동** 매수→매도. 주문/체결/원장 흐름 검증.
- [ ] **MOCK 7일 회고** — `data/trend_follow/journal.json` 으로 6/12~6/26 거래 backtest 기대값과 대조.

### D. 전환 직전 (금 6/26)
- [ ] **MOCK 데몬 정상 종료** — `taskkill /F /IM python.exe` (TrendFollow 프로세스만 골라서) 또는 작업스케줄러 비활성
- [ ] **state.json 백업** — `data/trend_follow/state.json` → `state.mock.json` 보존(MOCK 보유분 추적 종료)
- [ ] **`.env` 교체** — `.env.production` → `.env` 복사. 변경 핵심: `KIWOOM_APP_KEY`/`SECRET`/`ACCOUNT_NO`/`KIWOOM_PRODUCTION_MODE=true`
- [ ] **MCP 서버 재기동** — `python run_mcp_local.py stop && python run_mcp_local.py start` (필수: env 변경은 재기동 필요)
- [ ] **`check_status.py` + 토큰 발급 확인** — `%TEMP%/kiwoom_token_cache/token_production_*.json` 생성 확인

---

## 2. 전환 당일 (월 6/29) 운영

### 09:00 이전
- [ ] **데몬 기동 전 계좌 잔고 확인** — 키움HTS 또는 `--phase reconcile` 로 평가/예수금 정상
- [ ] **데몬 기동** — `TREND_UNIVERSE=largecap python scripts/trend_follow.py --daemon`
- [ ] **시작 로그 확인** — `[DAEMON] ⚠️ PRODUCTION MODE` 배너 + 사이징/슬롯 출력 확인
- [ ] **텔레그램 시작 알림 도착 확인** — "🚀 추세추종 데몬 시작 (💰 REAL)"

### 장중
- [ ] **09:30 진입 알림 모니터링** — 신규 진입 시 종목/수량/가격이 의도한 사이징(2% 균등)인지 확인
- [ ] **10:00 첫 트레일 점검** — `intraday` phase 로그 확인
- [ ] **15:20 청산 알림** — MA120 이탈/외인전환 청산 정상 동작 확인

### 장 마감 후
- [ ] **매매일지 자동 생성 확인** — `docs/2026-06-29-trend-journal.md`
- [ ] **16:10 Notion 자동화 확인** — 매매일지DB + 종합정리 페이지 갱신
- [ ] **실현손익 vs HTS 대조** — 키움HTS 실현손익과 `data/trend_follow/journal.json` net 합산 일치 확인

---

## 3. 긴급 정지 절차

**상황**: 데몬 오작동/연속 손실/시스템 장애.

```bash
# 1. 데몬 즉시 정지 (단일락 해제됨)
taskkill /F /IM python.exe                 # 모든 python 종료 (주의: 다른 작업 영향)
# 또는 정밀:
wmic process where "CommandLine like '%trend_follow%'" delete

# 2. watchdog 자동복구 비활성화 (재기동 차단)
schtasks /Change /TN "KiwoomTrendWatchdog" /Disable

# 3. 보유분 전량 시장가 청산 (수동)
python scripts/trend_follow.py --phase exit  # MA120/트레일 기반 청산 한번 실행
# 또는 키움HTS에서 직접 전량 매도(가장 확실)

# 4. 상태 백업 + 데몬 lock 해제
copy data\trend_follow\state.json data\trend_follow\state.emergency.json
del data\trend_follow\daemon.lock
```

---

## 4. 알려진 제약/주의

- **MCP 환경변수 적용**: `KIWOOM_PRODUCTION_MODE` 는 **MCP 서버 기동 시점**에 읽힘. 데몬만 재기동해도 MCP 서버가 paper 면 paper 로 주문됨. 모드 전환 시 **MCP 서버 반드시 재기동**.
- **MOCK_MODE env 무시**: 과거에 `MOCK_MODE=true/false` 로 라벨만 바뀌고 주문경로는 안 바뀌던 footgun 은 2026-06-19 제거됨. 이제 단일 소스 `KIWOOM_PRODUCTION_MODE`.
- **사이징 일관성**: 데몬은 `_account_equity` 결과로 `POSITION_PCT%` 사이징. paper 의 가짜 예탁자산(보통 1억 기본값)과 실전 잔고는 다르므로, 전환 후 첫날 사이즈 로그 반드시 확인.
- **토큰 8005**: 두 모드 동시 사용은 캐시 격리로 안전. 그래도 8005 발생 시 클라이언트가 강제 재발급 + 재시도.
- **watchdog**: 작업스케줄러 `KiwoomTrendWatchdog` 가 평일 08:40~15:55 / 5분 주기로 데몬 자동 복구. **사고 시 비활성화 필수**(위 §3 참조).

---

## 5. 롤백 절차 (실전→MOCK 되돌리기)

문제 발생 시 즉시 MOCK 복귀:

```bash
# 1. 데몬 정지 + watchdog 비활성
taskkill /F /IM python.exe
schtasks /Change /TN "KiwoomTrendWatchdog" /Disable

# 2. .env 복원 (KIWOOM_PRODUCTION_MODE=false + 모의키)
copy .env.mock .env  # 사전에 백업 둔 MOCK 설정

# 3. MCP 재기동
python run_mcp_local.py stop && python run_mcp_local.py start

# 4. state 분리 (실전 state 백업 보존)
copy data\trend_follow\state.json data\trend_follow\state.real_run1.json
copy data\trend_follow\state.mock.json data\trend_follow\state.json

# 5. MOCK 데몬 재기동
TREND_UNIVERSE=largecap python scripts/trend_follow.py --daemon
```

---

*최초 작성: 2026-06-19 / 전환 예정일: 2026-06-29. 전환 후 회고는 `docs/2026-06-29-live-switchover-retro.md` 에 작성.*
