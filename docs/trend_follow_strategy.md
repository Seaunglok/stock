# 대형주 추세추종 전략 (Trend-Following) — 별도 트랙

종가매매(closing-bet)가 **KOSPI 약세장 veto**로 거래 자체가 안 일어나 검증 불가 상태가 이어졌다.
이 트랙은 개별 종목 추세·돌파를 보고 수일~수주 보유하며, **시장필터·종가매수에 의존하지 않아 하락장에서도
동작·검증**된다. Naver 블로그(ppassong) 2편 — **블로그A**(4단계 관리, 손익비 1:3) + **블로그B**(차수재시실
5조건)를 기계화했다. **종가매매 코드는 일절 수정하지 않는 완전 별도 트랙**(파일·state·로그·데몬·백테스트·대시보드).

## 철학 (블로그A)
- **손익비 1:3, 승률 낮아도 OK.** 첫 목표(= 손절폭×3) 도달 시 30% 익절, 나머지는 추세 끝까지 ATR 트레일.
- 청산: **이평선(MA120) 하방돌파** / 외국인 5일 순매도 전환 / 트레일 이탈. **시간청산 없음, 시장필터 없음.**
  (2026-06-12 A/B 검증: 청산선 MA120 ≫ MA50 — 기대값·누적 2~4배. "추세 끝까지 탑승" 철학·PDF와 일치. `TREND_EXIT_MA`.)
- → 이번 세션 closing-bet 청산정책 백테스트 결론(`atr2_h3`: 저승률·우측꼬리·ATR 트레일)과 일치 → 청산/트레일 인프라 재사용.

## "차수재시실" 5조건 (블로그B) → 기계화
| 조건 | 기계화 | 재사용 |
|------|--------|--------|
| **차트** | 현재가>MA200 & 기울기↑; 횡보 후 첫 장대양봉(몸통≥4% & 위꼬리≤0.3) | `scorer.score_consolidation/score_candle_shape` + 신규 MA200·장대양봉 |
| **수급** | 외인5일·기관5일 순매수>0 | `scorer.score_institutional`, investor-domain MCP |
| **재료** | DART 공시 호재 + 뉴스 테마 | `catalyst.match_trends`, 정보레이어 (라이브 가점) |
| **시황** | 당일 주도섹터 집단상승 | ✅ `leading_sectors`(순수함수) + 09:30 장중 등락 스냅샷 — 가점(기본)/게이트(opt-in) |
| **실적** | 매출/영업이익 YoY↑·어닝서프라이즈 | ✅ `fundamentals_bonus`(순수함수) + DART finstate 당기/전기 YoY — 가점 |

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
| 08:50 | `screen` | 모드별 유니버스 스캔(완성봉) → entry_signal 게이트·점수 → 후보. 프리장 예상가·JH ZONE·실적 YoY 가점 표시 |
| 09:30 | `entry` | 동일비중 매수(최대 `TREND_MAX_POS`=5). 주도섹터 가점 재정렬. **하락 중 후보 보류→장중 반등 시 진입(10:30 컷오프 후 스킵)**. return_code 게이트(유령 방지) |
| (장중) | `intraday` | `TREND_POLL_MIN` 주기 트레일 갱신 + 첫목표 30% 부분익절 + 하드손절(`TREND_HARD_STOP_PCT`, 기본off) + 보류분 반등 점검 |
| 15:20 | `exit` | 계좌 보유분 편입(reconcile) → **MA120 이탈**(`TREND_EXIT_MA`) / 외인 5일 순매도전환 / 트레일 이탈 청산 |

**안전장치**: 주문 `return_code` 검증 + `[REJECT]` 로깅, 단일 인스턴스 락(`data/trend_follow/daemon.lock`),
물타기 금지(1종목 1진입), 텔레그램 HTML 안전화, exit_ledger net 손익, 자정 회전 로그(`logs/trend_follow/`, 30일), `events.jsonl`.

