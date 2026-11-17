#!/usr/bin/env python3
"""Deploy IntelliForge to AWS Lightsail (key auth, ubuntu user, sudo).

- Auto-reads and validates .env
- Installs Docker if missing
- Adds 2GB swap (414MB instance needs it)
- Uploads code + .env, starts full stack with low-RAM override
"""
import paramiko
import os
import tarfile
import io
import time

# ── Config ────────────────────────────────────────────────────
# Override with env vars for portability:
#   LIGHTSAIL_IP, LIGHTSAIL_USER, LIGHTSAIL_KEY
HOST = os.environ.get("LIGHTSAIL_IP", "52.27.235.196")
USER = os.environ.get("LIGHTSAIL_USER", "ubuntu")
KEY_FILE = os.environ.get(
    "LIGHTSAIL_KEY",
    r"F:\Codes\PycharmProjects\tts\aws\lightsail.pem",
)
REMOTE_DIR = "/opt/intelliforge"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# ── Validate .env ─────────────────────────────────────────────
REQUIRED_KEYS = ["SECRET_KEY", "DOMAIN", "ADMIN_USERNAME", "ADMIN_PASSWORD",
                 "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                 "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                 "ELEVENLABS_API_KEY", "SPEECH_PROVIDER"]

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        s = " ".join(str(a) for a in args)
        print(s.encode("ascii", errors="replace").decode(), **kwargs)

def load_env():
    env = {}
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env

def validate_env(env):
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        safe_print("ERROR: .env missing required keys:")
        for k in missing:
            safe_print(f"  - {k}")
        raise SystemExit(1)
    domain = env.get("DOMAIN", "")
    if "." not in domain:
        safe_print(f"ERROR: DOMAIN looks wrong: '{domain}'")
        raise SystemExit(1)
    safe_print(f".env OK — domain={env['DOMAIN']}, llm_model={env['LLM_MODEL']}, speech={env['SPEECH_PROVIDER']}")


