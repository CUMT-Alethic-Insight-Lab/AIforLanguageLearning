param(
  [string]$ServerExe = "..\\tools\\whisper.cpp\\server.exe",  # whisper.cpp server binary path (relative to env_check)
  [string]$ModelPath = "..\\models\\whisper.cpp\\ggml-base.bin", # GGML/GGUF model path (relative to env_check)
  [int]$Port = 8080,
  [int]$Threads = 8,
  [switch]$GPU = $false
)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $PSCommandPath
if (-not [System.IO.Path]::IsPathRooted($ServerExe)) {
  $ServerExe = Join-Path $scriptRoot $ServerExe
}
if (-not [System.IO.Path]::IsPathRooted($ModelPath)) {
  $ModelPath = Join-Path $scriptRoot $ModelPath
}
$ServerExe = [System.IO.Path]::GetFullPath($ServerExe)
$ModelPath = [System.IO.Path]::GetFullPath($ModelPath)

if (-not (Test-Path $ServerExe)) {
  Write-Host "[whispercpp] server.exe not found: $ServerExe" -ForegroundColor Yellow
  Write-Host "Please build whisper.cpp or download a release, then update -ServerExe."
  exit 2
}
if (-not (Test-Path $ModelPath)) {
  Write-Host "[whispercpp] model not found: $ModelPath" -ForegroundColor Yellow
  Write-Host "Place a GGML/GGUF model (e.g., ggml-base.bin / ggml-base-q5_1.gguf) and update -ModelPath."
  exit 3
}

$gpuFlag = if ($GPU) { "-ng 1" } else { "" }
# Common stable flags: auto language, use VAD, split on word timestamps, JSON output
$flags = @(
  "-m `"$ModelPath`"",
  "-t $Threads",
  "-l auto",
  "-su",            # split on word? (server supports internal segmentation)
  "-v",             # verbose logs
  $gpuFlag,
  "-p $Port"
) | Where-Object { $_ -ne "" }

Write-Host "[whispercpp] starting server on http://127.0.0.1:$Port" -ForegroundColor Green
& $ServerExe @flags
if ($LASTEXITCODE -ne 0) { throw "whisper.cpp server exited with code $LASTEXITCODE" }