**매매일지** (`data/trend_follow/journal.jsonl`, append-only):
- 자동(진입/부분/청산): 일시·종목·모드·진입가/손절/목표·청산가·수량·**손익률·net·손익비·청산사유·진입근거(게이트)·보유일수**.
- 수동(블로그 4단계): **심리상태 / 실수분석 / 개선점** — 대시보드 인라인 폼 또는
  `--journal-note <id> --psych "..." --mistake "..." --improve "..."` CLI.

**대시보드** — `scripts/trend_dashboard.py` (:8091, 종가매매 :8090 와 별개):
탭 ① 보유 포지션(손익·트레일 stop) ② 거래 내역(승률·손익비 payoff·net) ③ 매매일지(근거+심리/실수/개선 편집·저장).

## 운영 안정성 (watchdog) · 실거래 전환 준비
**문제**: 데몬·MCP 서버는 별도 프로세스라 PC 절전/콘솔 종료/인터럽트로 죽을 수 있다. 보유 중 데몬이
죽으면 손절·트레일 관리가 멈춰 실포지션이 방치된다(실거래 치명적). 두 단계로 방어한다.

1. **서버 분리 기동** (`run_mcp_local.py`): 자식 MCP 서버를 Windows `CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS`
   (그 외 OS `start_new_session`)로 띄워 런처 콘솔의 Ctrl+C/종료가 서버로 전파돼 동반 종료되는 것을 차단.
2. **watchdog** (`scripts/trend_watchdog.py` + `.cmd`): 멱등 복구 스크립트. 필수 MCP 포트(8030–8034)가
   죽었으면 `stop→start`(중복 세트 누적 방지)로 재기동, 데몬 락 PID가 죽었으면 분리 기동으로 재시작,
   둘 다 살아있으면 무동작. 주말은 즉시 종료. **작업스케줄러** 등록(평일 장중 5분 주기):
   ```bat
   schtasks /Create /TN KiwoomTrendWatchdog /TR "...\scripts\trend_watchdog.cmd" /SC DAILY /ST 08:40 /RI 5 /DU 07:15 /F
   ```
   (`/RI 5 /DU 07:15` = 08:40~15:55 5분 반복. `/ET`는 `/SC DAILY`에서 종료*일*로 오인되니 `/DU` 사용.)
   로그 `logs/trend_follow/watchdog.log`(이상 시에만 기록)·`daemon_stdout.log`.

**실거래 전환 전 권장 .env**(MOCK 에서도 동작): `TREND_HARD_STOP_PCT=7`(트레일 무관 즉시 손절 백스톱),
`TREND_DAILY_LOSS_LIMIT_PCT=2`(당일 실현손실>예탁 2% 시 신규진입 중단). 첫 실전은 사이징·종목수 축소
(예: `TREND_POSITION_PCT=2~3`·`TREND_MAX_POS=3~5`)로 실체결 경로(return_code/슬리피지/reconcile) 검증 후 확대.

