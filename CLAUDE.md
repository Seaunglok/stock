# CLAUDE.md — 주식 자동 매매 (키움 REST · 방어형 ETF 자동매매 I3)

> ## 🇰🇷 응답 언어 — 반드시 한국어 (운용자 지시, 2026-10-22)
> **사용자에게 보내는 모든 문장은 한국어로 쓴다.** 최종 답변뿐 아니라 도구 호출 사이의 진행 메시지,
> 표, 결정 요청까지 전부. 웹 검색 결과·논문·코드가 영어여도 답변은 한국어로 옮긴다.
> 코드 식별자·파일 경로·커밋 해시·명령어만 원문 그대로 둔다. 문서(docs/)·커밋 메시지도 한국어.
> (10-21~22·11-10~11 에 영어로 답했다가 지적받았다 — 대화 요약 뒤 첫 응답, 긴 분석·표가 있는 답일수록 보내기 전에 확인할 것.)

## 0. 지금 무엇이 돌고 있나 (2026-11-12 정리)

- **실전(실계좌·실주문)**: 방어형 ETF 자동매매(I3) 하나 — KODEX200 ↔ KODEX 머니마켓액티브(488770).
- **그림자 기록(주문 없음)**: I3 도전자 리그 26 멤버(11-19 「가치저변동」 등록일 11-20 · 11-20 X10a 등록일 11-23, 정원 30 ·
  **11-23 M11a 세 시장 I3 운용자 예외, 등록일 12-01**) · 공격형 리그 11 멤버(11-23 FLOW-S1).
- **수집**: 시장 일지(수급·뉴스·공시·밤사이 미국·일정) · 연구용 수급 이력 2010~ · 1분봉 8종목 · 종목별 외인(ka10008).
- **종료한 트랙**: 종가매매(코드 `archive/`) · 대형주 추세추종(10-22 종료, 데몬 `archive/`, 보유 SK이노베이션 1주는 감시 없이 계좌에 남김 —
  운용자 결정). 설명·검증 기록은 [docs/2026-11-12-claude-md-snapshot.md](docs/2026-11-12-claude-md-snapshot.md)(정리 전 이 파일 원문)·
  [docs/README.md](docs/README.md). **옛 성적 인용 금지** — 08-27 이전 기대값은 전부 무효(로더 `--start` 무시·생존편향·in-sample),
  추세추종 +234.8%·MAR 0.96 은 소급 유니버스 값(정본은 시점별 +72.0%·MAR 0.34).

## 1. 매일 자동 작업 (Windows 예약작업 — 로그온 세션에서만 돈다, PC 는 08:20 부팅·밤 22~23시 종료)

| 언제 | 작업 | 하는 일 |
|---|---|---|
| 네트워크 연결 · 로그온+1분 · 평일 15:30 | `KiwoomNetCheck` → `kiwoom_net_check.py` | 공인 IP + 키움 직접 조회 1번. 8050(IP 미등록)이면 즉시 텔레그램 critical + 현재 공인 IP |
| 평일 08:30 | `MarketJournalMorning` | 전 거래일 **확정** 수급(ka10051 KRX·억원 + ka90010 프로그램)·밤사이 미국·뉴스·일정 → 텔레그램, 수급 이력 1행 |
| 매일 08:40~ 5분마다 | `KiwoomTrendWatchdog` → `trend_watchdog.cmd` | MCP 서버 기동·감시(이름만 trend — `TREND_WATCHDOG_DAEMON=off` 라 데몬은 안 띄운다) |
| 평일 08:50 | `I3Trade` → `i3_live.py --phase trade` | 전날 판단대로 매매(대기 판단 없으면 건너뜀) |
| 매일 09:00 | `ClaudeCliDaily` → `cmd /k claude.exe --remote-control multi_agent_kiwoom` | 프로젝트 폴더에서 대화형 Claude Code 세션 + 원격 제어(claude.ai/code·모바일 앱). 운용자 요청(11-19). 창을 닫으면 그날은 끝. 다시 만들기 `scripts/register_claude_daily.ps1` |
| 평일 15:50 | `I3Decide` → `i3_decide.cmd` | 판단 → I3 리그 → 1분봉 수집 → 공격형 리그 → 시장 일지 close → 지표 일지 → Notion(`i3_notion.cmd`) → Claude 뉴스 판단(`llm_news.py`, 11-25~) |
| 매일 16:30 | `MarketFlowsBackfill` | 수급 이력 빈 날 메우기(오늘은 받지 않는다 — 확정치는 다음 날 아침) |

