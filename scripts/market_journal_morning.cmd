@echo off
REM Market journal - morning (overnight US, overnight news, calendar) + Telegram morning summary. Weekdays 08:30.
REM Read only - no orders. Korean details: scripts\market_journal.py docstring.
REM Manual test:  scripts\market_journal_morning.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\market_journal mkdir logs\market_journal
echo ==== morning %DATE% %TIME% >> logs\market_journal\journal.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\market_journal.py --phase morning >> logs\market_journal\journal.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> logs\market_journal\journal.log
exit /b %RC%