## 파라미터 (env, 기본값)
```bash
TREND_UNIVERSE=watchlist            # watchlist(기본) | largecap | gainers(v2)
TREND_WATCHLIST=005930,000660       # watchlist 모드 종목 (삼성전자·SK하이닉스)
TREND_TOP_N=100                     # largecap 시총상위 / gainers 등락률상위(30)
TREND_MIN_VALUE_KRW=1e11            # 거래대금 floor 1,000억 (잡주/저유동 배제)
TREND_MAX_POS=10                    # 최대 동시 보유(편입분 포함). .env 영속
TREND_SIZING_MODE=pct_equity        # pct_equity(예탁자산 %) | fixed(고정금액)
TREND_POSITION_PCT=8                 # 종목당 예탁자산의 8% (현금 한도 내). 10종목 ≈ 80% 투입·20% 버퍼
TREND_INVEST_PER_TRADE=500000       # fixed 모드 또는 예탁자산 조회 실패 시 폴백
TREND_EXIT_MA=120                   # 청산 이평선(A/B 검증 채택). MA50→MA120
TREND_ENTRY_WAIT_FALLING=true TREND_ENTRY_CUTOFF=10:30  # 하락 보류→반등 진입, 마감시각
TREND_HARD_STOP_PCT=0               # 하드손절 %(0=off, ATR 트레일 우월)
TREND_DAILY_LOSS_LIMIT_PCT=0        # 일일 최대손실 서킷브레이커: 당일 실현손실>예탁자산 X% 시 신규진입 중단(0=off)
TREND_MA_FAST=60 TREND_MA_SLOW=120 TREND_MA_PULLBACK=20 TREND_PULLBACK_PCT=3 TREND_RS_DAYS=60
TREND_MA_TREND=200 TREND_MA_SUPPORT=50 TREND_VOL_MULT=2.0 TREND_BODY_PCT=4 TREND_WICK_MAX=0.3   # gainers
TREND_STOP_PCT=7 TREND_ATR_K=2.0 TREND_RR=3 TREND_PARTIAL_PCT=30
TREND_USE_FOREIGN_EXIT=true TREND_NEWS_VETO=true   # 라이브. MOCK_MODE 공유.
TREND_FUND_BONUS=5                  # 실적 가점: 매출·영업이익 YoY 동반↑ +5점(영업이익만 +2.5) — 순위만, 0=off
TREND_SECTOR_BONUS=5                # 주도섹터 가점: 집단상승 섹터 소속 후보 +5점 — 0=off
TREND_SECTOR_GATE=false             # true 면 주도섹터 소속 후보만 진입(하드 게이트) — 기본 가점만
TREND_SECTOR_MIN_AVG=1.0 TREND_SECTOR_BREADTH=0.6 TREND_SECTOR_TOP_K=3  # 주도 판정: 평균등락/상승비율/상위K
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
- `src/mcp_servers/trend_mcp/signals.py` — 순수 함수(MA/기울기/횡보후장대양봉/RS/종합점수/청산 + `classify_zone` JH ZONE + `fundamentals_bonus` 실적 + `leading_sectors` 주도섹터 + `position_size`/`exit_decision`/`is_rising` 실행결정). scorer·exit_rules 재사용.
- `scripts/backtest_trend.py` — 비용포함 백테스트(3모드) + 갭다운 veto 스윕(`--gapdown-sweep`) + A/B(`--abtest`). `backtest_dynamic`·`backtest_walkforward` 재사용.
- `scripts/trend/` — 데몬 레이어 패키지: `config.py`(env·상수·logger), `kiwoom_io.py`(키움 MCP I/O), `market_data.py`(pykrx 시세/유니버스).
- `scripts/trend_follow.py` — MOCK 라이브 데몬(상태/락/매매일지/알림 + 스크린/진입/장중/청산 + 하락보류진입 + 계좌편입 reconcile + 실적·섹터 가점 + 일일손실 서킷브레이커) + 일별로그.
- `scripts/trend_dashboard.py` — :8091 대시보드(보유/거래/매매일지, 프리장·근거 표시).
- `tests/test_trend_signals.py` — 순수함수 회귀(54: 지표/진입/청산 + JH ZONE 6 + 실적 3 + 주도섹터 3).

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

**A/B 검증 완료(2026-06-12, `backtest_trend.py --abtest`)**:
| 변형 | largecap 기대값/누적 | watchlist 기대값/누적 | 결정 |
|------|------|------|------|
| 기준(1:3·MA50·ATR) | +2.00% / +564% | +4.29% / +116% | — |
| **청산선 MA120** | **+5.19% / +1465%** | **+17.54% / +474%** | ✅ **채택**(`TREND_EXIT_MA=120`) |
| 첫익절 1:1 | +1.76% / +496% | +3.37% / +91% | ❌ 1:3 유지 |
| 하드손절 −5% | +0.48% / +135% | +1.77% / +48% | ❌ off 유지(ATR 트레일 우월) |

→ **청산선 MA50→MA120 채택**(두 표본·이론·PDF 일치, 단일 파라미터, 추세 끝까지 탑승). 첫익절 1:3·하드손절 off 는 검증상 현행이 우월해 유지. RS 상위20% 컷은 미검증(추후).

## 라이브 가점 레이어 (v2, 2026-06-11) — 차수재시실 '실적'·'시황' 기계화

검증된 진입 게이트/점수(백테스트 엣지)는 **무변경** — 후보 **순위 가점**으로만 반영 (closing-bet 정보레이어와 동일 철학).
- **실적 자동 가점** (`fundamentals_bonus` 순수함수): 08:50 screen 에서 후보 한정 DART `finstate` 당기/전기 비교 →
  매출·영업이익 YoY 동반 증가 +5점, 영업이익만 +2.5점. 30일 디스크 캐시(`docs_cache/dart_fin/`).
  `DART_API_KEY` 없음/조회 실패 시 가점 생략(veto 아님). Telegram·journal 에 YoY 표시.
- **주도섹터 집단상승** (`leading_sectors` 순수함수): 09:30 entry 직전 키움 **업종지수 스냅샷**(ka20001,
  info-domain :8032 — KOSPI 27개 업종의 등락률+상승/하락/보합 종목수) → 등락률 ≥1.0% AND 상승비율 ≥60%
  AND 구성 ≥3 인 상위 3개 섹터를 주도섹터로 판정. 소속 후보 +5점 재정렬(기본). `TREND_SECTOR_GATE=true` 면
  주도섹터 소속만 진입(하드 게이트, opt-in). 업종지수 미확보(서버 다운) 시 **fail-open**(판정 생략, 게이트도
  미적용). `sector_rally` 이벤트 기록. ※ KRX 전종목 스냅샷(pykrx by_ticker)은 KRX 로그인 필요로 불가 → 키움 소스 채택.

## TODO (v2)
- ~~RS 게이트 절대값(>KOSPI) vs 상위 N% 랭킹 검증~~ → 2026-06-19 백테스트(largecap, ~2026-06-18, `--rstest`):
  **절대 RS>0 우월**(기대값 +1.87%·PF 1.49·진입 278 / 상위40% +1.47%·진입210 / 상위30% +0.96% / 상위20% +0.48% /
  RS off −0.15%). 절대값은 레짐 적응형(breadth 좋을 때 후보↑, 멜트업에 후보↓)이라 고정비율 컷보다 낫다 → **현행 유지**.
  멜트업 장 "후보 0"은 게이트가 추격을 자제하는 정상 동작(보유 승자 유지). 변경 없음.
- ~~피라미딩(승자 불타기) 검증~~ → 2026-06-19 백테스트(largecap, `--pyramidtest`/`--pyramidregime`/`--pyramidequity`,
  각 유닛=별도 거래). **강세장 참여도↑ 동기**(강세장인데 예탁 64%가 현금·승자를 가장 작게 보유). 결과:
  - **무조건 피라미딩**: 추세장(2025-01~2026-06 기대값 +1.87→+2.70%·누적 +520→+1181%) 우월하나 **횡보장(2025)은 손실 증폭**(−0.62→−0.81%·누적 −136→−254%) → 항상 켜면 위험.
  - **시장지표 게이트(KOSPI>MA50/120·60일모멘텀)**: 2025·2026 둘 다 KOSPI가 상승이라 **두 레짐 구분 실패**(횡보장 억제 0) → 기각.
  - **✅ equity-curve 게이트(최근 ~20 청산거래 평균 net>0일 때만 불타기)**: 횡보장 손실 **−254→−45%**(베이스 −136보다도 나음), 추세장 **+520→+654%**·유닛당 기대값 유지(+1.83%). "전략이 통할 때만" 직접 추적 → **채택**.
  → 라이브 **opt-in**(기본 off) 구현: `+2유닛 @1R`, 게이트=최근 20 청산 net 평균>0. 한계: 베이스가 진 구간(2025 −0.17%)을 흑자로 바꾸진 못함(증폭만 차단), P10 −10.5→−11% 소폭 악화.
- gainers 모드 음(−)기대값 재설계(등락률 진짜 상위 소형주 유니버스 + 재료/수급 라이브 반영).
- ~~실적(재무) 자동 가점, 주도섹터 집단상승 라이브 게이트~~ → 2026-06-11 구현(위 '라이브 가점 레이어').
- 어닝서프라이즈(분기 컨센서스 대비) 가점 — 현재는 연간 YoY 만.
- MOCK 며칠 관찰 후 실전 전환 논의.
