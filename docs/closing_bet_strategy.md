# 종가매매(Closing Bet) 전략 — 운영 명세

> 자동매매 스크립트: [scripts/direct_closing_bet.py](../scripts/direct_closing_bet.py)
> 채점/판단 모듈: [src/mcp_servers/closing_bet_mcp/](../src/mcp_servers/closing_bet_mcp/)
> 대시보드: `python scripts/dashboard.py` → http://localhost:8090

## 1. 전략 개요

전일 종가에 매수해 다음날 시초가/장중에 청산하는 **단기 스윙(보유 1영업일)** 전략.

```
14:50  선별 phase    →  거래대금 1,000억원+ × 상위 50종목 채점
15:15  매수 1차      →  점수 60+ 1~5종목, 의도 수량의 50% 시장가 매수
15:19  매수 2차      →  마감 직전, 잔여 50% 시장가 매수
18:05  AH phase      →  시간외 단일가로 익일 청산 우선순위 미리 산정
09:00  매도 phase    →  evaluate_exit() 신호로 청산 (부분청산 가능)
15:10  강제청산 phase →  09:00 잔량(부분청산 후 잔여/HOLD) 전량 시장가 청산 → 오버나잇 잔량 0
```

매수 후 보유 시간 ≈ 18시간. **하룻밤 위험**을 감수하는 대신, 종가 부근의 셋업(거래대금·매물대·외인 양매수)이 익일 시초가에 추가 매수세를 끌어올 확률에 베팅.

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

## 6. 청산 규칙 ([evaluate_exit](../src/mcp_servers/closing_bet_mcp/exit_rules.py))

우선순위 (위에서부터 평가):

| 조건 | 액션 | 수량 |
|------|------|------|
| 시간외 가격 < 평단 **AND** 시초가 ≤ 평단 | `SELL_ALL` | 100% |
| 정규장 `STOP_LOSS_PCT` 이탈 | `STOP_LOSS` | 100% |
| 09:00~09:05 + 수익 | `PARTIAL_SELL` | 33% (1/3 익절) |
| 09:05 이후 + +2% 이상 | `SELL_ALL` | 100% (탐욕 X) |
| 정규장 +3% 이상 | `PARTIAL_SELL` | 50% |
| 그 외 | `HOLD` | 0% (→ 15:10 강제청산) |

**핵심 규칙**:
1. 손절은 `STOP_LOSS_PCT` 한도 (기본 -2.0%, 노이즈 손절 방지)
2. 시초가 수익은 1/3만 익절 (러닝). HOLD/부분청산 잔량은 **같은 날 15:10 강제청산** → 1영업일 보유 보장.
3. 9:05 지나면 +2% 이상은 전량 매도 (욕심 X)
4. **(P1 2026-06-01)** 시간외 하락은 시초가도 평단 이하일 때만 즉시 전량 매도. 밤사이 회복해
   시초 갭업한 종목까지 투매하던 문제를 수정 — 시초 회복(현재가 > 평단) 시엔 정상 룰에 위임.

> **승률 측정 (P1)**: 모든 포지션이 09:00 부분청산 + 15:10 강제청산으로 1영업일 내 실현되며,
> sell.json 의 승률은 종목별 **가중 실현손익**(`exit_ledger` 합산)으로 계산된다. 과거 `HOLD`를
> 분모에서 제외해 승률이 상향 편향되던 문제 제거.

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
