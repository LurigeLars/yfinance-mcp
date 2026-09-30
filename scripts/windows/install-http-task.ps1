param(
    [string]$TaskName = "YFinanceMcpHttpServer",
    [ValidateRange(1, 65535)]
    [int]$Port = 8772
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvRoot = Join-Path $repoRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$pythonw = Join-Path $venvRoot "Scripts\pythonw.exe"
$launcher = Join-Path $PSScriptRoot "run-http-hidden.py"

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw "uv is required for a locked installation. Install uv and rerun this script."
}

Push-Location $repoRoot
try {
    & $uv.Source sync --locked --python 3.12
    if ($LASTEXITCODE -ne 0) {
        throw "Locked dependency installation failed."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $python)) {
    throw "Locked virtual environment creation failed."
}
$userId = "$env:USERDOMAIN\$env:USERNAME"
$argument = '"{0}" --port {1}' -f $launcher, $Port
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $argument -WorkingDirectory $repoRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

$taskParams = @{
    TaskName = $TaskName
    Action = $action
    Trigger = @($logonTrigger, $watchdogTrigger)
    Principal = $principal
    Settings = $settings
    Description = "Runs the loopback-only yfinance MCP HTTP server without a visible terminal window."
    Force = $true
}
Register-ScheduledTask @taskParams | Out-Null

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    $logPath = Join-Path $env:LOCALAPPDATA "yfinance-mcp\http.log"
    throw "The MCP server did not start on 127.0.0.1:$Port. Check $logPath"
}

Write-Host "Task '$TaskName' is installed."
Write-Host "MCP endpoint: http://127.0.0.1:$Port/mcp"
Write-Host "PID: $($listener.OwningProcess)"
Write-Host "Log: $env:LOCALAPPDATA\yfinance-mcp\http.log"
