<!-- 2026-11-12 CLAUDE.md 정리(리팩터링 2번) 전 원문 그대로. CLAUDE.md 는 gitignore 대상이라 옮긴 내용이 사라지지 않게
     여기 남긴다. 종료한 트랙(종가매매·대형주 추세추종)의 운영·검증 설명은 이 파일과 docs/README.md 가 정본. -->
# CLAUDE.md — Kiwoom Closing-Bet 자동매매 시스템

> ## 🇰🇷 응답 언어 — 반드시 한국어 (운용자 지시, 2026-10-22)
> **사용자에게 보내는 모든 문장은 한국어로 쓴다.** 최종 답변뿐 아니라 도구 호출 사이의 진행 메시지,
> 표, 결정 요청까지 전부. 웹 검색 결과·논문·코드가 영어여도 답변은 한국어로 옮긴다.
> 코드 식별자·파일 경로·커밋 해시·명령어만 원문 그대로 둔다. 문서(docs/)·커밋 메시지도 한국어.
> (10-21~22 에 영어로 답했다가 여러 번 지적받았다 — 긴 분석·표가 있는 답일수록 보내기 전에 확인할 것.)

키움증권 **종가매매(closing-bet) 자동매매** 시스템 + 도메인별 **FastMCP 서버**. (구 A2A 멀티에이전트
플랫폼은 2026-06 제거 — `scripts/direct_closing_bet.py` standalone 데몬이 MCP 서버만 사용해 동작한다.)

