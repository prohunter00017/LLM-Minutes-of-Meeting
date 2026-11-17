#!/usr/bin/env python3
"""Full redeploy to the current production VPS (AWS Lightsail).

Kept for backwards compatibility — the real implementation lives in
scripts/lightsail_deploy.py. Use that directly for new work.

Usage:
    python scripts/full_redeploy.py            # normal deploy (credential preflight)
    python scripts/full_redeploy.py --force    # skip preflight
"""
import os
import sys
import runpy

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightsail_deploy.py")

if __name__ == "__main__":
    sys.argv[0] = TARGET
    runpy.run_path(TARGET, run_name="__main__")
