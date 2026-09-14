@echo off
REM Trend model book (paper) - daily baseline for live fill comparison. Weekdays 16:10.
REM Task Scheduler could not run a bare "python" Execute (0x80070002 on 2026-09-11 and 09-14),
REM so the task runs this wrapper with the absolute venv interpreter instead.
REM Manual test:  scripts\trend_paper.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\trend_follow mkdir logs\trend_follow
echo ==== %DATE% %TIME% >> logs\trend_follow\trend_paper.task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\trend_paper.py >> logs\trend_follow\trend_paper.task.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> logs\trend_follow\trend_paper.task.log
exit /b %RC%
