# IntelliForge Windows Deploy Script (PowerShell)
# Usage: .\scripts\deploy.ps1 -VpsIp "67.205.168.149" -VpsUser "root" -Domain "intelliforgesystems.com"
#
# You will be prompted for the VPS password securely.

param(
    [Parameter(Mandatory=$true)]
    [string]$VpsIp,

    [Parameter(Mandatory=$true)]
    [string]$VpsUser,

    [Parameter(Mandatory=$true)]
    [string]$Domain
)

$ErrorActionPreference = "Stop"
$RemoteDir = "/opt/intelliforge"

Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  IntelliForge VPS Deployer (Windows)" -ForegroundColor Cyan
Write-Host "  Target: $VpsUser@$VpsIp" -ForegroundColor Cyan
Write-Host "  Domain: $Domain" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Cyan

# ── 1. Prepare local files ────────────────────────────────────────────
Write-Host ""
Write-Host "[1/6] Preparing local files..." -ForegroundColor Yellow

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# Generate SECRET_KEY if placeholder
$EnvContent = Get-Content ".env" -Raw
if ($EnvContent -match "SECRET_KEY=change-me-to-a-long-random-string") {
    $NewKey = -join ((1..64) | ForEach-Object { "0123456789abcdef".ToCharArray() | Get-Random })
    $EnvContent = $EnvContent -replace "SECRET_KEY=change-me-to-a-long-random-string", "SECRET_KEY=$NewKey"
    Write-Host "      -> Generated SECRET_KEY" -ForegroundColor Green
}

# Set domain
$EnvContent = $EnvContent -replace "^# DOMAIN=.*", "DOMAIN=$Domain"
$EnvContent = $EnvContent -replace "^DOMAIN=.*", "DOMAIN=$Domain"
$EnvContent | Set-Content ".env" -NoNewline
Write-Host "      -> DOMAIN set to $Domain" -ForegroundColor Green

# Create Caddyfile
$CaddyContent = @"
$Domain {
    reverse_proxy web:5000
    encode gzip zstd
    header {
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
"@
$CaddyContent | Set-Content "Caddyfile" -Encoding UTF8
Write-Host "      -> Created Caddyfile" -ForegroundColor Green

# ── 2. Prompt for password ────────────────────────────────────────────
Write-Host ""
Write-Host "[2/6] Enter VPS password:" -ForegroundColor Yellow
$SecurePass = Read-Host "Password" -AsSecureString
$Bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePass)
$Pass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($Bstr)

# ── 3. Upload files via SCP ───────────────────────────────────────────
Write-Host ""
Write-Host "[3/6] Uploading project to VPS (this may take a minute)..." -ForegroundColor Yellow

# Use ssh-keyscan to avoid host key prompt
ssh-keyscan -H $VpsIp 2>$null | Out-File "$env:USERPROFILE\.ssh\known_hosts" -Append -ErrorAction SilentlyContinue

# Create remote directory
$CreateDir = "mkdir -p $RemoteDir"
$CreateDir | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$VpsUser@$VpsIp" "bash -s" 2>$null

# Exclude patterns for upload
$Excludes = @(
    ".git", "__pycache__", "*.pyc", ".venv",
    "node_modules", "data/uploads/*", "instance/*"
)

# Build tar archive locally and pipe to remote
Write-Host "      -> Creating archive..." -ForegroundColor Gray
tar -czf /tmp/intelliforge-deploy.tar.gz `
    --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' `
    --exclude='.venv' --exclude='node_modules' `
    --exclude='data/uploads' --exclude='instance' `
    -C $ProjectRoot .

Write-Host "      -> Uploading archive..." -ForegroundColor Gray
$env:SSH_ASKPASS = ""
$env:DISPLAY = ""

# Use scp with password via sshpass if available, otherwise manual
$scpCmd = "scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null /tmp/intelliforge-deploy.tar.gz `"$VpsUser@${VpsIp}:${RemoteDir}/archive.tar.gz`""

# We need to pipe the password - use a simple approach with plink or just instruct user
# Since Windows OpenSSH doesn't support password automation easily, let's check for sshpass
$sshPass = Get-Command sshpass -ErrorAction SilentlyContinue
if ($sshPass) {
    & sshpass -p "$Pass" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null `
        /tmp/intelliforge-deploy.tar.gz "$VpsUser@${VpsIp}:${RemoteDir}/archive.tar.gz"
} else {
    Write-Host ""
    Write-Host "  NOTE: sshpass not found. Falling back to manual SCP." -ForegroundColor Yellow
    Write-Host "  You will be prompted for the password again." -ForegroundColor Yellow
    scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null `
        /tmp/intelliforge-deploy.tar.gz "$VpsUser@${VpsIp}:${RemoteDir}/archive.tar.gz"
}

# Extract on remote
Write-Host "      -> Extracting on VPS..." -ForegroundColor Gray
"cd $RemoteDir && tar -xzf archive.tar.gz && rm archive.tar.gz" | `
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$VpsUser@$VpsIp" "bash -s" 2>$null

# ── 4. Run remote setup ───────────────────────────────────────────────
Write-Host ""
Write-Host "[4/6] Running VPS setup (Docker install + service start)..." -ForegroundColor Yellow

Get-Content "$PSScriptRoot\vps-setup.sh" | `
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$VpsUser@$VpsIp" "bash -s" 2>$null

# ── 5. Cleanup ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/6] Cleaning up..." -ForegroundColor Yellow
Remove-Item /tmp/intelliforge-deploy.tar.gz -ErrorAction SilentlyContinue

# ── 6. Done ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  App URL:    https://$Domain" -ForegroundColor White
Write-Host "  VPS Path:   $RemoteDir" -ForegroundColor White
Write-Host ""
Write-Host "  Useful commands on VPS:" -ForegroundColor Gray
Write-Host "    cd $RemoteDir && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web" -ForegroundColor Gray
Write-Host "    cd $RemoteDir && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build" -ForegroundColor Gray
Write-Host ""
Write-Host "  SSL is auto-managed by Caddy (Let's Encrypt)." -ForegroundColor Gray
Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Green