> **추세추종 트랙(2026-06-08 추가, 2026-08-28 전면 재설계)**: 종가매매가 KOSPI 약세장 veto로 검증불가가
> 이어져, 시장필터·종가매수에 의존하지 않고 개별 종목 추세를 수주~수개월 추종하는 **대형주 추세추종**을
> 완전 별도 트랙으로 추가했다(종가매매 코드 무수정).
>
> ## ⚠️ 이 절을 읽기 전에 — 2026-08-27~28 에 검증 방법과 전략이 함께 바뀌었다
> 그 이전 문서·커밋의 기대값 수치(+3.38%, +17.5% 등)는 **전부 무효**다. 세 결함이 겹쳐 있었다:
> ① OHLCV 로더가 종료일 기준 고정 봉수만 가져와 `--start` 가 무시됐다(모든 A/B 가 멜트업 9개월 측정)
> ② 현재 시총 스냅샷을 과거에 소급(생존편향 거래당 +0.4~0.6%p) ③ 단일 구간 in-sample 채택.
> 읽는 순서는 [docs/README.md](../docs/README.md) 참조.
>
> **현재 운용 구성** (실계좌 예탁 385만원 기준 워크포워드 채택):
> ```
> 유니버스  KOSPI 시총상위 100 (스냅샷 자동 갱신 감지)
> 진입      MA60·MA120 정배열 + RS(60일)>KOSPI 절대 + MA20 ≤ 가격 ≤ MA20×1.12 + 거래량≥20일평균
> 시장게이트 KOSPI>MA60(레짐) · breadth≥0.4 · 일일손실 서킷 2%
> 랭킹      composite (blend 는 08-27 철회 — 12년 표본 4개 중 최악)
> 청산      TREND_EXITS=ma,hold → MA120 종가이탈 / 120영업일. **하드손절 10%는 항상**
> 사이징    pct_equity 5% × 슬롯 20 = 노출 100% (= 하니스의 notional, 동의어)
> 진입시각  08:50 스크린 → 11:00 진입(보류마감 14:00) → 15:20 청산
> ```
> **제거된 것**: ATR 트레일 · 첫목표 30% 부분익절 · 외인 5일 순매도 청산 · 피라미딩.
> 트레일이 12년 거래당 -0.57%(PF 0.84)의 원인이었다 — 같은 진입에 청산만 바꾸면 +7.40%(PF 2.15).
> 워크포워드 8폴드에서 구 4단 사다리는 **한 번도 선택되지 않았다**. 피라미딩은 환경변수로도
> 켜지지 않는다(영구 비활성). `stop`/`target` 은 **청산을 발동하지 않는다** — 그림자 원장의 R 기준값이다.
> **검증 후 기각**: 돌파 진입(20/55일, 2026-10-12 사전선언 A/B `walkforward_trend.py --entry-ab`) —
> 수익은 늘었지만 MDD 18→29%·MAR 0.96→0.72, PIT 거래당 PF 열위 → 눌림 유지. `entry_mode` 는 측정
> 장치로만 남김(기본 pullback). 돌파 기간을 바꿔 재측정하지 않는다(선언).
>
> ## ✅ 2026-10-22 부터 현재 운용 = **I3** ([docs/2026-10-22-i3-live.md](../docs/2026-10-22-i3-live.md))
> KODEX200 ↔ **KODEX 머니마켓액티브(488770)**(10-22 현금 자리 변경, 구 153130 단기채권 — 검증은 153130). 엔진(진입 후 최고 대비 −10% 이탈 · 20일 고점 + KOSPI>MA120 재진입) × 낙폭 예산
> (최근 252일 자기 자산 최고치의 82% 바닥선, 비중 min(1, 6×쿠션)). `scripts/i3_core.py`(판단 — 검증 함수
> `lab_dd_control.reentry_confirmed`·`lab_holdout` 상수를 **import**, 다시 구현 금지) · `scripts/i3_live.py`
> (`--phase decide` 평일 15:50 `I3Decide` / `--phase trade` 평일 08:50 `I3Trade`). 코드 기본값은 `I3_DRY_RUN=true`
> 이지만 **10-22 운용자 결정으로 `.env` 는 `false` — 실주문 중**(첫 실매수 10-23). `I3_HALT=true` 면 매매 정지.
> 투입 = 예탁자산 − I3 외 보유분. 매도는 08:50 동시호가 시장가(=검증의 시가 — 10시 이후·당일 종가 체결은
> `lab_exec_timing` 사전선언에서 −1.2/−2.8%p 로 기각), **매수는 09:05:30 이후 지정가**(LP 호가 의무 시간,
> 현재가+1%, 수량=kt00010 주문가능금액 안) — 키움은 시장가
> 매수 증거금을 상한가(+30%)로 잡아 자산 99% 시장가 매수는 거부된다. trading-domain 지정가 코드는 키움 '0'
> (`_trde_tp`, '01' 그대로 보내면 407022 매매구분 오류 — 10-22 실검증에서 발견).
> 전략 연구는 `scripts/strategy_lab.py`(운용자 잣대: MDD≤20%·최악연도≥−10%·KODEX200+5%p·구간별·격자 중앙값,
> 미공개 구간 HOLDOUT) — 1~7차 결과 [2026-10-22-lab-criteria-declaration.md](../docs/2026-10-22-lab-criteria-declaration.md).
> **도전자 리그**([2026-10-22-i3-league.md](../docs/2026-10-22-i3-league.md)) — '매일 발전'의 구조: `i3_shadow.py` 가
> 판단 뒤(i3_decide.cmd) 챔피언 I3 와 도전자를 **주문 없이** 매일 기록(`data/i3/shadow.json`·`shadow_history.csv`),
> 승격 규칙 사전선언(`PROMO_*`: 120영업일·다르게 행동 20일·누적 +2%p·MDD≤20%) 충족 시 critical 알림 → 운용자 승인.
> 도전자는 `lab_challengers.py` 사전선언·입장 조건(E1 제1원칙·E2 강세장 +1%p·E3 R1 약점 감소) 통과 후 등록.
> 새 세대는 **부모의 강점·약점 진단에서** 설계한다(계보 표 참고). 손절 강화(R4)는 폐기된 방향.
> **리그 v2(10-22)**: 멤버 23개(정원 25) — I3 계보(R1·R6[운용자 예외]·I1a·D5a[운용자 예외, 5세대 방어 자산 현금 자리 `lab_gen5`]·
> T6c[6세대 입장 조건 통과, 낙폭 예산 배수 장기 추세 연동 상승 8·그 외 4 `lab_gen6`, 10-26 등록 — 월 상한 밖 운용자 예외]·
> V7a[7세대, T6c + 변동성 브레이크 `lab_gen7`, 11-02 등록 — 미공개 여유 0.1%p 아슬아슬] · 9세대 재진입 × 외국인 수급
> `lab_gen9` F9a·F9b 11-10 **탈락**(84fd4c9 — 실패 재진입은 거르지만 2020 V자 반등에 두 달 늦음))·연구 계열(MA60·듀얼모멘텀·자산배분·한미반반)·종료한 추세추종·
> 고전 9종(`lab_classics`, 원 출처 파라미터 그대로: Faber10·TSMOM·변동성관리·올웨더·터틀·RSI2·볼린저·골든크로스·
> 변동성돌파)·AQR 팩터 2종(`lab_factors`, 저베타·퀄리티 롱온리, 10-23 등록). 매일 FDR↔키움 원자료 대조(0.5% 한도, critical). 백테스트는 입장 거름망일 뿐 — 실전 교체는 리그 실전
> 데이터로만. 매매가 잦은 계열은 비용 가정(편도 11.5bp)이 결과를 뒤집는다(변동성돌파 −11% ↔ 비용 0 +14%).
> **리그 운영 규칙**(10-22 운용자 확정, 상수 `RELEGATE_*`·`PROMO_*`·`CAPACITY`): 탈락 — 위험 MDD>25% 즉시 · 부진 60영업일 뒤
> 월간 점검에서 챔피언 −10%p · 5회 연속 실패. 중복(상관 0.98)은 알림만. 승격 — 월간 점검 2회 연속 + 운용자 승인.
> 정원 25(10-22 운용자 결정으로 20→25 — 1월 밖 예외) · 월 신규 3. 규칙 변경은 매년 1월 점검 때만. 상태 `data/i3/league_status.json`.
> **공격형 트랙(10-28 운용자 결정, [docs/2026-10-28-aggressive-track.md](../docs/2026-10-28-aggressive-track.md))**: 핵심 I3 는 그대로,
> 공격형 리그 그림자 기록 · **11-10 운용자 결정: 실계좌 투입 안 함**(60영업일 판정 뒤 다시 검토) · 그림자 −30% 정지선 경보. 목표 "3년 동안 계속 번다"(입장 P4 롤링 3년 > 0)
> · 지향 "월 10% × 3년"(보고만). A 양방향 `lab_aggr`(1세대 6개 전부 탈락 — 인버스 손실, 레버리지 낙폭) · B 단타 ORB `lab_orb`
> (10-29부터 저장 분봉으로 앞으로만 기록, 60영업일 뒤 판정). 레버리지·인버스 분봉도 매일 수집(`collect_i3_minutes.CODES`).
> C 하락 예측 판정대 `lab_downside`(10-28, 추세 밖 7개 — VIX·S&P500·원화·KOSPI 단기추세·변동성·다수결 — **전부 탈락**:
> 하락 신호 때 인버스가 현금을 못 이김. 가장 큰 상승일(2020-03-24 +9.4%·2026-06-11 +10.4%)이 하락 신호가 켜진 날에 온다).
> **공격형 리그** `aggr_shadow.py`(10-28, `i3_decide.cmd` 분봉 수집 뒤, 주문 없음, `data/aggr/`): ORB-B1·B2 + 공포 매수
> `lab_fear` FEAR-V1·V2(VIX>30)·K1·K2(KOSPI 20일 변동성>25%) × KODEX200/레버리지 — 판정대 표를 보고 떠올린 아이디어라
> **앞으로만**(10-29 시가 첫 체결), 판정 60영업일+보유 20일. 그림자 MDD 30% 첫 돌파 critical. 11-11 2주 점검 완료(규칙 변경 없음,
> 512d6d4) → 판정 2027-01-25(ORB-B1·B2·FEAR-V·K) · 01-26(HH1) · 02-05(B3·FEAR-P).
> **11-10 변형 추가**(d031344, 11-11 부터 앞으로만): ORB-B3(손절·익절 판단 = KODEX200 가격, `lab_orb.orb_day_k`) ·
> FEAR-P1·P2(변동성 25% 국면의 최근 20거래일 정점 대비 20% 꺾인 뒤, `lab_fear.peak_after`) — 멤버 10개.
> **Notion(11-11, c7403e9)**: 허브 아래 「⚔️ 공격형 트랙」 페이지 + 공격형 리그 멤버DB(`collection://7bd135a0-…`) · 일일 기록DB
> 「공격형 리그」 속성(자동, `i3_notion_sync.aggr_text`). 새 멤버는 멤버DB 행 + `AGGR_DISPLAY`(테스트가 빠짐을 잡는다).
> A2 2세대 `lab_aggr_gen2`(10-29, 레버리지 × 낙폭 예산 G1·G2 **탈락** — 격자가 '연수익 ≈ MDD × 0.5~0.65' 한 줄, 레버리지는
> 자리만 옮김. 연수익÷MDD 는 I3 0.65 가 최고. 엔진 없는 예산 G2 는 MDD 54.8%).
> A3 3세대 `lab_aggr_gen3`(10-29, 한미 반반 × 한국 2배 HH1·HH2 **탈락** — HH1 16.5%/18.7%·3년 최악 +9.7%, 줄 0.85~1.13 로 상승.
> HH2 미국 그냥 보유는 닷컴 포함 MDD 58%). **HH1 은 운용자 예외로 공격형 리그 등록**(10-29, `aggr_shadow.EXCEPTIONS`, 10-30 첫 체결). ⚠️ `strategy_lab.load_bars` 캐시가 시작일을 무시하던 결함 10-29 수정(`.meta.json`) —
> 장기 환율은 `FRED:DEXKOUS`(FDR USD/KRW 는 2003-12~). FDR 한국 ETF 는 최근 3,000거래일만 → 2027-10 무렵 I3 재생 시작일 위협(할 일 등록).
> **시장 일지(11-06, [docs/2026-11-06-market-journal.md](../docs/2026-11-06-market-journal.md))**: `market_journal.py` — 평일 08:30
> `MarketJournalMorning`(전 거래일 **확정** 수급 키움 ka10051 KRX·억원 + ka90010 프로그램 · 밤사이 미국 · 밤사이 뉴스 · 일정 →
> 텔레그램) + 판단 배치 close(뉴스 · DART · 잠정 수급). Notion 「📰 시장 일지」DB 는 i3_notion D절, 확정 수급 뒤라 **하루 늦게**.
> 원자료 `data/market_journal/`. 규칙 기반 요약만(AI 해설 없음). ka10051 은 2010년까지 과거 조회 가능.
> 연구용 수급 이력 `data/market_flows/daily.csv`(`market_flows.py`, 날짜 대조 가드 — 연구는 check=ok 만) — 채우기는 예약작업
> `MarketFlowsBackfill` 매일 16:30(PC 를 밤에 끈다 — 11-09 22:56 종료로 멈춘 적 있음).
> **키움 조회 실패 ≠ 휴장(11-10)**: `i3_live.missing_bar_reason` — 키움 응답이 비었거나 FDR 에만 오늘 일봉이 있으면 판단 중단 +
> critical(11-09 8050 IP 미등록이 '휴장' 일반 알림으로 지나갔다). 리그 `audit_gaps` 도 대조 불가 = critical. 고친 뒤 `i3_decide.cmd` 재실행.
> 11-12 재발(15:20 인터넷 교체) → **예약작업 `KiwoomNetCheck`**(네트워크 연결 이벤트 10000 · 로그온 · 평일 15:30, `kiwoom_net_check.py`):
> 키움 REST 직접 조회 1번, 8050 이면 즉시 텔레그램 critical + 현재 공인 IP. 재등록 `scripts/register_kiwoom_net_check.ps1`.
> **키움 조회 = `scripts/kiwoom_read.py` 한 곳(11-12 리팩터링)**: 최근 일봉·현재가·주문가능금액·1분봉은 키움 REST 직접,
> `Result(status ok|ip|fail, detail)` — 원인을 버리지 않는다(`KiwoomMarket/KiwoomBroker.errors` → 판단 중단·매수 건너뜀 알림).
> 주문·계좌 평가만 MCP(8030·8034). 새 조회는 여기에 추가하고, MCP `_kiwoom_call` 은 새로 쓰지 않는다.
> **P1(10-22)**: 낙폭 예산은 **성과 지수**(자산 ÷ 좌수, `i3_flows`) — 입출금은 **자동 기록**(매매일은 체결 기록으로 계산,
> 입금·출금·분배금 구분). 수동 덮어쓰기 `python scripts/i3_live.py --phase flow --amount ±원`. 체결가·슬리피지는
> `data/i3/fills.jsonl`(`i3_fills`, 2027-01 비용 가정 보정용). 분봉은 매일 `data/minute/`(`collect_i3_minutes`, 키움 ~900봉만 줌).
> **Notion(10-22)**: Notion 에 쓰기 전에 **[docs/notion-guide.md](../docs/notion-guide.md) 를 먼저 읽는다**. 매일 쌓이는 것은
> DB 행으로만 — I3 대시보드 페이지(`4011459d6f5881b6a381ddb8bb623f8c`)는 요약·바로가기만 두고(표 펼치지 않음) 손으로 늘리지 않는다.
> 트리 최상위는 「📈 주식 자동 매매」(허브) — I3·공통 장부DB·종료한 추세추종은 그 아래.
> **Notion 에선 줄임말 단독 금지 — 「풀네임(줄임말)」**(운용자 10-22): I3 = 「방어형 ETF 자동매매(I3)」, 최대 낙폭(MDD) 등
> 용어표는 notion-guide §1-7. 코드·텔레그램 문구는 그대로(운용자: "코드는 어쩔 수 없지만"). 자동 기록 문구는
> `i3_notion_sync.TRACK·MARK·DISPLAY`. 판단 뒤
> `i3_decide.cmd` 끝에서 `scripts\i3_notion.cmd`(prep `i3_notion_sync.py` → headless claude `i3_notion_task.md` → check)가
> 일일 기록DB·매매일지DB(🛡️ I3)·월별 결산DB 에 **없는 행만** 넣고, 실패하면 텔레그램 critical. 코드 변경·운용 결정·사고는
> 커밋할 때 **I3 운영 이력DB 에 1행**, 할 일은 Flow Task(Project I3).
> ETF 선택 근거 [2026-10-22-etf-choice.md](../docs/2026-10-22-etf-choice.md)(`lab_etf_screen.py`, 운용자 결정
> KODEX200 유지): 한국 ETF 전수 스크린에서 KOSPI200 계열이 I3 최상위, 같은 지수 ETF 간 I3 차이 ±0.5~1%p 는
> **소음**. 현금 자리는 머니마켓액티브가 153130 보다 연 +0.6~0.8%p(I3 현금 비중 평균 39%) → 10-22 운용자 승인으로
> 전환(`i3_core.CASH`). 엔진은 현금 코드를 이름표로만 쓴다(`test_engine_ignores_cash_code`).
> **추세추종은 종료(10-22 즉시)**: 데몬 중지, 워치독은 `TREND_WATCHDOG_DAEMON=off` 로 MCP 만 유지,
> `TrendPaperDaily`·`TrendJournalNotion` 비활성. 보유 SK이노베이션 1주는 감시 없이 계좌에 남김(운용자 결정).
> ⚠️ 이 세션 환경에선 `run_mcp_local.py stop`(taskkill)이 "액세스 거부"로 실패해 옛 MCP 가 포트를 쥔 채 남는다
> — `Stop-Process` 로 내리고 start, **재시작 후 도구 스키마로 새 코드 반영을 확인**할 것.
>
> ## ⛔ 2026-10-21 부터 신규진입 정지 (`TREND_ENTRY_HALT=true`, 보유분 청산은 계속)
> 워크포워드를 **시점별 유니버스**로 바꿔 재검증한 결과 08-28 기준 ①(MDD ≤ 벤치×0.5)이 0.2%p 차로
> 미달 — 사전 선언대로 정지. 재개 조건은 별도로 **사전 선언** 후 판정(결과 보고 기준·노출 맞추기 금지).
>
> **검증 성적 — 정본** (워크포워드 OOS, **시점별 유니버스**: 현재 상위 350 풀 → 매일 시총상위 100,
> 학습4년/검증1년 8폴드, 실계좌 예탁, `walkforward_trend.py` 기본값):
> 누적 +72.0% · CAGR 7.6% · MDD 22.4% · **MAR 0.34**(벤치마크 CAGR 11.0% · MDD 44.4% · MAR 0.25)
> · 플러스 5/8 · 벤치마크 상회 2/8. **실체: 수익은 벤치마크보다 낮고 낙폭은 절반.**
> 스냅샷 08-28/10-21 결과 동일(강건). 구 정본 +234.8%·MAR 0.96 은 **소급 유니버스**(현재 시총 상위를
> 과거에 적용, `--no-pit`) 값이었고 CAGR 약 10%p 가 생존편향이었다 — 인용 금지
> ([2026-10-21-universe-refresh-revalidation.md](../docs/2026-10-21-universe-refresh-revalidation.md)).
> 무플래그 거래당 백테스트(12년 PIT): 진입 3,194 · 승률 29.9% · 기대값 +9.65% · 손익비 6.06 · PF 2.59.
> ※ 시점별이어도 풀이 '현재' 상위 350 이라 편향이 남는다 — 절대값은 여전히 부풀려져 있다.
>
> ## 이 트랙의 작업 규칙 (오늘 사고들의 산물 — 반드시 지킬 것)
> 1. **단일 구간 in-sample 채택 금지.** 판정 기준을 측정 **전에** 코드 상수로 선언·커밋하고
>    워크포워드 OOS 로만 채택한다. 결과를 본 뒤 기준을 고치면 그 검증은 무효다.
> 2. **검증 조건 = 운용 조건.** 예탁금(정수 주식수 제약)·사다리 구성·유니버스가 하나라도 다르면
>    그 숫자는 다른 전략의 것이다. `TREND_BT_EQUITY` 로 실계좌 예탁을 주입할 것.
> 3. **안전장치는 하는 일과 적힌 일이 같아야 한다.** 새 가드를 넣으면 **일부러 깨뜨려** 발동을 확인한다.
> 4. **매년 1월 규칙 재선택**: `python scripts/walkforward_trend.py --select-now`
>    (워크포워드가 잰 것은 특정 규칙이 아니라 '매년 다시 고르는 절차'의 성적이다).
>
> ## 파일
> ⚠️ **2026-10-22 보관**: 데몬과 전용 도구(`trend_follow`·`trend_journal`·`trend_dashboard`·`shadow_ledger`·`kelly_monitor`·
> `collect_minute_bars`·`notion_sync`·`trend_panic`)는 `archive/` 로 옮겼다([archive/README.md](../archive/README.md)).
> 아래 목록 중 그 파일들은 보관본이다. I3·리그가 쓰는 `trend_config`·`trend_kiwoom_io`·`trend_runtime`·`trend_lock`·
> `trend_watchdog`·`collect_foreign_flow`·`trend_paper`·`backtest_trend*`·`walkforward_trend` 는 그대로.
> - 순수 도메인 `src/mcp_servers/trend_mcp/` — `signals.py`(진입/청산/사이징 순수함수, `exit_decision(exits=)`)
>   · `market_data.py`(pykrx OHLCV·유니버스, 스냅샷 갱신 자동감지) · `costs.py`(거래비용 단일소스)
>   · `server.py`(:8061 — 전략 요약을 **설정에서 조립**, 하드코딩 금지)
> - 데몬 `scripts/` — `trend_config.py`(설정 단일소스) · `trend_kiwoom_io.py`(키움 I/O)
>   · `trend_runtime.py`(알림·상태·락, 매매판단 없음) · `trend_journal.py`(일지 → `docs/journal/`)
>   · `trend_follow.py`(주문 내는 데몬만) · `trend_dashboard.py`(:8091)
> - 검증 — `walkforward_trend.py`(**정본**, 사전선언 기준·어서션 5종) · `backtest_trend.py`(거래당 A/B,
>   PIT 기본 on) · `backtest_trend_portfolio.py`(포트폴리오/MDD) · `trend_paper.py`(모델 장부 —
>   라이브 실체결 대조 기준선, 평일 16:10) · `shadow_ledger.py`(차단 후보 사후추적)
>   · `kelly_monitor.py`(켈리 과베팅 감시 — 기준 사전선언, 주문 무관. 출력의 `저널 판독: 전체 N거래` 가
>   0 이면 판독이 깨진 것)
> - 데이터 — `collect_minute_bars.py`(5분봉, 청산 phase 에서) · `collect_foreign_flow.py`(외인 ka10008
>   일별 스냅샷 → `data/trend_follow/foreign_flow/`, 평일 16:20 `TrendForeignFlowDaily`). **외인 청산이
>   꺼져 있어도 계속 수집한다** — ka10008 은 ~50 완성일만 주므로 그보다 오래 비우면 영구 유실(08-25~09-29
>   수집 중단 사고). 게이트 **통과**값은 events 의 `gates_pass`(막힌 날은 `regime_block`/`breadth_block`)
>   · Notion 일지(`notion_journal.cmd`, 평일 16:10) — `notion_sync.py prep` 이 최근 7일 거래를 계산해 두면
>   에이전트는 **없는 행만** 추가(하루 실패해도 다음 실행이 메움), `check` 가 이번 실행분 로그에 결과 줄이
>   없거나 ❌ 면 텔레그램 critical + exit 1(09-28 rate limit 로 매수 2건 누락 사고 — 작업 결과는 0x0 이었다)
> - 안전 — `trend_panic.py --full`(긴급 전량청산) · `trend_watchdog.py`(hang 감지 재기동)
>   · **응답 불명 주문은 재전송하지 않고 증권사 내역으로 확인**한다 — 매수는 잔고(`_confirm_unknown_buy`),
>   매도는 체결내역(`_confirm_unknown_sell`, 09-30 삼성E&A 유령 사고). **15:20~15:30 동시호가 주문은
>   15:30 체결 전엔 체결내역에 안 보인다** — 청산 phase 의 응답 불명 매도는 보류했다가 15:30 이후
>   `_settle_auction_sells` 로 확정(10-12 하나금융 유령 재발 사고). 미체결 조회(ka10075)는 형식 미검증이라
>   쓰지 않는다 · 장부↔계좌 대조(`_check_ledger_vs_broker`, reconcile 때
>   하루 2회, **알림만** — 조회 실패를 '보유 0'으로 믿지 않는다)
>   · `TREND_ENTRY_HALT=true`(신규진입 정지, 청산은 계속. 기본은 닫힌 쪽)
>
> **2026-08-17 안전 리팩터**(요약): state.json 원자적 쓰기 · 주문 재전송 제거(거부/불명 분리)
> · 채택값을 코드 기본값으로 승격 · fail-open except 6곳 → fail-closed · `levels()` 단일 정본.
> 상세 [docs/2026-08-17-safety-refactor.md](../docs/2026-08-17-safety-refactor.md).

