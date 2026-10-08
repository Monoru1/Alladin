# ALLADIN acceptance: read-only diagnostics and software validation.
# No order_send, no EXECUTE, no mutation of broker positions.
param([string]$RunId = "SYSTEM-TEST-002", [int]$Port = 8001)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (!(Test-Path $py)) { throw "Python venv missing: $py" }
$failed = $false
function Check([string]$name, [scriptblock]$action) {
  Write-Host "\n=== $name ===" -ForegroundColor Cyan
  try { & $action; if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }; Write-Host "PASS $name" -ForegroundColor Green }
  catch { Write-Warning "$name FAILED: $_"; $script:failed = $true }
}
Check "Ruff" { & $py -m ruff check src/alladin tests }
Check "Mypy" { & $py -m mypy src/alladin }
Check "Pytest full" { & $py -m pytest -o addopts='' -q }
Check "Challenge and MT5 read-only status" { & $py -m alladin challenge status --run $RunId }
Write-Host "\n=== Cockpit API (read only) ===" -ForegroundColor Cyan
$base = "http://127.0.0.1:$Port"
try {
  $rid = [uri]::EscapeDataString($RunId)
  $overview = Invoke-RestMethod "$base/api/overview?run_id=$rid" -TimeoutSec 12
  $positions = @(Invoke-RestMethod "$base/api/positions?run_id=$rid" -TimeoutSec 12)
  $trades = Invoke-RestMethod "$base/api/history?run_id=$rid" -TimeoutSec 12
  $events = @(Invoke-RestMethod "$base/api/journal?run_id=$rid&limit=100" -TimeoutSec 12)
  if ($overview.run.run_id -ne $RunId -or $trades.run_id -ne $RunId) { throw "Run mismatch" }
  Write-Host "Run: $RunId | Broker positions: $($positions.Count) | Journal trades: $(@($trades.trades).Count) | Events: $($events.Count)"
  foreach ($t in $trades.trades) {
    Write-Host "Ticket $($t.ticket) | $($t.symbol) | journal=$($t.status) | net_pnl=$($t.net_pnl)"
    if ($t.status -eq "OPEN" -and $t.ticket -notin @($positions | ForEach-Object { $_.ticket })) {
      Write-Warning "UNRECONCILED: trade OPEN in journal but absent from MT5 positions; inspect MT5 history. No automatic closure inferred."
    }
  }
  Write-Host "Cockpit: $base/?run_id=$rid"
} catch { Write-Warning "Cockpit API unavailable or inconsistent: $_"; $failed = $true }
if ($failed) { Write-Host "\nACCEPTANCE: FAIL / review warnings" -ForegroundColor Red; exit 1 }
Write-Host "\nACCEPTANCE: PASS (software/read-only checks only; not FTMO certification)" -ForegroundColor Green
