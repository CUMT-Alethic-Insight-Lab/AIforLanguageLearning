# 一键启动本地基础设施服务（Windows 本地二进制版）
# 依赖：scoop 已安装 redis, postgresql, minio

param(
    [switch]$Stop
)

$pgData = "$env:USERPROFILE\scoop\apps\postgresql\current\data"
$pgLog = "$env:USERPROFILE\scoop\apps\postgresql\current\logfile"
$pgCtl = "$env:USERPROFILE\scoop\apps\postgresql\current\bin\pg_ctl.exe"
$repoRoot = (Resolve-Path (Join-Path (Split-Path -Parent $PSCommandPath) "..")).Path
$minioData = Join-Path $repoRoot "infra_bin\minio_data"

function Test-Port($port) {
    try {
        $conn = New-Object System.Net.Sockets.TcpClient("localhost", $port)
        $conn.Close()
        return $true
    } catch {
        return $false
    }
}

if ($Stop) {
    Write-Host "Stopping infrastructure services..."
    & $pgCtl -D $pgData stop -m fast 2>$null
    Stop-Process -Name "redis-server" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "minio" -Force -ErrorAction SilentlyContinue
    Write-Host "All services stopped."
    exit 0
}

Write-Host "=== Starting AIFL Infrastructure (Native Windows) ==="

# PostgreSQL
if (-not (Test-Port 5432)) {
    Write-Host "Starting PostgreSQL..."
    if (-not (Test-Path $pgData)) {
        Write-Error "PostgreSQL data directory not found: $pgData"
        exit 1
    }
    & $pgCtl -D $pgData -l $pgLog start
    $maxWait = 30
    for ($i = 0; $i -lt $maxWait; $i++) {
        if (Test-Port 5432) { break }
        Start-Sleep -Seconds 1
    }
    if (Test-Port 5432) {
        Write-Host "PostgreSQL is ready (port 5432)."
    } else {
        Write-Error "PostgreSQL failed to start."
        exit 1
    }
} else {
    Write-Host "PostgreSQL already running."
}

# Redis
if (-not (Test-Port 6379)) {
    Write-Host "Starting Redis..."
    Start-Process -FilePath "redis-server" -ArgumentList "--daemonize","yes" -NoNewWindow
    $maxWait = 10
    for ($i = 0; $i -lt $maxWait; $i++) {
        if (Test-Port 6379) { break }
        Start-Sleep -Seconds 1
    }
    if (Test-Port 6379) {
        Write-Host "Redis is ready (port 6379)."
    } else {
        Write-Error "Redis failed to start."
        exit 1
    }
} else {
    Write-Host "Redis already running."
}

# MinIO
if (-not (Test-Port 9000)) {
    Write-Host "Starting MinIO..."
    New-Item -ItemType Directory -Force -Path $minioData | Out-Null
    $env:MINIO_ROOT_USER = "minioadmin"
    $env:MINIO_ROOT_PASSWORD = "minioadmin"
    Start-Process -FilePath "minio" -ArgumentList "server",$minioData,"--console-address",":9001" -WindowStyle Hidden
    $maxWait = 10
    for ($i = 0; $i -lt $maxWait; $i++) {
        if (Test-Port 9000) { break }
        Start-Sleep -Seconds 1
    }
    if (Test-Port 9000) {
        Write-Host "MinIO is ready (port 9000, console 9001)."
    } else {
        Write-Error "MinIO failed to start."
        exit 1
    }
} else {
    Write-Host "MinIO already running."
}

Write-Host ""
Write-Host "=== All infrastructure services are up ==="
Write-Host "PostgreSQL : localhost:5432 (user: postgres, password: <blank>)"
Write-Host "Redis      : localhost:6379"
Write-Host "MinIO      : localhost:9000 (console: http://localhost:9001)"
Write-Host ""
Write-Host "Note: Elasticsearch, RabbitMQ, Neo4j are not installed locally."
Write-Host "      - Celery uses Redis as broker (no RabbitMQ needed)."
Write-Host "      - Neo4j has graceful fallback in code."
Write-Host "      - ES search can use PostgreSQL LIKE as fallback."