## 스킬 자동 활성화

다음 작업 컨텍스트 감지 시 caveman 스킬을 **명시 호출 없이 자동 적용**한다:

- **코드 리뷰 / 분석** 요청 ("리뷰", "review", "분석", "분석해줘", "코드 봐줘", PR 리뷰, 함수 점검 등)
  → `caveman-review` 자동 활성화. 불필요한 칭찬·서론 제거, 핵심 이슈/리스크/개선점만 압축 출력.

- **프로젝트 통계 / 메트릭** 요청 ("통계", "메트릭", "stats", "코드 규모", "파일 개수", "복잡도", "테스트 커버리지", "프로젝트 현황" 등)
  → `caveman-stats` 자동 활성화. 수치 위주 압축 보고.

위 트리거에 해당하지 않으면 평소 톤 유지. 사용자가 "stop caveman" 또는 "normal mode" 명시 시 즉시 해제.

## 아키텍처 개요

> ⚠️ **2026-10-22 보관**: 종가매매 데몬(`direct_closing_bet.py`)·연구 스크립트·대시보드는 `archive/` 로 옮겼다(운영 안 함).
> MCP 서버 `closing_bet_mcp`(:8060)와 그 테스트는 그대로. 아래 종가매매 설명은 기록용이다.

```
scripts/direct_closing_bet.py  (standalone 데몬, A2A/Claude SDK 미사용)
   │  pykrx(시세) + closing_bet_mcp 함수 직접 임포트(채점/청산)
   │  MCPManager(src/claude_agents/base/mcp_client.py) 로 MCP 서버 호출
   ▼
FastMCP 서버 (src/mcp_servers/, 포트 8030–8060/3020)
   ├ trading-domain(8030) 주문/계좌    ├ kiwoom-market(8031) 시세
   ├ portfolio-domain(8034) 보유/평가  └ (선택) news/investor/...
```

