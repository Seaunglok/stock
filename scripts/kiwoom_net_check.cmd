@echo off
REM Kiwoom connection check - run by Windows task KiwoomNetCheck on network change / logon / weekdays 15:30.
REM Read only (one Kiwoom chart call). Alerts to Telegram if blocked (8050 = IP not registered) with the current public IP.
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
if not exist logs\kiwoom_net mkdir logs\kiwoom_net
"D:\kiwoom_rest_study\multi_agent_kiwoom\.venv\Scripts\python.exe" scripts\kiwoom_net_check.py --delay 20 >> logs\kiwoom_net\check.log 2>&1
