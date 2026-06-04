# 종가매매(Closing Bet) 전략 — 운영 명세

> 자동매매 스크립트: [scripts/direct_closing_bet.py](../scripts/direct_closing_bet.py)
> 채점/판단 모듈: [src/mcp_servers/closing_bet_mcp/](../src/mcp_servers/closing_bet_mcp/)
> 대시보드: `python scripts/dashboard.py` → http://localhost:8090

## 1. 전략 개요

전일 종가에 매수해 **최대 N영업일(`HOLD_DAYS`, 기본 3) 보유**하며 ATR 트레일링 스톱으로
청산하는 단기 스윙 전략. (구버전은 1영업일 강제청산이었으나, 백테스트에서 우측꼬리 포착이
기대값을 좌우함이 드러나 보유기간+트레일로 일반화 — §6 참조.)

```
14:50  선별 phase    →  거래대금 1,000억원+ × 상위 50종목 채점
15:15  매수 1차      →  점수 55+ 1~3종목, 의도 수량의 50% 시장가 매수 (+ATR/stop 초기화)
15:19  매수 2차      →  마감 직전, 잔여 50% 시장가 매수
18:05  AH phase      →  시간외 단일가로 트레일링 스톱 갱신(상방만)
09:00  매도 phase    →  보유 전 종목 트레일/손절 이탈만 청산 (시간청산 X)
15:10  청산 phase    →  트레일 이탈분 + 보유기간 만기분 시간청산. 미만기는 다음날로 이월
```

매수 후 셋업(거래대금·매물대·외인 양매수)이 추가 매수세를 끌어올 확률에 베팅하되,
**승자는 ATR 트레일로 끝까지 따라가고(우측꼬리), 패자는 ATR 손절로 제한**한다.

## 2. 진입 조건 — 6단계 게이트

후보가 되려면 모든 게이트를 통과해야 한다.

### Gate 1: 시장 필터 ([evaluate_market_filter](../src/mcp_servers/closing_bet_mcp/exit_rules.py))
- KOSPI 당일 ≤ -1.5% → **중단**
- KOSPI 5일 누적 ≤ -3.0% → **중단**

### Gate 2: 시장 레짐 ([classify_regime](../src/mcp_servers/closing_bet_mcp/exit_rules.py))
- KOSPI < -1.0% **또는** 양봉비율 < 35% → `weak` → **중단**
- 양봉비율은 pykrx 전종목 중 등락률 > 0인 비율

### Gate 3: 미국 야간 게이트
- S&P500 **AND** NASDAQ 모두 ≤ -1.5% → **중단**
- KOSPI가 미국 추종해 시초가 갭다운 위험이 큰 날을 회피

### Gate 4: MA20 필터 (종목별)
- 현재가 < 20일 이동평균 → 후보 제외
- 하락 추세 종목 사전 차단

### Gate 5: 당일 갭업 필터 (종목별)
- 당일 갭 ≥ **+2%** → 제외 (백테스트 기반)
- 백테스트(149종목, 6개월): +2~4% 갭 종목 승률 57.9% (가장 약함)
- 익일 시초 진입 시 가장 강한 구간은 -2~0% (조정 후 종가, 승률 80%) 와 0~2% (76%)

### Gate 6: composite 점수 ≥ 55 (기본)
- 모든 필터 통과 후 6개 기준 가중 합산 (아래 §3)
- **55점 미만은 후보 0개도 허용** — 시장이 약하면 매수 안 함
- 백테스트: strict-gap + thr55 + top_n3 → 승률 65.8%, +0.92% (env: `CLOSING_BET_MIN_SCORE`로 조정)

## 3. 채점 — 6개 기준 + 재료 가중

[scorer.py:compute_technical_scores_hybrid](../src/mcp_servers/closing_bet_mcp/scorer.py)

