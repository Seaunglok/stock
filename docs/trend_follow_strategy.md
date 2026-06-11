# 대형주 추세추종 전략 (Trend-Following) — 별도 트랙

종가매매(closing-bet)가 **KOSPI 약세장 veto**로 거래 자체가 안 일어나 검증 불가 상태가 이어졌다.
이 트랙은 개별 종목 추세·돌파를 보고 수일~수주 보유하며, **시장필터·종가매수에 의존하지 않아 하락장에서도
동작·검증**된다. Naver 블로그(ppassong) 2편 — **블로그A**(4단계 관리, 손익비 1:3) + **블로그B**(차수재시실
5조건)를 기계화했다. **종가매매 코드는 일절 수정하지 않는 완전 별도 트랙**(파일·state·로그·데몬·백테스트·대시보드).

## 철학 (블로그A)
- **손익비 1:3, 승률 낮아도 OK.** 첫 목표(= 손절폭×3) 도달 시 30% 익절, 나머지는 추세 끝까지 ATR 트레일.
- 청산: 이평선(MA50) 하방돌파 / 외국인 5일 순매도 전환 / 트레일 이탈. **시간청산 없음, 시장필터 없음.**
- → 이번 세션 closing-bet 청산정책 백테스트 결론(`atr2_h3`: 저승률·우측꼬리·ATR 트레일)과 일치 → 청산/트레일 인프라 재사용.

## "차수재시실" 5조건 (블로그B) → 기계화
| 조건 | 기계화 | 재사용 |
|------|--------|--------|
| **차트** | 현재가>MA200 & 기울기↑; 횡보 후 첫 장대양봉(몸통≥4% & 위꼬리≤0.3) | `scorer.score_consolidation/score_candle_shape` + 신규 MA200·장대양봉 |
| **수급** | 외인5일·기관5일 순매수>0 | `scorer.score_institutional`, investor-domain MCP |
| **재료** | DART 공시 호재 + 뉴스 테마 | `catalyst.match_trends`, 정보레이어 (라이브 가점) |
| **시황** | 당일 주도섹터 집단상승 | 동적테마 패턴 (라이브) |
| **실적** | 매출/영업이익 YoY↑·어닝서프라이즈 | financial MCP (v2) |

거래량 폭발(2배+)은 `scorer.score_volume_surge` 재사용. **백테스트는 차트+거래량+수급+RS 코어만**
(재료/실적/뉴스는 point-in-time 불가 → 라이브 가점·악재 veto로만 반영).

## 3 진입 모드 (`TREND_UNIVERSE` env 토글, 기본 `watchlist`)
점수·관리·청산은 공유하고 **유니버스 + 진입 트리거만** 다르다.
- **`watchlist`** (기본, 집중): `TREND_WATCHLIST` 고정 종목(기본 `005930,000660` 삼성전자·SK하이닉스).
  시장 스캔 없이 그 종목만 매일 추세·눌림·돌파 점검 → 타점만 잡음. largecap 게이트 사용.
- **`largecap`** (정석 추세): KOSPI 시총 상위 N(100). 게이트 = 현재가>MA60 & >MA120(정배열) + RS(60일)>KOSPI
  + 이평선 눌림 터치(현재가 ≤ MA20×1.03) + 거래량 증가.
- **`gainers`** (모멘텀/돌파, **v2 보류**): 당일 등락률 상위 N(30). 게이트 = 현재가>MA200 & 우상향 +
  횡보 후 첫 장대양봉 + 거래량≥20일평균×2.0 + MA50 지지권.

## 백테스트 결과 (2025-01-01 ~ 2026-05-31, 비용 차감 후)
| 모드 | 진입 | 승률 | 기대값(net) | 손익비(payoff) | 누적 | 판정 |
|------|------|------|------------|---------------|------|------|
| **watchlist**(삼성·하이닉스) | 27 | 33.3% | **+4.29%** | **4.38** | +116% | ✅ 최고 (사용자 직관 검증) |
| **largecap** | 282 | 37.6% | **+2.00%** | 2.61 | +564% | ✅ 검증됨 |
| gainers | 25 | — | −1.82% | — | — | ⛔ v2 보류 |

