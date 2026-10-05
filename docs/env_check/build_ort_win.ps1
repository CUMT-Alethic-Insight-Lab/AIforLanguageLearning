param(
  [string]$Config = "Release",
  [string]$CudaHome = $env:CUDA_PATH,
  [string]$CudaVersion = "13.0",
  [string]$TensorRtHome = "",
  [string]$CudaArch = "120",
  [switch]$BuildWheel = $true
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSCommandPath
$ws = (Resolve-Path (Join-Path $root "..")).Path
if (-not $TensorRtHome) {
  $TensorRtHome = Join-Path $ws "TensorRT-10.13.3.9"
}

# Resolve CUDA home if not set
if (-not $CudaHome -or -not (Test-Path $CudaHome)) {
  $defaultCuda = "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v$CudaVersion"
  if (Test-Path $defaultCuda) {
    $CudaHome = $defaultCuda
  } else {
    Write-Error "CUDA home not found. Set -CudaHome or ensure CUDA $CudaVersion installed."
  }
}

# cuDNN typically ships with Toolkit on recent versions; reuse CudaHome
$CudnnHome = $CudaHome

# Validate TensorRT SDK
if (-not (Test-Path $TensorRtHome)) {
  Write-Error "TensorRT SDK not found at $TensorRtHome. Set -TensorRtHome to your TRT SDK root."
}

# Print summary
Write-Host "[build_ort_win] Config=$Config"
Write-Host "[build_ort_win] CUDA_HOME=$CudaHome (version $CudaVersion)"
Write-Host "[build_ort_win] cuDNN_HOME=$CudnnHome"
Write-Host "[build_ort_win] TENSORRT_HOME=$TensorRtHome"
Write-Host "[build_ort_win] CUDA_ARCH=$CudaArch"

$ortSrc = Join-Path $ws "onnxruntime-main"

if (-not (Test-Path (Join-Path $ortSrc "build.bat"))) {
  Write-Error "onnxruntime-main/build.bat not found. Ensure sources are present."
}

Push-Location $ortSrc

# Build arguments
$buildArgs = @(
  "--config", $Config,
  "--parallel",
  "--build_shared_lib",
  "--use_cuda",
  "--cuda_home", $CudaHome,
  "--cudnn_home", $CudnnHome,
  "--cuda_version", $CudaVersion,
  "--use_tensorrt",
  "--tensorrt_home", $TensorRtHome,
  "--skip_tests"
)

# Ensure CMake uses specified arch (newer toolchains prefer CMAKE_CUDA_ARCHITECTURES)
$buildArgs += @("--cmake_extra_defines", "CMAKE_CUDA_ARCHITECTURES=$CudaArch")

if ($BuildWheel) {
  $buildArgs += "--build_wheel"
}

Write-Host "[build_ort_win] Preparing MSVC environment and invoking build.bat $($buildArgs -join ' ')"

# Ensure VC environment (VS 2022) is loaded in the same cmd session
$vcvars=""
try {
  $pf86 = ${env:ProgramFiles(x86)}
} catch { $pf86 = $null }
if ($pf86) {
  $vswhere = Join-Path $pf86 "Microsoft Visual Studio\Installer\vswhere.exe"
  if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
    if ($LASTEXITCODE -eq 0 -and $vsPath) {
      $cand = @(
        (Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"),
        (Join-Path $vsPath "VC\Auxiliary\Build\vcvarsamd64_x86.bat")
      )
      foreach ($c in $cand) { if (Test-Path $c) { $vcvars = $c; break } }
    }
  }
}
if (-not $vcvars) {
  $fallbacks = @(
    'C:\\Program Files\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat',
    'C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat',
    'C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat'
  )
  foreach ($c in $fallbacks) { if (Test-Path $c) { $vcvars = $c; break } }
}
if ($vcvars) { Write-Host "[build_ort_win] Using VC vars: $vcvars" }

<#
Compose a temporary .cmd to reliably handle quoting and ensure vcvars + build run in same cmd session.
#>
$quotedArgs = $buildArgs | ForEach-Object { if ($_ -match '\\s') { '"' + $_ + '"' } else { $_ } }
$argsLine = ($quotedArgs -join ' ')
$tmpCmd = Join-Path $env:TEMP ("ort_build_" + [System.IO.Path]::GetRandomFileName() + ".cmd")
if ($vcvars) {
  $cmdContent = @"
@echo off
call "$vcvars"
call build.bat $argsLine
"@
} else {
  Write-Warning "[build_ort_win] VS vcvars not found; attempting build without explicit vcvars (may fail)."
  $cmdContent = @"
@echo off
call build.bat $argsLine
"@
}
Set-Content -Path $tmpCmd -Value $cmdContent -Encoding ASCII
Write-Host "[build_ort_win] Running $tmpCmd"
cmd /c "\"$tmpCmd\""
if ($LASTEXITCODE -ne 0) {
  Pop-Location
  throw "ONNX Runtime build failed with exit code $LASTEXITCODE"
}

# Locate wheel (if built) and print path
$wheel = Get-ChildItem -Recurse -Filter "onnxruntime_gpu-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($wheel) {
  Write-Host "[build_ort_win] Built wheel: $($wheel.FullName)"
}

Pop-Location
