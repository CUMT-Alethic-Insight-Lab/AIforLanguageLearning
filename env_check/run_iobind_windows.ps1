# Run CosyVoice2 streaming with GPU-only ORT CUDA and IOBinding
param(
  [string]$Langs = "zh,en,ja",
  [switch]$TryTRT = $false,
  [switch]$TrtFp16 = $true,
  [switch]$ForceTorchCPU = $false,
  [int]$TokenHop = 8,
  [int]$FirstHop = -1,
  [int]$FirstChunks = 1,
  [switch]$LoadTrtEstimator = $false,
  [string]$TensorRtHome = "",
  [string]$CudaHome = $env:CUDA_PATH,
  [string]$CondaEnvPath = ""
)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $PSCommandPath
$workspaceRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
if (-not $TensorRtHome) {
  $TensorRtHome = Join-Path $workspaceRoot "TensorRT-10.13.3.9"
}

$env:COSY_TORCH_FORCE_CPU = $(if ($ForceTorchCPU) { "1" } else { "0" })  # Allow enabling CPU-only mode if kernels are incompatible
$env:COSY_GPU_ONLY        = "1"          # Enforce GPU EPs only in ORT
$env:COSY_ORT_TRT         = $(if ($TryTRT) { "1" } else { "0" })
$env:COSY_ORT_NO_TRT      = $(if ($TryTRT) { "0" } else { "1" })
$env:COSY_ORT_TRT_FP16    = $(if ($TryTRT -and $TrtFp16) { "1" } else { "0" })
$env:COSY_ORT_TRT_CACHE   = $(if ($TryTRT) { "1" } else { "0" })
$env:COSY_ORT_TRT_TIMING_CACHE = $(if ($TryTRT) { "1" } else { "0" })
$env:COSY_ORT_CUDA_TF32   = "1"
$env:COSY_ORT_IOBIND      = "1"
$env:COSY_ORT_SPEECH_CPU  = "0"          # Prefer GPU for speech tokenizer
$env:COSY_TOKEN_HOP       = "$TokenHop"
$env:COSY_FIRST_CHUNKS    = "$FirstChunks"
$env:COSY_FIRST_HOP       = $(if ($FirstHop -gt 0) { "$FirstHop" } else { $null })
$env:COSY_CV2_TRT         = $(if ($LoadTrtEstimator) { "1" } else { "0" })
$env:COSY_WARMUP          = "1"
$env:COSY_LANGS           = $Langs

$script = Join-Path $scriptRoot "run_cosyvoice2_stream_multilang.py"

if ($TryTRT) {
  # Prepend TensorRT and CUDA runtime libraries to PATH so ORT TRT EP can find nvinfer*.dll and cudnn
  $candidates = @()
  if ($TensorRtHome) {
    $candidates += @( Join-Path $TensorRtHome "lib"; Join-Path $TensorRtHome "lib\windows-x86_64" )
  }
  if ($CudaHome) {
    $candidates += @( Join-Path $CudaHome "bin"; Join-Path $CudaHome "libnvvp" )
  }
  foreach ($p in $candidates) {
    if (Test-Path $p) { $env:PATH = $p + ";" + $env:PATH }
  }
  # Ensure cache directories exist
  $trtCache = Join-Path $workspaceRoot "tmp\\trt_engine_cache"
  $timingCache = Join-Path $workspaceRoot "tmp\\trt_timing_cache"
  if (-not (Test-Path $trtCache)) { New-Item -ItemType Directory -Path $trtCache | Out-Null }
  if (-not (Test-Path $timingCache)) { New-Item -ItemType Directory -Path $timingCache | Out-Null }
  $env:COSY_ORT_TRT_CACHE_PATH = $trtCache
  $env:COSY_ORT_TRT_TIMING_CACHE_PATH = $timingCache
}

Write-Host "[run_iobind] Starting streaming baseline (TryTRT=$TryTRT, TrtFp16=$TrtFp16, Langs=$Langs)"
$pythonCmd = "python"
if ($CondaEnvPath -and (Test-Path $CondaEnvPath)) {
  $pythonCmd = "conda run -p `"$CondaEnvPath`" python"
}
cmd /c "$pythonCmd `"$script`""
if ($LASTEXITCODE -ne 0) {
  throw "Streaming baseline failed with exit code $LASTEXITCODE"
}