def preflight_credentials(env):
    """Validate third-party API credentials BEFORE deploying so dead keys
    are caught up front instead of surfacing as 401s during processing."""
    import json as _json
    import urllib.error
    import urllib.request

    def probe(name, url, headers, payload=None):
        try:
            if payload is None:
                req = urllib.request.Request(url, headers=headers)
            else:
                req = urllib.request.Request(url, data=_json.dumps(payload).encode(),
                                             headers=headers)
            urllib.request.urlopen(req, timeout=45)
            return name, True, "OK"
        except urllib.error.HTTPError as e:
            body = e.read()[:160].decode(errors="replace")
            return name, False, f"HTTP {e.code}: {body}"
        except Exception as e:
            return name, False, str(e)[:160]

    checks = []

    # LLM — Cloudflare Workers AI
    llm_base = env.get("LLM_BASE_URL", "")
    llm_key = env.get("LLM_API_KEY", "")
    llm_model = env.get("LLM_MODEL", "")
    if "cloudflare.com" in llm_base:
        acct = ""
        parts = llm_base.split("/")
        for i, p in enumerate(parts):
            if p == "accounts" and i + 1 < len(parts):
                acct = parts[i + 1]
                break
        checks.append(probe(
            "LLM (Cloudflare Workers AI)",
            f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{llm_model}",
            {"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
            {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
        ))
    elif llm_base:
        checks.append(probe(
            "LLM (OpenAI-compatible)",
            llm_base.rstrip("/") + "/chat/completions",
            {"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
            {"model": llm_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
        ))

    # Speech-to-text
    provider = env.get("SPEECH_PROVIDER", "").lower()
    speech_map = {
        "elevenlabs": ("ElevenLabs", "https://api.elevenlabs.io/v1/user/subscription",
                       "xi-api-key", "ELEVENLABS_API_KEY"),
        "deepgram": ("Deepgram", "https://api.deepgram.com/v1/projects",
                     "Authorization", "DEEPGRAM_API_KEY"),
        "assemblyai": ("AssemblyAI", "https://api.assemblyai.com/v2/subscription",
                       "x-api-key", "ASSEMBLYAI_API_KEY"),
        "sarvam": ("Sarvam AI", "https://api.sarvam.ai/health",
                   "api-key", "SARVAM_API_KEY"),
    }
    if provider in speech_map:
        label, url, hdr, env_key = speech_map[provider]
        key = env.get(env_key, "")
        if not key:
            checks.append((f"STT ({label})", False, "no API key in .env"))
        else:
            h = {hdr: key}
            if hdr == "Authorization":
                h = {"Authorization": f"Token {key}"}
            checks.append(probe(f"STT ({label})", url, h))

    # Stripe
    sk = env.get("STRIPE_SECRET_KEY", "")
    if sk:
        checks.append(probe("Stripe", "https://api.stripe.com/v1/balance",
                            {"Authorization": f"Bearer {sk}"}))

    safe_print("\n=== Credential preflight ===")
    failed = []
    for name, ok, detail in checks:
        flag = "OK  " if ok else "FAIL"
        safe_print(f"  [{flag}] {name}: {detail}")
        if not ok:
            failed.append((name, detail))
    safe_print("")

    if failed:
        safe_print("!! DEAD CREDENTIALS DETECTED — deploy aborted.")
        for name, detail in failed:
            safe_print(f"   - {name}: {detail}")
        safe_print("")
        safe_print("Fix these in .env, then re-run this script:")
        safe_print("  • Cloudflare  : https://dash.cloudflare.com/profile/api-tokens")
        safe_print("  • ElevenLabs : https://elevenlabs.io/app/settings/api-keys")
        safe_print("")
        safe_print("Use --force to deploy anyway (app will be up but processing will fail).")
        raise SystemExit(2)
    safe_print("All credentials valid.\n")

# ── Main ──────────────────────────────────────────────────────
def main():
    force = "--force" in os.sys.argv
    safe_print("=== IntelliForge → AWS Lightsail Deploy ===\n")
    env = load_env()
    validate_env(env)

    if force:
        safe_print("\n(--force set — skipping credential preflight)\n")
    else:
        preflight_credentials(env)

    # 1. Build archive
    safe_print("[1/6] Building code archive...")
    os.chdir(PROJECT_ROOT)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for item in os.listdir(PROJECT_ROOT):
            if item in {'.git', '__pycache__', '.venv', 'node_modules',
                        'data', 'instance', '.pytest_cache'}:
                continue
            full_path = os.path.join(PROJECT_ROOT, item)
            if os.path.isfile(full_path) or os.path.isdir(full_path):
                tar.add(full_path, arcname=item)
    archive_bytes = buffer.getvalue()
    safe_print(f"  Archive: {len(archive_bytes)/1024:.1f} KB")

    # 2. Connect
    safe_print("\n[2/6] Connecting via SSH key...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30,
                   look_for_keys=False, allow_agent=False)

    def run(cmd, timeout=300):
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out, err

    # 3. Install Docker + swap
    safe_print("\n[3/6] Installing Docker + swap...")
    out, _ = run("docker --version 2>&1", timeout=10)
    if "command not found" in out or "not found" in out:
        install = """
set -e
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg lsb-release
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker ubuntu
sudo systemctl enable docker
sudo systemctl start docker
docker --version
"""
        out, err = run(install, timeout=300)
        safe_print("  Docker:", out)
        if err:
            safe_print("  Warnings:", err[-300:])
    else:
        safe_print("  Docker already installed:", out)

    # Add swap if missing
    out, _ = run("swapon --show | wc -l", timeout=10)
    if out.strip() == "0":
        safe_print("  Adding 2GB swap...")
        swap_cmd = """
set -e
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
  echo "swap added"
else
  echo "swapfile exists"
fi
"""
        out, err = run(swap_cmd, timeout=120)
        safe_print("  Swap:", out)
    else:
        safe_print("  Swap already active")

    # 4. Upload code
    safe_print("\n[4/6] Uploading code...")
    run(f"sudo mkdir -p {REMOTE_DIR} && sudo chown -R ubuntu:ubuntu {REMOTE_DIR}")
    sftp = client.open_sftp()
    remote_archive = f"{REMOTE_DIR}/update.tar.gz"
    with sftp.file(remote_archive, "wb") as f:
        f.write(archive_bytes)
    sftp.close()
    safe_print("  Code uploaded.")

    # 5. Extract + Caddyfile + start
    safe_print("\n[5/6] Extracting and starting services...")
    domain = env["DOMAIN"]
    compose = "sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.lightsail.yml"
    cmd = f"""
cd {REMOTE_DIR}
tar -xzf update.tar.gz --overwrite
rm -f update.tar.gz

# Generate Caddyfile
cat > Caddyfile <<CADDYEOF
{domain} {{
    reverse_proxy web:5000
    encode gzip zstd
    header {{
        X-Frame-Options DENY
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }}
}}
CADDYEOF

echo "Caddyfile for domain: {domain}"
"""
    out, err = run(cmd, timeout=120)
    safe_print(out)
    if err:
        safe_print("Stderr:", err[-500:])

    # Build ONCE and reuse for all three services (they share the same context).
    # Building per-service triples the time, which is brutal on a 414MB instance.
    safe_print("  Building image (single build for all services)...")
    out, err = run(f"cd {REMOTE_DIR} && {compose} build web 2>&1 | tail -6", timeout=1200)
    safe_print(out[-800:])
    if err:
        safe_print("  Build warnings:", err[-400:])

    out, _ = run(f"sudo docker tag intelliforge-web:latest intelliforge-celery:latest && "
                  f"sudo docker tag intelliforge-web:latest intelliforge-celery-beat:latest && echo tagged")
    safe_print("  " + out)

    out, err = run(f"cd {REMOTE_DIR} && {compose} up -d --force-recreate --no-build 2>&1 | tail -10", timeout=300)
    safe_print(out[-800:])
    if err:
        safe_print("  Stderr:", err[-500:])

    # 6. Verify
    safe_print("\n[6/6] Verifying...")
    time.sleep(30)

    compose = "docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.lightsail.yml"

    out, _ = run(f"cd {REMOTE_DIR} && sudo {compose} ps")
    safe_print("\nContainer Status:\n" + out)
    out, _ = run("curl -s -m 20 -o /dev/null -w '%{http_code}' http://localhost:5000/health 2>&1 || echo fail")
    safe_print(f"\nHealth endpoint: {out}")

    # ── Crash-loop detection ────────────────────────────────────────────
    # A container can be "Up" while crash-looping (celery restarting on a
    # missing module looks fine in `ps` but never processes any jobs).
    safe_print("\nRestart counts (should all be 0):")
    out, _ = run("""
for c in intelliforge-web-1 intelliforge-celery-1 intelliforge-celery-beat-1 intelliforge-redis-1 intelliforge-caddy-1; do
  r=$(sudo docker inspect $c --format '{{.RestartCount}}' 2>/dev/null || echo "?")
  s=$(sudo docker inspect $c --format '{{.State.Status}}' 2>/dev/null || echo "?")
  echo "  $c: restarts=$r status=$s"
done
""")
    safe_print(out)

    safe_print("\nRecent container errors:")
    out, _ = run(f"cd {REMOTE_DIR} && sudo {compose} logs --tail=60 2>&1 | grep -iE 'ModuleNotFound|Traceback|CRITICAL|ERROR' | tail -12")
    safe_print(out if out else "  none")

    out, _ = run("free -h | head -2 && echo '--- swap ---' && swapon --show")
    safe_print(f"\nMemory:\n{out}")

    client.close()

    safe_print("\n=== Deploy Complete ===")
    safe_print(f"IP:   {HOST}")
    safe_print(f"URL:  https://{domain}")
    safe_print("\nACTION REQUIRED:")
    safe_print(f"1. Lightsail firewall: open TCP 80 + 443 (Networking → IPv4 firewall)")
    safe_print(f"2. DNS A record for {domain} → {HOST}")
    safe_print("3. Stripe webhook endpoint stays the same (no change needed)")

if __name__ == "__main__":
    main()