@echo off
REM 추세추종 매매일지 → Notion 자동 기록 (헤드리스 claude). Windows 작업 스케줄러용.
REM 데몬이 docs\YYYY-MM-DD-trend-journal.md 를 자동 생성한 뒤(15:20 청산 후), 그 날짜 일지를 Notion 에 반영.
REM 수동 테스트:  scripts\notion_journal.cmd
cd /d D:\kiwoom_rest_study\multi_agent_kiwoom
"C:\Users\hihih\.local\bin\claude" -p "오늘 날짜의 docs/YYYY-MM-DD-trend-journal.md 를 Read 로 읽어라(파일 없으면 종료). Notion 매매일지DB(data_source 63d8ae25-9910-4a36-ba3f-3dc942cb9733)에서 오늘 매수일자 행을 먼저 조회해 '이미 있는 종목은 건너뛰고', 일지의 신규 매수/청산만 매수일자=오늘, 증권사=키움증권, 매매이유 앞에 로봇이모지로 추가하라. 그리고 Trading OS 하위 월별결산 DB(data_source 2c0f5ffd-e5d7-4587-a765-85ba9ec084dc)의 2026년 6월 행 총매수/총실현 합계를 일지 기준으로 갱신하라. 끝나면 한 줄로 요약 출력." --allowedTools "Read,ToolSearch,mcp__claude_ai_Notion" --permission-mode acceptEdits >> "%TEMP%\notion_journal.log" 2>&1
