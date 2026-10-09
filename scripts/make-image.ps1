<#
    Builds a flashable boot.img from the UEFI payload produced by CI.

    Takes the artifact downloaded from the GitHub Actions run and injects it
    into a stock boot.img in place of the kernel.

    Example:
      .\scripts\make-image.ps1 -Payload .\out\UefiPayloadPkg.efi
#>

[CmdletBinding()]
param(
    [string]$Payload,
    [string]$StockBoot,
    [string]$Output,
    [switch]$NoFlash
)

# $PSScriptRoot is not yet available while param() defaults are evaluated.
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
if (-not $Payload)   { $Payload   = Join-Path $root 'out\UefiPayloadPkg.efi' }
if (-not $StockBoot) { $StockBoot = Join-Path $env:USERPROFILE 'Desktop\boot\boot.img' }
if (-not $Output)    { $Output    = Join-Path $root 'work\boot-uefi.img' }

$repack = Join-Path $root 'tools\repack.py'

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

Write-Host "=== build flashable image ===" -ForegroundColor Cyan

foreach ($p in @($Payload, $StockBoot, $repack)) {
    if (-not (Test-Path $p)) { Fail "not found: $p" }
}

$outDir = Split-Path $Output -Parent
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

Write-Host "payload : $Payload"
Write-Host "stock   : $StockBoot"
Write-Host "output  : $Output"
Write-Host ""

# Keep a pristine copy of the stock kernel once, for the rollback path.
$origKernel = Join-Path $outDir 'kernel.orig.bin'
if (-not (Test-Path $origKernel)) {
    Write-Host "[1/3] saving stock kernel for rollback"
    python $repack extract $StockBoot kernel $origKernel
    if ($LASTEXITCODE -ne 0) { Fail "could not extract stock kernel" }
} else {
    Write-Host "[1/3] stock kernel already saved: $origKernel"
}

Write-Host "[2/3] injecting payload"
python $repack inject $StockBoot $Payload $Output
if ($LASTEXITCODE -ne 0) { Fail "injection failed - payload rejected as non-EFI, see messages above" }

Write-Host "[3/3] verifying"
python $repack verify $Output $Payload
if ($LASTEXITCODE -ne 0) { Fail "verification failed" }

$size = (Get-Item $Output).Length
Write-Host ""
Write-Host "OK: $Output ($([math]::Round($size/1MB,2)) MiB)" -ForegroundColor Green

if (-not $NoFlash) {
    Write-Host ""
    Write-Host "Flash it with:" -ForegroundColor Yellow
    Write-Host "  fastboot devices"
    Write-Host "  fastboot flash boot `"$Output`""
    Write-Host ""
    Write-Host "Roll back with:" -ForegroundColor Yellow
    Write-Host "  fastboot flash boot `"$StockBoot`""
    Write-Host ""
    Write-Host "Keep $StockBoot - it is the way back to a working phone." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Flash with:  fastboot flash boot `"$Output`""
    Write-Host "Roll back :  fastboot flash boot `"$StockBoot`""
}
