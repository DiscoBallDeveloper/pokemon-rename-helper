Write-Host "Install ADB/platform-tools first if needed:"
Write-Host "  winget install Google.PlatformTools"
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
}

uv venv --python 3.11 .venv
uv pip install -e ".[dev]"

Write-Host ""
Write-Host "Done. Activate with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then check devices:"
Write-Host "  pogo devices"
