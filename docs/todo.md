# TODO — Closing-Bet 자동매매 시스템

마지막 갱신: 2026-05-08

---

## 🔴 우선순위 높음

### [백테스트] KS11(KOSPI) 복구 후 3차 실험
- **문제**: FDR/pykrx 모두 KS11 응답 거부 중. 현재 005930+000660 프록시로 대체.
- **필요 이유**: 2차 백테스트 결과가 프록시 기반이라 1차(KOSPI 실측)와 직접 비교 불가.
  weak 정의 완화의 순수 효과를 분리하려면 KS11 복구 필수.
- **작업**:
  - [ ] `fdr.DataReader("KS11", ...)` 대체 엔드포인트 탐색 (KRX 공식 API, FinanceData 등)
  - [ ] KS11 복구되면 동일 설정으로 3차 재실행 (`weak_kospi_pct=-0.5, adv=0.40`)
  - [ ] 1차·2차·3차 결과 3-way 비교표 작성
- **관련 파일**: `scripts/backtest_with_breadth_gate.py`, `docs/backtest_breadth_gate_v2.md`

---

### [백테스트] neutral-only 모드 검증
- **배경**: 2차에서 neutral 레짐이 55.2% / +1.01%로 최우수였지만 프록시 기반.
- **가설**: 중립장(시장 방향성 불분명)에서 거래대금 급등 신호가 가장 깨끗.
- **작업**:
  - [ ] `gate_mode=neutral-only` 추가 (`scripts/backtest_with_breadth_gate.py`)
  - [ ] KS11 복구 후 neutral-only 백테스트 실행
  - [ ] neutral 55.2% 재현 여부 확인
- **우선순위**: KS11 복구 후 진행

---

## 🟡 우선순위 중간

### [백테스트] weak sensitivity sweep
- **목적**: weak 레짐 정의 임계값 조합별 성능 격자 탐색.
- **그리드**:
  - `weak_kospi_pct ∈ {-1.5, -1.0, -0.7, -0.5}` (4개)
  - `weak_adv_ratio ∈ {0.30, 0.35, 0.40, 0.45}` (4개)
  - 총 16개 조합
- **작업**:
  - [ ] sweep 실행 스크립트 작성 (`scripts/sweep_weak_params.py`)
  - [ ] 결과 히트맵 시각화 (승률·평균수익 2차원 격자)
- **전제 조건**: KS11 복구 필수

---

### [MCP] `classify_breadth_regime` 도구 추가
- **목적**: 라이브 자동매매 흐름에 레짐 판정 내장.
  현재는 스크립트/프롬프트 레벨에서만 레짐을 계산.
- **위치**: `src/mcp_servers/closing_bet_mcp/` 또는 `stock_analysis_mcp/`
- **작업**:
  - [ ] `classify_breadth_regime(date, universe_codes)` MCP 도구 구현
    - KOSPI 당일 등락률 (KS11 또는 프록시)
    - universe 내 양봉 비율 계산
    - → `strong / neutral / weak` 반환
  - [ ] AnalysisAgent 프롬프트에 레짐 활용 지시 추가
  - [ ] closing-bet-mcp 서버에 등록
- **관련 파일**: `src/mcp_servers/closing_bet_mcp/`, `src/claude_agents/base/prompts.py`

---

### [대시보드] `docs/dashboard.html` 기능 개선
- **파일**: `scripts/gen_dashboard.py`
- 잠재적 개선 항목:
  - [ ] 날짜 범위 필터 (월별/주별 선택)
  - [ ] 종목별 누적 등장 횟수 및 평균 수익 집계 뷰
  - [ ] 레짐별 수익 분포 히스토그램 (각 모드 탭)
  - [ ] 대시보드 자동 갱신 — 새 백테스트 CSV 생성 시 re-run hook

---

## 🟢 낮은 우선순위 / 장기

### [백테스트] regime_adaptive 전략 검증
- **파일**: `scripts/backtest_regime_adaptive.py` (존재, 미완)
- 레짐별로 다른 top_n / threshold를 적용하는 적응형 전략.
- [ ] 완성 및 기존 fixed 전략과 성능 비교

### [인프라] docs_cache 관리
- `docs_cache/ohlcv/` 파일이 누적 중 (종목 × 기간별 중복 가능).
- [ ] 중복 캐시 정리 스크립트 (같은 코드, 기간 포함 관계인 경우 합산)
- [ ] 캐시 만료 정책 (90일 이상 된 파일 자동 제거 옵션)

### [라이브] 자동매매 실전 연결
- 현재는 백테스트·분석 레이어만 완성. 실제 주문 실행 미연결.
- [ ] `TradingAgent` mock → real 주문 전환 테스트 (소액 실전)
- [ ] closing-bet → 레짐 판정 → 픽 → 주문 전체 파이프라인 e2e 테스트
- **전제 조건**: 위 모든 백테스트 검증 완료

---

## 완료된 항목 (참고)

| 날짜 | 항목 |
|---|---|
| 2026-05-06 | closing-bet 스코어러 v2, 백테스트 1차 (KOSPI 실측), tune_weights |
| 2026-05-08 | KOSPI 프록시 폴백, 2차 백테스트, weak-filtered 모드, PLAYBOOK A 갱신 |
| 2026-05-08 | 인터랙티브 대시보드 (`scripts/gen_dashboard.py`, `docs/dashboard.html`) |
