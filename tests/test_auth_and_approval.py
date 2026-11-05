"""Adversarial and Authorization Tests for Overcharge Desk.

Tests actor authentication, role permissions, approval receipt generation,
cryptographic HMAC verification, and fail-closed approval gateway boundaries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest
from common import (CENT, STATE_BLOCKED, STATE_VERIFIED, ToolError,
                    canonical_json_bytes, q2, sha256_file, to_decimal)
from auth import (check_actor_permission, ensure_signing_key, get_actor,
                  issue_actor_token, load_actors_config, verify_actor_token)
from approval_receipt import (build_receipt_body, compute_receipt_hash,
                              sign_receipt, verify_approval_receipt)
from approval_gateway import process_approval_decision
from compare import compare
from pipeline import run_pipeline


@pytest.fixture
def signing_key(tmp_path):
    key_file = tmp_path / "test_signing.key"
    key_bytes = b"0123456789abcdef0123456789abcdef"
    key_file.write_bytes(key_bytes)
    return key_file, key_bytes


@pytest.fixture
def actors_config(tmp_path, signing_key):
    key_file, _ = signing_key
    cfg = {
        "config_version": "1.0.0",
        "signing_key_file": str(key_file),
        "token_validity_seconds": 300,
        "actors": [
            {
                "actor_id": "test_system",
                "display_name": "Test System",
                "role": "SYSTEM",
                "active": True,
                "permissions": ["register_evidence", "validate_invoice", "run_comparison", "generate_artifacts", "record_ledger"]
            },
            {
                "actor_id": "test_owner",
                "display_name": "Test Owner",
                "role": "APPROVER",
                "active": True,
                "permissions": ["view_cases", "approve_case", "reject_case", "view_approvals", "record_ledger"]
            },
            {
                "actor_id": "test_reviewer",
                "display_name": "Test Reviewer",
                "role": "REVIEWER",
                "active": True,
                "permissions": ["view_cases", "add_review_notes", "request_approval"]
            },
            {
                "actor_id": "disabled_user",
                "display_name": "Disabled User",
                "role": "APPROVER",
                "active": False,
                "permissions": ["approve_case"]
            }
        ]
    }
    cfg_file = tmp_path / "actors.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_file, cfg


# ---------------------------------------------------------------------------
# 1. Actor Authentication & Token Tests
# ---------------------------------------------------------------------------
def test_actor_token_generation_and_verification(signing_key, actors_config):
    _, key_bytes = signing_key
    _, cfg = actors_config

    token = issue_actor_token("test_owner", key_bytes, config=cfg)
    assert token.startswith("test_owner.")

    valid, reason, actor = verify_actor_token(token, key_bytes, config=cfg)
    assert valid is True
    assert reason == "Authenticated"
    assert actor["actor_id"] == "test_owner"
    assert actor["role"] == "APPROVER"


def test_expired_token_rejected_fail_closed(signing_key, actors_config):
    # Security Test: Verifies fail-closed rejection of stale/expired HMAC tokens
    _, key_bytes = signing_key
    _, cfg = actors_config

    # Token issued 400 seconds ago (TTL is 300)
    old_ts = int(time.time()) - 400
    token = issue_actor_token("test_owner", key_bytes, timestamp=old_ts, config=cfg)

    valid, reason, _ = verify_actor_token(token, key_bytes, max_age_seconds=300, config=cfg)
    assert valid is False
    assert "expired" in reason.lower()


def test_tampered_token_signature_rejected(signing_key, actors_config):
    _, key_bytes = signing_key
    _, cfg = actors_config

    token = issue_actor_token("test_owner", key_bytes, config=cfg)
    actor_id, ts, _ = token.split(".")
    tampered_sig = "a" * 64
    tampered_token = f"{actor_id}.{ts}.{tampered_sig}"

    valid, reason, _ = verify_actor_token(tampered_token, key_bytes, config=cfg)
    assert valid is False
    assert "mismatch" in reason.lower()


def test_unknown_actor_rejected(signing_key, actors_config):
    _, key_bytes = signing_key
    _, cfg = actors_config

    with pytest.raises(ToolError) as exc_info:
        issue_actor_token("intruder", key_bytes, config=cfg)
    assert "Unknown actor" in str(exc_info.value)


def test_disabled_actor_rejected(signing_key, actors_config):
    _, key_bytes = signing_key
    _, cfg = actors_config

    with pytest.raises(ToolError) as exc_info:
        issue_actor_token("disabled_user", key_bytes, config=cfg)
    assert "disabled/inactive" in str(exc_info.value)


def test_role_permissions_enforced(actors_config):
    _, cfg = actors_config

    assert check_actor_permission("test_owner", "approve_case", config=cfg) is True
    assert check_actor_permission("test_owner", "reject_case", config=cfg) is True
    assert check_actor_permission("test_reviewer", "approve_case", config=cfg) is False
    assert check_actor_permission("test_reviewer", "add_review_notes", config=cfg) is True
    assert check_actor_permission("test_system", "run_comparison", config=cfg) is True
    assert check_actor_permission("test_system", "approve_case", config=cfg) is False


# ---------------------------------------------------------------------------
# 2. Cryptographic Approval Receipts Tests
# ---------------------------------------------------------------------------
def test_valid_approval_receipt_lifecycle(signing_key):
    _, key_bytes = signing_key
    body = build_receipt_body(
        case_id="OC-20261106-01",
        invoice_number="INV-1103",
        invoice_sha256="22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6",
        contract_id="ACME-2026-01",
        compare_sha256="abcdef" * 10 + "1234",
        evidence_digest_set={"EV-1": "0123" * 16},
        actor_id="owner",
        actor_role="APPROVER",
        decision="APPROVED",
        approved_amount="60000.00",
        withheld_amount="6000.00",
        currency="INR",
    )

    signed = sign_receipt(body, key_bytes)
    assert "receipt_hash" in signed
    assert "receipt_signature" in signed
    assert len(signed["receipt_hash"]) == 64
    assert len(signed["receipt_signature"]) == 64

    valid, issues = verify_approval_receipt(signed, key_bytes, expected_case_id="OC-20261106-01")
    assert valid is True
    assert len(issues) == 0


def test_receipt_fails_if_amount_tampered(signing_key):
    _, key_bytes = signing_key
    body = build_receipt_body(
        case_id="OC-20261106-01",
        invoice_number="INV-1103",
        invoice_sha256="22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6",
        contract_id="ACME-2026-01",
        compare_sha256="abcdef" * 10 + "1234",
        evidence_digest_set={},
        actor_id="owner",
        actor_role="APPROVER",
        decision="APPROVED",
        approved_amount="60000.00",
        currency="INR",
    )
    signed = sign_receipt(body, key_bytes)

    # Maliciously modify amount after signing
    signed["approved_amount"] = "66000.00"

    valid, issues = verify_approval_receipt(signed, key_bytes)
    assert valid is False
    assert any("hash mismatch" in i.lower() for i in issues)


def test_receipt_fails_on_cross_case_binding(signing_key):
    _, key_bytes = signing_key
    body = build_receipt_body(
        case_id="OC-20261106-01",
        invoice_number="INV-1103",
        invoice_sha256="22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6",
        contract_id="ACME-2026-01",
        compare_sha256="abcdef" * 10 + "1234",
        evidence_digest_set={},
        actor_id="owner",
        actor_role="APPROVER",
        decision="APPROVED",
        approved_amount="60000.00",
        currency="INR",
    )
    signed = sign_receipt(body, key_bytes)

    # Attempting to use receipt for different case
    valid, issues = verify_approval_receipt(signed, key_bytes, expected_case_id="OC-20261106-02")
    assert valid is False
    assert any("Case ID mismatch" in i for i in issues)


def test_rejection_receipt_requires_reason(signing_key):
    _, key_bytes = signing_key
    with pytest.raises(ToolError) as exc_info:
        build_receipt_body(
            case_id="OC-20261106-01",
            invoice_number="INV-1103",
            invoice_sha256="22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6",
            contract_id="ACME-2026-01",
            compare_sha256="abcdef" * 10 + "1234",
            evidence_digest_set={},
            actor_id="owner",
            actor_role="APPROVER",
            decision="REJECTED",
            reason="",
        )
    assert "requires an explicit reason" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Authorization Gateway Tests
# ---------------------------------------------------------------------------
def test_gateway_approves_verified_case(tmp_path, signing_key, actors_config):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config

    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    case_dir = tmp_path / "case_verified"

    # Run pipeline first to generate comparison & evidence
    run_pipeline(inv_path, vendor_path, case_dir, ledger_db=tmp_path / "test.db")

    owner_token = issue_actor_token("test_owner", key_bytes, config=cfg)
    res = process_approval_decision(
        case_dir=case_dir,
        actor_token=owner_token,
        decision="APPROVED",
        amount="60000.00",
        key_file=key_file,
        config_file=cfg_file,
    )

    assert res["ok"] is True
    assert res["decision"] == "APPROVED"
    assert res["actor_id"] == "test_owner"
    assert res["approved_amount"] == "60000.00"
    assert res["withheld_amount"] == "6000.00"
    assert Path(res["receipt_file"]).exists()


def test_gateway_refuses_reviewer_approval(tmp_path, signing_key, actors_config):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config

    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    case_dir = tmp_path / "case_perm_test"
    run_pipeline(inv_path, vendor_path, case_dir, ledger_db=tmp_path / "test.db")

    # Reviewer does not have approve_case permission
    rev_token = issue_actor_token("test_reviewer", key_bytes, config=cfg)

    with pytest.raises(ToolError) as exc_info:
        process_approval_decision(
            case_dir=case_dir,
            actor_token=rev_token,
            decision="APPROVED",
            key_file=key_file,
            config_file=cfg_file,
        )
    assert exc_info.value.code == 4
    assert "lacks required permission" in str(exc_info.value)


def test_gateway_refuses_approval_of_blocked_audit(tmp_path, signing_key, actors_config, vendor, mk):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config
    make_invoice, carton, _ = mk

    # Arithmetic mismatch invoice
    inv = make_invoice([carton(500, "112.00", total="57000.00")])
    inv_file = tmp_path / "blocked_inv.json"
    ven_file = tmp_path / "vendor.json"
    inv_file.write_text(json.dumps(inv), encoding="utf-8")
    ven_file.write_text(json.dumps(vendor), encoding="utf-8")

    case_dir = tmp_path / "case_blocked"
    run_pipeline(inv_file, ven_file, case_dir, ledger_db=tmp_path / "test.db")

    owner_token = issue_actor_token("test_owner", key_bytes, config=cfg)

    # Must fail closed: cannot approve BLOCKED audit
    with pytest.raises(ToolError) as exc_info:
        process_approval_decision(
            case_dir=case_dir,
            actor_token=owner_token,
            decision="APPROVED",
            key_file=key_file,
            config_file=cfg_file,
        )
    assert exc_info.value.code == 4
    assert "Cannot approve BLOCKED audit" in str(exc_info.value)


def test_gateway_refuses_approval_with_incorrect_amount(tmp_path, signing_key, actors_config):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config

    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    case_dir = tmp_path / "case_amt_test"
    run_pipeline(inv_path, vendor_path, case_dir, ledger_db=tmp_path / "test.db")

    owner_token = issue_actor_token("test_owner", key_bytes, config=cfg)

    # Correct payable amount is 60000.00, user attempts to approve full 66000.00
    with pytest.raises(ToolError) as exc_info:
        process_approval_decision(
            case_dir=case_dir,
            actor_token=owner_token,
            decision="APPROVED",
            approved_amount="66000.00",
            key_file=key_file,
            config_file=cfg_file,
        )
    assert exc_info.value.code == 4
    assert "Approved amount mismatch" in str(exc_info.value)


def test_gateway_records_rejection_with_reason(tmp_path, signing_key, actors_config):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config

    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    case_dir = tmp_path / "case_rej_test"
    run_pipeline(inv_path, vendor_path, case_dir, ledger_db=tmp_path / "test.db")

    owner_token = issue_actor_token("test_owner", key_bytes, config=cfg)
    res = process_approval_decision(
        case_dir=case_dir,
        actor_token=owner_token,
        decision="REJECTED",
        reason="Rates renegotiated verbally with supplier; do not withhold",
        key_file=key_file,
        config_file=cfg_file,
    )

    assert res["ok"] is True
    assert res["decision"] == "REJECTED"
    receipt_data = json.loads(Path(res["receipt_file"]).read_text(encoding="utf-8"))
    assert receipt_data["decision"] == "REJECTED"
    assert "Rates renegotiated" in receipt_data["reason"]