비활성: `TrendPaperDaily` · `TrendJournalNotion` · **`TrendForeignFlowDaily`(11-18 — 종목별 외인 ka10008, 종료한 추세추종 검증용.
순매수는 ka10059 로 2015~ 다시 받을 수 있다 · ka10008 보유 변화는 2027-01 초 안에 다시 켜면 빈 날 없음)**.
작업이 사라지면: 연결 점검은 `scripts/register_kiwoom_net_check.ps1`.
**장 시간이 바뀌는 날**(수능 10:00~16:30 · 새해 첫 거래일 10:00 개장): **11-23 코드화(⑲, `market_session.py`)** — `scripts/market_calendar.json`
항목에 `"open"`·`"close"` 를 적으면 예약 실행(08:50 · 15:50)이 그날 개장 10분 전·마감 5분 뒤까지 기다린다(예약작업은 손대지 않는다).
**2027-01-04 는 관행으로 미리 적음(`confirmed: false`) — 12월 거래소 공지로 확인 뒤 true.** 2027 수능은 발표 뒤 같은 방식으로 더한다.

## 2. 방어형 ETF 자동매매(I3) — 실전 ([docs/2026-10-22-i3-live.md](docs/2026-10-22-i3-live.md))

- **규칙**: 엔진(진입 후 최고 대비 −10% 이탈 · 20일 고점 + KOSPI>MA120 재진입) × 낙폭 예산(최근 252일 자기 자산 최고치의 82% 바닥선,
  비중 min(1, 6×쿠션)). 판단 `scripts/i3_core.py` 는 검증 함수 `lab_dd_control.reentry_confirmed`·`lab_holdout` 상수를 **import** —
  다시 구현 금지(실전==검증 테스트가 잠근다). 실행 `scripts/i3_live.py`(`--phase decide|trade|status|flow`).
- **실주문 중**: 코드 기본값 `I3_DRY_RUN=true` 지만 **10-22 운용자 결정으로 `.env` 는 `false`**(첫 실매수 10-23). `I3_HALT=true` 면 매매 정지.
  투입 = 예탁자산 − I3 외 보유분.
- **매매 방식**: 매도는 08:50 동시호가 시장가(= 검증의 시가 — 10시 이후·당일 종가 체결은 `lab_exec_timing` 사전선언에서 −1.2/−2.8%p 로
  기각). **매수는 09:05:30 이후 지정가**(ETF LP 호가 의무 시간, 현재가 +1%, 수량 = kt00010 주문가능금액 안) — 키움은 시장가 매수 증거금을
  상한가(+30%)로 잡아 자산 99% 시장가 매수는 거부된다. trading-domain 지정가 코드는 키움 `'0'`(`_trde_tp` — '01' 은 407022 거부).
- **현금 자리** 488770(10-22 전환, 153130 보다 연 +0.6~0.8%p — 검증·실전==검증 테스트는 이력 있는 153130 으로 돈다, 엔진은 현금 코드를
  이름표로만 쓴다). ETF 는 KODEX200 유지([2026-10-22-etf-choice.md](docs/2026-10-22-etf-choice.md) — 같은 지수 ETF 간 ±0.5~1%p 는 소음).
- **장부(P1)**: 낙폭 예산은 성과 지수(자산 ÷ 좌수, `i3_flows`) — 입출금 자동 기록(입금·출금·분배금), 수동 `--phase flow --amount ±원`.
  체결가·슬리피지 `data/i3/fills.jsonl`(`i3_fills`, 2027-01 비용 가정 보정용).
- **키움 조회는 `scripts/kiwoom_read.py` 한 곳**(11-12): 최근 일봉·KOSPI 업종 일봉·현재가·주문가능금액·1분봉 = 키움 REST 직접,
  `Result(status ok|ip|fail, detail)` — 원인을 버리지 않는다(`KiwoomMarket/KiwoomBroker.errors` → 판단 중단·매수 건너뜀 알림에 「키움: …」).
  **주문·계좌 평가만 MCP**(8030 trading · 8034 portfolio — 검증된 길). 새 조회는 `kiwoom_read` 에 넣고 MCP `_kiwoom_call` 은 새로 쓰지 않는다.
