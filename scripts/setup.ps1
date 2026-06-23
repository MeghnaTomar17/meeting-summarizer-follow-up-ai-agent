# MannerAI — first-time setup on Windows (venv + dependencies)
# Usage: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "MannerAI Meetings Platform — setup" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Install Python 3.12+ and add it to PATH."
}

$pythonVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Using Python $pythonVersion"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

Write-Host "Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example — review before running services."
} else {
    Write-Host ".env already exists — skipped."
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  Activate:  .\.venv\Scripts\Activate.ps1"
Write-Host "  Gateway:   .\scripts\run-service.ps1 gateway"
Write-Host "  Health:    curl http://localhost:8000/health"
