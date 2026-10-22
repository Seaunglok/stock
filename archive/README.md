# archive — 운영을 끝낸 트랙 보관 (2026-10-22)

운용자 결정(10-22): 운영이 끝난 트랙은 지우지 않고 여기로 옮겨 운영 코드와 분리한다. git 기록과 함께 그대로 남는다.

| 묶음 | 파일 | 운영 기간 · 끝난 이유 |
|---|---|---|
| 종가매매 | `scripts/direct_closing_bet.py`(데몬) · `backtest_closing_bet.py` · `backtest_hybrid.py` · `tune_weights.py` · `_dart_cache.py` · `dashboard.py`/`.html` · `_force_selection.py` · `_start_daemon.py` · `_kill_daemons.py` · `tests/test_closing_bet_helpers.py` | 2026-05~06. KOSPI 약세장 veto 로 검증 불가가 이어져 추세추종으로 전환 |
| 추세추종 데몬 | `scripts/trend_follow.py`(데몬) · `shadow_ledger.py` · `trend_journal.py` · `collect_minute_bars.py` · `trend_dashboard.py` · `trend_panic.py` · `kelly_monitor.py` · `notion_sync.py` · `notion_journal.cmd` · 데몬 전용 테스트 9개 | 2026-06~10-22. 시점별 재검증에서 ① 미달 → 신규진입 정지(10-21) → I3 로 교체(10-22). 기록은 docs/ |

## 그대로 남긴 것 (I3·리그·인프라가 쓴다 — 옮기면 깨진다)

`trend_config` · `trend_kiwoom_io` · `trend_runtime` · `trend_lock` · `trend_watchdog`(MCP 유지, 예약 작업) ·
`collect_foreign_flow`(예약 작업) · `trend_paper` · `backtest_trend_portfolio` · `backtest_trend` · `walkforward_trend`
(리그의 '추세추종' 멤버와 연구 테스트) · `src/mcp_servers/closing_bet_mcp`·`trend_mcp`(MCP 서버).

## 되살리기

```bash
git mv archive/scripts/<파일> scripts/<파일>      # 테스트도 archive/tests → tests
```
여기 있는 코드는 `scripts/` 경로를 전제로 import 하므로, 그대로는 실행되지 않을 수 있다(보관용).
워치독은 `scripts/trend_follow.py` 가 없으면 데몬을 재기동하지 않는다(`TREND_WATCHDOG_DAEMON=off` 유지).
예약 작업 `TrendJournalNotion`(비활성)은 `scripts/notion_journal.cmd` 를 가리킨다 — 되살릴 때 경로도 되돌릴 것.
