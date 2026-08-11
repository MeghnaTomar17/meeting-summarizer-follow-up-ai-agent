# MannerAI — run a backend service locally in venv
# Usage: .\scripts\run-service.ps1 gateway|meeting|ai|search|worker

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("gateway", "meeting", "ai", "search", "worker")]
    [string]$Service
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual env not found. Run .\scripts\setup.ps1 first."
}

$env:PYTHONPATH = Join-Path $Root "backend"

$services = @{
    gateway = @{ Dir = "backend\gateway-service"; Module = "app.main:app"; Port = 8000 }
    meeting = @{ Dir = "backend\meeting-service"; Module = "app.main:app"; Port = 8001 }
    ai      = @{ Dir = "backend\ai-service";      Module = "app.main:app"; Port = 8002 }
    search  = @{ Dir = "backend\search-service";  Module = "app.main:app"; Port = 8003 }
    worker  = @{ Dir = "backend\worker-service";  Module = "app.main:app"; Port = 8004 }
}

$config = $services[$Service]
Set-Location (Join-Path $Root $config.Dir)

Write-Host "Starting $Service-service on port $($config.Port)..." -ForegroundColor Cyan
& $venvPython -m uvicorn $config.Module --host 0.0.0.0 --port $config.Port --reload