| # | 기준 | 가중 | 핵심 로직 |
|---|------|------|-----------|
| 1 | volume_surge | 20% | 오늘 거래대금 / 20일 평균 (1.5배 = 50점, 3배 = 90점) |
| 2 | resistance_proximity | 20% | 90일 전고점 대비 갭 (-8% ~ -3% = 만점) |
| 3 | candle_shape (v2) | 20% | 위꼬리 작을수록 高 (백테스트 결과 위꼬리 0-20% 구간 100% 승률) |
| 4 | consolidation | 25% | 90일 고점 → 조정 → 회복 패턴 (백테스트 가장 높은 기여) |
| 5 | institutional | 15% | 외인·기관 5일 누적 양매수 (둘 다 = 100, 하나 = 60) |
| 6 | catalyst | (별도) | 트렌드 키워드 매칭 (AI/반도체, 2차전지, 방산, 바이오, 원전, 로봇, 조선, 양자) |

**최종 합산 공식**:
```python
# tech = compute_technical_scores(...)  # 검증 백테스트와 동일한 v1 채점식 (candle v1 포함)
cat_weight = CATALYST_WEIGHT if cat.has_catalyst else 0.0   # CLOSING_BET_CATALYST_WEIGHT, 기본 0.0
composite = cat.score * cat_weight + tech.composite() * (1.0 - cat_weight)
```

> **P0(2026-06-01)**: catalyst 기본 가중을 **0.0**으로 낮췄다. 검증 백테스트(`compute_technical_scores`)에는
> catalyst가 없었고, 라이브 catalyst는 "회사명 뉴스 ≥2건"이면 켜져 대형주 대부분에서 항상 True가 돼
> 30%를 노이즈로 대체했다. 실거래·백테스트로 검증된 뒤 `CLOSING_BET_CATALYST_WEIGHT`로 다시 올린다.
> 또한 라이브 채점 함수를 `compute_technical_scores_hybrid`(candle **v2** = 위꼬리 클수록 高)에서
> `compute_technical_scores`(candle **v1** = 위꼬리 작을수록 高)로 되돌려 백테스트 결론과 부호를 맞췄다.

## 4. 포지션 사이즈 — 점수 차등

[direct_closing_bet.py:calc_position_qty](../scripts/direct_closing_bet.py)

| composite | 투자금 배수 (기본) | conviction sizing on |
|-----------|-------------------|----------------------|
| ≥ 85 | × 1.0 | × 2.0 |
| ≥ 70 | × 1.0 | × 1.5 |
| 55~70 | × 1.0 | × 1.0 |

기본 `INVESTMENT_PER_TRADE = 500,000원` (`.env`로 조정).

> **P0(2026-06-01)**: 점수 차등 사이징을 **기본 off(전 구간 1.0x)** 로 변경. 백테스트에서 70+ 구간이
> 오히려 부진(승률 50.0% / 평균 −0.13%, n=10)해 고확신 구간에 자본을 더 싣는 것이 금액가중 수익을 깎았다.
> 근거가 쌓이면 `CLOSING_BET_CONVICTION_SIZING=true`로 점수 차등을 다시 켤 수 있다.

## 5. 분산 — 섹터 집중 방지
- 섹터당 최대 **2종목** (`MAX_PER_SECTOR=2`)
- "반도체 5종목" 같은 상관 리스크 차단
- 섹터 정보는 FinanceDataReader → 실패 시 Kiwoom universe 캐시

## 6. 청산 규칙 — 보유기간 + ATR 트레일링 ([exit_rules.py](../src/mcp_servers/closing_bet_mcp/exit_rules.py))

**(a) 최대 `HOLD_DAYS` 영업일 보유 + (c) ATR 트레일링 스톱.** 매 영업일 09:00·15:10·18:05에
보유 전 종목을 평가한다 ([evaluate_hold_exit](../src/mcp_servers/closing_bet_mcp/exit_rules.py)):

| 시점 | 평가 | 청산 |
|------|------|------|
| 매수 직후 | `stop = 평단 − ATR_K×ATR` (ATR 없으면 `STOP_LOSS_PCT` 폴백) | — |
| 18:05 / 매 09:00·15:10 | 종가 최고점 갱신 시 `stop = max(stop, peak − ATR_K×ATR)` (상방만) | — |
| 매 09:00 | 현재가 ≤ stop | `SELL_ALL` (트레일/손절 이탈) |
| 매 15:10 | 현재가 ≤ stop **또는** 보유 ≥ `HOLD_DAYS` 영업일 | `SELL_ALL` (트레일 이탈 / 시간청산) |
| 그 외 | — | `HOLD` (다음 영업일 이월, stop 유지) |

