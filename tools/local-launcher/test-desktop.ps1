$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$testRoot = Join-Path $projectRoot ('tmp/desktop-acceptance-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
foreach ($phase in @('create', 'reopen', 'delete', 'empty')) {
    $report = Join-Path $testRoot "$phase.json"
    $arguments = @('--desktop-smoke-report', ('"' + $report + '"'),
        ('"' + (Join-Path $testRoot 'data') + '"'), ('"' + (Join-Path $testRoot 'profile') + '"'), $phase)
    $process = Start-Process -FilePath (Join-Path $projectRoot 'PDF资料库.exe') -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddMinutes(5)
    while (-not $process.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -gt $deadline) {
            $process.CloseMainWindow() | Out-Null
            throw "Desktop acceptance timed out in $phase. Test process was asked to close normally."
        }
    }
    if (-not (Test-Path -LiteralPath $report)) { throw "No desktop report for $phase (exit $($process.ExitCode))." }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($process.ExitCode -ne 0 -or $result.status -ne 'passed' -or -not $result.graceful_stop) {
        throw "Desktop acceptance failed: $(Get-Content -LiteralPath $report -Raw)"
    }
    Write-Output "PASS: $phase"
}
Write-Output "Desktop reports and screenshots: $testRoot"
