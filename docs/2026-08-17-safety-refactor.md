# 2026-08-17 안전 리팩터 — 조용히 실패하는 경로 닫기

**한 줄**: 코드 구조 문제를 찾으려다, **실계좌를 위험에 빠뜨리는 조용한 실패 경로 4건**과
**검증한 전략과 실제 도는 전략이 다르다는 사실**을 발견해 전부 고쳤다.

작업일은 대체공휴일(장 휴장)이라 데몬·MCP 서버가 전부 꺼진 상태에서 진행했다.

---

## 0. 배경 — 왜 "구조 리팩터"가 아니게 됐나

직전 두 작업(`5eb83f4` 계층분리, `29e9c25` 락 PID 재사용 방어)으로 함수 길이·계층 문제는
이미 해소돼 있었다(최장 79줄, `trend_mcp/` ↔ `scripts/` 경계 유지). 코드를 훑은 결과 나온 건
성격이 다른 문제였다 — **에러도 알림도 없이 틀리는 경로**들.

08-05 그림자 원장에서 얻은 교훈("측정 코드가 조용히 틀리면 전략 결정이 틀린다")과 같은 계열이고,
이번엔 측정이 아니라 **실행**과 **검증**이 틀릴 수 있는 자리였다.

---

## 1. P0 — 실계좌 위험 직결 (4건)

### 1-1. `state.json` 비원자적 쓰기 + 파싱 실패 시 조용한 `{}`

```python
# before
def load_state() -> dict:
    try:  return json.loads(STATE_FILE.read_text(...))
    except Exception:  return {}        # ← 조용히 "보유 없음"
def save_state(key, content):
    st = load_state(); st[key] = content
    STATE_FILE.write_text(...)          # ← 비원자적
```

**연쇄**: 쓰기 도중 프로세스 사망 → 파일 절단 → `load_state()` 가 경고 없이 `{}` → 데몬이
**보유 0으로 판단** → 실보유분에 손절·트레일이 영영 안 걸림 → 다음 `save_state` 가 빈 dict 를
덮어써 **손실 확정**. `.env` 의 `TREND_ADOPT_MODE=off` 라 `phase_reconcile` 도 다시 안 줍는다.

**이론이 아닌 이유**: watchdog 은 hung 데몬을 `taskkill /F /T` 로 죽이고
([trend_watchdog.py](../scripts/trend_watchdog.py)), `save_state` 는 청산 루프 안에서
**매 매도마다** 호출된다([`_manage`](../scripts/trend_follow.py)). 강제종료와 쓰기가 겹칠
확률이 가장 높은 조합이 이미 코드에 있었다.

**수정**: tmp 쓰기 → `os.replace` 원자적 치환 + 직전본 `.bak` 보존. 손상 시 `.bak` 폴백,
둘 다 실패하면 `StateCorrupted` 예외. `save_state` 가 `load_state` 로 시작하므로 **손상 파일을
덮어쓰지 않고 멈춘다**. 데몬은 이를 critical 텔레그램으로 알린다.

### 1-2. 주문 타임아웃 시 시장가 재전송 → 중복 체결

`_place(..., retries: int = 1)` 이 `wait_for(timeout=10)` 실패 시 **같은 시장가 주문을 재전송**
했다. 브로커가 이미 접수했는데 응답만 늦으면 그대로 이중 체결이다 — 멱등키도 주문번호 대조도
없다. 매도는 `_sell_with_retry` 가 `_place` 를 두 번 부르므로 **최대 4회**.

**핵심은 거부와 불명의 구분**:

| 응답 | 의미 | 재시도 |
|---|---|---|
| `return_code != 0` | 접수 안 됨이 **확실** (8005 토큰만료 등) | 안전 |
| 타임아웃/통신실패 | 접수 여부 **불명** | **금지** |

**수정**: `_place` 재시도 제거, 불명 시 `{"unknown": True}` 표시.
- 매수 → `_confirm_unknown_buy()` 로 잔고 대조 후 실제 체결됐으면 편입(`ADOPT_MODE=off` 가
  기본이라 reconcile 이 안 줍는다 — 여기가 유일한 회수 경로).
- 매도 → 재전송 없이 critical 알림. 이중 매도는 보유보다 많이 파는 결제 사고다.

