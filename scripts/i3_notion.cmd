@echo off
REM I3 -> Notion daily records (headless claude). ASCII only (cmd.exe cp949 safe).
REM Korean instructions: scripts\i3_notion_task.md (read by claude). Rules: docs\notion-guide.md
REM Called at the end of scripts\i3_decide.cmd (after decide, league, minutes). Manual: scripts\i3_notion.cmd
REM   prep  - python computes the last 10 days of rows -> data\i3\notion_sync.json
REM           (the agent only inserts missing rows, so a failed day heals on the next run)
REM   check - if this run's log has no result line (or an X mark), Telegram critical alert and exit 1
REM           (task result 0x0 is only a process exit code - the 2026-07 OAuth / 09-28 rate-limit lessons)
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
set "PY=D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe"
set "LOG=%TEMP%\i3_notion.log"
set "OFS=0"
if exist "%LOG%" for %%A in ("%LOG%") do set "OFS=%%~zA"
echo ==== i3_notion %DATE% %TIME% >> "%LOG%"
"%PY%" scripts\i3_notion_sync.py prep >> "%LOG%" 2>&1
"C:\Users\hihih\.local\bin\claude.exe" -p "Read the file scripts/i3_notion_task.md and do exactly what it instructs. Be concise." --allowedTools "Read,ToolSearch,mcp__claude_ai_Notion" --permission-mode acceptEdits < NUL >> "%LOG%" 2>&1
"%PY%" scripts\i3_notion_sync.py check --log "%LOG%" --offset %OFS% >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
