#!/usr/bin/env bash
# VPS Remote Setup Script — runs ON the VPS, not locally
# This is uploaded and executed by the deploy script

set -euo pipefail

cd /opt/intelliforge

echo "[REMOTE] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg lsb-release rsync

# Docker
echo "[REMOTE] Installing Docker..."
if ! command -v docker &> /dev/null; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \$(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
fi

# Ensure docker compose works
docker compose version || {
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
}

# Generate Caddyfile if not exists
if [[ ! -f Caddyfile ]]; then
    DOMAIN=\$(grep '^DOMAIN=' .env | cut -d= -f2 || echo "localhost")
    cat > Caddyfile <<EOF
\$DOMAIN {
    reverse_proxy web:5000
    encode gzip zstd
    header {
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
EOF
fi

# Start services
echo "[REMOTE] Starting services..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

echo "[REMOTE] Waiting for health checks..."
sleep 10
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

echo "[REMOTE] Done! App should be live at https://\$(grep '^DOMAIN=' .env | cut -d= -f2)"