**핵심 규칙**:
1. **부분 익절 없음** — 승자를 조기 절단하지 않고 ATR 트레일로 끝까지 추종(우측꼬리 포착).
2. **손절은 변동성 비례(ATR)** — 고정 -2% 일봉 근사 대체. ATR 데이터 부족 시 `STOP_LOSS_PCT` 폴백.
3. **시간청산**은 15:10에만 (`buy_date + HOLD_DAYS` 영업일 도달 시). 미만기 종목은 다음날 이월.
4. 트레일 스톱은 절대 내려가지 않음(상방 래칫) — 한번 확보한 이익을 보호.

> **검증 (atr2_h3, OOS)**: 동일 진입(55/3) 기준 p1(구 1일 청산) 대비 누적 net +120.9% vs +47.9%,
> 기대값 +1.15% vs +0.46%, 승률 47.6% vs 41.0%, P90 +11.9% vs +6.8%. 상세
> [docs/backtest_exit_policy_2026-06-01.md](backtest_exit_policy_2026-06-01.md).
> 승률 측정은 종목별 **net 가중 실현손익**(`exit_ledger`) — 모든 포지션이 트레일/시간청산으로 실현돼 HOLD 편향 없음.

> ⚠️ **트레이드오프**: 최대 `HOLD_DAYS` 오버나잇 노출(기본 3일). 단일 레짐(6개월) 검증이며
> 우측꼬리가 소수 종목에 의존 → 추세장 의존 가능. `CLOSING_BET_HOLD_DAYS=1`로 사실상 구 동작에 근접.

## 7. 운영 파라미터 (튜닝 가능)

| 파라미터 | 기본 | 환경변수 | 설명 |
|----------|------|----------|------|
| `MIN_SCORE` | 55.0 | `CLOSING_BET_MIN_SCORE` | 후보 최저 점수 (백테스트 검증) |
| `TOP_CANDIDATES` | 3 | `CLOSING_BET_TOP_CANDIDATES` | 1일 최대 종목 수 (3개가 5개보다 승률 ↑) |
| `MIN_VALUE_KRW` | 1,000억 | `CLOSING_BET_MIN_VALUE_KRW` | 거래대금 최저 임계 (원 단위) |
| `STOP_LOSS_PCT` | -2.0 | `CLOSING_BET_STOP_LOSS_PCT` | 손절 % (외부 권장 -1~-2%) |
| `INVESTMENT_PER_TRADE` | 500,000 | `INVESTMENT_PER_TRADE` | 1종목 기준 투자금 |
| `CATALYST_WEIGHT` | 0.0 | `CLOSING_BET_CATALYST_WEIGHT` | catalyst 블렌딩 가중 (0=technical-only, 백테스트와 동일) |
| `CONVICTION_SIZING` | false | `CLOSING_BET_CONVICTION_SIZING` | 점수 차등 사이징 on/off (기본 off=전 구간 1.0x) |
| `HOLD_DAYS` | 3 | `CLOSING_BET_HOLD_DAYS` | 최대 보유 영업일 (시간청산 기한). 1이면 사실상 구 1일 청산 |
| `INTRADAY_POLL_MIN` | 10 | `CLOSING_BET_INTRADAY_POLL_MIN` | 장중 트레일 점검 주기(분) — 일중 손절 이탈 포착 |
| `FORCE_PHASE` | false | `CLOSING_BET_FORCE_PHASE` | true 시 phase 일일 중복실행 가드 무시(수동 강제 재실행) |
| `ATR_K` | 2.0 | `CLOSING_BET_ATR_K` | 트레일 손절 밴드 = ATR_K × ATR |
| `ATR_PERIOD` | 14 | `CLOSING_BET_ATR_PERIOD` | ATR 평균 기간(봉) |
| `TAX/FEE/SLIPPAGE_BPS` | 18/1.5/10 | `CLOSING_BET_*_BPS` | 거래비용(편도 bps) — net 손익 차감 (왕복 ≈0.41%) |
| `MOCK_MODE` | true | `MOCK_MODE` | 모의 주문 |
| `MAX_PER_SECTOR` | 2 | (코드) | 섹터 분산 |
| `TOP_N_STOCKS` | 50 | (코드) | 거래대금 상위 N |
| `US_MARKET_WEAK_THR` | -1.5 | (코드) | 미국 야간 차단 임계 |

