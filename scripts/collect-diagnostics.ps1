<#
    Collects every free, read-only diagnostic available on courbet.

    Safety: nothing here writes to the device. adb shell only reads, fastboot
    fetch only downloads, getvar only queries. No flashing, no abl, no EDL.

    Run this twice:
      1) while the phone is in Android  -> collects adb data
      2) while the phone is in fastboot -> collects bootloader vars + crash logs

    Usage:
      powershell -ExecutionPolicy Bypass -File .\scripts\collect-diagnostics.ps1 -Mode adb
      powershell -ExecutionPolicy Bypass -File .\scripts\collect-diagnostics.ps1 -Mode fastboot
#>

[CmdletBinding()]
param(
    [ValidateSet('adb', 'fastboot', 'all')]
    [string]$Mode = 'all'
)

$ErrorActionPreference = 'Continue'
$pt = "$env:USERPROFILE\Downloads\platform-tools"
$adb = Join-Path $pt 'adb.exe'
$fastboot = Join-Path $pt 'fastboot.exe'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$out = Join-Path $root 'work\diagnostics'

New-Item -ItemType Directory -Force -Path $out | Out-Null

function Save([string]$name, [string]$text) {
    $p = Join-Path $out $name
    [System.IO.File]::WriteAllText($p, $text)
    $len = (Get-Item $p).Length
    Write-Host ("  saved {0,-28} {1,9:N0} bytes" -f $name, $len)
}

function Try-Adb([string]$label, [string[]]$argv) {
    $r = (& $adb @argv 2>&1 | Out-String)
    Write-Host ("  {0,-28} {1}" -f $label, $(if ($r.Length -gt 60) { $r.Substring(0, 60).Trim() + '...' } else { $r.Trim() }))
    return $r
}

Write-Host "`n=== phase: adb (phone in Android) ===" -ForegroundColor Cyan
if ($Mode -in @('adb', 'all')) {
    $dev = (& $adb devices 2>&1 | Out-String).Trim()
    Write-Host "  devices: $dev"

    if ($dev -notmatch '\tdevice$') {
        Write-Host "  [!] no authorised device - connect the phone, enable USB debugging," -ForegroundColor Yellow
        Write-Host "      accept the prompt, then run again" -ForegroundColor Yellow
    } else {
        # The cmdline the bootloader actually passed: this is the real contract
        # between bootloader and payload, and the empty cmdline in our image is
        # the most obvious difference from a working boot.
        Save 'adb-cmdline.txt'         (Try-Adb '/proc/cmdline'        @('shell','cat','/proc/cmdline'))
        Save 'adb-device-tree.txt'     ((Try-Adb 'dt: model'   @('shell','cat','/proc/device-tree/model')) + "`n" +
                                        (Try-Adb 'dt: compatible' @('shell','cat','/proc/device-tree/compatible')))
        Save 'adb-getprop.txt'         (Try-Adb 'getprop'              @('shell','getprop'))
        Save 'adb-partitions.txt'      ((Try-Adb '/proc/partitions'   @('shell','cat','/proc/partitions')) + "`n" +
                                        (Try-Adb 'by-name' @('shell','ls','-l','/dev/block/by-name/')))
        # dmesg is the highest value item: it records how the bootloader handed
        # over to Android, which is exactly the contract we are guessing at.
        Save 'adb-dmesg.txt'           (Try-Adb 'dmesg'                @('shell','dmesg'))
        Save 'adb-cmdline-and-boot.txt' ((Try-Adb 'ro.boot.*'  @('shell','getprop')) )
    }
}

Write-Host "`n=== phase: fastboot (phone in fastboot) ===" -ForegroundColor Cyan
if ($Mode -in @('fastboot', 'all')) {
    $dev = (& $fastboot devices 2>&1 | Out-String).Trim()
    Write-Host "  devices: $dev"

    if ($dev -notmatch 'fastboot') {
        Write-Host "  [!] phone is not in fastboot - boot with Vol Down + Power," -ForegroundColor Yellow
        Write-Host "      connect the cable, then run again" -ForegroundColor Yellow
    } else {
        Save 'fastboot-getvar-all.txt' ((& $fastboot getvar all 2>&1 | Out-String))

        # Crash breadcrumbs. These are read-only downloads. Qualcomm records
        # why an early boot stage failed in oops / logdump / core_nhlos, which
        # is exactly the evidence a black screen cannot give us.
        foreach ($part in @('oops', 'logdump', 'core_nhlos')) {
            Write-Host "  fetching $part ..."
            $r = (& $fastboot fetch $part (Join-Path $out "fb-$part.img") 2>&1 | Out-String)
            $p = Join-Path $out "fb-$part.img"
            if (Test-Path $p) {
                Write-Host ("    saved fb-{0}.img  {1:N0} bytes" -f $part, (Get-Item $p).Length)
            } else {
                Write-Host ("    no $part : " + $r.Trim()) -ForegroundColor DarkYellow
            }
        }
    }
}

Write-Host "`n=== done ===" -ForegroundColor Cyan
Get-ChildItem $out | Select-Object Name, Length | Format-Table -AutoSize
Write-Host "folder: $out" -ForegroundColor Green
