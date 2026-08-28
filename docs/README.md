# docs/ 안내

## 추세추종 트랙 — 읽는 순서

**현재 운용 구성과 그 근거를 알고 싶다면** 아래 5개를 시간순으로 읽으면 된다.
2026-08-27~28 이틀 동안 검증 방법과 전략이 함께 바뀌었고, 각 문서가 그 한 단계다.

| # | 문서 | 무엇을 밝혔나 |
|---|---|---|
| 1 | [2026-08-27-backtest-window-defect.md](2026-08-27-backtest-window-defect.md) | 백테스트가 `--start` 를 무시해 모든 A/B 가 멜트업 9개월만 측정했다. `blend` 랭킹 철회 |
| 2 | [2026-08-27-full-revalidation.md](2026-08-27-full-revalidation.md) | 채택값 12축 전수 재검증 + 구간분할 도입 |
| 3 | [2026-08-28-survivorship-and-12y-sample.md](2026-08-28-survivorship-and-12y-sample.md) | 생존편향 제거(시점별 유니버스) + 12년 표본 — 엣지 없음 확인 |
| 4 | [2026-08-28-stage-diagnosis.md](2026-08-28-stage-diagnosis.md) | 진입/청산 기여도 분해 — **ATR 트레일이 원인**, 진입은 작동 |
| 5 | [2026-08-28-walkforward.md](2026-08-28-walkforward.md) | 워크포워드 하니스 + 사전선언 기준 + 노출 프론티어 |
| 6 | [2026-08-28-adoption.md](2026-08-28-adoption.md) | 채택 구성 적용 · 라이브 재개 · 실계좌 예탁금 재검증 |

부수: [2026-08-28-rs-definition-ab.md](2026-08-28-rs-definition-ab.md)(RS 정의 A/B — 막다른 길),
[trend_follow_strategy.md](trend_follow_strategy.md)(전략 상세),
[shadow_ledger.md](shadow_ledger.md)(그림자 원장),
[live_trading_switchover.md](live_trading_switchover.md)(실전 전환 절차).

## 일별 매매일지

`journal/YYYY-MM-DD-trend-journal.md` — 데몬이 15:20 청산 phase 뒤 자동 생성한다.
평일 16:10 `TrendJournalNotion` 이 그 파일을 읽어 Notion 에 반영한다.
**경로를 바꾸면 `scripts/trend_journal.py` 와 `scripts/notion_journal_task.md` 를 함께 고쳐야 한다**
(`tests/test_trend_journal.py::test_journal_path_and_notion_task_agree` 가 잠근다).

## 종가매매 트랙

[closing_bet_strategy.md](closing_bet_strategy.md) ·
[backtest_exit_policy_2026-06-01.md](backtest_exit_policy_2026-06-01.md)

## 회고

[2026-06-19-mock-7day-review.md](2026-06-19-mock-7day-review.md) ·
[2026-08-03-live-first-month-review.md](2026-08-03-live-first-month-review.md) ·
[2026-08-17-safety-refactor.md](2026-08-17-safety-refactor.md)
