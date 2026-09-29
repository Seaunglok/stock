@echo off
REM Foreign flow (ka10008) daily snapshot - keeps history for foreign-exit revalidation.
REM Collection had silently stopped on 2026-08-25 when the foreign exit was switched off.
REM ka10008 returns only ~50 completed days, so gaps longer than that are lost for good.
REM Weekdays 16:20. Read-only: investor-domain :8033, no orders.
REM Manual test:  scripts\foreign_flow.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\trend_follow mkdir logs\trend_follow
echo ==== %DATE% %TIME% >> logs\trend_follow\foreign_flow.task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\collect_foreign_flow.py >> logs\trend_follow\foreign_flow.task.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> logs\trend_follow\foreign_flow.task.log
exit /b %RC%