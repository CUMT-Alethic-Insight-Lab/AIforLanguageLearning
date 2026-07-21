<#
HELIX LAN Web startup script.

Builds the Vue frontend and serves it from FastAPI so classroom clients can
open the app in a browser without installing Electron. HTTPS is the default
because browsers require a secure context for microphone access on LAN hosts.
#>

[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8012,

    [ValidateNotNullOrEmpty()]
    [string]$HostAddress = "0.0.0.0",

    [ValidateSet("Https", "HttpDevelopment")]
    [string]$Mode = "Https",

    [string]$CertificatePath = $env:AIFL_HTTPS_CERTFILE,
    [string]$PrivateKeyPath = $env:AIFL_HTTPS_KEYFILE,

    [switch]$SkipBuild,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Text) {
    Write-Host ("`n" + $Text) -ForegroundColor Yellow
}

function Write-Ok([string]$Text) {
    Write-Host ("[OK] " + $Text) -ForegroundColor Green
}

function Stop-Helix([string]$Message, [int]$ExitCode = 1) {
    [Console]::Error.WriteLine("ERROR: " + $Message)
    exit $ExitCode
}

function Test-PortInUse([int]$Port) {
    try {
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        return [bool]($listeners | Where-Object { $_.Port -eq $Port } | Select-Object -First 1)
    } catch {
        Stop-Helix "Unable to inspect listening ports: $($_.Exception.Message)" 4
    }
}

function Get-LanIPv4Addresses() {
    try {
        $preferred = @(
            Get-NetIPConfiguration -ErrorAction Stop |
                Where-Object { $_.NetAdapter.Status -eq "Up" -and $_.IPv4DefaultGateway } |
                ForEach-Object { $_.IPv4Address.IPAddress } |
                Where-Object { $_ -and $_ -notlike "127.*" -and $_ -notlike "169.254.*" } |
                Select-Object -Unique
        )
        if ($preferred.Count -gt 0) {
            return $preferred
        }

        return @(
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object {
                    $_.IPAddress -notlike "127.*" -and
                    $_.IPAddress -notlike "169.254.*" -and
                    $_.PrefixOrigin -ne "WellKnown"
                } |
                Select-Object -ExpandProperty IPAddress -Unique
        )
    } catch {
        return @()
    }
}

function Assert-FrontendDist([string]$DistDirectory) {
    $indexPath = Join-Path $DistDirectory "index.html"
    $assetsPath = Join-Path $DistDirectory "assets"

    if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) {
        Stop-Helix "Frontend dist is incomplete: app/v5/dist/index.html is missing. Run without -SkipBuild." 3
    }
    if ((Get-Item -LiteralPath $indexPath).Length -eq 0) {
        Stop-Helix "Frontend dist is incomplete: app/v5/dist/index.html is empty." 3
    }
    if (-not (Test-Path -LiteralPath $assetsPath -PathType Container)) {
        Stop-Helix "Frontend dist is incomplete: app/v5/dist/assets is missing." 3
    }
    if (-not (Get-ChildItem -LiteralPath $assetsPath -File -Filter "*.js" | Select-Object -First 1)) {
        Stop-Helix "Frontend dist is incomplete: app/v5/dist/assets contains no JavaScript bundle." 3
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$frontendDir = Join-Path $repoRoot "app\v5"
$frontendDist = Join-Path $frontendDir "dist"
$backendDir = Join-Path $repoRoot "backend_fastapi"
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    Stop-Helix "Backend virtual environment was not found at backend_fastapi/.venv. Install backend dependencies first." 3
}