**레이어**:
1. **MCP Servers** (`src/mcp_servers/`) — 도메인 도구 노출 (포트 8030–8060, 3020). FastMCP, 독립 실행.
2. **MCP 클라이언트** (`src/claude_agents/base/mcp_client.py`) — `MCPManager` 하나만 잔존 (구 멀티에이전트 패키지에서 유일하게 사용되는 모듈).
3. **closing_bet_mcp** (`src/mcp_servers/closing_bet_mcp/`) — 채점/청산 **순수 함수**. 데몬이 직접 임포트(서버 불필요).

**핵심 트랙**:
- `scripts/direct_closing_bet.py` — 종가매매 자동화 데몬. 자세한 전략은 [docs/closing_bet_strategy.md](../docs/closing_bet_strategy.md).
- `scripts/dashboard.py` — 일별 거래/이벤트/로그 시각화 대시보드 (Starlette + 단일 HTML, 포트 8090).
- `scripts/backtest_walkforward.py` — 비용 포함 워크포워드 OOS + 청산정책 비교.

## 개발 환경 설정

```bash
# 의존성 설치 (uv 사용)
./setup.sh

# 환경 변수 설정
cp .env.example .env
# .env 파일에서 API 키 설정

# 전체 서비스 실행 (Docker)
./1-run-all-services.sh

# 서비스 중지
./2-stop-all-services.sh

# MCP 서버 로컬 기동 (Docker 없이) — 종가매매에 필요한 전부
python run_mcp_local.py start    # 모든 MCP 서버 기동
python run_mcp_local.py stop     # 모든 MCP 서버 종료 (taskkill /T 로 자식까지)
python run_mcp_local.py status   # 상태 확인

# MCP 서버 헬스체크
python check_status.py             # 1회
python check_status.py --watch     # 10초마다 자동 갱신

# 종가매매 자동화 (A2A 에이전트 불필요, MCP만 필요)
python scripts/direct_closing_bet.py --daemon            # 14:50/15:15·15:19/18:05/익일 09:00·15:10 자동 실행
python scripts/direct_closing_bet.py --test              # 즉시 선별 (주문 없음)
python scripts/direct_closing_bet.py --status            # 현재 포지션/상태
python scripts/direct_closing_bet.py --phase {selection|buy_first|buy_second|after_hours|sell|force_close|intraday_stop|reconcile}
python scripts/dashboard.py                              # http://localhost:8090 대시보드
```

