param(
    [string]$ModelSize,
    [string]$Device,
    [string]$ComputeType,
    [string]$Language,
    [switch]$ListDevices,
    [string]$InputDevice,
    [switch]$NoPrefix,
    [switch]$Json,
    [switch]$VuMeter,
    [int]$SilenceMs,
    [int]$FrameMs = 30,
    [int]$BeamSize = 1,
    [double]$MaxSegmentSec = 15.0,
    [double]$ForceFlushSec = 6.0,
    [string]$InitialPrompt
)

# Resolve defaults from environment or fallback values
if (-not $ModelSize) { $ModelSize = $env:FASTWHISPER_MODEL_SIZE; if (-not $ModelSize) { $ModelSize = 'medium' } }
if (-not $Device) { $Device = $env:FASTWHISPER_DEVICE; if (-not $Device) { $Device = 'cpu' } }
if (-not $ComputeType) { $ComputeType = $env:FASTWHISPER_COMPUTE; if (-not $ComputeType) { $ComputeType = 'int8' } }
if (-not $Language) { $Language = $env:FASTWHISPER_LANG; if (-not $Language) { $Language = 'auto' } }
if (-not $SilenceMs) { if ($env:MIC_SILENCE_MS) { $SilenceMs = [int]$env:MIC_SILENCE_MS } else { $SilenceMs = 500 } }

# Helper: find python
function Get-Python {
    if ($env:FASTWHISPER_PYTHON -and (Test-Path $env:FASTWHISPER_PYTHON)) { return $env:FASTWHISPER_PYTHON }
    $candidates = @()
    if ($env:CONDA_PREFIX) {
        $candidates += (Join-Path $env:CONDA_PREFIX 'python.exe')
    }
        $userProfile = $env:USERPROFILE
        if ($userProfile) {
        $candidates += @(
                (Join-Path $userProfile 'Miniconda3\envs\torchnb311\python.exe'),
                (Join-Path $userProfile 'miniconda3\envs\torchnb311\python.exe')
        )
    }
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $py = (Get-Command python -ErrorAction SilentlyContinue)
    if ($py) { return "python" }
    $py3 = (Get-Command python3 -ErrorAction SilentlyContinue)
    if ($py3) { return "python3" }
    throw "Python not found. Please activate your environment or install Python."
}

$python = Get-Python
Write-Host "[mic-quickstart] Using Python: $python" -ForegroundColor Cyan

# Ensure deps
$deps = @('faster-whisper','sounddevice','webrtcvad','soundfile','numpy')
$code = @'
import importlib, sys
missing=[]
for m in ["faster_whisper","sounddevice","webrtcvad","soundfile","numpy"]:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
print("OK" if not missing else "MISSING:"+",".join(missing))
'@
$depStatus = (& $python -c $code) 2>$null
if ($null -eq $depStatus) { $depStatus = "" }
$depStatus = $depStatus.Trim()

if ($depStatus -and $depStatus.StartsWith('MISSING')) {
    $toInstall = $depStatus.Substring(8).Split(',') | Where-Object { $_ -ne '' }
    Write-Host "[mic-quickstart] Installing deps: $($toInstall -join ', ')" -ForegroundColor Yellow
    & $python -m pip install --upgrade pip | Out-Null
    & $python -m pip install @toInstall
}

# Build args for Python script
$scriptPath = Join-Path $PSScriptRoot 'run_faster_whisper_mic.py'
if (-not (Test-Path $scriptPath)) { throw "Script not found: $scriptPath" }

$argsList = @()
if ($ListDevices) { $argsList += '--list-devices' }
if ($Json) { $argsList += '--json' }
if ($VuMeter) { $argsList += '--vumeter' }
if ($NoPrefix) { $argsList += '--no-prefix' }
if ($InputDevice) { $argsList += @('--input-device', "$InputDevice") }
if ($InitialPrompt) { $argsList += @('--initial-prompt', "$InitialPrompt") }

$argsList += @('--model-size', "$ModelSize", '--device', "$Device", '--compute-type', "$ComputeType",
               '--language', "$Language", '--silence-ms', "$SilenceMs", '--frame-ms', "$FrameMs",
               '--beam-size', "$BeamSize", '--max-segment-sec', "$MaxSegmentSec", '--force-flush-sec', "$ForceFlushSec",
               '--interactive')

Write-Host "[mic-quickstart] Launching mic ASR..." -ForegroundColor Green
Write-Host "[mic-quickstart] Tip: Speak after you see the VU updates. Ctrl+C to stop." -ForegroundColor DarkGray

& $python $scriptPath @argsList