### 시장별 결과 패턴

| 시장 셋업 | 결과 |
|-----------|------|
| 약한 날 (60점 종목 0개) | **0개 진입** — 매수 안 함 |
| 보통 날 (60점 1~3개) | **1~3개 진입** |
| 좋은 날 (60점 5개+) | **상위 5개**, 섹터당 최대 2 |

## 8. 데이터 흐름

```
data/closing_bet/YYYY-MM-DD/
├── selection.json     # 시장 상태 + 전체 채점 + 후보 + 통계
├── buy.json           # 매수 주문 + 총 투자금
├── sell.json          # 청산 결과 + 승률 summary
└── events.jsonl       # 시계열 이벤트 (phase_start/market_filter/regime/us_market/
                       #   selection_done/buy/after_hours/sell/force_close/skip/error)
```

**상태 파일** (in-memory state 보조): `%TEMP%/closing_bet_state_direct.json`

**텍스트 로그** — 일자별 자동 회전 (자정 기준, 30일 보관):
```
logs/closing_bet/
├── closing_bet.log               # 활성 (오늘)
├── closing_bet.log.2026-05-10    # 회전된 백업
├── closing_bet.log.2026-05-09
└── ...
```

## 9. 실행 명령

### 일상 운영 (자동)
```bash
python scripts/direct_closing_bet.py --daemon
```
스케줄: 14:50 selection → 15:20 buy → 18:05 after_hours → 익일 09:00 sell

### 수동 phase 실행
```bash
python scripts/direct_closing_bet.py --phase selection
python scripts/direct_closing_bet.py --phase buy
python scripts/direct_closing_bet.py --phase after_hours
python scripts/direct_closing_bet.py --phase sell
```

### 테스트 / 상태 확인
```bash
python scripts/direct_closing_bet.py --test       # 즉시 선별 (주문 없음)
python scripts/direct_closing_bet.py --status     # 상태 확인
python check_status.py                            # MCP/A2A 헬스체크
```

### 대시보드
```bash
python scripts/dashboard.py                       # http://localhost:8090
```

## 10. 알림 (Telegram)

`.env`의 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 설정 시 4개 phase에서 자동 전송.

**선별 알림 예시**:
```
📊 종가배팅 후보 [05/11 14:50]
KOSPI +0.42%  레짐:neutral  양봉:54%
분석:50  MA20제외:18  갭제외:3  US S&P+0.8%/NQ+1.7%
1. 삼성전자(005930) [반도체] 📰
   점수 78  가 268,500원  수량 3주
2. LG에너지솔루션(373220) [2차전지] —
   점수 65  가 412,000원  수량 1주
```

## 11. 안전장치

| 항목 | 보호 |
|------|------|
| `MOCK_MODE=true` | 키움 모의투자만 사용 (실거래 차단) |
| `KIWOOM_PRODUCTION_MODE=false` | paper API 도메인 강제 |
| `STOP_LOSS -3%` | 손실 한도 |
| 6단계 게이트 | 셋업 미달 시 0종목 진입 |
| `MAX_PER_SECTOR=2` | 섹터 집중 위험 차단 |
| Token caching (24h) | 키움 API 부하 최소화 |

## 12. 참고
- 일별 dev-log: [docs/2026-05-09-dev-log.md](2026-05-09-dev-log.md), [docs/2026-05-10-dev-log.md](2026-05-10-dev-log.md)
- 시스템 헬스체크: `python check_status.py --watch`
- 분석 리포트 (CLI): `python scripts/direct_closing_bet.py --analyze --days 30`