**PID 파일** (Windows): `%TEMP%/mcp_pids.json` (MCP 서버)
**MCP stdout 로그**: `%TEMP%/mcp_logs/` (예: `mcp_kiwoom_trade.log`)
**종가매매 로그**: `logs/closing_bet/closing_bet.log` (자정에 자동 회전, `closing_bet.log.YYYY-MM-DD` 30일치 보관)
**종가매매 데이터**: `data/closing_bet/YYYY-MM-DD/{selection,buy,sell}.json` + `events.jsonl`
**종가매매 상태/락**: `data/closing_bet/state.json` (영속, 구 `%TEMP%`에서 이전) + `daemon.lock`(단일 인스턴스)
**키움 토큰 공유 캐시**: `%TEMP%/kiwoom_token_cache/token_<mode>_<hash>.json` (서버 간 토큰 공유 → 8005 방지)

**필수 API 키** (`.env`):
- `KIWOOM_APP_KEY`, `KIWOOM_APP_SECRET`, `KIWOOM_ACCOUNT_NO` — 키움증권 (필수)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — 종가매매 알림 (선택)
- `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`(뉴스), `TAVILY_API_KEY`(웹검색) — 선택 MCP 서버용
- `ANTHROPIC_API_KEY` — 현재 closing-bet 트랙은 미사용 (구 Claude 에이전트 제거)

