# Local Windows acceptance preflight; deliberately does not start MT5 or place orders.
# Run after reviewing local changes and synchronizing main.
$ErrorActionPreference = 'Stop'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dir = Join-Path 'acceptance_reports' ('offline-' + $stamp)
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$summary = @()
$commands = @(
    @{Name='git-status'; Executable='git'; Arguments=@('status','-sb')},
    @{Name='git-head'; Executable='git'; Arguments=@('rev-parse','HEAD')},
    @{Name='targeted-pytest'; Executable='python'; Arguments=@('-m','pytest','-o','addopts=','-q','tests/test_paper_risk_reservations.py','tests/test_paper_reconciliation.py','tests/test_economic_intelligence.py','tests/test_official_signals.py','tests/test_market_observatory.py','tests/test_offline_diagnostics.py','tests/test_performance_research.py','tests/test_offline_adversarial.py')},
    @{Name='full-pytest'; Executable='python'; Arguments=@('-m','pytest','-o','addopts=','-q','-m','not mt5_integration')},
    @{Name='ruff'; Executable='python'; Arguments=@('-m','ruff','check','src/alladin','tests')},
    @{Name='mypy'; Executable='python'; Arguments=@('-m','mypy','src/alladin')}
)
foreach ($task in $commands) {
    $log = Join-Path $dir ($task.Name + '.log')
    $started = (Get-Date).ToUniversalTime().ToString('o')
    # Native stderr warnings (e.g. Git permission-denied temp dirs) must not
    # become terminating PowerShell errors before pytest has a chance to run.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $task.Executable @($task.Arguments) 2>&1 | Out-File -FilePath $log -Encoding utf8
        $exit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $summary += [pscustomobject]@{name=$task.Name; exit_code=$exit; started_utc=$started; log=$log}
    if ($exit -ne 0) { break }
}
$summary | ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $dir 'summary.json') -Encoding utf8
$summary | Format-Table -AutoSize
if ($summary[-1].exit_code -ne 0) { throw "Offline acceptance FAILED. Review $dir" }
Write-Host "Offline acceptance PASSED; MT5 remains unvalidated. Evidence: $dir"
