#!/usr/bin/env python3
"""Run a command on the AWS Lightsail VPS over SSH.

Usage:
    python scripts/remote_exec.py "sudo docker compose ps"
    python scripts/remote_exec.py "cd /opt/intelliforge && sudo docker compose logs --tail=50 celery"

Also supports piping a local Python file into the web container:
    python scripts/remote_exec.py --py scripts/seed_demo_users.py
"""
import paramiko
import os
import sys

HOST = os.environ.get("LIGHTSAIL_IP", "52.27.235.196")
USER = os.environ.get("LIGHTSAIL_USER", "ubuntu")
KEY_FILE = os.environ.get(
    "LIGHTSAIL_KEY",
    r"F:\Codes\PycharmProjects\tts\aws\lightsail.pem",
)
REMOTE_DIR = "/opt/intelliforge"
COMPOSE = ("sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml "
           "-f docker-compose.lightsail.yml")


def safe_print(*args):
    try:
        print(*args)
    except UnicodeEncodeError:
        s = " ".join(str(a) for a in args)
        print(s.encode("ascii", errors="replace").decode())


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY_FILE, timeout=30,
              look_for_keys=False, allow_agent=False)
    return c


def main():
    if len(sys.argv) < 2:
        safe_print(__doc__)
        raise SystemExit(1)

    client = connect()

    if sys.argv[1] == "--py":
        if len(sys.argv) < 3:
            safe_print("Need a path to a local .py file")
            raise SystemExit(1)
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            script = f.read()
        stdin, stdout, stderr = client.exec_command(
            f"cd {REMOTE_DIR} && {COMPOSE} exec -T web python -", timeout=600)
        stdin.write(script)
        stdin.channel.shutdown_write()
        safe_print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            safe_print("STDERR:", err[-800:])
    else:
        cmd = sys.argv[1]
        stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
        safe_print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err.strip():
            safe_print("STDERR:", err[-800:])

    client.close()


if __name__ == "__main__":
    main()
