Write-Host "Install ADB/platform-tools first if needed:"
Write-Host "  winget install Google.PlatformTools"
Write-Host ""

conda env create -f environment.yml
if ($LASTEXITCODE -ne 0) {
  conda env update -f environment.yml --prune
}

Write-Host ""
Write-Host "Done. Activate with:"
Write-Host "  conda activate pogo-automation"
Write-Host ""
Write-Host "Then check devices:"
Write-Host "  pogo devices"
