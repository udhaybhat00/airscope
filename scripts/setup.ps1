# airscope setup -- Windows
Write-Host "airscope setup (Windows)" -ForegroundColor Cyan
Write-Host ""

# Check uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  Installing uv..." -ForegroundColor Yellow
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
} else {
    Write-Host "  [ok] uv found" -ForegroundColor Green
}

# Install deps
Write-Host "  Syncing dependencies..."
uv sync --group dev

# Windows note
Write-Host ""
Write-Host "  If your adapter is not detected:" -ForegroundColor Yellow
Write-Host "    1. Download Zadig: https://zadig.akeo.ie/"
Write-Host "    2. Replace driver with WinUSB"
Write-Host "    3. Re-plug adapter"
Write-Host ""

# Run doctor
uv run python -m airscope.doctor

Write-Host ""
Write-Host "Setup complete. Run: uv run airscope" -ForegroundColor Green
