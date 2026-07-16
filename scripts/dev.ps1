# Sanjaya dev helper (Windows PowerShell). Usage: .\scripts\dev.ps1 <command>
#   setup    - create venv and install deps (uv sync)
#   run      - start the collector + tray (foreground)
#   version  - print version
#   initdb   - create/migrate the SQLite database
#   test     - run pytest
#   lint     - byte-compile all modules (cheap smoke check)
param([Parameter(Position = 0)][string]$cmd = "run")

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

switch ($cmd) {
    "setup"   { uv sync }
    "run"     { uv run python -m sanjaya }
    "version" { uv run python -m sanjaya --version }
    "initdb"  { uv run python -m sanjaya --init-db }
    "test"    { uv run pytest }
    "lint"    { uv run python -m compileall sanjaya }
    default   { Write-Host "Unknown command: $cmd" ; exit 1 }
}
