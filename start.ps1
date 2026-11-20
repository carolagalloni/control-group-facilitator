# Avvio demo (Windows PowerShell): .\start.ps1   (per ricompilare il frontend: .\start.ps1 -Rebuild)
param([switch]$Rebuild, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
if ($Rebuild -or -not (Test-Path frontend\dist)) {
  Push-Location frontend; npm install --no-audit --no-fund; npm run build; Pop-Location
}
Write-Host "Demo su http://localhost:$Port  (LLM atteso su http://localhost:11434/v1 - modificabile in Impostazioni)"
Set-Location backend
& ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