### 1-3. 검증된 파라미터가 `.env` 에만 존재

| 변수 | `.env`(채택) | 코드 기본값(구값) | `.env` 유실 시 |
|---|---|---|---|
| `TREND_SIZING_MODE` | risk | pct_equity | 사이징 체계 변경 |
| `TREND_PULLBACK_PCT` | 12 | 3 | 후보 거의 0 |
| `TREND_HARD_STOP_PCT` | 10 | 0 | **하드손절 없음** |
| `TREND_DAILY_LOSS_LIMIT_PCT` | 2 | 0 | **서킷 없음** |
| `TREND_BREADTH_MIN_PCT` | 0.4 | 0 | **breadth 게이트 없음** |
| `TREND_ADOPT_MODE` | off | all | **HTS 수동매수분 강제청산** |
| `TREND_ENTRY_CUTOFF` | 14:00 | 10:30 | 보류분 즉시 스킵 |
| `TREND_UNIVERSE` | largecap | watchlist | 유니버스 변경 |

기본값이 전부 **안전장치 OFF 방향**이다. 그리고 `[LIVE-GUARD]` 는 이걸 못 막았다 —
`PRODUCTION_MODE` 자체가 `.env` 의 `KIWOOM_PRODUCTION_MODE` 에서 오므로, `.env` 로드가 실패하면
`PRODUCTION_MODE=false` → **가드 블록 전체가 건너뛰어진다**. 정작 안전장치가 전부 꺼진 그 순간에.
MCP 서버는 여전히 실거래라 주문은 실제로 나가면서 알림 라벨만 `🧪 MOCK` 이 된다 —
6월에 없앤 "라벨↔주문경로 불일치" footgun 의 재발.

**수정**: 기본값을 채택값으로 승격(`.env` 는 override 전용), `ENV_LOADED` 플래그 노출,
LIVE-GUARD 를 `PRODUCTION_MODE` 밖으로 빼서 **항상 평가**.
`tests/test_trend_config.py` 25케이스가 `.env` 없이 import 했을 때의 값을 잠근다.

### 1-4. fail-open `except` 6곳

| 위치 | 과거 동작 | 결과 |
|---|---|---|
| `_circuit_broken` | 일지 판독 실패 → `(False,"")` | 일일손실 서킷 무력화 |
| `_past_entry_cutoff` | 파싱 실패 → `False` | 진입 컷오프 소멸 |
| `_busdays_since` | 파싱 실패 → `0` | `MAX_HOLD` 시간청산 영구 미발동 |
| `_verify_buy_fills` | 조회 실패 → 미검증 통과 | 미체결분이 실포지션으로 잔존 |
| `_try_pending` | 예외 → `return` | 매수분이 pending 에 남아 **재매수** |
| `_manage` | 예외 → `return` | 나머지 포지션 미평가 + 트레일 폐기 + **누적 매도거부 알림 소실** |

**원칙 두 가지로 정리**:
1. 안전장치는 실패 시 **닫힌다** — 판정 근거를 못 구하면 차단/보류 쪽으로.
2. **한 종목의 실패가 나머지 포지션의 손절을 막지 않는다** — `_manage` 는 종목 단위 try/except.

---

## 2. P1 — 검증한 전략 ≠ 실제 도는 전략 (가장 큰 발견)

### 2-1. 무플래그 백테스트가 라이브와 다른 전략을 돌리고 있었다

`backtest_trend.py` 의 A/B 노브(`V_*`)가 **전부 off 기본값**이었고, `run()` 은 이를 설정하지
않는다. 즉 `python scripts/backtest_trend.py --mode largecap` 은 이 설정으로 돌았다:

| 항목 | 무플래그 백테스트 | 라이브 |
|---|---|---|
| 청산 이평선 | MA50 (`cfg.ma_support`) | **MA120** |
| 하드손절 | 없음 | **-10%** |
| 눌림목 게이트 | 3% | **12%** |
| breadth 게이트 | 없음 | **0.4** |
| 레짐 게이트 | 없음 | **KOSPI>MA60** |
| 거래세 | 18bps (왕복 0.41%) | **20bps (왕복 0.43%)** |

