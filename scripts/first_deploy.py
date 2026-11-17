#!/usr/bin/env python3
"""First-time deploy to the current production VPS (AWS Lightsail).

Kept for backwards compatibility — the real implementation lives in
scripts/lightsail_deploy.py, which already handles Docker installation,
swap setup, key-based auth, and a fresh-instance bootstrap.
"""
import os
import sys
import runpy

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightsail_deploy.py")

if __name__ == "__main__":
    sys.argv[0] = TARGET
    runpy.run_path(TARGET, run_name="__main__")