- **판단 안전장치**(일부러 깨뜨려 확인함): 15:35 전엔 판단 안 함 · 키움 응답이 비었거나 FDR 에만 오늘 일봉 → **판단 중단 + critical**
  (휴장 아님, `missing_bar_reason`) · 둘 다 없으면 휴장 일반 알림 · FDR↔키움 종가 0.5% 넘게 다르면 중단(분배락일에 한 출처만
  과거를 다시 계산한 모양이면 알림에 「분배금 반영 시차로 보임」 — 11-25 `basis_step`, 4월 분배가 커서 생길 수 있다, 보통 다음 날 풀림) ·
  **재생 시작일(2015-07-28) 앞 KODEX200 20일·KOSPI 120일 미만이면 중단(11-24 ⑮ `i3_core.history_short`)** · 계좌 조회 불명이면 중단 ·
  현재가·주문가능금액을 못 읽으면 매수 안 함 · **응답 불명 주문은 재전송하지 않고 잔고·체결내역으로 확인** ·
  **`state.json` 없이 `state.bak` 만 있으면 판단·매매 중단**(11-18 — 빈 상태로 시작하지 않는다. 복구: .bak 확인 → state.json 으로 복사 → 재실행) ·
  **매매 단계가 09:20 뒤에 돌았는데 대기 판단이 남아 있으면 「매매 놓침」 critical**(11-19 `_alert_missed_window` — 동작 불변, 다음 매매일 08:50) ·
  **대기 판단 유효 기간 평일 4일 · 버릴 때 `state.w` 를 `prev_w`(계좌가 든 목표)로 되돌림**(11-23 — 전엔 달력 4일이라 12-30 판단이 01-04 에
  버려지고 w 가 새 목표로 남아 다음 판단이 '유지'로 굳었다) · 일정 파일을 못 읽으면 평소 장 시간 + critical ·
  **무소식 감시 `heartbeat.py`**(11-19 ㉑ — 매매·판단 단계 시작 때 Healthchecks.io 에 GET, 예외면 `/fail`; 매매 09:10·판단 16:20 까지
  없으면 서비스가 휴대폰 경보. `.env` `HEARTBEAT_TRADE_URL`·`HEARTBEAT_DECIDE_URL`, 없으면 아무것도 안 함 — **11-23 운용자: 가입 안 함**
  ("어차피 8시30분에 일지를 주잖아" — 평일 08:30 시장 일지가 살아 있음 신호. 다시 권하지 않는다).
  평가·남은 개선안: [docs/2026-11-19-system-review.md](docs/2026-11-19-system-review.md) · 백로그 ㉑~㉘.
- **파일 쓰기는 `scripts/atomic_io.py`**(11-18, `write_text`·`write_csv` — tmp → 교체, PermissionError 5번 재시도, 실패해도 원본 그대로,
  `keep_bak` 은 복사). 새 파일 쓰기도 여기로(`trend_runtime` 만 자체 복구 규칙이라 예외).

## 3. 연구 · I3 도전자 리그

- **잣대**(`scripts/strategy_lab.py`, 운용자): MDD≤20%·최악연도≥−10%·KODEX200+5%p·구간별(박스권·강세장)·격자 중앙값·미공개 구간 HOLDOUT —
  [2026-10-22-lab-criteria-declaration.md](docs/2026-10-22-lab-criteria-declaration.md). 백테스트는 입장 거름망일 뿐, 실전 교체는 리그 실전 데이터로만.
  매매가 잦은 계열은 비용 가정(편도 11.5bp)이 결과를 뒤집는다(변동성돌파 −11% ↔ 비용 0 +14%).
- **I3 에 대해 할 수 있는 말(㉘ 11-20, `lab_i3_overfit.py`)**: 낙폭 축소는 **타이밍 덕**(시점만 무작위인 같은 노출 전략 중 학습 0.04%·
  장기 0.9% 만 그만큼 얕음) · **수익·샤프 우위는 확인 안 됨**(보정 PSR z 2.49 < 3.00, 지수 대비 샤프 p 0.67) · 5차 격자 고르기 PBO 0.6~0.7.
  리그 120영업일로 유의를 말하려면 차이 연 샤프 ≥ 2.41(㉔ 재료) — [docs/2026-11-20-i3-overfit.md](docs/2026-11-20-i3-overfit.md).
- **발굴 구조(11-18, 운용자 "오픈되지 않은 조건식… 더 발굴")**: 새 후보는 **아이디어 장부** [docs/strategy-ideas.md](docs/strategy-ideas.md)에
  출처·왜 돈이 되나(누가 손해)·실행·자료 네 칸부터 — 못 채우면 재지 않는다. 재기 전에 **시험 횟수 장부** `scripts/lab_trials.py`
  `TRIALS` 에 행을 더해 선언과 같이 커밋, 통과선 = `hurdle_t(total_through('scripts/lab_….py'))`(그 행까지 누적 — 같은 날 묶음이
  여럿이어도 앞 묶음 통과선 불변. 본페로니, 하한 3.0 — 11-18 누적 98 → 3.48). 1묶음 달력 `lab_calendar.py` **5개 전부 탈락**(최대 t 1.45).
  **2묶음 해외 팩터 한국판 `lab_jkp.py`(JKP 공개 나라별 팩터 자료, 사는 쪽만, 1996~2025) — 가치만 통과**(연 +5.7%p · 알파 t 5.46,
  힘은 1996~2009 에 몰림), 저변동·모멘텀·퀄리티·배당 탈락. 자료 `docs_cache/lab/jkp/`(SHA256 고정, CC BY-NC — 커밋 안 함).
  **리그 등록 선언 `lab_value_etf.py`(525b308)**: 「가치저변동」 = KODEX 200가치저변동(223190, 가치+저변동 혼합) × I3 엔진을 ETF 자기
  가격으로 — **11-19 `i3_shadow.MEMBERS` 에 넣음(e1824bb, 등록일 11-20)**. 보고만 재생 연 +12.7%·MDD 21.6%
  (I3 +12.0%·19.9%). **3묶음 연말 대주주 매도 `lab_taxsell.py`(11-23, 누적 104 → t ≥ 3.49) 탈락** — 마감일(폐장일 2거래일 전)
  뒤 5일 코스닥 되돌림 t 3.487(0.004 모자람), 개인 수급은 기사대로지만 기준이 낮은 해에 되돌림이 더 작아 세금이 아니라 연초 상승.
  **4묶음 MSCI 한국 정기변경 종목 `lab_msci.py`(11-23, 누적 107 → 3.50) 탈락** — 편입 앞 매수는 2021~ 비용만큼도 안 남고(효과는 발표 전에
  끝남), 편출 되돌림은 시대에 따라 뒤집혔다. 자료: MSCI 공개 목록 PDF(`docs_cache/lab/msci/`) · 이름 → 코드 `lab_msci_map`.
  **발굴 묶음 넷 끝(달력 · 해외 팩터 · 대주주 · MSCI) — 통과는 가치 하나.**
- **리그**([2026-10-22-i3-league.md](docs/2026-10-22-i3-league.md)): `i3_shadow.py` 가 챔피언 I3 와 도전자를 주문 없이 매일 기록
  (`data/i3/shadow.json`·`shadow_history.csv`), 매일 FDR↔키움 원자료 대조(0.5%, 대조 불가도 critical `audit_gaps`).
  - 멤버 26(**정원 30 — 11-20 운용자 "리그정원을 30으로 늘리고 추가해줘"**, 남은 자리 4, 12월 신규 1 씀(M11a) — 운용자 "3자리를 다 채우지 말고 1자리"):
    **M11a(11세대 `lab_gen11`, KODEX200·S&P500(H)·금(H) 1/3씩 각자 I3 엔진·매년 재조정 — G2 미달(연 −4.1%p·MDD 반)을 운용자 예외로, 등록 12-01)** ·
    I3 계보 R1·R6(운용자 예외)·I1a·D5a(운용자 예외)·T6c(6세대, 배수 장기 추세 연동 8/4)·
    V7a(7세대, + 변동성 브레이크 — 미공개 여유 0.1%p)·**X10a(10세대 ㉕, 이탈폭 10% × clip(σ20÷15.6%, 1, 2) — 과거 판정 없이 앞으로만,
    등록 11-23, `lab_gen10`)** · 연구 계열 MA60·듀얼모멘텀·자산배분·한미반반 · 종료한 추세추종 · 고전 9종
    (`lab_classics`, 원 출처 파라미터) · AQR 저베타·퀄리티(`lab_factors`) · 외부 팩터 가치저변동(`lab_value_etf`, 223190 × I3).
  - 시험의 실데이터 캐시는 **고정 기준일(HOLDOUT 끝 10-21 이하)만** — 날짜별 캐시는 리그가 매일 받으며 `prune_live_cache` 가 지운다(11-19).
  - 규칙(10-22 확정, 상수 `RELEGATE_*`·`PROMO_*`·`CAPACITY`): 승격 = 120영업일·다르게 행동 20일·누적 +2%p·MDD≤20% 를 월간 점검 2회 연속 +
    운용자 승인 · **+ 통계 조건 S1(㉔ 11-23 선언, 2027-01 점검부터 — `league_stats.py`: 차이 수익 z ≥ 본페로니 단측 5%, 미달이면 '보류(통계)'
    · 공격형은 실계좌 재검토 자격에만 S2)** · 탈락 = MDD>25% 즉시 / 60영업일 뒤 월간 점검에서 챔피언 −10%p / 5회 연속 실패 · 중복(상관 0.98)은 알림만 · 월 신규 3 ·
    규칙 변경은 매년 1월 점검 때만(정원 25 는 운용자 예외). 상태 `data/i3/league_status.json`, 월간 점검 = 그 달 첫 실행.
  - 새 세대는 **부모의 강점·약점 진단에서** 설계 → `lab_genN.py` 사전선언 커밋 → 측정 → 입장 조건 통과 시 등록. 6~8세대 배수 축은 멈춤,
    9세대 재진입 × 외국인 수급 F9a·F9b **탈락**(11-10, 실패 재진입은 거르지만 2020 V자 반등에 두 달 늦음). 폐기된 방향: 손절 강화(R4)·장중 손절(S1)·
    **점프 모형 국면 J1·J2(㉗ 11-20, `lab_jump` — 반등장 눌림을 하락으로 읽어 MDD 28.7·22.7%, 이 축은 닫음)**.
- 데이터 주의: `strategy_lab.load_bars` 캐시는 `.meta.json` 으로 시작일을 지킨다(10-29 결함 수정) · 장기 환율 `FRED:DEXKOUS` ·
  **FDR 한국 ETF 는 최근 3,000거래일만**(첫 날이 매일 밀림) → **11-24 일봉 보관소 `bar_archive.py`**(`data/bar_archive/`): 실전·두 리그
  (`load_bars(..., archive=True)` — 공격형은 11-25)가 받은 이력을 쌓고 앞쪽을 붙인다 — 연구는 안 쓴다. **FDR·키움 수정주가는 분배금 때 과거 전체를
  같은 비율로 다시 계산한다**(10월 × 0.99858) → 붙일 땐 겹치는 날 비율을 곱한다 · 받은 날이 다른 캐시끼리 가격 수준을 비교하지 않는다.

## 4. 공격형 트랙 — 그림자 기록 ([docs/2026-10-28-aggressive-track.md](docs/2026-10-28-aggressive-track.md))

- 10-28 운용자 결정, **11-10 운용자 결정: 실계좌 투입 안 함**(60영업일 판정 뒤 통과 멤버가 있으면 그때 다시 — 그 전엔 먼저 꺼내지 않는다).
  목표 "3년 동안 계속 번다"(입장 P4 롤링 3년 > 0) · "월 10% × 3년"은 보고만. 그림자 MDD 30% 첫 돌파 critical(정지선).
- **공격형 리그** `aggr_shadow.py`(`data/aggr/`, 판단 배치에서 분봉 수집 뒤, 멤버마다 50만원): ORB-B1·B2(5분 시가 범위 돌파, `lab_orb`) ·
  ORB-B3(손절·익절 판단 = KODEX200 가격, 11-11~) · FEAR-V1·V2(VIX>30)·K1·K2(KOSPI 20일 변동성>25%, `lab_fear`) · FEAR-P1·P2(변동성 국면의
  최근 20거래일 정점 대비 20% 꺾인 뒤, 11-11~) · HH1(한미 반반 × 한국 2배, 운용자 예외 `aggr_shadow.EXCEPTIONS`) ·
  **FLOW-S1(외국인 극단 순매도 뒤 인버스 20일, `lab_flow_fwd`, 11-24 신호부터 — 판정은 완료 거래 10번 뒤)**. 모두 **앞으로만** 기록.
  FEAR-K2 는 11-06 정지선 도달. 2주 점검(11-11) 규칙 변경 없음 → **판정 2027-01-25**(ORB-B1·B2·FEAR-V·K) · 01-26(HH1) · 02-05(B3·FEAR-P).
- 측정 끝난 세대(전부 탈락): A 양방향 `lab_aggr`(인버스 손실) · C 하락 예측 판정대 `lab_downside`(추세 밖 7개 — 가장 큰 상승일이 하락 신호
  켜진 날에 온다) · A2 레버리지 × 낙폭 예산 `lab_aggr_gen2`(연수익 ≈ MDD × 0.5~0.65 한 줄 — 레버리지는 자리만 옮김) · A3 한미 반반 ×
  한국 2배 `lab_aggr_gen3`(HH1 만 운용자 예외로 리그에).

## 5. 시장 일지 · 수급 이력 ([docs/2026-11-06-market-journal.md](docs/2026-11-06-market-journal.md))

- `market_journal.py`: 아침(확정 수급 · 밤사이 미국 · 밤사이 뉴스 · 일정 `market_calendar.json`) + 판단 배치 close(뉴스 · DART · 잠정 수급).
  원자료 `data/market_journal/`, 규칙 기반 요약만(AI 해설 없음). Notion 「📰 시장 일지」DB 는 확정 수급 뒤라 하루 늦게.
- 연구용 수급 이력 `data/market_flows/daily.csv`(`market_flows.py`, 2010-01-04~, 4,000일+): 날짜 대조 가드(응답 지수 vs FDR ^KS11 0.5%) —
  **연구는 `check == ok` 만**. 대조값이 틀린 날은 `market_flows.VERIFIED`(다른 출처로 확인한 종가와 정확히 같을 때만 ok — 2021-05-06).
- **수급 판정대 `lab_flows.py`(11-16, 통과 없음)**: 외국인·기관·프로그램 수급의 5일 방향 신호 5개가 2010~2020·2021~ 두 구간을 못 버텼다
  ('쌍끌이'는 2020 까지만, 2021 이후 대량 매도 뒤 되돌림) — [docs/2026-11-16-flows-news-lab.md](docs/2026-11-16-flows-news-lab.md).
- **뉴스·경제 지표 일지 `market_features.py`(11-16~, 앞으로만)**: 판단 배치에서 일지 close 뒤 하루 1행(`data/market_features/daily.csv`).
  가설 N1~N3 **판정 2027-04-30(120거래일)** — 그 전엔 결과를 계산하지 않는다(`--judge` 도 해당 날 수만).
- **Claude 뉴스 판단 일지 `llm_news.py`(11-25~, 운용자 "시작하자", 앞으로만 — 매매엔 안 씀)**: 판단 배치 맨 끝, 그날 일지의 뉴스·공시 제목
  (정해진 규칙, 410개 안팎)만 headless Claude(**`claude-opus-5-5` 고정** · 도구·MCP·설정 없음 · 프로젝트 밖 `%TEMP%\llm_news_cwd`)에게 주고
  다음 5거래일 코스피 direction −2~+2 · risk 를 묻는다 → `data/llm_news/daily.csv` + 넣은 글 `inputs/`. 그날 안에만·하루 한 번·거래일만,
  지난 날은 안 채운다. 가설 L1(부정 → 뒤 5일 약함)·L2 — N2 와 같은 잣대 + 구간 섞기 p ≤ 0.01, **판정 120거래일(2027-05 무렵)** —
  [docs/2026-11-25-llm-news-lab.md](docs/2026-11-25-llm-news-lab.md). 실패 알림 뒤 그날 안에 `python scripts\llm_news.py` 재실행.

## 6. Notion — 쓰기 전에 [docs/notion-guide.md](docs/notion-guide.md) 를 먼저 읽는다

- 트리 최상위 「📈 주식 자동 매매」(허브) → I3 대시보드(`4011459d6f5881b6a381ddb8bb623f8c`, 요약·바로가기만 — 손으로 늘리지 않는다) ·
  ⚔️ 공격형 트랙(공격형 리그 멤버DB) · 공통 장부DB · 종료한 추세추종(지우지 않는다).
- 매일 쌓이는 것은 **DB 행으로만**: 판단 배치 끝 `scripts\i3_notion.cmd`(prep `i3_notion_sync.py` → headless claude `i3_notion_task.md` →
  check)가 일일 기록DB(+「리그」·「공격형 리그」 한 줄)·매매일지DB(🛡️ I3)·월별 결산DB·시장 일지DB 에 **없는 행만**, 실패하면 텔레그램 critical.
- **줄임말 단독 금지 — 「풀네임(줄임말)」**(운용자 10-22, 용어표 notion-guide §1-7). 코드·텔레그램 문구는 그대로. 자동 문구는
  `i3_notion_sync.TRACK·MARK·DISPLAY·AGGR_DISPLAY`(새 멤버가 빠지면 테스트가 잡는다). 파일명은 백틱으로.
- 코드 변경·운용 결정·사고는 커밋할 때 **운영 이력DB 1행**, 연구 1회는 연구 기록DB, 할 일은 Flow Task(Project I3).

## 7. 작업 규칙 (사고들의 산물 — 반드시 지킨다)

1. **사전 선언.** 판정 기준을 측정 **전에** 코드 상수로 선언·커밋한다. 결과를 본 뒤 기준을 고치면 그 검증은 무효. 단일 구간 in-sample 채택 금지.
   같은 숫자로 다시 재지 않는다. 결과 표를 보고 떠올린 아이디어는 과거로 판정하지 않고 앞으로만 기록한다.
2. **검증 조건 = 운용 조건.** 예탁금(정수 주식수)·비용·데이터 출처·체결 시각이 하나라도 다르면 그 숫자는 다른 전략의 것이다.
3. **안전장치는 하는 일과 적힌 일이 같아야 한다** — 새 가드는 **일부러 깨뜨려** 발동을 확인한다. 테스트는 목 대신 실제 경계(writer→reader)를 지난다.
4. **실전 코드를 바꿀 때**: 옛 길 vs 새 길 실데이터 대조 → 일부러 깨뜨리기 → 전체 테스트 → 커밋. 주문 시간(08:30~09:20 · 15:50~16:00)엔
   배치 재실행·MCP 재시작을 하지 않는다 — **PreToolUse 훅 `scripts/claude_guard.py` 가 막는다**(11-19 ㉓, `.claude/settings.json`,
   평일 그 시간 배치·MCP·프로세스 종료·예약작업·git 작업 트리·`scripts/`·`src/`·`data/`·`.env` 쓰기 차단, 읽기는 됨. 사고 방지용 —
   보안 경계 아님). 막히면 우회하지 말고 시간 뒤에. `ClaudeCliDaily` 는 `--permission-mode default` 지만 **11-20 운용자 "권한 요청하지 말고
   진행"** → `.claude/settings.local.json` 허용 목록(PowerShell·Bash·Edit·Write·Notion 등)이라 승인 창이 없다. 훅은 그대로 막는다.
   **이 파일은 프로젝트 루트 `CLAUDE.md`**(11-23 `.claude/` 에서 옮김 — `.claude/` 안 파일 수정은 허용 목록과 무관하게 늘 승인을 묻는다
   (내장 안전 검사). 설정·훅은 일부러 `.claude/` 에 남겨 보호받게 둔다. 루트 `CLAUDE.md` 는 **11-23 운용자 "CLAUDE.md도 git에 올려줘" →
   git 에 올린다** — 비밀값(키·계좌번호·IP)을 이 파일에 적지 않는다).
5. **조회 실패를 0·보유 없음·휴장으로 믿지 않는다. 응답 불명 주문은 재전송하지 않는다.**
6. 커밋마다 문서(`docs/`)·Notion 운영 이력·메모리를 맞추고 push. `.env` 비밀값은 출력하지 않는다.
7. 수십 분 넘는 작업은 Windows 예약작업으로(세션에서 띄운 프로세스는 세션 종료 때 같이 죽는다). Bash 도구는 자주 멈춘다 → PowerShell·Grep·Read.

## 8. 장애 대응

- **키움 8050(IP 미등록)** — 11-09·11-12 두 번(공인 IP 변경). 연결 점검 알림 또는 15:50 「판단 중단 · 키움: 8050」 →
  공인 IP(`api.ipify.org`)를 운용자에게 알려 **키움 REST API 사용신청에 등록** → `cmd /c scripts\i3_decide.cmd` 재실행(약 5분) → 판단·두 리그 asof·
  분봉·`%TEMP%\i3_notion.log` 의 '재판단 갱신' 확인. 분봉은 다음 날 15:50 전까지 복구된다. **8050 은 앱키 만료 때도 같은 문구였다(10-06)** — 둘 다 확인.
- **`.env` 키를 바꾸면 MCP 서버 재시작**(서버가 기동 때 키를 들고 있다 — 워치독은 포트가 살아 있으면 재시작하지 않는다). 이 환경에선
  `run_mcp_local.py stop`(taskkill)이 "액세스 거부" → `Stop-Process` 로 내리고 `start`, **재시작 후 도구 스키마로 새 코드 반영 확인**.
  trading-domain 코드를 바꿨으면 8030 재시작 필수.
- **Notion 자동 기록 실패 `Failed to authenticate: OAuth session expired`**(11-19 첫 발생): 배치가 띄우는 headless `claude` 의 로그인 만료 —
  대화 세션의 Notion 연결과 별개다. 운용자가 터미널에서 `claude` → `/login`. 그 뒤 `scripts\i3_notion.cmd` 재실행 또는 다음 배치가
  없는 행만 채운다(prep 창이 최근 ~10일).
- **토큰 8005**: 클라이언트가 공유 캐시(`%TEMP%/kiwoom_token_cache/`) + 강제 재발급으로 자동복구. 안 되면 `KIWOOM_PRODUCTION_MODE` 와 키 종류
  (실거래/모의) 일치 확인, 캐시 삭제 후 재시도.
- 로그: `logs/i3/i3_live.log`(판단·매매·키움 조회 경고) · `logs/i3/i3_task.log`(배치 전체) · `%TEMP%\i3_notion.log` ·
  `logs/kiwoom_net/check.log` · `logs/market_journal/` · `%TEMP%/mcp_logs/`(MCP stdout).

## 9. 파일 지도 (운용 중인 것)

- **실전**: `i3_core.py`(판단) · `i3_live.py`(판단·매매 실행) · `i3_flows.py` · `i3_fills.py` · `kiwoom_read.py`(키움 조회) · `atomic_io.py`(파일 쓰기) ·
  `bar_archive.py`(일봉 보관소 — FDR 3,000거래일 상한, `--status`·`--seed`) ·
  `market_session.py`(장 시간 — 일정 파일 open·close, 훅도 읽는다) ·
  `heartbeat.py`(무소식 감시) · `claude_guard.py`(주문 시간 훅) ·
  `ops_base.py`(I3 쪽이 부르는 공용 이름 — URL·계좌·`notify` 를 다시 내보낸다) · `trend_kiwoom_io.py`(MCP 계좌 평가·주문 헬퍼 —
  `_broker_holdings_checked` 는 실패를 None 으로) · `trend_config.py`(.env 로드·MCP URL·계좌 — 구현) · `trend_runtime.py`(`notify` 구현) ·
  `trend_lock.py` · `trend_watchdog.py`. trend_* 는 종료한 트랙 이름을 단 공용 기반이고, 구현은 옮기지 않았다(.env 로드 순서·
  `test_trend_config` reload 시험) — I3 쪽 새 코드는 `ops_base` 로 부른다.
- **리그·연구**: `i3_shadow.py` · `aggr_shadow.py` · `strategy_lab.py` · `lab_*.py`(세대·판정대 선언과 결과가 docstring 에) · `trend_paper.py`(리그의 추세추종 멤버).
- **수집·기록**: `market_journal.py` · `market_flows.py` · `market_features.py` · `llm_news.py`(Claude 뉴스 판단) · `collect_i3_minutes.py` · `i3_notion_sync.py` + `i3_notion_task.md` ·
  `kiwoom_net_check.py` · (중단 11-18: `collect_foreign_flow.py` + `foreign_flow.cmd`).
- **배치**: `i3_decide.cmd` · `i3_trade.cmd` · `i3_notion.cmd` · `market_journal_morning.cmd` · `market_flows_backfill.cmd` · `kiwoom_net_check.cmd` ·
  `trend_watchdog.cmd`.
- **데이터**: `data/i3/`(state·events·fills·shadow) · `data/bar_archive/`(일봉 보관 — 지우지 않는다, `.bak` 있음) · `data/llm_news/` · `data/aggr/` ·
  `data/market_journal/` · `data/market_flows/` · `data/minute/` · `data/kiwoom_net/` ·
  `docs_cache/lab/`(연구 캐시 — 커밋하지 않는다).
- **MCP 서버**(`src/mcp_servers/kiwoom_mcp/domains/`, `run_mcp_local.py`): 8030 trading(주문) · 8034 portfolio(계좌 평가) · 8033 investor(11-18 외인 수집 중단 뒤 운용 코드는 안 씀 — 워치독 목록은 그대로) ·
  8031 market · 8032 info. **워치독은 `run_mcp_local.py start live` 로 이 키움 5개만 띄운다**(11-12 — `LIVE` = `ESSENTIAL_PORTS`, 테스트가 맞춰 본다).
  tavily·naver_news·stock·financial·macro·closing_bet·trend 7개는 운용 코드가 쓰지 않는다(손으로 `start` 하면 전부 — 시장 일지는 네이버 API 직접).
  MCP 클라이언트 `src/claude_agents/base/mcp_client.py`(`MCPManager`). 키움 도메인 URL 은 `/mcp/`(슬래시).

## 10. 개발 환경

- Python 3.12+ · `uv` · 실행 `D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe`.
- 테스트 `python -m pytest tests/ -q`(약 910개, 1분 남짓 — 실데이터 캐시가 없으면 일부 건너뜀).
- `.env`: `KIWOOM_APP_KEY`·`KIWOOM_APP_SECRET`·`KIWOOM_ACCOUNT_NO`(필수) · `KIWOOM_PRODUCTION_MODE`(실거래 키 + true 만, 모의 키면 false) ·
  `TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID`(+ `TELEGRAM_CRITICAL_CHAT_ID`) · `I3_DRY_RUN`·`I3_HALT` · `HEARTBEAT_TRADE_URL`·`HEARTBEAT_DECIDE_URL` · `NAVER_CLIENT_ID/SECRET` · `DART_API_KEY` ·
  `TREND_WATCHDOG_DAEMON=off`.

## 스킬 자동 활성화

다음 작업 컨텍스트 감지 시 caveman 스킬을 **명시 호출 없이 자동 적용**한다:

- **코드 리뷰 / 분석** 요청 ("리뷰", "review", "분석", "분석해줘", "코드 봐줘", PR 리뷰, 함수 점검 등)
  → `caveman-review` 자동 활성화. 불필요한 칭찬·서론 제거, 핵심 이슈/리스크/개선점만 압축 출력.
- **프로젝트 통계 / 메트릭** 요청 ("통계", "메트릭", "stats", "코드 규모", "파일 개수", "복잡도", "테스트 커버리지", "프로젝트 현황" 등)
  → `caveman-stats` 자동 활성화. 수치 위주 압축 보고.

위 트리거에 해당하지 않으면 평소 톤 유지. 사용자가 "stop caveman" 또는 "normal mode" 명시 시 즉시 해제.
