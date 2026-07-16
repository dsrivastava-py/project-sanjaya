# Install Sanjaya as a desktop "app": create Desktop + Start Menu shortcuts that
# launch it windowless (pythonw -m sanjaya) with the eye icon. Double-clicking
# the icon starts the collector + tray + local server, then the tray's "Open
# Dashboard" shows the UI in a chromeless app window.
#
# Usage (from the repo root):   powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
# Remove them again:            powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1 -Uninstall
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot           # repo root (this script lives in scripts\)
$name = "Sanjaya.lnk"
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Sanjaya"
$targets = @((Join-Path $desktop $name), (Join-Path $startMenu $name))

if ($Uninstall) {
  foreach ($t in $targets) { if (Test-Path $t) { Remove-Item $t -Force } }
  if ((Test-Path $startMenu) -and -not (Get-ChildItem $startMenu -Force)) { Remove-Item $startMenu -Force }
  Write-Host "Removed Sanjaya shortcuts." -ForegroundColor Yellow
  return
}

# Prefer the project's own virtualenv so the shortcut has all dependencies.
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
  $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
  if ($cmd) { $pythonw = $cmd.Source } else {
    Write-Host "No .venv found and pythonw.exe not on PATH. Run 'uv sync' first." -ForegroundColor Red
    exit 1
  }
}

$icon = Join-Path $root "sanjaya\assets\sanjaya.ico"
if (-not (Test-Path $startMenu)) { New-Item -ItemType Directory -Path $startMenu -Force | Out-Null }

$shell = New-Object -ComObject WScript.Shell
foreach ($t in $targets) {
  $sc = $shell.CreateShortcut($t)
  $sc.TargetPath = $pythonw
  $sc.Arguments = "-m sanjaya"
  $sc.WorkingDirectory = $root
  $sc.Description = "Sanjaya - your day, witnessed."
  if (Test-Path $icon) { $sc.IconLocation = $icon }
  $sc.Save()
  Write-Host "Created: $t" -ForegroundColor Green
}
Write-Host "`nDouble-click the Sanjaya icon to start. Use the tray eye -> Open Dashboard." -ForegroundColor Cyan
