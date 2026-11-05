"""Tests for Interactive Terminal Owner Approval CLI (tools/approve.py) & Auth Lockdown."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from common import ToolError, load_json
from tools.approve import approve_case_cli

ROOT = Path(__file__).resolve().parent.parent


def test_approve_non_tty_refusal():
    """Verify that approve.py immediately refuses to execute without an interactive TTY."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "approve.py"), "demo-overcharge"],
        stdin=subprocess.PIPE,
        capture_output=True,
        text=True,
    )
    # When piped / non-TTY, exit code must be non-zero (code 4 or 1 via ToolError)
    assert res.returncode != 0
    assert "Human approval requires an interactive TTY session" in (res.stdout + res.stderr)


def test_auth_issue_token_without_dev_fails():
    """Verify that tools/auth.py issue-token fails closed without explicit --dev flag."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "auth.py"), "issue-token", "owner"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "CLI token minting is disabled in production" in (res.stdout + res.stderr)


def test_approve_invalid_password_refusal():
    """Verify that incorrect approver credentials fail closed."""
    with pytest.raises(ToolError, match="Authentication failed: Invalid credentials"):
        approve_case_cli(
            case_arg="demo-overcharge",
            username="owner",
            force_tty=True,
            password_input="wrong-password-999",
        )


def test_approve_unauthorized_role_refusal():
    """Verify that users without APPROVER or ADMINISTRATOR role cannot approve."""
    # 'reviewer' has role REVIEWER
    with pytest.raises(ToolError, match="lacks approval permissions"):
        approve_case_cli(
            case_arg="demo-overcharge",
            username="reviewer",
            force_tty=True,
            password_input="reviewer123",
        )


def test_approve_blocked_case_refusal():
    """Verify that an arithmetic discrepancy or blocked case cannot be approved."""
    with pytest.raises(ToolError, match="Only 'VERIFIED' cases may be approved"):
        approve_case_cli(
            case_arg="demo-blocked",
            username="owner",
            force_tty=True,
            password_input="owner123",
        )


def test_approve_success_produces_64_char_hash():
    """Verify that valid owner approval produces exact amounts and full 64-char receipt hash."""
    res = approve_case_cli(
        case_arg="demo-overcharge",
        username="owner",
        decision="APPROVED",
        force_tty=True,
        password_input="owner123",
    )
    assert res["ok"] is True
    assert res["case_id"] == "OC-20261106-01"
    assert res["decision"] == "APPROVED"
    assert res["authenticated_actor"] == "owner"
    assert res["approved_amount"] == "60000.00"
    assert res["withheld_amount"] == "6000.00"
    assert len(res["receipt_hash"]) == 64
    assert "Switch Room Notification" in res.get("switch_notification", "") or "Human approval recorded" in res.get("switch_notification", "")

