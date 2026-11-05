"""Pipeline Orchestration and Execution Manifest Tests.

Tests the upgraded pipeline's execution manifest generation, artifact digest tracking,
evidence registry population, SQLite ledger integration, and approval enforcement.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from common import STATE_VERIFIED, ToolError
from auth import issue_actor_token
from approval_gateway import process_approval_decision
from audit_ledger import list_events, verify_ledger
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
                "actor_id": "test_owner",
                "display_name": "Test Owner",
                "role": "APPROVER",
                "active": True,
                "permissions": ["approve_case", "reject_case"]
            }
        ]
    }
    cfg_file = tmp_path / "actors.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_file, cfg


def test_pipeline_generates_execution_manifest_and_evidence(tmp_path):
    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    out_dir = tmp_path / "pipeline_run"
    db_path = tmp_path / "audit.db"

    res = run_pipeline(inv_path, vendor_path, out_dir, ledger_db=db_path)
    assert res["ok"] is True
    assert res["execution_id"].startswith("EXEC-")

    # Check manifest.json
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["execution_id"] == res["execution_id"]
    assert manifest["verification_status"] == STATE_VERIFIED
    assert "stage_results" in manifest
    assert "artifact_references" in manifest
    assert "artifact_hashes" in manifest

    # Check evidence registry
    assert (out_p := out_dir / "evidence_registry.json").exists()
    registry = json.loads(out_p.read_text(encoding="utf-8"))
    assert len(registry["evidence"]) >= 2

    # Check SQLite ledger
    events = list_events(db_path=db_path)
    assert len(events) >= 3
    valid, issues = verify_ledger(db_path)
    assert valid is True
    assert len(issues) == 0


def test_pipeline_refuses_payment_without_approval_when_required(tmp_path):
    # Orchestration Test: Verifies refusal of payment sheet when required approval is missing
    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    out_dir = tmp_path / "pipeline_no_app"
    db_path = tmp_path / "audit.db"

    # require_approval=True with no receipt
    with pytest.raises(ToolError) as exc_info:
        run_pipeline(inv_path, vendor_path, out_dir, require_approval=True, ledger_db=db_path)
    assert exc_info.value.code == 4
    assert "requires an authorized human approval receipt" in str(exc_info.value)


def test_pipeline_succeeds_with_valid_approval_receipt(tmp_path, signing_key, actors_config):
    key_file, key_bytes = signing_key
    cfg_file, cfg = actors_config

    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    case_dir = tmp_path / "case_end_to_end"
    db_path = tmp_path / "audit.db"

    # 1. Run pipeline in analysis mode
    run_pipeline(inv_path, vendor_path, case_dir, ledger_db=db_path)

    # 2. Owner approves via gateway
    owner_token = issue_actor_token("test_owner", key_bytes, config=cfg)
    app_res = process_approval_decision(
        case_dir=case_dir,
        actor_token=owner_token,
        decision="APPROVED",
        amount="60000.00",
        key_file=key_file,
        config_file=cfg_file,
    )
    receipt_path = Path(app_res["receipt_file"])
    assert receipt_path.exists()

    # 3. Run pipeline requiring approval, providing receipt
    final_res = run_pipeline(
        inv_path,
        vendor_path,
        case_dir,
        with_approval=receipt_path,
        require_approval=True,
        signing_key_file=key_file,
        ledger_db=db_path,
    )

    assert final_res["ok"] is True
    assert final_res["approval_verified"] is True
    assert (case_dir / "corrected_payment.csv").exists()
