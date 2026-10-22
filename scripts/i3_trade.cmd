@echo off
REM I3 live - trade at the opening auction (sells first, buys after 09:00 fill). Weekdays 08:50.
REM Manual test:  scripts\i3_trade.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\i3 mkdir logs\i3
echo ==== trade %DATE% %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\i3_live.py --phase trade >> logs\i3\i3_task.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> logs\i3\i3_task.log
exit /b %RC%