**로컬 개발 환경 변수**:
```bash
IS_DOCKER=false                # localhost URL 사용
MOCK_MODE=true                 # 실제 주문 대신 모의 주문
DEBUG=true                     # 상세 로깅
KIWOOM_PRODUCTION_MODE=false   # 키움 paper API(mockapi.kiwoom.com) 사용
                               # ※ 모의투자 키일 땐 반드시 false. 실거래 키 + true 조합만 허용.
```

**종가매매 튜닝 환경 변수** (선택):
```bash
CLOSING_BET_MIN_SCORE=55           # 후보 최저 composite 점수 (기본 55.0)
CLOSING_BET_TOP_CANDIDATES=3       # 1일 최대 종목 수 상한 (기본 3)
INVESTMENT_PER_TRADE=500000        # 1종목 기준 투자금 (기본 500,000원)
CLOSING_BET_CATALYST_WEIGHT=0.0    # catalyst 블렌딩 가중 (기본 0.0 = technical-only, 백테스트와 동일)
CLOSING_BET_CONVICTION_SIZING=false # 점수 차등 사이징(≥70 1.5x/≥85 2.0x) — 기본 off(전 구간 1.0x)
CLOSING_BET_HOLD_DAYS=3            # 최대 보유 영업일 (1이면 사실상 구 1일 청산)
CLOSING_BET_ATR_K=2.0             # 트레일 손절 밴드 = ATR_K × ATR
CLOSING_BET_ATR_PERIOD=14         # ATR 평균 기간(봉)
CLOSING_BET_TAX_BPS=18 / FEE_BPS=1.5 / SLIPPAGE_BPS=10  # 거래비용(편도 bps) → net 손익 차감
CLOSING_BET_INTRADAY_POLL_MIN=10   # 장중 트레일 점검 주기(분)
CLOSING_BET_RECONCILE=true         # 실계좌 보유분 대조(고아 청산). false 로 끔
CLOSING_BET_FORCE_PHASE=false      # true 시 phase 일일 중복실행 가드 무시(수동 강제 재실행)
CLOSING_BET_NEWS_VETO=true         # 악재(부정 공시/뉴스) 종목 후보 제외
CLOSING_BET_INFO_LOOKBACK_DAYS=5   # 뉴스/DART 공시 조회 기간(일)
CLOSING_BET_INFO_MAX=8             # 정보분석 대상 상한(상위 N 후보)
CLOSING_BET_TRENDS_LEADERS=30      # 동적 테마: 주도주 표본 수 (14:45 trends phase)
CLOSING_BET_TREND_MIN_STOCKS=3     # 키워드 핫 판정: 서로 다른 종목 N개 뉴스에 등장
CLOSING_BET_TREND_AUTO_NEW=false   # 신규 키워드 자동 테마화(노이즈) — 기본 off, hot 목록은 파일에 기록
# DART_API_KEY, NAVER_CLIENT_ID/SECRET 있어야 공시·뉴스 수집 (없으면 graceful skip)
```

> **정보 분석 레이어(2026-06-04)**: 기술점수 후보에 한해 **뉴스(테마)+DART 공시(호재/악재)+수급**을
> 모아 분석한다. **악재**(유상증자·감자·소송·관리종목 등 부정 공시/뉴스) 종목은 후보에서 **제외(veto)**,
> 호재/테마/수급은 selection.json·Telegram·대시보드에 **표시만**(composite 미반영 = 검증 기술엣지 보존).
> **동적 테마**: 매일 14:45 `trends` phase 가 거래대금 주도주 뉴스에서 빈출 키워드를 집계해 **그날 핫한
> 테마만** 자동 도출(`data/closing_bet/market_trends.json`). 시장 로테이션 추종 — 안 뜨는 테마는 빠진다.
> 정적 `catalyst.py:TREND_KEYWORDS` 는 시드/폴백. 신규 키워드는 파일에 기록(운영자가 시드에 승격).

> P0(2026-06-01): 라이브 채점식을 검증 백테스트(`compute_technical_scores`, candle **v1**)와 일치시켰다.
> catalyst(검증 전)·확신 사이징(70+ 구간 근거 약함)은 기본 off. 자세한 배경은 [docs/closing_bet_strategy.md](../docs/closing_bet_strategy.md) §3·§4.

## 프로젝트 구조

