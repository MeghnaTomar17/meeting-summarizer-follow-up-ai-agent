# Start PostgreSQL, Redis, and Qdrant only (for local venv development)
# Usage: .\scripts\start-infra.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Install Docker Desktop or start data stores manually."
}

Write-Host "Starting postgres, redis, qdrant..." -ForegroundColor Cyan
docker compose up -d postgres redis qdrant

Write-Host ""
Write-Host "Infrastructure ready on localhost:" -ForegroundColor Green
Write-Host "  PostgreSQL  localhost:5432"
Write-Host "  Redis       localhost:6379"
Write-Host "  Qdrant      localhost:6333"
