param(
  [string]$PyTorchSrc = "",
  [string]$CudaHome = $env:CUDA_PATH,
  [string]$CudaVersion = "13.0",
  [string]$ArchList = "12.0",
  [int]$MaxJobs = 1,
  [string]$VcvarsPath = ""
)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $PSCommandPath
$workspaceRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
if (-not $PyTorchSrc) {
  $PyTorchSrc = Join-Path $workspaceRoot "pytorch-main"
}

# Locate VS vcvars
$vcvars = ""
if ($VcvarsPath -and (Test-Path $VcvarsPath)) { $vcvars = $VcvarsPath }
try { $pf86 = ${env:ProgramFiles(x86)} } catch { $pf86 = $null }
if (-not $vcvars -and $pf86) {
  $vswhere = Join-Path $pf86 "Microsoft Visual Studio\Installer\vswhere.exe"
  if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
    if ($LASTEXITCODE -eq 0 -and $vsPath) {
      $cand = @(
        (Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat")
      )
      foreach ($c in $cand) { if (Test-Path $c) { $vcvars = $c; break } }
    }
  }
}
if (-not $vcvars) {
  $fallbacks = @(
    'C:\\Program Files\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat',
    'C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat'
  )
  foreach ($c in $fallbacks) { if (Test-Path $c) { $vcvars = $c; break } }
}
if (-not $vcvars) { throw "VC environment (vcvars64.bat) not found. Provide -VcvarsPath if installed in a custom location." }

# Resolve CUDA home
if (-not $CudaHome -or -not (Test-Path $CudaHome)) {
  $def = "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v$CudaVersion"
  if (Test-Path $def) { $CudaHome = $def } else { throw "CUDA $CudaVersion not found. Set -CudaHome." }
}

# Prepare environment
$env:CUDA_PATH = $CudaHome
$env:PATH = (Join-Path $CudaHome 'bin') + ';' + (Join-Path $CudaHome 'libnvvp') + ';' + $env:PATH
$env:TORCH_CUDA_ARCH_LIST = $ArchList
$env:MAX_JOBS = "$MaxJobs"
$env:USE_CUDA = "1"
$env:USE_CUDNN = "1"
$env:USE_NINJA = "1"

# Ensure Python build deps
$deps = @(
  'cmake>=3.26', 'ninja', 'setuptools', 'wheel', 'packaging', 'typing_extensions',
  'numpy', 'pyyaml', 'jinja2', 'sympy', 'filelock', 'networkx'
)
python -m pip install --upgrade @deps
if ($LASTEXITCODE -ne 0) { throw "Failed to install python deps" }

# Create temp build dir to avoid long TMP paths issues
$localTmp = Join-Path $PyTorchSrc 'build_tmp'
if (-not (Test-Path $localTmp)) { New-Item -ItemType Directory -Path $localTmp | Out-Null }
$env:TMP = $localTmp
$env:TEMP = $localTmp

# Generate a .cmd to load vcvars then pip install -e .
if (-not (Test-Path $PyTorchSrc)) { throw "PyTorch source not found: $PyTorchSrc" }
$cmd = Join-Path $env:TEMP ("torch_build_" + [System.IO.Path]::GetRandomFileName() + ".cmd")
$cmdContent = @"
@echo off
call "$vcvars"
cd /d "$PyTorchSrc"
echo Building PyTorch with CUDA_HOME=%CUDA_PATH%, TORCH_CUDA_ARCH_LIST=%TORCH_CUDA_ARCH_LIST%
python -m pip install -v -e .
"@
Set-Content -Path $cmd -Value $cmdContent -Encoding ASCII
Write-Host "[build_pytorch_win] Cmd file: $cmd"
Write-Host "[build_pytorch_win] --- cmd content start ---"
Get-Content -Path $cmd | ForEach-Object { Write-Host $_ }
Write-Host "[build_pytorch_win] --- cmd content end ---"
cmd /c "\"$cmd\""
if ($LASTEXITCODE -ne 0) { throw "PyTorch build failed with exit code $LASTEXITCODE" }
Write-Host "[build_pytorch_win] Build finished"
