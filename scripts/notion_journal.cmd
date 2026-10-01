@echo off
REM Trend journal -> Notion (headless claude). ASCII only (cmd.exe cp949 safe).
REM Korean instructions live in scripts\notion_journal_task.md (read by claude).
REM Manual test:  scripts\notion_journal.cmd
REM
REM 2026-10-01: the 09-28 run hit a Notion rate limit and ended with no result line, yet the
REM task result was 0x0 and the day's two buys never reached the DB. Now:
REM   prep  - python computes the last 7 days of trades -> data\trend_follow\notion_sync_trades.json
REM           (the agent only inserts rows that are missing, so a failed day heals on the next run)
REM   check - if this run's log has no result line (or an X mark), send a Telegram alert and exit 1
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
set "PY=D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe"
set "LOG=%TEMP%\notion_journal.log"
set "OFS=0"
if exist "%LOG%" for %%A in ("%LOG%") do set "OFS=%%~zA"
"%PY%" scripts\notion_sync.py prep >> "%LOG%" 2>&1
"C:\Users\hihih\.local\bin\claude.exe" -p "Read the file scripts/notion_journal_task.md and do exactly what it instructs. Be concise." --allowedTools "Read,ToolSearch,mcp__claude_ai_Notion" --permission-mode acceptEdits < NUL >> "%LOG%" 2>&1
"%PY%" scripts\notion_sync.py check --log "%LOG%" --offset %OFS% >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
