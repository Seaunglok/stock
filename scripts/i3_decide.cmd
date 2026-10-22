@echo off
REM I3 live - decide target weight from today's close. Weekdays 15:50 (after 15:35 guard).
REM I3_DRY_RUN (default true in code) controls whether the next trade phase sends real orders.
REM Manual test:  scripts\i3_decide.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\i3 mkdir logs\i3
echo ==== decide %DATE% %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\i3_live.py --phase decide >> logs\i3\i3_task.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> logs\i3\i3_task.log
exit /b %RC%