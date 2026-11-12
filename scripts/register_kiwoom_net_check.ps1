# Registers Windows task KiwoomNetCheck (2026-11-12) - re-run this file to re-create it.
# Triggers: (1) NetworkProfile/Operational event 10000 "network connected" (2) logon + 1 min (3) weekdays 15:30.
# Same principal style as the other tasks (current user, interactive). Runs on battery too. Overlapping runs are ignored.
$ErrorActionPreference = 'Stop'
$root = 'D:\kiwoom_rest_study\multi_agent_kiwoom'
$query = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[(EventID=10000)]]</Select></Query></QueryList>'

$cls = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$onNet = New-CimInstance -CimClass $cls -ClientOnly
$onNet.Enabled = $true
$onNet.Subscription = $query

$onLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$onLogon.Delay = 'PT1M'
$beforeDecide = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 15:30

$action = New-ScheduledTaskAction -Execute "$root\scripts\kiwoom_net_check.cmd" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName 'KiwoomNetCheck' -Force -Action $action -Settings $settings -Principal $principal `
    -Trigger @($onNet, $onLogon, $beforeDecide) `
    -Description 'Kiwoom connection check on network change / logon / weekdays 15:30 - Telegram alert with public IP if blocked (8050). scripts\kiwoom_net_check.py'