문서에 "검증 완료"로 적힌 기대값은 **이 설정**의 숫자였다. 매매일지의 `net_pct`(0.43% 차감)와
백테스트 기대값(0.41% 차감)은 애초에 비교 불가능했고, 실전 성과를 "검증값 대비 미달"로 판단해
온 근거 자체가 어긋나 있었다.

**수정**: `apply_live_mirror()` 가 `trend_config` 에서 읽어 노브를 라이브에 맞춘다 — **기본 동작**.
`--legacy-defaults` 로 구 수치 재현 가능(회귀 확인용, 실제로 완전 재현됨).
거래비용은 `src/mcp_servers/trend_mcp/costs.py` 단일 소스로 통합(`CLOSING_BET_*` 공용 제거 —
종가매매 비용을 바꾸면 추세추종 손익이 같이 움직이던 문제).

**재산출 결과** (2025-01-01 ~ 2026-05-31, 왕복 0.43%):

| 모드 | | 진입 | 승률 | 기대값 | payoff | PF | 누적 |
|---|---|---|---|---|---|---|---|
| largecap | 구 | 282 | 37.6% | +2.00% | 2.61 | 1.57 | +564% |
| largecap | **라이브 미러** | **516** | **50.2%** | **+3.38%** | 2.04 | **2.06** | **+1742%** |
| watchlist | 구 | 27 | 33.3% | +4.29% | 4.38 | 2.19 | +116% |
| watchlist | 라이브 미러 | 45 | 80.0% | +11.10% | 2.61 | 10.42 | +500% |

> watchlist 는 **종목 2개·45거래**라 승률 80%가 종목 선택(삼성·하이닉스)의 결과인지 전략의
> 결과인지 분리되지 않는다. largecap 이 기준이다.
>
> 그리고 이 구간은 **상승장**이다. 실전 6전6패의 원인이던 레짐 불일치는 그대로 유효하며,
> 위 숫자를 하락장 기대값으로 읽으면 안 된다.

**포트폴리오 A/B 재확인** (누락돼 있던 하드손절 추가 후):

| 변형 | 최종 | MDD | MAR | Sharpe |
|---|---|---|---|---|
| 기준(notional 15%) | +38.4% | 18.6% | 1.46 | 1.15 |
| **리스크 균등(risk 1.0%)** | +29.1% | **12.2%** | **1.70** | **1.42** |

리스크 균등 사이징 채택 결론은 **유지**(MDD·MAR·Sharpe 전부 우월). 단 기존 문서의
"수익도 증가(+18.3→+35.5%)"는 성립하지 않는다 — **수익을 내주고 MDD 를 사는 트레이드오프**다.
섹터상한 기각·부분익절 30% 유지 결론도 그대로.

### 2-2. 손절/목표 공식 8중 복제 → `levels()` 단일 정본

ATR→손절→목표(1:rr) 3줄이 라이브·백테스트·그림자원장 8곳에 각각 복제돼 있었다. 정본이던
`_levels` 는 `entry_signal` 안에서만 쓰였다. `atr_k`/`stop_pct`/`rr` 을 바꿀 때 일부만 반영되면
검증한 손익비와 실제 손익비가 조용히 갈린다 — 이 전략의 기대값은 전적으로 1:3 에서 나온다.

`signals.levels(entry, cfg, *, ohlcv|atr_value, stop_ref)` 로 승격하고 8곳 통합.
**동작 무변경 확인**(백테스트 수치 완전 일치).

### 2-3. 청산 사다리 — 통합 대신 동치 테스트

`trend_exit()` 은 프로덕션 호출부 0곳인데 청산 우선순위를 별도 구현하고 있었다(사문화된 세 번째
사다리) → **제거**, 테스트 4개는 `exit_decision` 으로 이관.

백테스트 사다리(`simulate_trade`)는 **구현 통합을 하지 않기로 판단**했다. 일봉 백테스트는 한 봉에서
저가/고가/종가로 각각 다른 신호를 봐야 해 `exit_decision` 을 세 번 부르며 `stop=0`·`target=0`
같은 **센티널로 서로를 비활성화**해야 한다. 그 방식은 지금의 명시적 비교문보다 읽기 어렵고,
`exit_decision` 인자 의미가 바뀌면 백테스트 뜻이 조용히 달라진다 — **막으려던 것과 같은 종류의
결합**이다.

