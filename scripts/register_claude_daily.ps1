# Registers Windows task ClaudeCliDaily (2026-11-19, operator request) - re-run this file to re-create it.
# Daily 09:00: opens a cmd window in the project dir with an interactive Claude Code session, Remote Control on
# (reach it from claude.ai/code or the Claude mobile app). The session only starts - it runs nothing by itself.
# cmd /k keeps the window after claude exits. While an earlier window is still open, that day's run is skipped
# (IgnoreNew) - the PC is shut down nightly, so normally a fresh window every morning.
# Windows Terminal (wt.exe) is not installed on this PC, so plain cmd.exe.
# 09:00 is inside the order window (08:30-09:20): do not re-run batches or restart MCP from this session
# before 09:20 (CLAUDE.md rule 4).
$ErrorActionPreference = 'Stop'
$root = 'D:\kiwoom_rest_study\multi_agent_kiwoom'
$claude = "$env:USERPROFILE\.local\bin\claude.exe"
if (-not (Test-Path $claude)) { throw "claude.exe not found: $claude" }

$action = New-ScheduledTaskAction -Execute 'cmd.exe' `
    -Argument "/k `"`"$claude`" --remote-control multi_agent_kiwoom`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName 'ClaudeCliDaily' -Force -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal `
    -Description 'Daily 09:00 interactive Claude Code session in the project dir with Remote Control. scripts\register_claude_daily.ps1'