```
src/
├── claude_agents/base/mcp_client.py  # MCPManager — MCP 서버 연결/도구 호출 (구 멀티에이전트의 유일 잔존 모듈)
│
├── mcp_servers/                  # FastMCP 서버
│   ├── kiwoom_mcp/domains/
│   │   ├── trading_domain.py      # :8030 주문/계좌/모의거래
│   │   ├── market_domain.py       # :8031 실시간 시세/차트
│   │   ├── info_domain.py         # :8032 종목정보/ETF/테마
│   │   ├── investor_domain.py     # :8033 기관/외국인 투자자
│   │   └── portfolio_domain.py    # :8034 포트폴리오/VaR/리스크
│   ├── financial_analysis_mcp/    # :8040 재무 분석
│   ├── macroeconomic_analysis_mcp/ # :8041 매크로 지표
│   ├── stock_analysis_mcp/        # :8042 기술적 분석
│   ├── naver_news_mcp/            # :8050 뉴스/감성분석
│   ├── tavily_search_mcp/         # :3020 웹 검색
│   └── closing_bet_mcp/           # :8060 종가매매 채점·청산 규칙 (순수 함수)
│       ├── catalyst.py             # 트렌드 키워드 매칭 → 재료 점수
│       ├── scorer.py               # 6개 기준 가중 합산 (volume/resistance/candle/...)
│       ├── exit_rules.py           # evaluate_hold_exit(ATR 트레일)/evaluate_exit/classify_regime/market_filter
│       └── server.py               # FastMCP 도구 노출 (대시보드/UI용)

scripts/                          # 스탠드얼론 자동화/유틸
├── direct_closing_bet.py         # ★ 종가매매 자동화 (selection/buy/after_hours/sell/force_close/
│                                 #   intraday_stop/reconcile phase + scheduler_daemon). 핵심 라이브 로직.
├── dashboard.py                  # 종가매매 Starlette 대시보드 백엔드 (:8090)
├── dashboard.html                # 단일 HTML UI (Tailwind CDN + Chart.js)
├── backtest_walkforward.py       # ★ 비용 포함 워크포워드 OOS + 청산정책 비교(expectancy). 현행 검증 하니스.
├── backtest_dynamic.py           # 동적 유니버스 백테스트 (walkforward 가 데이터 로더 재사용)
├── tune_weights.py               # scorer 가중치 회귀 튜닝 (v1/v2 scorer)
├── _start_daemon.py / _kill_daemons.py  # 데몬 기동/일괄종료 헬퍼
├── _force_selection.py           # 시장필터 우회 채점(테스트 전용 — 실매수 금지)
├── _universe_kiwoom.py           # docs_cache/universe_kiwoom_*.json 갱신
└── (history) backtest_closing_bet/_hybrid.py, _dart_cache.py — 과거 실험(2026-10-22 미사용 6개 삭제:
              regime_adaptive·breadth_gate·gen_dashboard·probe_stocklist·test_closing_bet·_gate_funnel — git 기록에 있음)

tests/                            # pytest 회귀 안전망 (핵심 순수함수)
├── test_exit_rules.py            # ATR stop/ratchet/hold-exit, 시장게이트, AH 완화
├── test_scorer.py                # candle v1 방향, composite 가중합
└── test_closing_bet_helpers.py   # ATR/영업일/order_accepted/fill_price/원장 net집계
```

`src/mcp_servers/`에 `code_index.md`가 있다 — 파일별 책임을 빠르게 살펴볼 때 참조 (A2A 관련 링크는 stale).

## MCP 서버 포트 매핑

| 서비스 | 포트 | 역할 |
|--------|------|------|
| trading-domain | 8030 | 주문/계좌 |
| kiwoom-market-mcp | 8031 | 시세/차트 |
| kiwoom-info-mcp | 8032 | 종목 정보 |
| investor-domain | 8033 | 투자자 동향 |
| portfolio-domain | 8034 | 포트폴리오/리스크 |
| financial-analysis-mcp | 8040 | 재무 분석 |
| macroeconomic-analysis-mcp | 8041 | 매크로 지표 |
| stock-analysis-mcp | 8042 | 기술적 분석 |
| naver-news-mcp | 8050 | 뉴스/감성 |
| tavily-search-mcp | 3020 | 웹 검색 |
| closing-bet-mcp | 8060 | 종가매매 채점/청산 규칙 (직접 임포트도 가능) |
| trend-mcp | 8061 | 추세추종 진입/청산/사이징/JH ZONE/주도섹터 (직접 임포트도 가능) |
| dashboard | 8090 | 종가매매 대시보드 (Starlette, `python scripts/dashboard.py`) |

> 종가매매 데몬이 쓰는 MCP URL은 `direct_closing_bet.py` 상단 상수(`TRADING_URL`/`MARKET_URL`/`PORTFOLIO_URL`/...)에 하드코딩. 키움 도메인은 `/mcp/`(슬래시), 분석/외부 서비스는 `/mcp`(무슬래시) 규약. 새 MCP 서버 추가 시 `check_status.py`의 `SERVICES` 리스트도 갱신.

## 종가매매 자동화 워크플로우

`scripts/direct_closing_bet.py`가 단독 실행되며, MCP 서버만 떠 있으면 동작한다.

**5-phase 스케줄** (영업일 기준):
| 시각 | phase | 동작 |
|------|-------|------|
| 14:50 | `selection` | 거래대금 상위 50종목 채점 → composite ≥ 55인 1~3개 후보 (섹터당 최대 2) |
| 15:15 / 15:19 | `buy_first` / `buy_second` | trading-domain MCP로 종가 시장가 분할 매수 (50%+50%) |
| 18:05 | `after_hours` | 시간외 단일가로 ATR 트레일링 스톱 갱신(상방만) |
| 09:00 | `sell` | 보유 전 종목 트레일/손절 이탈만 청산 (시간청산 X) |
| 15:10 | `force_close` | 트레일 이탈 + 보유기간(`HOLD_DAYS`) 만기 시간청산. 미만기는 다음날 이월 |

> 청산은 **(a) 최대 `HOLD_DAYS`(기본 3) 영업일 보유 + (c) ATR 트레일링 스톱** 모델
> ([evaluate_hold_exit](../src/mcp_servers/closing_bet_mcp/exit_rules.py)). 부분 익절 없이 승자를
> 트레일로 추종(우측꼬리), 패자는 ATR 손절로 제한. 백테스트 근거: [docs/backtest_exit_policy_2026-06-01.md](../docs/backtest_exit_policy_2026-06-01.md).

