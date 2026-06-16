@echo off
REM Trend journal -> Notion (headless claude). ASCII only (cmd.exe cp949 safe).
REM Korean instructions live in scripts\notion_journal_task.md (read by claude).
REM Manual test:  scripts\notion_journal.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
"C:\Users\hihih\.local\bin\claude.exe" -p "Read the file scripts/notion_journal_task.md and do exactly what it instructs. Be concise." --allowedTools "Read,ToolSearch,mcp__claude_ai_Notion" --permission-mode acceptEdits < NUL >> "%TEMP%\notion_journal.log" 2>&1
