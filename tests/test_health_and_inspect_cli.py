"""Tests for Health Check and Cryptographic Receipt Inspector CLI tools."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_health_check_cli_json():
    """Verify tools/health_check.py --json reports HEALTHY with all components."""
    cmd = [sys.executable, str(ROOT / "tools" / "health_check.py"), "--json"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"health check failed: {proc.stderr}"

    data = json.loads(proc.stdout)
    assert data.get("status") == "HEALTHY"
    checks = data.get("checks", {})
    assert checks.get("decimal_arithmetic", {}).get("status") == "PASS"
    assert checks.get("argon2id", {}).get("status") == "PASS"
    assert checks.get("case_storage", {}).get("status") == "PASS"
    assert checks.get("ledger_chain", {}).get("status") == "PASS"


def test_inspect_receipt_cli_valid():
    """Verify tools/inspect_receipt.py correctly verifies demo-overcharge receipt."""
    cmd = [sys.executable, str(ROOT / "tools" / "inspect_receipt.py"), "OC-20261106-01", "--json"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"inspect receipt failed: {proc.stderr}"

    data = json.loads(proc.stdout)
    assert data.get("status") == "VALID"
    assert data.get("case_id") == "OC-20261106-01"
    assert data.get("decision") == "APPROVED"
    assert data.get("approved_amount") == "60000.00"
    assert data.get("hashes", {}).get("signature") is not None
    assert len(data.get("issues", [])) == 0


def test_inspect_receipt_cli_missing_target():
    """Verify tools/inspect_receipt.py exits 1 on non-existent case or path."""
    cmd = [sys.executable, str(ROOT / "tools" / "inspect_receipt.py"), "non_existent_case_999", "--json"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data.get("status") == "ERROR"
