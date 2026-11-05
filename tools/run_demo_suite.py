#!/usr/bin/env python3
"""End-to-End Four Demo Case Verification Suite for Overcharge Desk.

Executes and verifies all 4 benchmark cases:
  - Case A (demo-clean): Clean contract match (100% verified, zero variance)
  - Case B (demo-overcharge): ₹6,000 overcharge detected, withheld, and approved
  - Case C (demo-review): Uncontracted line item requires commercial review
  - Case D (demo-blocked): Arithmetic discrepancy blocked with zero payable fields

Verifies the complete lifecycle:
  Invoice -> Evidence Registry -> Deterministic Compare -> Independent Validation
  -> Human Authorization Gateway -> SQLite Audit Ledger -> Final Settlement

Exit codes: 0 ok | 2 verification failed.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
                    ToolError, emit, load_json, run_cli)
from auth import ensure_signing_key, issue_actor_token, load_actors_config
from approval_gateway import process_approval_decision
from audit_ledger import DEFAULT_LEDGER_DB, list_events, verify_ledger
from pipeline import run_pipeline


def run_full_demo(base_dir: Path | str = ".", clean_run: bool = False, cases_base_dir: Path | str | None = None) -> dict:
    """Execute all four benchmark demo cases end-to-end."""
    root = Path(base_dir)
    vendor_file = root / "vendors" / "acme.json"
    if not vendor_file.exists():
        vendor_file = root / "seed" / "acme.json"

    demo_results = {}
    key_bytes = ensure_signing_key(root / "config" / "signing.key")
    actors_cfg = load_actors_config(root / "config" / "actors.json")
    ledger_db = root / "ledger.db"

    cases_root = Path(cases_base_dir) if cases_base_dir else root / "cases"

    # Reset ledger if clean run requested
    if clean_run and ledger_db.exists():
        ledger_db.unlink()

    # -------------------------------------------------------------------------
    # Case A: Clean Match
    # -------------------------------------------------------------------------
    case_a_dir = cases_root / "demo-clean"
    case_a_inv = case_a_dir / "invoice.json"

    # Pipeline pass 1: Analysis
    p_a1 = run_pipeline(case_a_inv, vendor_file, case_a_dir, base_dir=root, ledger_db=ledger_db)
    assert p_a1["verification_status"] == STATE_VERIFIED
    assert p_a1["artifact_type"] == "corrected_payment"

    # Human Owner Approval
    token_owner = issue_actor_token("owner", key_bytes, config=actors_cfg)
    app_a = process_approval_decision(
        case_dir=case_a_dir,
        actor_token=token_owner,
        decision="APPROVED",
        amount="30000.00",
        key_file=root / "config" / "signing.key",
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
        signing_key_file=root / "config" / "signing.key",
        ledger_db=ledger_db,
    )
    assert p_a2["approval_verified"] is True
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
    assert p_b1["artifact_type"] == "corrected_payment"

    # Human Owner approves paying contract rate and withholding ₹6,000 overcharge
    token_owner = issue_actor_token("owner", key_bytes, config=actors_cfg)
    app_b = process_approval_decision(
        case_dir=case_b_dir,
        actor_token=token_owner,
        decision="APPROVED",
        amount="60000.00",
        key_file=root / "config" / "signing.key",
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
        signing_key_file=root / "config" / "signing.key",
        ledger_db=ledger_db,
    )
    assert p_b2["approval_verified"] is True
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
            key_file=root / "config" / "signing.key",
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
    # Ledger Chain Verification
    # -------------------------------------------------------------------------
    ledger_valid, ledger_issues = verify_ledger(ledger_db)
    events = list_events(db_path=ledger_db)
    assert ledger_valid is True
    assert len(ledger_issues) == 0

    return {
        "ok": True,
        "all_cases_passed": True,
        "cases": demo_results,
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