$scheme = "https"
$tlsArgs = @()
if ($Mode -eq "Https") {
    if ([string]::IsNullOrWhiteSpace($CertificatePath) -or [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
        Stop-Helix "HTTPS is required by default. Provide -CertificatePath and -PrivateKeyPath, or explicitly use -Mode HttpDevelopment." 2
    }
    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
        Stop-Helix "HTTPS certificate file was not found." 2
    }
    if (-not (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf)) {
        Stop-Helix "HTTPS private key file was not found." 2
    }

    $resolvedCertificate = (Resolve-Path -LiteralPath $CertificatePath).Path
    $resolvedPrivateKey = (Resolve-Path -LiteralPath $PrivateKeyPath).Path
    $certificateCheck = "import ssl,sys; c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); c.load_cert_chain(sys.argv[1],sys.argv[2])"
    & $pythonExe -c $certificateCheck $resolvedCertificate $resolvedPrivateKey 2>$null
    if ($LASTEXITCODE -ne 0) {
        Stop-Helix "HTTPS certificate/private key validation failed. Confirm PEM format and that the files form a matching, unencrypted pair." 2
    }
    $tlsArgs = @("--ssl-certfile", $resolvedCertificate, "--ssl-keyfile", $resolvedPrivateKey)

    # Classroom HTTPS is a production boundary. Force Settings to reject the
    # repository's development JWT/admin defaults before spending time on a
    # frontend build. The validation process prints no configuration values.
    $env:AIFL_APP_ENV = "production"
    Push-Location $backendDir
    try {
        & $pythonExe -c "from app.settings import settings; assert settings.app_env == 'production'" 1>$null 2>$null
        $authConfigExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($authConfigExitCode -ne 0) {
        Stop-Helix "Production authentication configuration is invalid. Set a non-default AIFL_JWT_SECRET and, when admin seeding is enabled, a non-default AIFL_SEED_ADMIN_PASSWORD." 2
    }
} else {
    $scheme = "http"
    Write-Warning "HTTP development mode was explicitly selected. LAN browsers will block microphone access; use only for non-audio development or localhost checks."
}

if (Test-PortInUse $BackendPort) {
    Stop-Helix "TCP port $BackendPort is already in use. Stop the existing process or choose -BackendPort <port>." 4
}

if (-not $SkipBuild) {
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $npmCommand) {
        Stop-Helix "npm was not found. Install Node.js, or use -SkipBuild with a previously validated dist." 3
    }

    Write-Step "Building Vue frontend"
    Push-Location $frontendDir
    try {
        & $npmCommand.Source run build
        $buildExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($buildExitCode -ne 0) {
        Stop-Helix "Frontend build failed with exit code $buildExitCode." 10
    }
}

Assert-FrontendDist $frontendDist
Write-Ok "Frontend dist passed integrity checks"

if (Test-PortInUse $BackendPort) {
    Stop-Helix "TCP port $BackendPort became occupied during preparation. Startup was cancelled." 4
}

if ($Mode -eq "Https") {
    Write-Ok "HTTPS certificate and private key files are present"
    Write-Warning "Each client must trust the certificate, and its hostname/IP must appear in the certificate SAN. Otherwise microphone access and WSS can still fail."
}

Write-Step "Client URLs"
$clientAddresses = @()
if ($HostAddress -eq "0.0.0.0" -or $HostAddress -eq "::") {
    $clientAddresses = @(Get-LanIPv4Addresses)
} elseif ($HostAddress -eq "localhost") {
    $clientAddresses = @("localhost")
} else {
    $clientAddresses = @($HostAddress)
}

if ($clientAddresses.Count -eq 0) {
    Write-Host "No LAN IPv4 address was detected. Check the active Wi-Fi/Ethernet adapter."
    Write-Host "Local check only: ${scheme}://127.0.0.1:$BackendPort"
} else {
    foreach ($address in $clientAddresses) {
        Write-Host "${scheme}://${address}:$BackendPort"
    }
}

Write-Host "Allow inbound TCP $BackendPort in Windows Firewall before classroom use."
if ($ValidateOnly) {
    Write-Ok "LAN Web configuration validation completed; the server was not started"
    exit 0
}

Write-Step "Starting FastAPI on $HostAddress`:$BackendPort"
$uvicornArgs = @(
    "-m", "uvicorn", "app.main:app",
    "--host", $HostAddress,
    "--port", "$BackendPort",
    "--log-level", "warning",
    "--no-access-log"
) + $tlsArgs

Push-Location $backendDir
try {
    & $pythonExe @uvicornArgs
    $serverExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($null -eq $serverExitCode) {
    $serverExitCode = 1
}
if ($serverExitCode -ne 0) {
    Stop-Helix "FastAPI stopped with exit code $serverExitCode." $serverExitCode
}
exit 0
