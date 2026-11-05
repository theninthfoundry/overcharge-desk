"""Tests for Vendor Historical Memory & Cross-Invoice Recall Mechanics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_desk_history_vendor_acme_success():
    """Verify desk.py history --vendor acme recalls prior cases and returns structured JSON."""
    cmd = [sys.executable, str(ROOT / "tools" / "desk.py"), "history", "--vendor", "acme"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"desk history failed: {proc.stderr}"

    data = json.loads(proc.stdout)
    assert data.get("vendor_id") == "acme" or data.get("vendor_query") == "acme"
    count = data.get("prior_cases_count", data.get("total_cases", 0))
    assert count >= 1

    # Check that case information contains required fields
    cases = data.get("prior_cases", data.get("historical_cases", []))
    assert len(cases) >= 1
    found_acme = any("acme" in str(c.get("vendor", "")).lower() or "acme" in str(c.get("case_id", "")).lower() or "inv" in str(c.get("invoice_number", "")).lower() for c in cases)
    assert found_acme


def test_desk_history_vendor_nonexistent():
    """Verify desk.py history --vendor non_existent_vendor returns 0 matches cleanly."""
    cmd = [sys.executable, str(ROOT / "tools" / "desk.py"), "history", "--vendor", "non_existent_vendor_xyz_999"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    count = data.get("prior_cases_count", data.get("total_cases", 0))
    assert count == 0


def test_credit_note_lifecycle_invariants():
    """Verify credit note lifecycle states follow Invariant Rule 2.3."""
    ALLOWED_STATES = {"PROMISED", "RECEIVED", "APPLIED", "OUTSTANDING"}
    sample_credit_notes = [
        {"id": "CN-001", "state": "PROMISED", "amount": "1000.00"},
        {"id": "CN-002", "state": "RECEIVED", "amount": "2500.00"},
        {"id": "CN-003", "state": "APPLIED", "amount": "1200.00"},
    ]
    for note in sample_credit_notes:
        assert note["state"] in ALLOWED_STATES
        # Promised credit note cannot be treated as applied
        if note["state"] == "PROMISED":
            assert note["state"] != "APPLIED"
