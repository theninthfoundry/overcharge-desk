"""Adversarial tests for API security, headers, lockout, and export boundaries."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from domain.identity.models import IdentityService, SystemRole
from services.api.main import app

client = TestClient(app)


def test_security_headers_present():
    """Verify production security headers are set on all responses."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    headers = res.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
    assert "X-Request-ID" in headers
    assert len(headers["X-Request-ID"]) > 0


def test_security_headers_on_404_response():
    """Verify security headers are still emitted on 404 Not Found responses."""
    res = client.get("/api/v1/non_existent_endpoint_xyz")
    assert res.status_code == 404
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in res.headers.get("Content-Security-Policy", "")
    assert "X-Request-ID" in res.headers



def test_login_brute_force_lockout():
    """Verify account is locked out after consecutive failed login attempts."""
    test_user = f"brute_{uuid.uuid4().hex[:8]}"
    for i in range(4):
        res = client.post(
            "/api/v1/auth/login",
            json={"username": test_user, "password": f"wrong_{i}"},
        )
        assert res.status_code == 401
        assert "Invalid username or password" in res.json()["detail"]

    # 5th attempt triggers lockout and returns 429 Too Many Requests
    blocked_res = client.post(
        "/api/v1/auth/login",
        json={"username": test_user, "password": "wrong_final"},
    )
    assert blocked_res.status_code == 429
    assert "temporarily locked" in blocked_res.json()["detail"]


def test_generic_auth_error_messages():
    """Authentication errors must never reveal whether username or password was invalid."""
    # Non-existent username
    res1 = client.post(
        "/api/v1/auth/login",
        json={"username": "non_existent_user_999", "password": "some_password"},
    )
    assert res1.status_code == 401
    detail1 = res1.json()["detail"]

    # Existing username with wrong password
    res2 = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong_password_xyz"},
    )
    assert res2.status_code == 401
    detail2 = res2.json()["detail"]

    # Both must return identical generic message
    assert detail1 == detail2 == "Invalid username or password"


def test_api_payment_instruction_lifecycle():
    """Test full payment instruction generation and export boundary via API."""
    import shutil
    from common import load_json, write_json_atomic

    identity_svc = IdentityService()
    pay_op_user = identity_svc.get_user_by_username("pay_operator")
    pay_token = identity_svc.issue_session_token(pay_op_user)
    headers = {"Authorization": f"Bearer {pay_token}"}

    case_id = f"test-pay-{uuid.uuid4().hex[:6]}"
    test_case_dir = Path("cases") / case_id
    src_dir = Path("cases") / "demo-overcharge"
    shutil.copytree(src_dir, test_case_dir)

    try:
        # Assign unique receipt_id
        receipt_p = test_case_dir / "approvals" / "approval_receipt.json"
        if receipt_p.exists():
            receipt_data = load_json(receipt_p)
            receipt_data["case_id"] = case_id
            receipt_data["receipt_id"] = f"AR-{case_id}-001"
            write_json_atomic(receipt_p, receipt_data)

        # 1. Create instruction
        res = client.post(
            f"/api/v1/cases/{case_id}/payment-instruction",
            json={"idempotency_key": f"IDEM-{case_id}"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["case_id"] == case_id
        assert data["vendor_id"] == "acme"
        assert data["status"] == "AUTHORIZED"
        instruction_id = data["instruction_id"]

        # 2. Export CSV
        export_res = client.get(
            f"/api/v1/cases/{case_id}/payment-instruction/{instruction_id}/export?format=csv",
            headers=headers,
        )
        assert export_res.status_code == 200
        assert "text/csv" in export_res.headers["content-type"]
        assert "instruction_id" in export_res.text

        # 3. Duplicate export attempt must fail (duplicate export prevention)
        dup_res = client.get(
            f"/api/v1/cases/{case_id}/payment-instruction/{instruction_id}/export?format=csv",
            headers=headers,
        )
        assert dup_res.status_code == 403
        assert "already been exported" in dup_res.json()["detail"]
    finally:
        shutil.rmtree(test_case_dir, ignore_errors=True)


def test_unauthorized_user_cannot_export_payment_instruction():
    """Reviewer or operator cannot export payment instruction."""
    identity_svc = IdentityService()
    reviewer_user = identity_svc.get_user_by_username("reviewer")
    rev_token = identity_svc.issue_session_token(reviewer_user)
    headers = {"Authorization": f"Bearer {rev_token}"}

    res = client.post(
        "/api/v1/cases/demo-overcharge/payment-instruction",
        json={},
        headers=headers,
    )
    assert res.status_code == 403
