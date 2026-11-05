from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient

from domain.authorization.policies import AuthorizationService, PERM_CASE_APPROVE
from domain.identity.models import IdentityService, SystemRole, User
from services.api.main import app

client = TestClient(app)


@pytest.fixture
def identity_service():
    return IdentityService()


@pytest.fixture
def auth_service():
    return AuthorizationService(enforce_strict_separation_of_duties=True)


def test_rbac_permissions_mapping(auth_service, identity_service):
    admin = identity_service.get_user_by_username("admin")
    operator = identity_service.get_user_by_username("operator")
    reviewer = identity_service.get_user_by_username("reviewer")
    approver = identity_service.get_user_by_username("approver")
    auditor = identity_service.get_user_by_username("auditor")
    pay_operator = identity_service.get_user_by_username("pay_operator")

    # Approver has approval authority; operator & auditor do not
    assert auth_service.has_permission(approver, PERM_CASE_APPROVE) is True
    assert auth_service.has_permission(operator, PERM_CASE_APPROVE) is False
    assert auth_service.has_permission(auditor, PERM_CASE_APPROVE) is False
    assert auth_service.has_permission(reviewer, PERM_CASE_APPROVE) is False
    assert auth_service.has_permission(pay_operator, PERM_CASE_APPROVE) is False
    assert auth_service.has_permission(admin, PERM_CASE_APPROVE) is True


def test_separation_of_duties_prevents_self_approval(auth_service, identity_service):
    approver = identity_service.get_user_by_username("approver")

    # Case created by another user: permitted
    ok, msg = auth_service.evaluate_approval_policy(
        approver=approver,
        case_creator_username="operator",
        verification_status="VERIFIED",
    )
    assert ok is True
    assert "Approval authorized" in msg

    # Case created by the approver themselves: strictly forbidden by separation of duties
    ok_self, err_self = auth_service.evaluate_approval_policy(
        approver=approver,
        case_creator_username="approver",
        verification_status="VERIFIED",
    )
    assert ok_self is False
    assert "Separation of duties violation" in err_self


def test_approval_policy_enforces_positive_allowlist(auth_service, identity_service):
    approver = identity_service.get_user_by_username("approver")

    # Case in BLOCKED or REVIEW_REQUIRED cannot be approved
    ok_blk, err_blk = auth_service.evaluate_approval_policy(
        approver=approver,
        case_creator_username="operator",
        verification_status="BLOCKED",
    )
    assert ok_blk is False
    assert "Strict allowlist violation" in err_blk

    ok_rev, err_rev = auth_service.evaluate_approval_policy(
        approver=approver,
        case_creator_username="operator",
        verification_status="REVIEW_REQUIRED",
    )
    assert ok_rev is False
    assert "Strict allowlist violation" in err_rev


def test_api_enforces_rbac_on_endpoints(identity_service):
    auditor = identity_service.get_user_by_username("auditor")
    auditor_token = identity_service.issue_session_token(auditor)

    # Auditor attempting to create a case must receive 403 Forbidden
    headers = {"Authorization": f"Bearer {auditor_token}"}
    res = client.post(
        "/api/v1/cases",
        headers=headers,
        json={"case_id": "OC-TEST-FORBIDDEN", "vendor_id": "acme", "invoice_json": {}},
    )
    assert res.status_code == 403
    assert "Requires 'cases:create'" in res.json()["detail"]


def test_token_expiration_and_tampering(identity_service):
    user = identity_service.get_user_by_username("approver")
    token = identity_service.issue_session_token(user)

    # Valid token passes
    assert identity_service.verify_session_token(token) is not None

    # Tampered signature fails
    tampered_sig = token[:-4] + "0000"
    assert identity_service.verify_session_token(tampered_sig) is None

    # Tampered / forged token fails
    forged_token = "admin:ADMINISTRATOR:fake_token_value_that_is_not_in_db"
    assert identity_service.verify_session_token(forged_token) is None

    # Revoked token fails
    identity_service.revoke_token(token)
    assert identity_service.verify_session_token(token) is None

