<#
AI 外语学习系统 - 快速启动脚本 (v2.1)

支持两种模式：
1. 开发模式（默认）：启动 FastAPI + Vite 开发服务器
2. Portable 模式（-Portable）：启动 FastAPI + 已打包的 Electron Portable 版本

已适配模块：
- 词汇模块 (/v1/vocab/*)
- 作文模块 (/v1/essays/*, WebSocket /ws/v1)
- 语音对话 (WebSocket /ws/v1, ASR→LLM→TTS 全链路)
- 智能助教 (WebSocket /api/v1/realtime-assistant/ws, OCR→LLM→TTS)

原则：控制台输出必须与实际状态一致。
- 只有在端口监听 / HTTP 健康检查通过后才打印 ✓
- 不盲目 Stop-Process -Name node/python（避免误杀其它开发进程）
#>

param(
    [int]$BackendPort = 8012,
    [int]$FrontendPort = 5173,
    [switch]$SkipBrowser,
    [switch]$EnableAsr,
    [switch]$DisableAsr,
    [string]$AsrCondaEnv = 'asr',
    [switch]$ForceRestartBackend,
    [switch]$Portable          # 使用已打包的 Electron Portable 版本（不启动 Vite 开发服务器）
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$text) {
    Write-Host ("`n" + $text) -ForegroundColor Yellow
}

function Write-Ok([string]$text) {
    Write-Host ("✓ " + $text) -ForegroundColor Green
}

function Write-Warn([string]$text) {
    Write-Host ("! " + $text) -ForegroundColor Yellow
}

function Write-Fail([string]$text) {
    Write-Host ("✗ " + $text) -ForegroundColor Red
}

function Test-PortListening([int]$port) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        return ($null -ne $conns)
    } catch {
        return $false
    }
}

function Get-ListeningPids([int]$port) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        return @($pids)
    } catch {
        return @()
    }
}

function Stop-ListeningPort([int]$port) {
    $pids = Get-ListeningPids -port $port
    if ($pids.Count -eq 0) {
        return
    }

    $failed = @()
    foreach ($procId in $pids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            $failed += $procId
        }
    }

    Start-Sleep -Milliseconds 600

    if (Test-PortListening -port $port) {
        if ($failed.Count -gt 0) {
            throw "尝试停止占用端口 $port 的进程失败（PID=$($failed -join ', ')）。请关闭对应后端窗口，或以管理员权限运行终端后重试。"
        }
        throw "端口 $port 仍在监听，无法完成重启。请先释放端口后重试。"
    }
}

function Get-BackendAsrEnabled([int]$port) {
    try {
        $cfg = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/system/config" -TimeoutSec 3
        return [bool]($cfg.data.asr.enabled)
    } catch {
        return $null
    }
}

function Wait-HttpOk([string]$url, [int]$timeoutSeconds = 25) {
    $start = Get-Date
    while (((Get-Date) - $start).TotalSeconds -lt $timeoutSeconds) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                return $true
            }
        } catch {
            # Some PowerShell versions throw on non-2xx. If we still got an HTTP response,
            # consider the server reachable.
            try {
                $resp = $_.Exception.Response
                if ($null -ne $resp -and $resp.StatusCode) {
                    $code = [int]$resp.StatusCode
                    if ($code -ge 200 -and $code -lt 500) {
                        return $true
                    }
                }
            } catch {
                # ignore
            }
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

function Wait-HttpOkAny([string[]]$urls, [int]$timeoutSeconds = 25) {
    $start = Get-Date
    while (((Get-Date) - $start).TotalSeconds -lt $timeoutSeconds) {
        foreach ($u in $urls) {
            if (Wait-HttpOk -url $u -timeoutSeconds 1) {
                return $u
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return $null
}

function Test-CondaAvailable() {
    return ($null -ne (Get-Command conda -ErrorAction SilentlyContinue))
}

function Get-CondaEnvPythonExe([string]$envName) {
    if (-not (Test-CondaAvailable)) {
        throw "当前终端找不到 conda。"
    }

    try {
        $envs = (conda env list --json | ConvertFrom-Json).envs
    } catch {
        throw "无法读取 conda 环境列表（conda env list --json）。"
    }

    $prefix = $null
    foreach ($p in $envs) {
        if (((Split-Path $p -Leaf).ToLower()) -eq $envName.ToLower()) {
            $prefix = $p
            break
        }
    }

    if (-not $prefix) {
        throw "未找到 conda 环境 '$envName'。"
    }

    $pyExe = Join-Path $prefix "python.exe"
    if (-not (Test-Path $pyExe)) {
        throw "未找到 python.exe：$pyExe"
    }

    return $pyExe
}

function Get-ProcessExecutablePath([int]$processId) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop
        return [string]$p.ExecutablePath
    } catch {
        return $null
    }
}

function Test-PythonHasModule([string]$pythonExe, [string]$moduleName) {
    $null = & $pythonExe -c "import $moduleName" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-AsrBackendEnv([string]$envName) {
    if (-not (Test-CondaAvailable)) {
        throw "已启用 -EnableAsr，但当前终端找不到 conda。请先安装/初始化 Miniconda/Anaconda，或取消 -EnableAsr。"
    }

    $pyExe = Get-CondaEnvPythonExe -envName $envName

    if (-not (Test-PythonHasModule -pythonExe $pyExe -moduleName 'faster_whisper')) {
        throw "Conda 环境 '$envName' 中未找到 faster_whisper。请在该环境安装 faster-whisper，或改用其他 ASR 方案。"
    }

    # backend_fastapi 运行所需依赖（如果缺失则尝试自动安装）
    $need = @('fastapi','uvicorn','sqlmodel','pydantic_settings','jinja2','structlog')
    $missing = @()
    foreach ($m in $need) {
        if (-not (Test-PythonHasModule -pythonExe $pyExe -moduleName $m)) {
            $missing += $m
        }
    }

    if ($missing.Count -gt 0) {
        Write-Warn "Conda 环境 '$envName' 缺少后端依赖：$($missing -join ', ')；将尝试自动安装..."
        # 注意：webrtcvad 为可选；未安装也不影响 enable_vad=false 的默认模式。
        & $pyExe -m pip install -U fastapi "uvicorn[standard]" pydantic-settings sqlmodel sqlalchemy alembic jinja2 structlog | Out-Host
    }
}

Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "AI 外语学习系统 - 启动中..." -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan

# 模式说明：
# -Portable：使用已打包的 Electron Portable 版本（不启动 Vite 开发服务器）
# -EnableAsr：强制启用 ASR（依赖不满足则报错）
# -DisableAsr：显式禁用 ASR
# 默认：开发模式（Vite热重载），ASR auto（能用就启用，不满足则降级）
$asrMode = 'auto'
if ($DisableAsr) { $asrMode = 'off' }
elseif ($EnableAsr) { $asrMode = 'on' }

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$rootPath = Split-Path -Parent $scriptPath
$backendFastApiPath = Join-Path $rootPath "backend_fastapi"
$frontendV5Path = Join-Path $rootPath "app\v5"
$pidDir = Join-Path $rootPath ".tmp\pids"
$backendPidFile = Join-Path $pidDir "backend_fastapi_pwsh.pid"
$frontendPidFile = Join-Path $pidDir "frontend_v5_pwsh.pid"

New-Item -ItemType Directory -Force -Path $pidDir | Out-Null

Write-Step "[1/3] 环境与端口检查"
if (-not (Test-Path $backendFastApiPath)) {
    throw "backend_fastapi 目录不存在：$backendFastApiPath"
}
if (-not (Test-Path $frontendV5Path)) {
    throw "app/v5 目录不存在：$frontendV5Path"
}

if ($asrMode -eq 'off') {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "未找到 python。请先安装 Python，或在当前终端激活你的虚拟环境/conda 环境后重试。"
    }
} else {
    try {
        Ensure-AsrBackendEnv -envName $AsrCondaEnv
    } catch {
        if ($asrMode -eq 'on') {
            throw
        }
        Write-Warn "未能启用 ASR（将自动降级为不启用 ASR 启动后端）：$($_.Exception.Message)"
        $asrMode = 'off'

        if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
            throw "未找到 python。请先安装 Python，或在当前终端激活你的虚拟环境/conda 环境后重试。"
        }
    }
}

$asrPythonExe = $null
if ($asrMode -ne 'off') {
    try {
        $asrPythonExe = Get-CondaEnvPythonExe -envName $AsrCondaEnv
        Write-Ok "ASR Python 环境：$asrPythonExe"
    } catch {
        if ($asrMode -eq 'on') { throw }
        Write-Warn "无法解析 conda env '$AsrCondaEnv' 的 python 路径，将降级为不启用 ASR：$($_.Exception.Message)"
        $asrMode = 'off'
    }
}
if (-not $Portable) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "未找到 npm。请先安装 Node.js（含 npm），或确保 npm 在 PATH。"
    }
}

if (Test-PortListening -port $BackendPort) {
    Write-Warn "端口 $BackendPort 已在监听。将跳过启动 FastAPI，并改为做健康检查。"
}
if (Test-PortListening -port $FrontendPort) {
    Write-Warn "端口 $FrontendPort 已在监听。将跳过启动前端，并改为做连通性检查。"
}

Write-Ok "基础检查完成"

Write-Step "[2/3] 启动后端 (FastAPI)"
$backendListening = Test-PortListening -port $BackendPort
if ($backendListening) {
    $shouldRestartBackend = $ForceRestartBackend

    # 自动重启条件：
    # 1) 明确确认是本项目后端（/api/system/config 可读且结构匹配）
    # 2) 需要 ASR（asrMode!=off）但运行态 ASR=disabled，或监听进程不是 conda env 的 python
    if (-not $shouldRestartBackend -and $asrMode -ne 'off') {
        $cfgOk = $false
        $runtimeAsrEnabled = $null
        $runtimeAsrAvailable = $null
        $runtimePythonExe = $null
        try {
            $cfg = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/system/config" -TimeoutSec 3
            if ($cfg -and ($cfg.success -eq $true) -and $cfg.data -and ($cfg.data.port -eq $BackendPort)) {
                $cfgOk = $true
                $runtimeAsrEnabled = [bool]($cfg.data.asr.enabled)
                try { $runtimeAsrAvailable = [bool]($cfg.data.asr.runtime.available) } catch { $runtimeAsrAvailable = $null }
                try { $runtimePythonExe = [string]($cfg.data.python.executable) } catch { $runtimePythonExe = $null }
            }
        } catch { }

        if (-not $cfgOk) {
            Write-Warn "端口 $BackendPort 已在监听，但无法确认是本项目后端；将不自动重启。"
        } else {
            if ($runtimeAsrEnabled -eq $false) {
                Write-Warn "检测到后端已在运行但 ASR=disabled；将自动重启后端以启用 ASR。"
                $shouldRestartBackend = $true
            } elseif ($runtimeAsrAvailable -eq $false) {
                Write-Warn "检测到后端 ASR 依赖不可用（runtime.available=false）；将自动重启后端以切到正确环境。"
                $shouldRestartBackend = $true
            } elseif ($null -ne $asrPythonExe -and $runtimePythonExe) {
                if ($runtimePythonExe.Trim().ToLower() -ne $asrPythonExe.Trim().ToLower()) {
                    Write-Warn "检测到后端未运行在 conda env '$AsrCondaEnv' 的 Python 上；将自动重启以修复 ASR 依赖不可用问题。"
                    $shouldRestartBackend = $true
                }
            }
        }
    }

    if ($shouldRestartBackend) {
        $pids = Get-ListeningPids -port $BackendPort
        if ($pids.Count -gt 0) {
            Write-Warn "将重启后端：停止占用端口 $BackendPort 的进程 PID=$($pids -join ', ')"
            Stop-ListeningPort -port $BackendPort
        }
        $backendListening = Test-PortListening -port $BackendPort
    }
}

if (-not $backendListening) {
    if ($asrMode -ne 'off') {
        if (-not $asrPythonExe) {
            throw "ASR 模式已启用，但无法解析 conda env '$AsrCondaEnv' 的 python 路径。"
        }
        $backendCmd = "cd '$backendFastApiPath'; Write-Host 'FastAPI 后端启动中（ASR 已启用）...' -ForegroundColor Cyan; `$env:PYTHONPATH='$backendFastApiPath'; `$env:AIFL_ENABLE_ASR='1'; `$env:AIFL_ASR_BACKEND='faster-whisper'; & '$asrPythonExe' -m uvicorn --app-dir '$backendFastApiPath' app.main:app --reload --host 127.0.0.1 --port $BackendPort"
    } else {
        $backendCmd = "cd '$backendFastApiPath'; Write-Host 'FastAPI 后端启动中...' -ForegroundColor Cyan; `$env:PYTHONPATH='$backendFastApiPath'; python -m uvicorn --app-dir '$backendFastApiPath' app.main:app --reload --host 127.0.0.1 --port $BackendPort"
    }
    $backendProc = Start-Process pwsh -PassThru -ArgumentList "-NoExit", "-Command", $backendCmd
    Set-Content -Path $backendPidFile -Value $backendProc.Id
    Write-Host "已启动后端窗口（PID=$($backendProc.Id)），等待健康检查..." -ForegroundColor Gray
}

$healthUrl = "http://127.0.0.1:$BackendPort/health"
if (Wait-HttpOk -url $healthUrl -timeoutSeconds 35) {
    Write-Ok "后端可用：$healthUrl"
} else {
    Write-Fail "后端健康检查失败：$healthUrl"
    Write-Host "建议：查看后端窗口输出；确认依赖已安装（backend_fastapi/pyproject.toml）并且端口未被占用。" -ForegroundColor Gray
    throw "后端未就绪，停止继续启动前端。"
}

# 运行态配置回显（用于确认 ASR 是否启用）
try {
    $cfg = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/system/config" -TimeoutSec 5
    $asrEnabled = [bool]($cfg.data.asr.enabled)
    $asrAvailable = $null
    try { $asrAvailable = [bool]($cfg.data.asr.runtime.available) } catch { $asrAvailable = $null }
    if ($asrEnabled) {
        if ($asrAvailable -eq $false) {
            Write-Warn "ASR 配置已启用，但运行环境缺少 ASR 依赖（backend=$($cfg.data.asr.backend)）。请用本脚本启动以自动切换到 conda env '$AsrCondaEnv'。"
        } else {
            Write-Ok "ASR 已启用（backend=$($cfg.data.asr.backend), model=$($cfg.data.asr.model)）"
        }
    } else {
        Write-Warn "ASR 未启用（默认会尝试启用；如需强制启用：./scripts/start.ps1 -EnableAsr；如要禁用：./scripts/start.ps1 -DisableAsr）"
    }
} catch {
    Write-Warn "无法读取后端运行态配置（/api/system/config）。"
}

# 查找已打包的 Portable 版本
$portableExe = $null
$releaseDir = Join-Path $frontendV5Path "release"
if (Test-Path $releaseDir) {
    $portableCandidates = Get-ChildItem -Path $releaseDir -Filter "*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "AIFL-V5*.exe" }
    if ($portableCandidates) {
        $portableExe = $portableCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
}

if ($Portable) {
    Write-Step "[3/3] 启动前端 (Electron Portable)"
    if (-not $portableExe) {
        Write-Fail "未找到已打包的 Portable 版本（app/v5/release/AIFL-V5*.exe）"
        Write-Host "建议：先执行 'cd app/v5 && npm run dist' 打包，或去掉 -Portable 参数使用开发模式。" -ForegroundColor Gray
        throw "Portable 版本未找到。"
    }
    
    # 检查 portable 是否已在运行
    $portableRunning = $false
    try {
        $portableProcs = Get-Process | Where-Object { $_.ProcessName -like "*AIFL-V5*" -or $_.ProcessName -like "*AIFL*" }
        if ($portableProcs) { $portableRunning = $true }
    } catch { }
    
    if (-not $portableRunning) {
        $frontendProc = Start-Process -FilePath $portableExe.FullName -PassThru -WorkingDirectory $releaseDir
        Set-Content -Path $frontendPidFile -Value $frontendProc.Id
        Write-Ok "已启动 Portable 前端：$($portableExe.Name) (PID=$($frontendProc.Id))"
    } else {
        Write-Warn "Portable 前端已在运行，跳过启动"
    }
    
    $frontendUrl = "Electron Portable (独立窗口)"
    Write-Ok "前端可用：$frontendUrl"
} else {
    Write-Step "[3/3] 启动前端 (Vite / app/v5)"
    if (-not (Test-PortListening -port $FrontendPort)) {
        $frontendCmd = "cd '$frontendV5Path'; Write-Host 'Vite 前端启动中...' -ForegroundColor Cyan; npm run dev"
        $frontendProc = Start-Process pwsh -PassThru -ArgumentList "-NoExit", "-Command", $frontendCmd
        Set-Content -Path $frontendPidFile -Value $frontendProc.Id
        Write-Host "已启动前端窗口（PID=$($frontendProc.Id)），等待连通性检查..." -ForegroundColor Gray
    }

    $frontendUrl = "http://127.0.0.1:$FrontendPort"
    $frontendCandidates = @(
        "http://localhost:$FrontendPort",
        "http://127.0.0.1:$FrontendPort",
        "http://[::1]:$FrontendPort"
    )
    $frontendReadyUrl = Wait-HttpOkAny -urls $frontendCandidates -timeoutSeconds 75
    if ($frontendReadyUrl) {
        $frontendUrl = $frontendReadyUrl
        Write-Ok "前端可用：$frontendUrl"
    } else {
        Write-Fail "前端连通性检查失败：$frontendUrl"
        Write-Host "建议：查看前端窗口输出；首次启动需要在 app/v5 下执行 npm install。" -ForegroundColor Gray
        throw "前端未就绪。"
    }

    if (-not $SkipBrowser) {
        Write-Step "[完成] 打开浏览器"
        Start-Process $frontendUrl
        Write-Ok "已打开：$frontendUrl"
    }
}

Write-Host ("`n" + "=" * 60) -ForegroundColor Cyan
Write-Host "系统启动完成（已验证可用）" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "`n服务地址：" -ForegroundColor White
Write-Host "  • 后端 API:    http://127.0.0.1:$BackendPort" -ForegroundColor White
Write-Host "  • 前端页面:    $frontendUrl" -ForegroundColor White
Write-Host "  • WebSocket (语音对话): ws://127.0.0.1:$BackendPort/ws/v1" -ForegroundColor White
Write-Host "  • WebSocket (智能助教): ws://127.0.0.1:$BackendPort/api/v1/realtime-assistant/ws" -ForegroundColor White
Write-Host "`n提示：本脚本不会强制杀进程；如需停止服务，请关闭各自的新窗口。" -ForegroundColor Gray