비교: closing-bet `atr2_h3` OOS 기대값 +1.15%(동일 구간 0거래) / 진입규칙 고정(파라미터 피팅 없음 → 과최적화 낮음).
블로그 철학 "승률 낮아도 손익비만 맞추면 수익" 확인. 동일 구간 closing-bet 0거래 → **검증불가 문제 해소**.

## 라이브 (MOCK 우선) — `scripts/trend_follow.py`
`direct_closing_bet.py` 구조 미러. MCP 서버만 떠 있으면 동작. **별도 트랙**.

**스케줄** (영업일):
| 시각 | phase | 동작 |
|------|-------|------|
| 08:50 | `screen` | 모드별 유니버스 스캔 → entry_signal 게이트·점수 → 후보 |
| 09:30 | `entry` | 동일비중 매수(최대 `TREND_MAX_POS`=5). return_code 게이트(유령 방지) |
| (장중) | `intraday` | `TREND_POLL_MIN` 주기 트레일 갱신 + 첫목표 30% 부분익절 |
| 15:20 | `exit` | MA50 이탈 / 외인 5일 순매도전환 / 트레일 이탈 청산 |

**안전장치**: 주문 `return_code` 검증 + `[REJECT]` 로깅, 단일 인스턴스 락(`data/trend_follow/daemon.lock`),
exit_ledger net 손익, 자정 회전 로그(`logs/trend_follow/`, 30일), `events.jsonl`, 텔레그램.

**매매일지** (`data/trend_follow/journal.jsonl`, append-only):
- 자동(진입/부분/청산): 일시·종목·모드·진입가/손절/목표·청산가·수량·**손익률·net·손익비·청산사유·진입근거(게이트)·보유일수**.
- 수동(블로그 4단계): **심리상태 / 실수분석 / 개선점** — 대시보드 인라인 폼 또는
  `--journal-note <id> --psych "..." --mistake "..." --improve "..."` CLI.

**대시보드** — `scripts/trend_dashboard.py` (:8091, 종가매매 :8090 와 별개):
탭 ① 보유 포지션(손익·트레일 stop) ② 거래 내역(승률·손익비 payoff·net) ③ 매매일지(근거+심리/실수/개선 편집·저장).

## 파라미터 (env, 기본값)
```bash
TREND_UNIVERSE=watchlist            # watchlist(기본) | largecap | gainers(v2)
TREND_WATCHLIST=005930,000660       # watchlist 모드 종목 (삼성전자·SK하이닉스)
TREND_TOP_N=100                     # largecap 시총상위 / gainers 등락률상위(30)
TREND_MIN_VALUE_KRW=1e11            # 거래대금 floor 1,000억 (잡주/저유동 배제)
TREND_MAX_POS=5  TREND_INVEST_PER_TRADE=500000
TREND_MA_FAST=60 TREND_MA_SLOW=120 TREND_MA_PULLBACK=20 TREND_PULLBACK_PCT=3 TREND_RS_DAYS=60
TREND_MA_TREND=200 TREND_MA_SUPPORT=50 TREND_VOL_MULT=2.0 TREND_BODY_PCT=4 TREND_WICK_MAX=0.3   # gainers
TREND_STOP_PCT=7 TREND_ATR_K=2.0 TREND_RR=3 TREND_PARTIAL_PCT=30
TREND_USE_FOREIGN_EXIT=true TREND_NEWS_VETO=true   # 라이브. MOCK_MODE 공유.
```

## 실행
```bash
# 백테스트 (선검증)
python scripts/backtest_trend.py --mode watchlist --watchlist 005930,000660 --start 2025-01-01 --end 2026-05-31
python scripts/backtest_trend.py --mode largecap

# 라이브 (MOCK) — MCP 서버 가동 후
python scripts/trend_follow.py --phase screen     # 후보 선별 (주문 없음)
python scripts/trend_follow.py --daemon           # 08:50/09:30/장중/15:20 자동
python scripts/trend_follow.py --status
python scripts/trend_dashboard.py                 # http://localhost:8091

# 순수함수 회귀
python -m pytest tests/test_trend_signals.py -q
```

