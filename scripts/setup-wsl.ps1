<#
    Prepares this Windows host for building EDK2 AArch64 firmware.

    Two things are required and neither can be done from inside Windows:
      1. Hardware virtualization (VT-x / AMD-V) MUST be enabled in the BIOS.
      2. The "Virtual Machine Platform" Windows optional feature.

    This script does what it can from PowerShell and tells you exactly what
    still needs manual work. Run it from an elevated PowerShell.

    Check 0 = nothing to do, 1 = manual action required, 2 = done.
#>

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-HypervisorPresent {
    try {
        $cs = Get-CimInstance Win32_ComputerSystem
        return [bool]$cs.HypervisorPresent
    } catch { return $false }
}

Write-Host "=== EDK2 build host preparation ===" -ForegroundColor Cyan

if (-not (Test-Admin)) {
    Write-Host "[!] Not running as Administrator. Re-run from an elevated shell." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- hypervisor
if (Get-HypervisorPresent) {
    Write-Host "[ok] Hypervisor present (virtualization is active)" -ForegroundColor Green
} else {
    Write-Host "[!!] Hyper-V hypervisor is NOT present." -ForegroundColor Red
    Write-Host "     -> Enter BIOS/UEFI setup and enable:" -ForegroundColor Yellow
    Write-Host "        Intel: Intel Virtualization Technology / VT-x" -ForegroundColor Yellow
    Write-Host "        AMD:   SVM Mode / AMD-V" -ForegroundColor Yellow
    Write-Host "     -> Also disable 'Secure Boot' if the board locks it down." -ForegroundColor Yellow
    Write-Host "     -> Then reboot and re-run this script." -ForegroundColor Yellow
}

# ------------------------------------------------------------ optional feature
$vmplat = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction SilentlyContinue
$wslopt = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction SilentlyContinue

if ($vmplat.State -ne 'Enabled') {
    Write-Host "[..] Enabling VirtualMachinePlatform"
    Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart | Out-Null
    $needsRestart = $true
} else {
    Write-Host "[ok] VirtualMachinePlatform enabled"
}

if ($wslopt.State -ne 'Enabled') {
    Write-Host "[..] Enabling Microsoft-Windows-Subsystem-Linux"
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart | Out-Null
    $needsRestart = $true
} else {
    Write-Host "[ok] WSL feature enabled"
}

if ($needsRestart) {
    Write-Host "`n[!] A reboot is required before WSL2 can run." -ForegroundColor Yellow
    Write-Host "    Reboot, then run:  wsl --install -d Ubuntu-22.04" -ForegroundColor Yellow
    exit 1
}

# ----------------------------------------------------------------- wsl itself
$distros = (wsl -l -q 2>$null) -replace "`0", '' | Where-Object { $_ -ne '' }
if ($distros.Count -eq 0) {
    Write-Host "[..] No WSL distro installed. Installing Ubuntu-22.04"
    wsl --install -d Ubuntu-22.04
    Write-Host "     Finish the Ubuntu setup (create user + password), then re-run." -ForegroundColor Yellow
} else {
    Write-Host "[ok] WSL distros: $($distros -join ', ')"
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if (-not (Get-HypervisorPresent)) {
    Write-Host "BLOCKED: enable virtualization in BIOS first." -ForegroundColor Red
    exit 1
}
Write-Host "Next step: install the cross toolchain inside WSL" -ForegroundColor Green
Write-Host "  wsl -d Ubuntu-22.04 -- sudo apt-get update"
Write-Host "  wsl -d Ubuntu-22.04 -- sudo apt-get install -y build-essential git python3 ninja-build uuid-dev gcc-aarch64-linux-gnu"
exit 0
