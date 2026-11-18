$ErrorActionPreference = 'Stop'
$python = (Get-Command python.exe -CommandType Application -TotalCount 1).Source
$logDirectory = Join-Path $PSScriptRoot 'logs'
$null = New-Item -ItemType Directory -Path $logDirectory -Force
$timestamp = [DateTime]::UtcNow.ToString('yyyy-MM-dd_HHmmss_fff')
$log = Join-Path $logDirectory "run_$timestamp.log"

$originalEncoding = [Console]::OutputEncoding
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    # Windows PowerShell can surface redirected native stderr as nonterminating errors.
    $ErrorActionPreference = 'Continue'
    & $python -I -X utf8 (Join-Path $PSScriptRoot 'notify.py') 2>&1 |
        Out-File -LiteralPath $log -Encoding utf8 -ErrorAction Stop
    $exitCode = $LASTEXITCODE
} finally {
    [Console]::OutputEncoding = $originalEncoding
    $ErrorActionPreference = 'Stop'
}

Add-Content -LiteralPath $log -Value "exit code: $exitCode" -Encoding utf8
$cutoff = [DateTime]::UtcNow.AddDays(-60)
Get-ChildItem -LiteralPath $logDirectory -Filter 'run_*.log' -File |
    Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
    Remove-Item
exit $exitCode