대신 `tests/test_exit_ladder_parity.py` 17케이스로 동치를 잠갔다: 우선순위 5단, 하드손절
발동가 == 백테스트 `hard_floor`, 부분익절 수량 == `cfg.partial_pct`, 외인 MA60 AND 조건,
센티널 비활성화 동작. **한쪽만 고치면 여기서 깨진다** — "주석으로만 보증"되던 불변식을
실행 가능하게 만든 것.

---

## 3. P2/P3 — 구조·문서 (동작 무변경)

- **`trend_config` import 부작용** → `setup_daemon_runtime()` 분리. import 만으로 소켓 타임아웃·
  루트 로거·stdout 인코딩을 바꾸고 있어서, 대시보드가 이 모듈을 쓰는 대신 경로 상수·journal
  파싱·state 로딩을 **통째로 복사**해 뒀었다("config.py 와 동일 파일명" 주석까지 달린 채).
  이제 `trend_dashboard` 가 `trend_runtime` 을 재사용(166→155줄).
- **`src/` → `scripts/` 역참조 제거**. `market_data._broad_codes` 가 `sys.path` 에 `scripts/` 를
  끼워넣고 `backtest_dynamic` 을 import 해, 데몬의 유니버스 조회가 pykrx·FDR·closing_bet scorer 를
  전이 import 했다. 방향을 뒤집었다.
- `from trend_config import *` → 명시 import 47개. `_is_rising` 별칭·`to_dict` 죽은 분기 제거.
- heartbeat 주기(60) ↔ watchdog stale 임계(600)를 **한 쌍**으로 명시 + 일치 테스트.
  주기만 늘리면 watchdog 이 정상 데몬을 hung 으로 오판해 `taskkill` 하는 구조였다.
- `.env.example` 재작성 — `TREND_*` 가 **0개**였고 제거된 `MOCK_MODE=true` 가 남아 있었다.
- 문서가 안내하던 **존재하지 않는 env** 삭제(`TREND_MA_FAST` 등 9개는 `TrendConfig` 하드코딩값,
  `TREND_POLL_MIN` → 실제는 `TREND_INTRADAY_POLL_MIN`).

---

## 4. 테스트

**109 → 257**. 신규 5파일:

| 파일 | 케이스 | 잠그는 것 |
|---|---|---|
| `test_trend_runtime.py` | 13 | state 원자성·손상 복구·미덮어쓰기 |
| `test_trend_config.py` | 25 | `.env` 없이도 채택 전략값 |
| `test_trend_orders.py` | 22 | 유령주문 게이트·재전송 금지 |
| `test_trend_follow_helpers.py` | 32 | fail-closed 방향·heartbeat 쌍 |
| `test_exit_ladder_parity.py` | 17 | 라이브↔백테스트 청산 동치 |

`_order_accepted`(8005 유령주문 게이트, 실주문 성패를 가르는 단일 판정)는 그동안 **테스트가
0개**였다.

> **알아둘 것**: `pytest-asyncio` 가 설치돼 있지 않아 `pytest.ini` 의 `asyncio_mode=auto` 는
> 무효다(`pyproject.toml` 은 `strict` — 서로 충돌하지만 둘 다 작동 안 함). async 테스트는
> `asyncio.run()` 으로 직접 구동한다.

---

## 5. 남은 것

- **CI 없음** — 257개 테스트가 수동 실행에만 의존한다. 실계좌 시스템에서 가장 큰 구조적 공백.
  `pyproject.toml` 의 ruff/coverage 범위도 `src/**` 뿐이라 **실거래 데몬이 사는 `scripts/` 가
  lint·coverage 대상 밖**이다.
- **watchdog hang 감지** — heartbeat 태스크는 살아 있는데 스케줄러만 멈춘 08-13 장애를 못 잡는다.
  "마지막 완료 phase 와 그 시각"을 heartbeat 에 기록해야 한다(기능 추가라 이번 범위 밖).
- **외인 청산룰 전 구간 검증** — ka10008 이력 ~50영업일 한계.
- **11:00 진입 시각** — 일봉 백테스트로 재현 불가. 분봉 축적 후 재평가.
- `docs/` 정리 — 81개 중 45개가 일별 매매일지 + 제거된 A2A 시절 덤프. Notion 자동화가
  `docs/*-trend-journal.md` 경로를 참조하므로 이동 전 그 rule 확인 필요.
