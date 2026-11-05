"""Case Manager and Evidence Registry Tests for Overcharge Desk.

Tests standardized case directory layout, lifecycle state transitions,
evidence registration, cryptographic fingerprinting, and tamper detection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from common import ToolError, sha256_file
from case_manager import (CASE_STATE_APPROVAL_PENDING, CASE_STATE_APPROVED,
                          CASE_STATE_BLOCKED, CASE_STATE_CLOSED,
                          CASE_STATE_COMPARED, CASE_STATE_CREATED,
                          CASE_STATE_INTAKE_VERIFIED,
                          CASE_STATE_PAYMENT_GENERATED,
                          CASE_STATE_REVIEW_REQUIRED, CASE_STATE_VERIFIED,
                          init_case, load_case, transition_case_state)
from evidence import (get_evidence, get_evidence_digest_map, list_evidence,
                      load_registry, register_evidence, verify_evidence)


# ---------------------------------------------------------------------------
# 1. Case Lifecycle & Structure Tests
# ---------------------------------------------------------------------------
def test_case_initialization_structure(tmp_path):
    cases_dir = tmp_path / "cases"
    case_id = "OC-20261106-01"

    meta = init_case(case_id, cases_dir=cases_dir, vendor_id="acme", invoice_number="INV-1103")
    assert meta["case_id"] == case_id
    assert meta["status"] == CASE_STATE_CREATED

    c_dir = cases_dir / case_id
    assert (c_dir / "case.json").exists()
    assert (c_dir / "source").is_dir()
    assert (c_dir / "normalized").is_dir()
    assert (c_dir / "comparison").is_dir()
    assert (c_dir / "artifacts").is_dir()
    assert (c_dir / "approvals").is_dir()
    assert (c_dir / "audit").is_dir()


def test_duplicate_case_init_refused(tmp_path):
    cases_dir = tmp_path / "cases"
    case_id = "OC-20261106-01"
    init_case(case_id, cases_dir=cases_dir)

    with pytest.raises(ToolError) as exc_info:
        init_case(case_id, cases_dir=cases_dir)
    assert exc_info.value.code == 4
    assert "already exists" in str(exc_info.value)


def test_valid_state_transitions(tmp_path):
    cases_dir = tmp_path / "cases"
    case_id = "OC-20261106-01"
    init_case(case_id, cases_dir=cases_dir)

    # CREATED -> INTAKE_VERIFIED -> VERIFIED -> APPROVAL_PENDING -> APPROVED -> PAYMENT_GENERATED -> CLOSED
    transition_case_state(case_id, CASE_STATE_INTAKE_VERIFIED, cases_dir=cases_dir)
    transition_case_state(case_id, CASE_STATE_VERIFIED, cases_dir=cases_dir)
    transition_case_state(case_id, CASE_STATE_APPROVAL_PENDING, cases_dir=cases_dir)
    transition_case_state(case_id, CASE_STATE_APPROVED, cases_dir=cases_dir)
    transition_case_state(case_id, CASE_STATE_PAYMENT_GENERATED, cases_dir=cases_dir)
    meta = transition_case_state(case_id, CASE_STATE_CLOSED, cases_dir=cases_dir)

    assert meta["status"] == CASE_STATE_CLOSED
    assert len(meta["history"]) == 7


def test_invalid_state_transitions_refused(tmp_path):
    cases_dir = tmp_path / "cases"
    case_id = "OC-20261106-01"
    init_case(case_id, cases_dir=cases_dir)

    # Cannot jump straight from CREATED to APPROVED
    with pytest.raises(ToolError) as exc_info:
        transition_case_state(case_id, CASE_STATE_APPROVED, cases_dir=cases_dir)
    assert exc_info.value.code == 4
    assert "Illegal state transition" in str(exc_info.value)

    # Cannot transition out of terminal CLOSED state
    transition_case_state(case_id, CASE_STATE_BLOCKED, cases_dir=cases_dir)
    transition_case_state(case_id, CASE_STATE_CLOSED, cases_dir=cases_dir)

    with pytest.raises(ToolError) as exc_info2:
        transition_case_state(case_id, CASE_STATE_CREATED, cases_dir=cases_dir)
    assert exc_info2.value.code == 4


# ---------------------------------------------------------------------------
# 2. Evidence Registry Tests
# ---------------------------------------------------------------------------
def test_evidence_registration_and_verification(tmp_path):
    case_dir = tmp_path / "case_01"
    case_dir.mkdir(parents=True)

    dummy_file = tmp_path / "invoice.txt"
    dummy_file.write_text("Raw Invoice Payload 12345", encoding="utf-8")
    expected_hash = sha256_file(str(dummy_file))

    rec = register_evidence(
        case_dir=case_dir,
        file_path=dummy_file,
        evidence_type="source_invoice",
        case_id="OC-20261106-01",
    )

    assert rec["evidence_id"] == "EV-OC-20261106-01-001"
    assert rec["content_hash"] == expected_hash
    assert rec["hash_algorithm"] == "SHA-256"
    assert rec["validation_status"] == "VERIFIED"

    # Re-verify on disk
    res = verify_evidence(case_dir)
    assert res["ok"] is True
    assert res["verified_count"] == 1
    assert res["failed_count"] == 0


def test_evidence_verification_detects_tampered_file(tmp_path):
    case_dir = tmp_path / "case_02"
    case_dir.mkdir(parents=True)

    dummy_file = case_dir / "invoice.txt"
    dummy_file.write_text("Authentic Text", encoding="utf-8")

    register_evidence(
        case_dir=case_dir,
        file_path=dummy_file,
        evidence_type="source_invoice",
        case_id="OC-20261106-02",
    )

    # Maliciously modify the file on disk
    dummy_file.write_text("Tampered Text by Attacker", encoding="utf-8")

    res = verify_evidence(case_dir)
    assert res["ok"] is False
    assert res["failed_count"] == 1
    assert any(f["evidence_id"] == "EV-OC-20261106-02-001" for f in res["failures"])


def test_evidence_verification_detects_missing_file(tmp_path):
    case_dir = tmp_path / "case_03"
    case_dir.mkdir(parents=True)

    dummy_file = case_dir / "artifact.csv"
    dummy_file.write_text("line,total", encoding="utf-8")

    register_evidence(
        case_dir=case_dir,
        file_path=dummy_file,
        evidence_type="payment_artifact",
        case_id="OC-20261106-03",
    )

    # Delete file
    dummy_file.unlink()

    res = verify_evidence(case_dir)
    assert res["ok"] is False
    assert res["failed_count"] == 1
    assert any("not found" in f["error"].lower() for f in res["failures"])


def test_evidence_digest_map(tmp_path):
    case_dir = tmp_path / "case_04"
    case_dir.mkdir(parents=True)

    f1 = case_dir / "f1.txt"
    f2 = case_dir / "f2.txt"
    f1.write_text("file 1", encoding="utf-8")
    f2.write_text("file 2", encoding="utf-8")

    register_evidence(case_dir, f1, "source_invoice", case_id="OC-20261106-04")
    register_evidence(case_dir, f2, "comparison_result", case_id="OC-20261106-04")

    digests = get_evidence_digest_map(case_dir)
    assert len(digests) == 2
    assert "EV-OC-20261106-04-001" in digests
    assert "EV-OC-20261106-04-002" in digests
