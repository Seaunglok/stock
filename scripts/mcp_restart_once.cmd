@echo off
REM One-off MCP restart after market close (picks up server code changes). Not a recurring task.
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\i3 mkdir logs\i3
echo ==== mcp restart %DATE% %TIME% >> logs\i3\i3_task.log
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" run_mcp_local.py stop >> logs\i3\i3_task.log 2>&1
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" run_mcp_local.py start >> logs\i3\i3_task.log 2>&1
echo exit=%ERRORLEVEL% >> logs\i3\i3_task.log