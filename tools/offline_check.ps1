# Offline check: proves Chaukas works with ALL outbound network access blocked.
#
# Run once, from an Administrator PowerShell in the Chaukas folder, after `run.bat setup`:
#     powershell -ExecutionPolicy Bypass -File tools\offline_check.ps1
#
# 1. Adds Windows Firewall rules that block every outbound connection from Chaukas's Python
#    (the virtual environment's launcher and the interpreter it starts).
# 2. Proves the block works: a request to example.com must FAIL, or the test is invalid.
# 3. Runs the live path end to end (tools/offline_selfcheck.py: models from disk, a
#    synthetic call through voice detection and Whisper, the risk engine, loopback capture)
#    and the held-out evaluation.
# 4. Always removes the rules, even if something fails.
# Nothing is played aloud. The rules only affect Chaukas's Python, not the rest of the PC.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Please run this from an Administrator PowerShell (firewall rules need it)." -ForegroundColor Red
    exit 1
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No virtual environment found. Run 'run.bat setup' first." -ForegroundColor Red
    exit 1
}
$basePython = (& $venvPython -c "import sys; print(sys._base_executable)").Trim()
$programs = @($venvPython, $basePython) | Select-Object -Unique
$ruleName = "Chaukas offline check (temporary)"

function Remove-Rules {
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}

$failed = $false
try {
    Remove-Rules  # a leftover from an interrupted run
    foreach ($program in $programs) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Outbound -Action Block `
            -Program $program -Profile Any | Out-Null
        Write-Host "Blocked outbound network for $program"
    }

    Write-Host "`n== Proving the block works (this request must fail) =="
    & $venvPython -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=10)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "The request succeeded, so the firewall rule is not effective. Test invalid." -ForegroundColor Red
        $failed = $true
        return
    }
    Write-Host "Blocked, as expected." -ForegroundColor Green

    Write-Host "`n== Live path, end to end, offline =="
    & $venvPython tools\offline_selfcheck.py
    if ($LASTEXITCODE -ne 0) { $failed = $true }

    Write-Host "`n== Held-out evaluation, offline =="
    & $venvPython -m chaukas eval eval\cases --split test
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}
finally {
    Remove-Rules
    Write-Host "`nFirewall rules removed."
}

if ($failed) {
    Write-Host "`nOFFLINE CHECK FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "`nOFFLINE CHECK PASSED: Chaukas ran with all outbound network access blocked." -ForegroundColor Green
