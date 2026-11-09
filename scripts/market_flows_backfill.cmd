@echo off
REM Market flows history backfill (Kiwoom ka10051/ka90010, read only) - resumes from what daily.csv already has.
REM Runs as Windows task MarketFlowsBackfill so it survives the Claude session (11-06 run died with the session).
REM Manual:  schtasks /run /tn MarketFlowsBackfill   (or run this file). Do not run during 08:30-09:10 or 15:50-16:00.
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\market_journal mkdir logs\market_journal
echo ==== backfill %DATE% %TIME% >> logs\market_journal\backfill.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\market_flows.py --backfill --start 2010-01-04 >> logs\market_journal\backfill.log 2>&1
echo exit=%ERRORLEVEL% >> logs\market_journal\backfill.log
