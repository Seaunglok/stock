# 종가매매(Closing Bet) 전략 — 운영 명세

> 자동매매 스크립트: [scripts/direct_closing_bet.py](../scripts/direct_closing_bet.py)
> 채점/판단 모듈: [src/mcp_servers/closing_bet_mcp/](../src/mcp_servers/closing_bet_mcp/)
> 대시보드: `python scripts/dashboard.py` → http://localhost:8090

## 1. 전략 개요

전일 종가에 매수해 다음날 시초가/장중에 청산하는 **단기 스윙(보유 1영업일)** 전략.

```
14:50  선별 phase  →  거래대금 상위 50종목 채점
15:20  매수 phase  →  점수 60+ 1~5종목 종가 시장가 매수
18:05  AH phase    →  시간외 단일가로 익일 청산 우선순위 미리 산정
09:00  매도 phase  →  evaluate_exit() 신호로 청산
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
- 당일 종가가 전일 대비 +4% 이상 → 후보 제외
- 이벤트성 급등은 익일 차익실현 압력 큼

### Gate 6: composite 점수 ≥ 60
- 모든 필터 통과 후 6개 기준 가중 합산 (아래 §3)
- **60점 미만은 후보 0개도 허용** — 시장이 약하면 매수 안 함

## 3. 채점 — 6개 기준 + 재료 가중

[scorer.py:compute_technical_scores_hybrid](../src/mcp_servers/closing_bet_mcp/scorer.py)

| # | 기준 | 가중 | 핵심 로직 |
|---|------|------|-----------|
| 1 | volume_surge | 25% | 오늘 거래대금 / 20일 평균 (3배 = 50점, 5배+ = 100점) |
| 2 | resistance_proximity | 20% | 90일 전고점 대비 갭 (-8% ~ -3% = 만점) |
| 3 | candle_shape (v2) | 15% | 위꼬리 비율 큼 → 익일 추격매수 여지 (회귀로 부호 반전 확인) |
| 4 | consolidation | 20% | 90일 고점 → 조정 → 회복 패턴 (조정 30봉+ 보너스 +10) |
| 5 | institutional | 20% | 외인·기관 5일 누적 양매수 (둘 다 = 100, 하나 = 60) |
| 6 | catalyst | (별도) | 트렌드 키워드 매칭 (AI/반도체, 2차전지, 방산, 바이오, 원전, 로봇, 조선, 양자) |

**최종 합산 공식**:
```python
cat_weight = 0.30 if cat.has_catalyst else 0.0
composite = cat.score * cat_weight + tech.composite() * (1.0 - cat_weight)
```

> 재료 있는 종목만 30% 가중. 조용한 종목을 페널티하지 않음.

## 4. 포지션 사이즈 — 점수 차등

[direct_closing_bet.py:calc_position_qty](../scripts/direct_closing_bet.py)

| composite | 투자금 배수 | 의도 |
|-----------|-------------|------|
| ≥ 85 | INVESTMENT_PER_TRADE × 2.0 | 초고확신 |
| ≥ 70 | × 1.5 | 고확신 |
| 60~70 | × 1.0 | 표준 |

기본 `INVESTMENT_PER_TRADE = 500,000원` (`.env`로 조정).

## 5. 분산 — 섹터 집중 방지
- 섹터당 최대 **2종목** (`MAX_PER_SECTOR=2`)
- "반도체 5종목" 같은 상관 리스크 차단
- 섹터 정보는 FinanceDataReader → 실패 시 Kiwoom universe 캐시

## 6. 청산 규칙 ([evaluate_exit](../src/mcp_servers/closing_bet_mcp/exit_rules.py))

우선순위 (위에서부터 평가):

| 조건 | 액션 | 수량 |
|------|------|------|
| 시간외 가격 < 평단 | `SELL_ALL` | 100% |
| 정규장 -3% 이탈 | `STOP_LOSS` | 100% |
| 09:00~09:05 + 수익 | `PARTIAL_SELL` | 33% (1/3 익절) |
| 09:05 이후 + +2% 이상 | `SELL_ALL` | 100% (탐욕 X) |
| 정규장 +3% 이상 | `PARTIAL_SELL` | 50% |
| 그 외 | `HOLD` | 0% |

**핵심 규칙**:
1. 손절은 -3% 한도 (노이즈 손절 방지)
2. 시초가 수익은 1/3만 익절 (러닝)
3. 9:05 지나면 +2% 이상은 전량 매도 (욕심 X)
4. 시간외 하락 시 익일 09:00 즉시 매도 (애프터마켓 신호 우선)

## 7. 운영 파라미터 (튜닝 가능)

| 파라미터 | 기본 | 환경변수 | 설명 |
|----------|------|----------|------|
| `MIN_SCORE` | 60.0 | `CLOSING_BET_MIN_SCORE` | 후보 최저 점수 |
| `TOP_CANDIDATES` | 5 | `CLOSING_BET_TOP_CANDIDATES` | 1일 최대 종목 수 (상한) |
| `INVESTMENT_PER_TRADE` | 500,000 | `INVESTMENT_PER_TRADE` | 1종목 기준 투자금 |
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
                       #   selection_done/buy/after_hours/sell/skip/error)
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