**상시 운영 안전장치/보강** (모두 `direct_closing_bet.py`):
- **장중 트레일 점검** (`intraday_stop`): 정규장 보유 중 `INTRADAY_POLL_MIN`(기본 10분) 주기로 트레일 갱신·이탈 청산 — 일봉 근사(스냅샷) vs 백테스트(일중) 괴리 축소.
- **실계좌 reconciliation** (`reconcile`, 15:10 직후): portfolio-domain 보유분 ↔ state 대조. 봇 매수이력에 있는 **고아 포지션은 청산**, 매수이력 없는 보유분은 알림만. `CLOSING_BET_RECONCILE=false`로 끔.
- **멱등성**: 데몬 **단일 인스턴스 락**(`data/closing_bet/daemon.lock`) + 매수 회차 **일일 중복실행 가드**(실주문 발생 시) → 이중 주문 방지. `CLOSING_BET_FORCE_PHASE=true`로 우회.
- **주문 수락 검증(#3)**: `place_buy/sell` 응답 `return_code`를 확인 — `success:true`라도 `return_code!=0`(예: 8005)이면 **유령 포지션 미기록**. 거부 시 [REJECT] 로그(원인 분류 + raw)·`order_reject` 이벤트.
- **토큰 8005 자동복구**: 키움 클라이언트가 **프로세스 간 공유 토큰 캐시**(`%TEMP%/kiwoom_token_cache/`)로 서버 간 상호 무효화 방지 + 8005 응답 시 강제 재발급·재시도.
- **상태 영속화**: state는 `data/closing_bet/state.json`(구 `%TEMP%`에서 이전) — 재부팅/temp 정리에도 보유 추적 유지. 손익은 **net**(거래비용 차감).

**진입 게이트** (`phase_selection`): KOSPI 필터 → regime → 미국 야간 → MA20 → 갭업 → composite 점수.
약한 날엔 0종목 진입 (강제로 5개 안 채움).

**이벤트 로깅** (`data/closing_bet/YYYY-MM-DD/events.jsonl`): append-only JSONL로 시계열 기록 — `phase_start`, `market_filter`, `regime`, `us_market`, `selection_done`, `news_veto`, `buy`, `after_hours`, `sell`, `force_close`, `order_reject`, `reconcile_close`, `skip`, `error`. 청산 손익/승률은 종목별 가중 실현손익(`exit_ledger` 합산)으로 계산 — HOLD 편향 없음.

**대시보드** (`scripts/dashboard.py`): Starlette + 단일 HTML. `/api/{health,days,day/{date},summary,log,state}` 엔드포인트로 데이터 노출. `?date=YYYY-MM-DD` 로 회전된 로그 백업 조회 가능.

자세한 전략/파라미터는 [docs/closing_bet_strategy.md](../docs/closing_bet_strategy.md) 참조.

## 코드 패턴 & 컨벤션

**MCP 도구 로딩**: `MCPManager(urls)` async context manager가 서버 연결/해제를 관리하고 `mcp.tools`로 tool 스키마, `mcp.call_tool(name, input)`으로 실행한다 (`src/claude_agents/base/mcp_client.py`). langchain-mcp-adapters 없이 MCP 클라이언트를 직접 사용.

**비동기**: 데몬/MCP 호출은 `async/await`. 채점/청산 로직(`closing_bet_mcp`)은 순수 동기 함수.

**로깅**: `structlog.get_logger(__name__)`(MCP 서버) / 표준 `logging`(종가매매 데몬 — `[REJECT]`, `[RECONCILE]` 등 태그).

## 테스트

`tests/` — 종가매매 핵심 순수함수 pytest 회귀 안전망 (23 케이스: exit_rules ATR/트레일/시장게이트, scorer candle v1 방향·가중합, 헬퍼/원장 net집계).

```bash
python -m pytest tests/ -q          # 순수함수 회귀 (pytest 필요: uv pip install pytest)
```

통합 시나리오는 `examples/` 아래 도메인별로 (`examples/{supervisor,data_collector,analysis,trading,common}/`):
```bash
python examples/run_integration_tests.py
pytest examples/ -m integration
```

`pyproject.toml`의 `testpaths = ["tests"]`. 테스트 마커(`unit`, `integration`, `e2e`, `a2a`, `workflow`, `performance`, `stress`)는 `pytest.ini` 참조.

## 의존성 관리

Python 3.12+ 필수. 패키지 관리는 `uv`를 사용한다.

```bash
# 의존성 추가
uv add <package>

# 의존성 설치 (lock 파일 기준)
uv sync
```

**핵심 의존성** (`pyproject.toml`):
- `fastmcp>=2.11.3`, `mcp>=1.0.0` — MCP 서버/클라이언트
- 데이터: `pandas`, `pykrx`, `finance-datareader`, `fredapi`, `opendartreader`, `publicdatareader`
- 인프라: `httpx`, `httpx-sse`, `aiohttp`, `redis`, `structlog`, `psutil`

## 디버깅 팁

- `MOCK_MODE=true` — 알림 라벨만 MOCK (실제 모의/실거래는 `KIWOOM_PRODUCTION_MODE`가 결정)
- `KIWOOM_PRODUCTION_MODE=false` — 키움 paper API 강제 (모의투자 키일 때 필수)
- MCP 헬스체크: `python check_status.py` (`/mcp` 엔드포인트 응답으로 확인 — 별도 `/health` 없음)
- MCP stdout 로그: `%TEMP%/mcp_logs/<service>.log` (예: `mcp_kiwoom_trade.log`)
- 종가매매 로그: `logs/closing_bet/closing_bet.log` (자정 자동 회전, 30일 보관). 주문 거부는 `[REJECT] … 분류=… rc=… raw=…` 라인 검색.
- 종가매매 상태/내역: `python scripts/direct_closing_bet.py --status` (현재 포지션/락) · `--analyze --days 30` · `--phase reconcile`(실계좌 대조 수동 실행)
- 종가매매 데이터/이벤트: `data/closing_bet/YYYY-MM-DD/{selection,buy,sell}.json` + `events.jsonl`(`order_reject`/`reconcile_close` 포함)
- Docker 로그: `docker-compose -f docker-compose.full.yml logs -f <service-name>`
- **`.env` 의 키움 키를 바꾸면 MCP 서버를 반드시 재시작**(`python run_mcp_local.py stop` → `start`). 서버는
  기동 시 키를 읽고 들고 있어서, 재시작 전까지 예전 키로 계속 실패한다. watchdog 은 포트가 살아 있으면
  재시작하지 않는다. 데몬 재시작은 불필요(키를 직접 쓰지 않음). 10-06: 키 만료였는데 로그 문구는
  "8050: IP 미등록"이었다 — 8050 이 보이면 IP 등록과 앱키 만료를 **둘 다** 확인할 것(09-21 은 실제 IP 변경).
- 키움 토큰 무효(8005)/발급 실패: 이제 클라이언트가 **공유 캐시 + 8005 강제 재발급**으로 자동복구. 그래도 안 되면 `KIWOOM_PRODUCTION_MODE`와 키 종류(실거래/모의) 일치 확인, `%TEMP%/kiwoom_token_cache/` 삭제 후 재시도. 8030 좀비는 `taskkill /F /T`(자식까지) 또는 `Stop-Process`로 정리(`run_mcp_local.py stop`에 `/T` 반영됨).
- state↔실계좌 불일치(유령/고아 포지션): `--phase reconcile`로 대조. 봇 매수이력 고아는 자동 청산, 미지 보유분은 알림.
- DART/외부 API 응답 캐시는 `docs_cache/`에 누적될 수 있음 (재현용; 커밋하지 말 것)
