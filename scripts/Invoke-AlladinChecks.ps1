[CmdletBinding()]
param(
    [switch]$Mt5ReadOnly,
    [switch]$BackupOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Environnement absent : creer .venv et installer le projet avec les dependances dev.'
}
$arguments = @((Join-Path $PSScriptRoot 'verify_workstation.py'))
if ($Mt5ReadOnly) { $arguments += '--mt5-readonly' }
if ($BackupOnly) { $arguments += '--backup-only' }
Push-Location $repoRoot
try {
    & $python @arguments
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
