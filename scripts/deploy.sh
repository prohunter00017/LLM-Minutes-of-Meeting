# IntelliForge VPS Deployment Script
# Usage: ./scripts/deploy.sh <VPS_IP> <VPS_USER> <VPS_PASSWORD> <DOMAIN>
#
# Example:
#   ./scripts/deploy.sh 67.205.168.149 root "your-password" intelliforgesystems.com
#
# Requirements on local machine: sshpass, rsync

#!/usr/bin/env bash
set -euo pipefail

# ── Arguments ─────────────────────────────────────────────────────────
VPS_IP="${1:-}"
VPS_USER="${2:-}"
VPS_PASS="${3:-}"
DOMAIN="${4:-}"

if [[ -z "$VPS_IP" || -z "$VPS_USER" || -z "$VPS_PASS" || -z "$DOMAIN" ]]; then
    echo "Usage: $0 <VPS_IP> <VPS_USER> <VPS_PASSWORD> <DOMAIN>"
    echo "Example: $0 203.0.113.1 root 'mypass' intelliforgesystems.com"
    exit 1
fi

REMOTE_DIR="/opt/intelliforge"
SSH_CMD="sshpass -p '$VPS_PASS' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $VPS_USER@$VPS_IP"

echo "══════════════════════════════════════════════════════════"
echo "  IntelliForge VPS Deployer"
echo "  Target: $VPS_USER@$VPS_IP"
echo "  Domain: $DOMAIN"
echo "══════════════════════════════════════════════════════════"

# ── 1. Prepare local archive ──────────────────────────────────────────
echo ""
echo "[1/7] Preparing local project archive..."

cd "$(dirname "$0")/.."

# Generate a real SECRET_KEY if not set
if grep -q "SECRET_KEY=change-me-to-a-long-random-string" .env; then
    NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    sed -i "s/SECRET_KEY=change-me-to-a-long-random-string/SECRET_KEY=$NEW_KEY/" .env
    echo "      → Generated SECRET_KEY"
fi

# Set domain in .env
sed -i "s/^# DOMAIN=.*/DOMAIN=$DOMAIN/" .env
sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env

echo "      → DOMAIN set to $DOMAIN"

# ── 2. Upload to VPS ──────────────────────────────────────────────────
echo ""
echo "[2/7] Uploading project to VPS..."

$SSH_CMD "mkdir -p $REMOTE_DIR"

# Use rsync over ssh (via sshpass)
sshpass -p "$VPS_PASS" rsync -az --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='data/uploads' \
    --exclude='instance' \
    ./ "$VPS_USER@$VPS_IP:$REMOTE_DIR/"

echo "      → Uploaded to $REMOTE_DIR"

# ── 3. Install Docker & Docker Compose ────────────────────────────────
echo ""
echo "[3/7] Installing Docker & Docker Compose on VPS..."

$SSH_CMD '
set -e
if ! command -v docker &> /dev/null; then
    echo "      → Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release sshpass rsync
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "      → Docker installed"
else
    echo "      → Docker already installed"
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "      → Installing docker-compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "      → docker-compose installed"
else
    echo "      → docker-compose already installed"
fi
'

# ── 4. Generate Caddyfile ─────────────────────────────────────────────
echo ""
echo "[4/7] Generating Caddy reverse-proxy config..."

$SSH_CMD "cat > $REMOTE_DIR/Caddyfile" <<EOF
$DOMAIN {
    reverse_proxy web:5000
    encode gzip zstd
    header {
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
EOF

echo "      → Caddyfile created"

# ── 5. Start services ─────────────────────────────────────────────────
echo ""
echo "[5/7] Starting IntelliForge services..."

$SSH_CMD "cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d"

echo "      → Services started"

# ── 6. Verify health ──────────────────────────────────────────────────
echo ""
echo "[6/7] Waiting for services to be healthy..."
sleep 10

$SSH_CMD "cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"

# ── 7. done ───────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "  App URL:    https://$DOMAIN"
echo "  VPS Path:   $REMOTE_DIR"
echo ""
echo "  Useful commands on VPS:"
echo "    cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web"
echo "    cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo ""
echo "  SSL certificate is auto-managed by Caddy (Let's Encrypt)."
echo "══════════════════════════════════════════════════════════"
