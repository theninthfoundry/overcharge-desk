"""Tests for Seed & Demo State Manager CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_seed_demo_check_cli():
    """Verify tools/seed_demo.py --check reports PASS on repository seeds."""
    cmd = [sys.executable, str(ROOT / "tools" / "seed_demo.py"), "--check", "--json"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"seed check failed: {proc.stderr}"

    data = json.loads(proc.stdout)
    assert data.get("status") == "PASS"
    checks = data.get("checks", {})
    assert checks.get("seed_exists", {}).get("status") == "PASS"
    assert checks.get("rates", {}).get("status") == "PASS"
    assert checks.get("rates", {}).get("sku_count", 0) >= 2

