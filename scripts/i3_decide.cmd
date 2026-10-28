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
REM I3 challenger league (shadow, no orders) - runs after decide; its failure does not change RC.
echo ---- league %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\i3_shadow.py >> logs\i3\i3_task.log 2>&1
echo league_exit=%ERRORLEVEL% >> logs\i3\i3_task.log
REM Minute bars (Kiwoom keeps only ~900 recent bars - collect daily or lose them). Does not change RC.
echo ---- minutes %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\collect_i3_minutes.py >> logs\i3\i3_task.log 2>&1
echo minutes_exit=%ERRORLEVEL% >> logs\i3\i3_task.log
REM Aggressive league (shadow, no orders: ORB + fear buy) - after minutes, since ORB needs today's minute bars.
REM Does not change RC.
echo ---- aggr %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\aggr_shadow.py >> logs\i3\i3_task.log 2>&1
echo aggr_exit=%ERRORLEVEL% >> logs\i3\i3_task.log
REM Notion daily records (DB rows only - see docs\notion-guide.md). Last, so it sees decide+league. Does not change RC;
REM its own check step sends a Telegram alert when the sync did not finish.
echo ---- notion %TIME% >> logs\i3\i3_task.log
call scripts\i3_notion.cmd
echo notion_exit=%ERRORLEVEL% >> logs\i3\i3_task.log
exit /b %RC%