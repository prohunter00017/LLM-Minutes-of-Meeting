# Deploying IntelliForge to a VPS

This guide covers deploying IntelliForge to a VPS (e.g., DigitalOcean) with automatic SSL via Caddy.

## Requirements

- A VPS running **Ubuntu 22.04/24.04** with root or sudo access
- A **domain name** pointing to your VPS IP (A record)
- On your Windows machine:
  - **Git for Windows** (includes Git Bash, ssh, scp) — [download](https://git-scm.com/download/win)
  - Or **WSL2** with Ubuntu

## Quick Deploy (Git Bash / WSL)

Open Git Bash in the project folder and run:

```bash
# Replace with your actual credentials
./scripts/deploy.sh 67.205.168.149 root "your-password" intelliforgesystems.com
```

This single command will:
1. Generate a secure `SECRET_KEY`
2. Set your domain in `.env`
3. Upload the entire project to `/opt/intelliforge`
4. Install Docker & Docker Compose on the VPS
5. Configure Caddy with auto-SSL
6. Start all services

## Manual Deploy (Step by Step)

If you prefer full control, follow these steps:

### 1. Prepare Local Files

```bash
# Generate a secret key
python -c "import secrets; print(secrets.token_hex(32))"

# Edit .env
domain=intelliforgesystems.com
# Set DOMAIN=$domain
# Set STRIPE_* keys, LLM_* keys, etc.
```

### 2. Create Caddyfile

```bash
cat > Caddyfile <<'EOF'
intelliforgesystems.com {
    reverse_proxy web:5000
    encode gzip zstd
    header {
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
EOF
```

### 3. Upload to VPS

```bash
VPS_IP=67.205.168.149
VPS_USER=root

# Create remote directory
ssh $VPS_USER@$VPS_IP "mkdir -p /opt/intelliforge"

# Upload files (run from project root)
scp -r . $VPS_USER@$VPS_IP:/opt/intelliforge/
```

### 4. Install Docker on VPS

SSH into your VPS:

```bash
ssh root@67.205.168.149

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose plugin
apt-get update
apt-get install -y docker-compose-plugin

# Verify
docker compose version
```

### 5. Start Services

```bash
cd /opt/intelliforge
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 6. Verify

```bash
# Check containers
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web
```

### 7. SSL Certificate

Caddy automatically obtains a Let's Encrypt certificate. Visit:
- `https://intelliforgesystems.com`

The first request may take 10-30 seconds while Caddy provisions the certificate.

## Updating After Code Changes

```bash
ssh root@67.205.168.149 "cd /opt/intelliforge && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"
```

## Useful Commands

| Task | Command |
|---|---|
| View logs | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f web` |
| Restart | `docker compose -f docker-compose.yml -f docker-compose.prod.yml restart` |
| Stop all | `docker compose -f docker-compose.yml -f docker-compose.prod.yml down` |
| Backup DB | `scp root@67.205.168.149:/opt/intelliforge/instance/app.db ./backup.db` |
| Update certs | Caddy auto-renews — no action needed |

## Troubleshooting

### Port 5000 exposed?
The base compose binds port 5000 to `127.0.0.1` only (localhost), so it's not accessible externally. Only Caddy (on 80/443) faces the internet.

### SSL not working?
- Ensure your domain's A record points to the VPS IP
- Check Caddy logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs caddy`
- Ensure ports 80 and 443 are open in your VPS firewall

### 502 Bad Gateway?
- The web container is still starting. Wait 30 seconds.
- Check web health: `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps`

## Firewall Rules (DigitalOcean)

In your DigitalOcean dashboard, ensure these inbound rules:

| Type | Protocol | Port | Source |
|---|---|---|---|
| SSH | TCP | 22 | Your IP (or 0.0.0.0/0) |
| HTTP | TCP | 80 | 0.0.0.0/0 |
| HTTPS | TCP | 443 | 0.0.0.0/0 |
