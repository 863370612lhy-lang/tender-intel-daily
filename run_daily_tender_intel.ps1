$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$pythonExe = "C:\Program Files\Python313\python.exe"
$digestScript = Join-Path $scriptDir "daily_tender_digest.py"
$logDir = Join-Path $scriptDir "logs"
$logFile = Join-Path $logDir "last-run.log"
$stdoutFile = Join-Path $logDir "stdout.log"
$stderrFile = Join-Path $logDir "stderr.log"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

if (-not $env:SMTP_USERNAME -or -not $env:SMTP_PASSWORD) {
    throw "SMTP_USERNAME or SMTP_PASSWORD is not configured in the user environment."
}

$env:SEND_EMAIL = "1"
$env:LOOKBACK_DAYS = "7"
$env:SOURCE_PAGE_LIMIT = "3"
$env:MAX_ITEMS = "80"
Remove-Item Env:DEMO_WORKBOOK -ErrorAction SilentlyContinue

Push-Location $projectRoot
try {
    $quotedDigestScript = '"' + $digestScript + '"'
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList @($quotedDigestScript) `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile `
        -Wait `
        -PassThru `
        -NoNewWindow

    @(
        "=== STDOUT ==="
        if (Test-Path $stdoutFile) { Get-Content $stdoutFile }
        ""
        "=== STDERR ==="
        if (Test-Path $stderrFile) { Get-Content $stderrFile }
    ) | Set-Content -Path $logFile -Encoding UTF8

    if ($process.ExitCode -ne 0) {
        throw "daily_tender_digest.py exited with code $($process.ExitCode)"
    }
}
finally {
    Pop-Location
}
