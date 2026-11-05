#!/usr/bin/env python3
"""End-to-End Six Benchmark Demo Case Verification Suite for Overcharge Desk.

Executes and verifies all 6 benchmark cases:
  - Case A (demo-clean): Clean contract match (100% verified, zero variance)
  - Case B (demo-overcharge): ₹6,000 overcharge detected, withheld, and approved
  - Case C (demo-review): Uncontracted line item requires commercial review
  - Case D (demo-blocked): Arithmetic discrepancy blocked with zero payable fields
  - Case E (demo-tampering): Post-approval evidence modification detected & refused
  - Case F (demo-ledger-failure): Unwriteable audit ledger causes fail-closed abort

Verifies the complete lifecycle:
  Invoice -> Evidence Registry -> Deterministic Compare -> Independent Verification
  -> Human Authorization Gateway -> SQLite Audit Ledger -> Final Settlement
  -> Standalone Case Audit Package Export & Cryptographic Integrity Verification

Exit codes: 0 ok | 2 verification failed.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
                    ToolError, emit, load_json, run_cli, write_json_atomic)
from auth import ensure_signing_key, get_default_key_path, issue_actor_token, load_actors_config
from approval_gateway import process_approval_decision
from audit_ledger import DEFAULT_LEDGER_DB, list_events, verify_ledger
from pipeline import run_pipeline
from export_audit_package import export_case_audit, verify_package_integrity


def run_full_demo(
    base_dir: Path | str = ".",
    clean_run: bool = False,
    cases_base_dir: Path | str | None = None,
    key_file: Path | str | None = None,
) -> dict:
    # Benchmark Suite: End-to-end verification across Clean, Overcharged, Review, Blocked, Tampered, and Failure cases
    """Execute all six benchmark demo cases end-to-end."""
    root = Path(base_dir)
    vendor_file = root / "vendors" / "acme.json"
    if not vendor_file.exists():
        vendor_file = root / "seed" / "acme.json"

    demo_results = {}
    key_path = Path(key_file) if key_file else get_default_key_path()
    key_bytes = ensure_signing_key(key_path)
    actors_cfg = load_actors_config(root / "config" / "actors.json")
    ledger_db = root / "ledger.db"

    cases_root = Path(cases_base_dir) if cases_base_dir else root / "cases"

    # Reset ledger and transient demo artifacts if clean run requested
    if clean_run:
        if ledger_db.exists():
            ledger_db.unlink()
        for c_name in ("demo-clean", "demo-overcharge", "demo-review", "demo-blocked"):
            c_dir = cases_root / c_name
            if c_dir.exists():
                shutil.rmtree(c_dir / "approvals", ignore_errors=True)
                shutil.rmtree(c_dir / "audit", ignore_errors=True)
                for art in (
                    "compare.json",
                    "manifest.json",
                    "evidence_registry.json",
                    "payment_preview.csv",
                    "corrected_payment.csv",
                    "partial_review.csv",
                    "blocked_review_report.csv",
                ):
                    (c_dir / art).unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # Case A: Clean Match (100% Verified, Zero Variance)
    # -------------------------------------------------------------------------
    case_a_dir = cases_root / "demo-clean"
    case_a_inv = case_a_dir / "invoice.json"

    # Pipeline pass 1: Analysis (Pre-approval preview)
    p_a1 = run_pipeline(case_a_inv, vendor_file, case_a_dir, base_dir=root, ledger_db=ledger_db)
    assert p_a1["verification_status"] == STATE_VERIFIED
    assert p_a1["artifact_type"] == "payment_preview"
    assert (case_a_dir / "payment_preview.csv").exists()

    # Human Owner Approval
    token_owner = issue_actor_token("owner", key_bytes, config=actors_cfg)
    app_a = process_approval_decision(
        case_dir=case_a_dir,
        actor_token=token_owner,
        decision="APPROVED",
        amount="30000.00",
        key_file=key_path,
        config_file=root / "config" / "actors.json",
    )
    assert app_a["approved_amount"] == "30000.00"
    assert app_a["withheld_amount"] == "0.00"

    # Pipeline pass 2: Finalize with verified human approval
    p_a2 = run_pipeline(
        case_a_inv,
        vendor_file,
        case_a_dir,
        base_dir=root,
        with_approval=Path(app_a["receipt_file"]),
        require_approval=True,
        signing_key_file=key_path,
        ledger_db=ledger_db,
    )
    assert p_a2["approval_verified"] is True
    assert p_a2["artifact_type"] == "corrected_payment"
    assert (case_a_dir / "corrected_payment.csv").exists()

    demo_results["case_a_clean"] = {
        "status": "PASSED",
        "verification_status": STATE_VERIFIED,
        "payable_total": "30000.00",
        "withheld_total": "0.00",
        "receipt_id": app_a["receipt_id"],
    }

    # -------------------------------------------------------------------------
    # Case B: Acme Overcharge (Benchmark ₹6,000 Variance)
    # -------------------------------------------------------------------------
    case_b_dir = cases_root / "demo-overcharge"
    case_b_inv = case_b_dir / "invoice.json"

    p_b1 = run_pipeline(case_b_inv, vendor_file, case_b_dir, base_dir=root, ledger_db=ledger_db)
    assert p_b1["verification_status"] == STATE_VERIFIED
    assert p_b1["artifact_type"] == "payment_preview"
    assert (case_b_dir / "payment_preview.csv").exists()

    # Human Owner approves paying contract rate and withholding ₹6,000 overcharge
    token_owner = issue_actor_token("owner", key_bytes, config=actors_cfg)
    app_b = process_approval_decision(
        case_dir=case_b_dir,
        actor_token=token_owner,
        decision="APPROVED",
        amount="60000.00",
        key_file=key_path,
        config_file=root / "config" / "actors.json",
    )
    assert app_b["approved_amount"] == "60000.00"
    assert app_b["withheld_amount"] == "6000.00"

    p_b2 = run_pipeline(
        case_b_inv,
        vendor_file,
        case_b_dir,
        base_dir=root,
        with_approval=Path(app_b["receipt_file"]),
        require_approval=True,
        signing_key_file=key_path,
        ledger_db=ledger_db,
    )
    assert p_b2["approval_verified"] is True
    assert p_b2["artifact_type"] == "corrected_payment"
    assert (case_b_dir / "corrected_payment.csv").exists()

    demo_results["case_b_overcharge"] = {
        "status": "PASSED",
        "verification_status": STATE_VERIFIED,
        "invoiced_total": "66000.00",
        "payable_total": "60000.00",
        "withheld_total": "6000.00",
        "receipt_id": app_b["receipt_id"],
    }

    # -------------------------------------------------------------------------
    # Case C: Uncontracted Line Item (Commercial Review Required)
    # -------------------------------------------------------------------------
    case_c_dir = cases_root / "demo-review"
    case_c_inv = case_c_dir / "invoice.json"

    p_c = run_pipeline(case_c_inv, vendor_file, case_c_dir, base_dir=root, ledger_db=ledger_db)
    assert p_c["verification_status"] == STATE_REVIEW_REQUIRED
    assert p_c["artifact_type"] == "partial_review"
    assert (case_c_dir / "partial_review.csv").exists()

    demo_results["case_c_review_required"] = {
        "status": "PASSED",
        "verification_status": STATE_REVIEW_REQUIRED,
        "artifact": str(case_c_dir / "partial_review.csv"),
        "unresolved_lines": p_c["unresolved_evidence_count"],
    }

    # -------------------------------------------------------------------------
    # Case D: Arithmetic Discrepancy (Blocked Audit)
    # -------------------------------------------------------------------------
    case_d_dir = cases_root / "demo-blocked"
    case_d_inv = case_d_dir / "invoice.json"

    p_d = run_pipeline(case_d_inv, vendor_file, case_d_dir, base_dir=root, ledger_db=ledger_db)
    assert p_d["verification_status"] == STATE_BLOCKED
    assert p_d["artifact_type"] == "blocked_review_report"
    assert (case_d_dir / "blocked_review_report.csv").exists()

    # Confirm Gateway strictly refuses approval
    blocked_approval_prevented = False
    try:
        process_approval_decision(
            case_dir=case_d_dir,
            actor_token=token_owner,
            decision="APPROVED",
            key_file=key_path,
            config_file=root / "config" / "actors.json",
        )
    except ToolError as exc:
        if exc.code == 4 and "Cannot approve BLOCKED audit" in str(exc):
            blocked_approval_prevented = True

    assert blocked_approval_prevented is True
    demo_results["case_d_blocked"] = {
        "status": "PASSED",
        "verification_status": STATE_BLOCKED,
        "artifact": str(case_d_dir / "blocked_review_report.csv"),
        "approval_refused_fail_closed": True,
    }

    # -------------------------------------------------------------------------
    # Case E: Post-Approval Evidence Tampering (Fail-Closed Refusal)
    # -------------------------------------------------------------------------
    case_e_dir = cases_root / "demo-tampering"
    shutil.rmtree(case_e_dir, ignore_errors=True)
    case_e_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(case_a_inv, case_e_dir / "invoice.json")
    case_e_inv = case_e_dir / "invoice.json"
    inv_e_init = load_json(case_e_inv)
    inv_e_init["case_id"] = "OC-20261001-02"
    write_json_atomic(case_e_inv, inv_e_init)

    p_e1 = run_pipeline(case_e_inv, vendor_file, case_e_dir, base_dir=root, ledger_db=ledger_db)
    app_e = process_approval_decision(
        case_dir=case_e_dir,
        actor_token=token_owner,
        decision="APPROVED",
        amount="30000.00",
        key_file=key_path,
        config_file=root / "config" / "actors.json",
    )
    receipt_e = Path(app_e["receipt_file"])

    # Adversarial action: Alter invoice lines on disk post-approval
    inv_e_data = load_json(case_e_inv)
    inv_e_data["lines"][0]["quantity"] = 9999
    write_json_atomic(case_e_inv, inv_e_data)

    tampering_detected = False
    try:
        run_pipeline(
            case_e_inv,
            vendor_file,
            case_e_dir,
            base_dir=root,
            with_approval=receipt_e,
            require_approval=True,
            signing_key_file=key_path,
            ledger_db=ledger_db,
        )
    except ToolError as exc:
        tampering_detected = True

    assert tampering_detected is True
    demo_results["case_e_tampering"] = {
        "status": "PASSED",
        "attack_simulated": "POST_APPROVAL_COMPARISON_ALTERATION",
        "tampering_detected": True,
        "payment_prevented_fail_closed": True,
    }

    # -------------------------------------------------------------------------
    # Case F: Audit Ledger Failure (Fail-Closed Refusal)
    # -------------------------------------------------------------------------
    case_f_dir = cases_root / "demo-ledger-failure"
    shutil.rmtree(case_f_dir, ignore_errors=True)
    case_f_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(case_a_inv, case_f_dir / "invoice.json")
    case_f_inv = case_f_dir / "invoice.json"
    inv_f_init = load_json(case_f_inv)
    inv_f_init["case_id"] = "OC-20261001-03"
    write_json_atomic(case_f_inv, inv_f_init)

    bad_ledger_db = case_f_dir / "unwriteable_ledger_dir"
    bad_ledger_db.mkdir(parents=True, exist_ok=True)

    ledger_failure_blocked = False
    try:
        run_pipeline(
            case_f_inv,
            vendor_file,
            case_f_dir,
            base_dir=root,
            ledger_db=bad_ledger_db,
            record_ledger_events=True,
        )
    except ToolError as exc:
        if exc.code == 2 and "audit ledger" in str(exc).lower():
            ledger_failure_blocked = True

    assert ledger_failure_blocked is True
    assert not (case_f_dir / "corrected_payment.csv").exists()

    demo_results["case_f_ledger_failure"] = {
        "status": "PASSED",
        "failure_simulated": "UNWRITEABLE_AUDIT_LEDGER",
        "pipeline_refused_fail_closed": True,
        "payment_prevented_fail_closed": True,
    }

    # -------------------------------------------------------------------------
    # Export Standalone Case Audit Package (Case B) & Verify Package Integrity
    # -------------------------------------------------------------------------
    pkg_report = export_case_audit(
        case_dir=case_b_dir,
        ledger_db=ledger_db,
        key_file=key_path,
    )
    pkg_valid, pkg_issues = verify_package_integrity(
        package_dir=pkg_report["target_package_directory"],
        key_file=key_path,
    )
    assert pkg_valid is True
    assert len(pkg_issues) == 0

    # -------------------------------------------------------------------------
    # Global Ledger Chain Verification
    # -------------------------------------------------------------------------
    ledger_valid, ledger_issues = verify_ledger(ledger_db)
    events = list_events(db_path=ledger_db)
    assert ledger_valid is True
    assert len(ledger_issues) == 0

    return {
        "ok": True,
        "all_cases_passed": True,
        "cases": demo_results,
        "audit_package_exported": {
            "case_id": pkg_report["case_id"],
            "target_dir": pkg_report["target_package_directory"],
            "package_integrity_digest": pkg_report["package_integrity_digest"],
            "package_verified": pkg_valid,
        },
        "ledger_summary": {
            "total_events": len(events),
            "chain_valid": ledger_valid,
            "first_event_hash": events[0]["event_hash"] if events else None,
            "latest_event_hash": events[-1]["event_hash"] if events else None,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="Reset ledger.db before running")
    args = ap.parse_args()

    res = run_full_demo(clean_run=args.clean)
    emit(res)
    return 0


if __name__ == "__main__":
    run_cli(main)
