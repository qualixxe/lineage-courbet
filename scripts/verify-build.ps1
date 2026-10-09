<#
    Thin wrapper around tools/verify_image.py.

    Validates the CI-produced boot image before it goes near the phone, and
    confirms the stock image on disk is still a usable rollback.

    Usage:
      powershell -ExecutionPolicy Bypass -File .\scripts\verify-build.ps1
#>

[CmdletBinding()]
param(
    [string]$Built,
    [string]$RawFd,
    [string]$StockBoot
)

# $PSScriptRoot is not yet available while param() defaults are evaluated.
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
if (-not $Built)     { $Built     = Join-Path $root 'work\boot-courbet.img' }
if (-not $RawFd)     { $RawFd     = Join-Path $root 'work\SM7150_UEFI.fd' }
if (-not $StockBoot) { $StockBoot = Join-Path $env:USERPROFILE 'Desktop\boot\boot.img' }

$verify = Join-Path $root 'tools\verify_image.py'

Write-Host "=== files ===" -ForegroundColor Cyan
$missing = $false
foreach ($p in @($Built, $RawFd, $StockBoot)) {
    if (Test-Path $p) {
        Write-Host ("  [ok]   {0}  ({1} MiB)" -f $p, [math]::Round((Get-Item $p).Length/1MB, 2)) -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] missing: $p" -ForegroundColor Red
        $missing = $true
    }
}
if ($missing) { exit 1 }

Write-Host "`n=== rollback image ===" -ForegroundColor Cyan
$hdr = [System.IO.File]::ReadAllBytes($StockBoot)[0..7]
if (($hdr -join ',') -eq '65,78,68,82,79,73,68,33') {
    Write-Host "  [ok]   stock boot.img is a valid boot image - keep it, it is the way back" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] stock boot.img is damaged - do not flash anything" -ForegroundColor Red
    exit 1
}

python $verify $Built --fd $RawFd
exit $LASTEXITCODE
