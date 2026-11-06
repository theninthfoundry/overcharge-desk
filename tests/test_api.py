from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from domain.identity.models import IdentityService, SystemRole
from services.api.main import app

client = TestClient(app)


@pytest.fixture
def auth_tokens():
    identity_svc = IdentityService()
    tokens = {}
    for username, role in [
        ("admin", SystemRole.ADMINISTRATOR),
        ("operator", SystemRole.FINANCE_OPERATOR),
        ("reviewer", SystemRole.REVIEWER),
        ("approver", SystemRole.APPROVER),
        ("auditor", SystemRole.AUDITOR),
        ("pay_operator", SystemRole.PAYMENT_OPERATOR),
    ]:
        user = identity_svc.get_user_by_username(username)
        tokens[username] = identity_svc.issue_session_token(user)
    return tokens


def test_health_check():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "READY")
    assert data["version"] == "3.2.0"


def test_login_success():
    res = client.post("/api/v1/auth/login", json={"username": "approver", "password": "approver123"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["role"] == "APPROVER"
    assert "access_token" in data


def test_login_invalid_password():
    res = client.post("/api/v1/auth/login", json={"username": "approver", "password": "wrongpassword"})
    assert res.status_code == 401


def test_get_me(auth_tokens):
    headers = {"Authorization": f"Bearer {auth_tokens['approver']}"}
    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "approver"
    assert data["role"] == "APPROVER"
    assert "cases:approve" in data["permissions"]


def test_list_cases(auth_tokens):
    headers = {"Authorization": f"Bearer {auth_tokens['approver']}"}
    res = client.get("/api/v1/cases", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    case_ids = [c["case_id"] for c in data]
    # Check that benchmark cases exist
    assert any("demo-clean" in cid or "OC-20261001-01" in cid for cid in case_ids)


def test_get_case_detail(auth_tokens):
    headers = {"Authorization": f"Bearer {auth_tokens['approver']}"}
    res = client.get("/api/v1/cases/demo-overcharge", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == "OC-20261106-01" or data["case_id"] == "demo-overcharge"
    assert data["vendor_id"] == "acme"
    assert "verification_status" in data


def test_unauthenticated_request_blocked():
    res = client.get("/api/v1/cases")
    assert res.status_code == 401


def test_ledger_endpoints(auth_tokens):
    headers = {"Authorization": f"Bearer {auth_tokens['auditor']}"}
    res_evs = client.get("/api/v1/audit/ledger/events?limit=10", headers=headers)
    assert res_evs.status_code == 200
    assert isinstance(res_evs.json(), list)

    res_ver = client.get("/api/v1/audit/ledger/verify", headers=headers)
    assert res_ver.status_code == 200
    assert res_ver.json()["valid"] is True


def test_vendors_endpoint(auth_tokens):
    headers = {"Authorization": f"Bearer {auth_tokens['operator']}"}
    res = client.get("/api/v1/vendors", headers=headers)
    assert res.status_code == 200
    vendors = res.json()
    assert any(v["vendor_id"] == "acme" for v in vendors)


def test_serve_frontend():
    res = client.get("/")
    assert res.status_code == 200
    assert "Overcharge Desk" in res.text

    css_res = client.get("/styles.css")
    assert css_res.status_code == 200
    assert "body" in css_res.text or "font" in css_res.text

    js_res = client.get("/app.js")
    assert js_res.status_code == 200
    assert "STATE" in js_res.text

