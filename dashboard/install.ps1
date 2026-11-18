# Install for the current Windows user, then start the dashboard on loopback.
$ErrorActionPreference = 'Stop'
$python = (Get-Command python.exe -CommandType Application -TotalCount 1).Source
$node = (Get-Command node.exe -CommandType Application -TotalCount 1).Source
$entry = Join-Path $PSScriptRoot 'server.py'
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
$taskName = 'India Tech Job Dashboard'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.Arguments -notlike ('*' + $entry + '*'))) {
    throw 'A different scheduled task already uses this name.'
}
if ($existing -and $existing.State -eq 'Running') {
    Write-Output 'Dashboard task is already running.'
    return
}
$arguments = '-X utf8 "' + $entry + '" --background --node "' + $node + '"'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $PSScriptRoot
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User $account -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State