## 파일
- `src/mcp_servers/trend_mcp/signals.py` — 순수 함수(MA/기울기/횡보후장대양봉/RS/종합점수/청산). scorer·exit_rules 재사용.
- `scripts/backtest_trend.py` — 비용포함 백테스트(3모드). `backtest_dynamic`·`backtest_walkforward` 재사용.
- `scripts/trend_follow.py` — MOCK 라이브 데몬 + 매매일지 + 일별로그.
- `scripts/trend_dashboard.py` — :8091 대시보드(보유/거래/매매일지).
- `tests/test_trend_signals.py` — 순수함수 회귀(13).

## PDF 설계가이드(이종호 대형주 추세추종) 대조

`trading_system_guide.pdf` 와 현재 구현 비교. **대부분 일치**, 일부는 보강/검증대기.

| 항목 | PDF | 우리 구현 | 상태 |
|------|-----|-----------|------|
| 손익비 3:1·저승률 OK | 핵심 | rr=3, 첫목표 1:3 | ✅ 일치 |
| 시총상위 100 유니버스 | KOSPI200/시총100 | largecap 시총상위 100 | ✅ |
| 정배열 Price>MA60·MA120 | 게이트 | gates price>MA60·MA120 | ✅ |
| 상대강도 RS(60일) | 상위 20% | RS>0 (코스피 대비) | ⚠️ 우리가 더 느슨(>0) |
| 거래량/유동성 floor | 잡주 배제 | MIN_VALUE_KRW 1,000억 | ✅ |
| 진입 09:30~10:30 | 타임프레임 제한 | 09:30 + 보류 반등(≤10:30 컷오프) | ✅ 보강 |
| 첫목표 30% 부분익절 | **1:1 지점** | **1:3 지점(target)** | ⚠️ 차이(검증대기) |
| 트레일 청산 | 고점대비 고정 7% | ATR 트레일(atr_k×ATR) | ⚠️ 우리가 변동성적응 |
| 하드 손절 | **진입가 -5% 즉시** | ATR init_stop(−7% floor) + 옵션 HARD_STOP_PCT | ⚠️ 옵션화(기본 off) |
| 이평선 청산 | **MA120 이탈** | **MA50 이탈** | ⚠️ 차이(검증대기) |
| 물타기 금지(1종목1진입) | 절대원칙 | _buy_one 가드 | ✅ 보강 |
| 충동/뉴스추격 금지 | 절대원칙 | 스크린 유니버스 내에서만 진입 | ✅ |
| 손절 오버라이드 금지 | 절대원칙 | 자동 청산, 수동개입 없음 | ✅ |
| 호가 스캘핑 금지 | 절대원칙 | 일봉 기반 | ✅ |
| 매매일지/로그 강제 보존 | 절대원칙 | journal.jsonl + events + 회전로그 | ✅ |
| JH ZONE(GO/HOLD/CAUTION/STOP_LOSS) | 매매구역 모델 | classify_zone + 라벨 표시 | ✅ 보강 |

**보강 완료(검증 엣지 보존)**: JH ZONE 라벨, 진입 10:30 컷오프, 물타기 가드, 하드손절 옵션(`TREND_HARD_STOP_PCT`).
**검증 대기(백테스트 후 결정)**: ① 첫목표 1:1 vs 1:3 부분익절, ② 청산선 MA120 vs MA50, ③ RS 상위20% 컷,
④ 하드손절 −5% 상시. 이들은 검증된 largecap +2.00%/watchlist +4.29% 설정을 바꾸므로 `backtest_trend` 로
A/B 비교 후 채택 결정(현재 기본값은 검증 설정 유지).

## TODO (v2)
- gainers 모드 음(−)기대값 재설계(등락률 진짜 상위 소형주 유니버스 + 재료/수급 라이브 반영).
- 실적(재무) 자동 가점, 주도섹터 집단상승 라이브 게이트.
- MOCK 며칠 관찰 후 실전 전환 논의.
