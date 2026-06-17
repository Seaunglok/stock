@echo off
REM Trend daemon watchdog — keeps MCP servers + daemon alive (auto-recovery).
REM Registered to Task Scheduler; runs every 5 min during market hours (weekdays).
REM Manual test:  scripts\trend_watchdog.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
set TREND_UNIVERSE=largecap
python scripts\trend_watchdog.py >> "%TEMP%\trend_watchdog.task.log" 2>&1
