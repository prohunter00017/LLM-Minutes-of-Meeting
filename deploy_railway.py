#!/usr/bin/env python3
"""Deploy IntelliForge to Railway.

Reads .env, provisions a project (Redis + app service + volumes), sets
environment variables, and deploys. Idempotent — reuses existing resources.

Usage:
    python deploy_railway.py
"""
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")


def resolve_railway_bin():
    """Locate the real railway.exe (npm installs a .ps1/.cmd shim)."""
    candidates = [
        os.environ.get("RAILWAY_BIN"),
        os.path.join(os.environ.get("APPDATA", ""), "npm",
                     "node_modules", "@railway", "cli", "bin", "railway.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache", "_npx",
                     "node_modules", "@railway", "cli", "bin", "railway.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Fall back to PATH resolution for .exe / .com only
    import shutil
    found = shutil.which("railway.exe")
    if found:
        return found
    return "railway"


RAILWAY_BIN = resolve_railway_bin()

PROJECT_NAME = "intelliforge"
SERVICE_NAME = "intelliforge"
ENV_NAME = "production"

# .env keys that are NOT app runtime variables
SKIP_KEYS = {"APP_PORT", "RAILWAY_TOKEN", "RAILWAY_API_TOKEN"}

# Keys whose value comes from the managed Redis service, not .env
REDIS_OVERRIDES = {
    "CELERY_BROKER_URL": None,  # set to ${{<redis>.REDIS_URL}}
    "CELERY_RESULT_BACKEND": None,
}


def log(msg):
    print(f"[deploy] {msg}", flush=True)


def load_env(path):
    env = {}
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def run(cmd, *, check=False, show=True, input_data=None):
    cmd = [RAILWAY_BIN] + [str(c) for c in cmd]
    if show:
        log("$ railway " + " ".join(str(c) for c in cmd[1:]))
        if input_data:
            log(f"      (stdin) {input_data}")
    p = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        input=input_data,
        capture_output=True,
        text=True,
    )
    if show:
        if p.stdout.strip():
            for line in p.stdout.strip().splitlines():
                print(f"      {line}", flush=True)
        if p.stderr.strip():
            for line in p.stderr.strip().splitlines():
                print(f"      [err] {line}", flush=True)
    if check and p.returncode != 0:
        log(f"! command failed (exit {p.returncode}): {' '.join(cmd)}")
        sys.exit(p.returncode)
    return p


def run_json(cmd, *, check=True):
    p = run(cmd, check=check, show=True)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except json.JSONDecodeError:
        return None


def find_project():
    p = run_json([ "project", "list", "--json"])
    if p:
        for proj in p:
            if proj.get("name") == PROJECT_NAME:
                return proj
    return None


def find_service(name):
    p = run_json([ "service", "list", "--json"])
    if p:
        for svc in p:
            if svc.get("name") == name:
                return svc
    return None


def main():
    env = load_env(ENV_PATH)
    log(f"Loaded {len(env)} vars from .env")

    # ── 1. Auth check ─────────────────────────────────────────────
    who = run_json([ "whoami", "--json"], check=True)
    log(f"Authed as: {who.get('email') or who.get('name') or 'OK'}")

    # ── 2. Project ────────────────────────────────────────────────
    proj = find_project()
    if proj:
        log(f"Project '{PROJECT_NAME}' exists ({proj.get('id')}) — linking")
        run([ "link", "--project", PROJECT_NAME], check=True)
    else:
        log(f"Creating project '{PROJECT_NAME}'")
        run([ "init", "--name", PROJECT_NAME], check=True)

    # ── 3. Redis database ─────────────────────────────────────────
    redis_name = None
    svc = find_service("Redis") or find_service("redis")
    if svc:
        redis_name = svc.get("name")
        log(f"Redis service exists: {redis_name}")
    else:
        log("Creating Redis database")
        out = run_json([ "add", "--database", "redis", "--json"], check=True)
        redis_name = (out or {}).get("serviceName") or "Redis"
        log(f"Redis created: {redis_name}")

    redis_url_ref = f"${{{{{redis_name}.REDIS_URL}}}}"

    # ── 4. App service ────────────────────────────────────────────
    svc = find_service(SERVICE_NAME)
    if svc:
        service_id = svc.get("id")
        log(f"Service '{SERVICE_NAME}' exists ({service_id})")
    else:
        log(f"Creating app service '{SERVICE_NAME}'")
        out = run_json([ "add", "--service", SERVICE_NAME, "--json"], check=True)
        service_id = (out or {}).get("id")
        log(f"Service created: id={service_id}")

    # ── 5. Service build/deploy config (JSON patch via stdin) ─────
    log("Configuring builder + start command")
    patch = {
        "services": {
            service_id: {
                "build": {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"},
                "deploy": {"startCommand": "bash start.sh"},
            }
        }
    }
    run([ "environment", "edit", "--environment", ENV_NAME, "--json"],
        check=True, input_data=json.dumps(patch))

    # ── 6. Volume (SQLite db + uploads share one volume) ──────────
    vol_resp = run_json([ "volume", "list", "--json"]) or {}
    vol_list = vol_resp.get("volumes", []) if isinstance(vol_resp, dict) else vol_resp
    mounted = {v.get("mountPath") for v in vol_list if isinstance(v, dict)}

    # SQLite lives at /app/instance/app.db; uploads go to /app/instance/uploads
    # (UPLOAD_FOLDER is overridden below so both persist on one volume).
    for mount in ("/app/instance",):
        if mount in mounted:
            log(f"Volume at {mount} exists")
        else:
            log(f"Adding volume at {mount}")
            run([ "volume", "add",
                 "--mount-path", mount, "--json"], check=True)

    # ── 7. Environment variables ──────────────────────────────────
    vars_to_set = {}
    for k, v in env.items():
        if k in SKIP_KEYS:
            continue
        if not v:
            continue
        vars_to_set[k] = v

    # Override Celery broker/backend with managed Redis
    for k in REDIS_OVERRIDES:
        vars_to_set[k] = redis_url_ref

    # Store uploads inside the mounted volume so they persist alongside SQLite
    vars_to_set["UPLOAD_FOLDER"] = "/app/instance/uploads"

    # Run as root so Railway volumes (mounted as root) are writable
    vars_to_set["RAILWAY_RUN_UID"] = "0"

    log(f"Setting {len(vars_to_set)} environment variables")
    args = []
    for k, v in vars_to_set.items():
        args.append(f"{k}={v}")

    # Batch via one `variable set` call
    cmd = ["variable", "set"] + args + ["--service", SERVICE_NAME]
    run(cmd, check=True)

    # ── 8. Deploy ─────────────────────────────────────────────────
    log("Deploying (detached)...")
    run([ "up", "--service", SERVICE_NAME,
         "--environment", ENV_NAME, "--detach",
         "-m", "IntelliForge initial Railway deploy"], check=True)

    # ── 9. Poll for terminal deploy status ────────────────────────
    log("Polling deployment status...")
    deadline = time.time() + 900  # 15 min
    status = None
    while time.time() < deadline:
        deps = run_json([ "deployment", "list",
                         "--service", SERVICE_NAME,
                         "--environment", ENV_NAME, "--json"], check=False)
        if deps:
            status = (deps[0].get("status") or "").upper()
            log(f"  status: {status}")
            if status in ("SUCCESS", "FAILED", "CRASHED", "REMOVED", "SLEEPING",
                          "NEEDS_APPROVAL", "SKIPPED"):
                break
        time.sleep(15)

    if status == "SUCCESS":
        log("DEPLOY SUCCEEDED")
    else:
        log(f"! deploy ended with status={status or 'unknown'}")
        run([ "logs", "--service", SERVICE_NAME, "--lines", "60"],
            check=False)
        sys.exit(1)

    # ── 10. Public domain ─────────────────────────────────────────
    log("Generating Railway public domain...")
    dom = run_json([ "domain", "--service", SERVICE_NAME, "--json"],
                   check=False)
    url = None
    if dom:
        url = dom.get("domain") or (dom[0].get("domain") if isinstance(dom, list) else None)
    if url and not url.startswith("http"):
        url = "https://" + url

    log("=== Deploy complete ===")
    log(f"App URL: {url}" if url else "App URL: see Railway dashboard")
    log("")
    log("Next steps for custom domain (intelliforgesystems.com):")
    log("  railway domain intelliforgesystems.com --service " + SERVICE_NAME)
    log("  then add the DNS records Railway returns (CNAME -> *.up.railway.app)")


if __name__ == "__main__":
    main()