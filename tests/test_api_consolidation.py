"""Integration test suite for consolidated FastAPI backend routers."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from domain.identity.models import IdentityService
from services.api.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def admin_token():
    """Obtain a valid admin JWT bearer token."""
    identity_svc = IdentityService()
    user = identity_svc.get_user_by_username("admin")
    return identity_svc.issue_session_token(user)


def test_system_health_endpoint():
    """Verify /api/v1/system/health operational status."""
    resp = client.get("/api/v1/system/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "overcharge-desk-api"
    assert "checks" in data


def test_overview_metrics(admin_token):
    """Verify financial control metrics."""
    resp = client.get(
        "/api/v1/overview/metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "financial_position" in data
    assert "case_counts" in data
    assert "audit_integrity" in data


def test_case_workspace_endpoint(admin_token):
    """Verify case workspace endpoint."""
    resp = client.get(
        "/api/v1/cases/demo-overcharge/workspace",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert "case_id" in data
        assert "detail" in data
        assert "comparison" in data


def test_contracts_endpoint(admin_token):
    """Verify contracts directory endpoint."""
    resp = client.get(
        "/api/v1/contracts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_evidence_global_endpoint(admin_token):
    """Verify global evidence inventory endpoint."""
    resp = client.get(
        "/api/v1/evidence",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_registered" in data
    assert "verified_count" in data


def test_approvals_queue_endpoint(admin_token):
    """Verify approvals queue and receipts endpoint."""
    resp = client.get(
        "/api/v1/approvals",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "pending_queue" in data
    assert "decided_receipts" in data


def test_payments_overview_endpoint(admin_token):
    """Verify payments control endpoint."""
    resp = client.get(
        "/api/v1/payments",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "instructions" in data
    assert "metrics" in data
    assert "approved_cases" in data


def test_ledger_checkpoints_endpoint(admin_token):
    """Verify ledger checkpoints endpoint."""
    resp = client.get(
        "/api/v1/audit/ledger/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_integrations_endpoint(admin_token):
    """Verify integrations status endpoint."""
    resp = client.get(
        "/api/v1/integrations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "integrations" in data
    assert "agents" in data


def test_settings_users_endpoint(admin_token):
    """Verify settings users list endpoint."""
    resp = client.get(
        "/api/v1/settings/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert "roles" in data
