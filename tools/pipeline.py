#!/usr/bin/env python3
"""Canonical Controlled Reconciliation Pipeline for Overcharge Desk.

Usage:
    python tools/pipeline.py INVOICE_JSON VENDOR_JSON OUT_DIR [--strict] [--with-approval RECEIPT_JSON] [--ledger-db DB]

Executes the formal verification & payment-control pipeline:
  1. Load invoice JSON & vendor contract metadata.
  2. Validate invoice schema, structure, and required fields.
  3. Resolve source path safely (preventing cross-platform traversal).
  4. Verify source file existence on disk.
  5. Recalculate SHA-256 digest of source file.
  6. Verify source digest against invoice declaration.
  7. Run deterministic contract rate comparison (schema 2.0.0).
  8. Validate comparison result and generate formal verification artifact (verification.json).
  9. Register all evidence artifacts in case evidence registry (fail-closed).
 10. Record events in SQLite audit ledger (fail-closed).
 11. Enforce authorization gate for payment recommendation:
     - Validates signed approval receipt.
     - Without approval, generates pre-approval payment_preview.csv.
     - With approval, generates authorized corrected_payment.csv.
 12. Route to the strictly authorized artifact generator:
     - VERIFIED (with valid approval)    -> corrected_payment.csv
     - VERIFIED (pre-approval preview)   -> payment_preview.csv
     - REVIEW_REQUIRED                    -> partial_review.csv
     - BLOCKED                            -> blocked_review_report.csv
 13. Write structured execution manifest (manifest.json) for crash recovery and audit.

Exit codes: 0 ok | 2 pipeline blocked or integrity failure | 3 vendor/currency problem | 4 unauthorized.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
                    ToolError, canonical_json_bytes, emit, is_safe_relative_path,
                    load_json, run_cli, save_comparison_with_digest, sha256_file,
                    utc_now_iso, write_json_atomic)
from check_invoice import find_issues
from compare import compare
from validate_comparison import generate_verification_artifact, validate_comparison
from payment_sheet import COLUMNS as PAYMENT_COLUMNS, build_rows as build_payment_rows
from partial_review import COLUMNS as PARTIAL_COLUMNS, build_partial_review_rows
from blocked_review_report import COLUMNS as BLOCKED_COLUMNS, build_blocked_rows
from evidence import load_registry, register_evidence, save_registry
from audit_ledger import DEFAULT_LEDGER_DB, record_event
from approval_receipt import load_signing_key, verify_approval_receipt
from state_model import CommercialStatus, VerificationStatus, validate_state_consistency

PIPELINE_VERSION = "2.1.0"


def make_stage_record(
    stage_id: str,
    stage_name: str,
    status: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    artifact_references: Optional[Dict[str, str]] = None,
    artifact_hashes: Optional[Dict[str, str]] = None,
    error_code: Optional[int] = None,
    recoverable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a structured stage result record for manifest.json."""
    return {
        "stage_id": stage_id,
        "stage_name": stage_name,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "artifact_references": artifact_references or {},
        "artifact_hashes": artifact_hashes or {},
        "error_code": error_code,
        "recoverable": recoverable,
        "details": details or {},
    }


def run_pipeline(
    # Reconciliation Pipeline: Formal 13-stage verification, reconciliation, and payment control
    invoice_path: Path | str,
    vendor_path: Path | str,
    out_dir: Path | str,
    base_dir: Path | str | None = None,
    with_approval: Path | str | None = None,
    require_approval: bool = False,
    ledger_db: Path | str | None = None,
    signing_key_file: Path | str | None = None,
    record_ledger_events: bool = True,
) -> dict:
    """Execute the end-to-end controlled reconciliation pipeline."""
    pipeline_started_at = utc_now_iso()
    t_start = time.perf_counter()

    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else Path.cwd()

    inv_path_obj = Path(invoice_path)
    ven_path_obj = Path(vendor_path)

    stage_records: List[Dict[str, Any]] = []
    stage_results: Dict[str, Any] = {}
    artifact_references: Dict[str, str] = {}
    artifact_hashes: Dict[str, str] = {}
    ledger_event_ids: List[str] = []

    # -------------------------------------------------------------------------
    # Stage 1: Load invoice and vendor metadata
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    inv = load_json(inv_path_obj)
    vendor = load_json(ven_path_obj)
    case_id = inv.get("case_id") or "OC-UNKNOWN"
    execution_id = f"EXEC-{case_id}-{int(time.time())}"
    s_dur = int((time.perf_counter() - s_start) * 1000)

    stg1 = make_stage_record(
        stage_id="STAGE_01",
        stage_name="Load Inputs",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        details={"case_id": case_id, "vendor_id": vendor.get("vendor_id")},
    )
    stage_records.append(stg1)
    stage_results["stage_1_load"] = {"ok": True, "case_id": case_id}

    # -------------------------------------------------------------------------
    # Stage 2: Validate invoice schema and fields
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    invoice_issues = find_issues(inv, base_dir=base)
    s_dur = int((time.perf_counter() - s_start) * 1000)

    stg2 = make_stage_record(
        stage_id="STAGE_02",
        stage_name="Validate Invoice Schema",
        status="PASSED" if len(invoice_issues) == 0 else "WARNING",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        details={"issues_count": len(invoice_issues), "issues": invoice_issues},
    )
    stage_records.append(stg2)
    stage_results["stage_2_validate_invoice"] = {
        "ok": len(invoice_issues) == 0,
        "issues_count": len(invoice_issues),
    }

    # -------------------------------------------------------------------------
    # Stage 3 to 6: Source file verification and SHA-256 fingerprinting
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    src = inv.get("source_file")
    src_sha = inv.get("source_sha256")
    source_verified = False

    if not src or not is_safe_relative_path(str(src)):
        invoice_issues.append(f"Invalid or unsafe source_file: {src!r}")
    else:
        src_path = base / src if not Path(src).is_absolute() else Path(src)
        if not (src_path.exists() and src_path.is_file()):
            invoice_issues.append(f"source_file not found on disk: {src}")
        elif not src_sha:
            invoice_issues.append("Missing source_sha256")
        else:
            calc = sha256_file(str(src_path))
            if calc.lower() != str(src_sha).lower():
                invoice_issues.append(f"Source SHA mismatch: calculated {calc} != declared {src_sha}")
            else:
                source_verified = True
                artifact_hashes["source_invoice"] = calc

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg3 = make_stage_record(
        stage_id="STAGE_03_06",
        stage_name="Source Intake Fingerprinting",
        status="PASSED" if source_verified else "FAILED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        artifact_hashes={"source_invoice": src_sha} if src_sha else {},
        error_code=None if source_verified else 2,
        recoverable=False,
        details={"source_verified": source_verified},
    )
    stage_records.append(stg3)
    stage_results["stage_3_to_6_source_verification"] = {
        "ok": source_verified,
        "source_verified": source_verified,
    }

    # -------------------------------------------------------------------------
    # Stage 7: Run deterministic contract rate comparison
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    comp_result = compare(inv, vendor, base_dir=base)

    if invoice_issues:
        for issue in invoice_issues:
            if issue not in comp_result["blocking_issues"]:
                comp_result["blocking_issues"].append(issue)
        comp_result["verification_status"] = STATE_BLOCKED
        comp_result["settlement_status"] = "PAYMENT_RECOMMENDATION_BLOCKED: INTEGRITY_ERRORS"
        comp_result["totals"]["complete"] = False

    v_status = comp_result.get("verification_status")
    comm_status = comp_result.get("commercial_status") or CommercialStatus.UNDETERMINED
    s_dur = int((time.perf_counter() - s_start) * 1000)

    stg7 = make_stage_record(
        stage_id="STAGE_07",
        stage_name="Deterministic Comparison",
        status="PASSED" if v_status != STATE_BLOCKED else "BLOCKED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        details={
            "verification_status": v_status,
            "commercial_status": comm_status,
            "blocking_issues_count": len(comp_result.get("blocking_issues") or []),
        },
    )
    stage_records.append(stg7)
    stage_results["stage_7_comparison"] = {
        "ok": True,
        "verification_status": v_status,
        "commercial_status": comm_status,
        "settlement_status": comp_result.get("settlement_status"),
    }

    # -------------------------------------------------------------------------
    # Stage 8: Validate comparison and generate formal verification artifact
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    comp_json_path = out_p / "compare.json"
    digest = save_comparison_with_digest(comp_result, comp_json_path)
    artifact_references["comparison_json"] = str(comp_json_path)
    artifact_hashes["comparison_json"] = digest

    comp_issues = validate_comparison(comp_result, companion_digest_file=out_p / "compare.json.sha256")
    if comp_issues:
        raise ToolError(f"Comparison result failed validation: {'; '.join(comp_issues)}", 2)

    # Generate formal verification.json artifact
    audit_dir = out_p / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    vrf_path = audit_dir / "verification.json"
    vrf_record = generate_verification_artifact(
        comparison_data=comp_result,
        invoice_data=inv,
        vendor_data=vendor,
        base_dir=base,
        companion_digest_file=out_p / "compare.json.sha256",
        out_path=vrf_path,
    )
    artifact_references["verification_record"] = str(vrf_path)
    artifact_hashes["verification_record"] = vrf_record["verifier_integrity_digest"]

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg8 = make_stage_record(
        stage_id="STAGE_08",
        stage_name="Independent Verification",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        artifact_references={"comparison_json": str(comp_json_path), "verification_record": str(vrf_path)},
        artifact_hashes={"comparison_json": digest, "verification_record": vrf_record["verifier_integrity_digest"]},
        details={"verification_id": vrf_record["verification_id"]},
    )
    stage_records.append(stg8)
    stage_results["stage_8_validation"] = {
        "ok": True,
        "comparison_digest": digest,
        "verification_id": vrf_record["verification_id"],
    }

    # -------------------------------------------------------------------------
    # Stage 9: Register Evidence in Evidence Registry (Fail-Closed)
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    try:
        reg_inv = register_evidence(
            out_p,
            inv_path_obj if inv_path_obj.is_absolute() else base / inv_path_obj,
            evidence_type="extracted_invoice",
            case_id=case_id,
            base_dir=base,
        )
        artifact_references["extracted_invoice_evidence"] = reg_inv["evidence_id"]

        reg_comp = register_evidence(
            out_p,
            comp_json_path,
            evidence_type="comparison_result",
            case_id=case_id,
            base_dir=base,
        )
        artifact_references["comparison_evidence"] = reg_comp["evidence_id"]

        if source_verified and src:
            src_full = base / src if not Path(src).is_absolute() else Path(src)
            reg_src = register_evidence(
                out_p,
                src_full,
                evidence_type="source_invoice",
                case_id=case_id,
                base_dir=base,
            )
            artifact_references["source_invoice_evidence"] = reg_src["evidence_id"]

        reg_vrf = register_evidence(
            out_p,
            vrf_path,
            evidence_type="verification_record",
            case_id=case_id,
            base_dir=base,
        )
        artifact_references["verification_evidence"] = reg_vrf["evidence_id"]
    except Exception as exc:
        raise ToolError(f"Evidence registration failed: {exc}", 2)

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg9 = make_stage_record(
        stage_id="STAGE_09",
        stage_name="Evidence Registration",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        artifact_references=artifact_references,
    )
    stage_records.append(stg9)
    stage_results["stage_9_evidence_registration"] = {"ok": True}

    # -------------------------------------------------------------------------
    # Stage 10: Record audit ledger events (Fail-Closed)
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    if record_ledger_events:
        db = ledger_db or DEFAULT_LEDGER_DB
        try:
            ev1 = record_event(
                case_id=case_id,
                event_type="INVOICE_VALIDATED",
                actor_id="SYSTEM",
                payload={"invoice_number": inv.get("invoice_number"), "issues_count": len(invoice_issues)},
                db_path=db,
            )
            ledger_event_ids.append(ev1["event_id"])

            ev2 = record_event(
                case_id=case_id,
                event_type="COMPARISON_COMPLETED",
                actor_id="SYSTEM",
                payload={"verification_status": v_status, "comparison_digest": digest},
                db_path=db,
            )
            ledger_event_ids.append(ev2["event_id"])

            ev3 = record_event(
                case_id=case_id,
                event_type="VERIFICATION_COMPLETED",
                actor_id="SYSTEM",
                payload={
                    "verification_id": vrf_record["verification_id"],
                    "verification_status": vrf_record["verification_status"],
                    "commercial_status": vrf_record["commercial_status"],
                    "verifier_integrity_digest": vrf_record["verifier_integrity_digest"],
                },
                db_path=db,
            )
            ledger_event_ids.append(ev3["event_id"])
        except Exception as exc:
            raise ToolError(f"Audit ledger write failed: {exc}", 2)

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg10 = make_stage_record(
        stage_id="STAGE_10",
        stage_name="Ledger Audit Events",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        details={"events_recorded": len(ledger_event_ids)},
    )
    stage_records.append(stg10)
    stage_results["stage_10_ledger"] = {"ok": True, "event_ids": ledger_event_ids}

    # -------------------------------------------------------------------------
    # Stage 11: Authorization Gate for Payment Recommendations
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    approval_info = None

    # Resolve approval receipt path if specified or present in standard location
    resolved_approval_path = with_approval
    if not resolved_approval_path and require_approval:
        for cand in (out_p / "approvals" / "approval_receipt.json", out_p / "approval_receipt.json"):
            if cand.exists():
                resolved_approval_path = cand
                break

    if resolved_approval_path and Path(resolved_approval_path).exists():
        receipt_data = load_json(resolved_approval_path)
        key_bytes = load_signing_key(signing_key_file)
        app_valid, app_issues = verify_approval_receipt(
            receipt_data,
            key_bytes,
            expected_case_id=case_id,
            expected_compare_sha=digest,
        )
        if not app_valid:
            raise ToolError(
                f"PAYMENT_RECOMMENDATION_REFUSED: Invalid approval receipt: {'; '.join(app_issues)}",
                4,
            )
        if receipt_data.get("decision") != "APPROVED":
            raise ToolError(
                f"PAYMENT_RECOMMENDATION_REFUSED: Approval receipt decision is {receipt_data.get('decision')!r}, not APPROVED",
                4,
            )
        approval_info = receipt_data
        artifact_references["approval_receipt"] = str(resolved_approval_path)
        artifact_hashes["approval_receipt"] = receipt_data.get("receipt_hash", "")
    elif require_approval and v_status == STATE_VERIFIED:
        raise ToolError(
            f"PAYMENT_RECOMMENDATION_REFUSED: Case {case_id} requires an authorized human approval receipt. "
            f"None provided and none found at {out_p / 'approvals' / 'approval_receipt.json'}",
            4,
        )

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg11 = make_stage_record(
        stage_id="STAGE_11",
        stage_name="Authorization Gate",
        status="PASSED" if (approval_info is not None or not require_approval) else "FAILED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        details={"approval_verified": approval_info is not None, "require_approval": require_approval},
    )
    stage_records.append(stg11)
    stage_results["stage_11_authorization"] = {
        "ok": True,
        "approval_verified": approval_info is not None,
    }

    # -------------------------------------------------------------------------
    # Stage 12: Route to strictly authorized artifact generator
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    artifact_type: str
    artifact_path: Path
    artifact_summary: dict

    if v_status == STATE_VERIFIED:
        if approval_info is not None:
            # AUTHORIZED PAYMENT RECOMMENDATION
            artifact_type = "corrected_payment"
            artifact_path = out_p / "corrected_payment.csv"
            rows, artifact_summary = build_payment_rows(comp_result)
            with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(PAYMENT_COLUMNS)
                writer.writerows(rows)

            artifact_references["payment_sheet"] = str(artifact_path)
            artifact_hashes["payment_sheet"] = sha256_file(str(artifact_path))

            if record_ledger_events:
                try:
                    ev_pay = record_event(
                        case_id=case_id,
                        event_type="PAYMENT_RECOMMENDATION_CREATED",
                        actor_id="SYSTEM",
                        payload={
                            "payable_total": artifact_summary.get("payable_total"),
                            "withheld_total": artifact_summary.get("withheld_total"),
                            "artifact": str(artifact_path),
                        },
                        db_path=ledger_db or DEFAULT_LEDGER_DB,
                    )
                    ledger_event_ids.append(ev_pay["event_id"])
                except Exception as exc:
                    raise ToolError(f"Audit ledger write failed: {exc}", 2)
        else:
            # PRE-APPROVAL PAYMENT PREVIEW (Explicitly labeled NOT AUTHORIZED)
            artifact_type = "payment_preview"
            artifact_path = out_p / "payment_preview.csv"
            rows, artifact_summary = build_payment_rows(comp_result)
            with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["# NOTICE: PRE-APPROVAL PAYMENT PREVIEW ONLY - NOT AUTHORIZED FOR PAYMENT - REQUIRES OWNER APPROVAL"])
                writer.writerow(PAYMENT_COLUMNS)
                writer.writerows(rows)

            artifact_references["payment_preview"] = str(artifact_path)
            artifact_hashes["payment_preview"] = sha256_file(str(artifact_path))

    elif v_status == STATE_REVIEW_REQUIRED:
        artifact_type = "partial_review"
        artifact_path = out_p / "partial_review.csv"
        rows, artifact_summary = build_partial_review_rows(comp_result)
        with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(PARTIAL_COLUMNS)
            writer.writerows(rows)

        artifact_references["review_artifact"] = str(artifact_path)
        artifact_hashes["review_artifact"] = sha256_file(str(artifact_path))

        if record_ledger_events:
            try:
                ev_rev = record_event(
                    case_id=case_id,
                    event_type="REVIEW_REQUESTED",
                    actor_id="SYSTEM",
                    payload={
                        "unresolved_lines": artifact_summary.get("unresolved_lines_count"),
                        "artifact": str(artifact_path),
                    },
                    db_path=ledger_db or DEFAULT_LEDGER_DB,
                )
                ledger_event_ids.append(ev_rev["event_id"])
            except Exception as exc:
                raise ToolError(f"Audit ledger write failed: {exc}", 2)

    else:  # STATE_BLOCKED
        artifact_type = "blocked_review_report"
        artifact_path = out_p / "blocked_review_report.csv"
        rows, artifact_summary = build_blocked_rows(comp_result)
        with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(BLOCKED_COLUMNS)
            writer.writerows(rows)

        artifact_references["blocked_report"] = str(artifact_path)
        artifact_hashes["blocked_report"] = sha256_file(str(artifact_path))

        if record_ledger_events:
            try:
                ev_blk = record_event(
                    case_id=case_id,
                    event_type="PAYMENT_RECOMMENDATION_BLOCKED",
                    actor_id="SYSTEM",
                    payload={
                        "blocking_issues_count": len(comp_result.get("blocking_issues") or []),
                        "artifact": str(artifact_path),
                    },
                    db_path=ledger_db or DEFAULT_LEDGER_DB,
                )
                ledger_event_ids.append(ev_blk["event_id"])
            except Exception as exc:
                raise ToolError(f"Audit ledger write failed: {exc}", 2)

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg12 = make_stage_record(
        stage_id="STAGE_12",
        stage_name="Artifact Generation",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        artifact_references={artifact_type: str(artifact_path)},
        artifact_hashes={artifact_type: artifact_hashes.get(artifact_type, "")},
        details={"artifact_type": artifact_type},
    )
    stage_records.append(stg12)

    # -------------------------------------------------------------------------
    # Stage 13: Write Execution Manifest for crash recovery and audit
    # -------------------------------------------------------------------------
    s_start = time.perf_counter()
    s_iso_start = utc_now_iso()
    pipeline_completed_at = utc_now_iso()
    total_duration_ms = int((time.perf_counter() - t_start) * 1000)

    manifest = {
        "manifest_version": "2.0.0",
        "pipeline_version": PIPELINE_VERSION,
        "execution_id": execution_id,
        "case_id": case_id,
        "started_at": pipeline_started_at,
        "completed_at": pipeline_completed_at,
        "total_duration_ms": total_duration_ms,
        "verification_status": v_status,
        "commercial_status": comm_status,
        "settlement_status": comp_result.get("settlement_status"),
        "source_digest_verified": source_verified,
        "comparison_digest": digest,
        "artifact_type": artifact_type,
        "artifact_file": str(artifact_path),
        "stages": stage_records,
        "stage_results": stage_results,
        "artifact_references": artifact_references,
        "artifact_hashes": artifact_hashes,
        "ledger_event_ids": ledger_event_ids,
        "approval_verified": approval_info is not None,
    }
    manifest_path = out_p / "manifest.json"
    write_json_atomic(manifest_path, manifest)

    s_dur = int((time.perf_counter() - s_start) * 1000)
    stg13 = make_stage_record(
        stage_id="STAGE_13",
        stage_name="Execution Manifest",
        status="PASSED",
        started_at=s_iso_start,
        completed_at=utc_now_iso(),
        duration_ms=s_dur,
        artifact_references={"manifest": str(manifest_path)},
    )
    stage_records.append(stg13)

    return {
        "ok": True,
        "pipeline_status": "COMPLETED",
        "execution_id": execution_id,
        "case_id": case_id,
        "verification_status": v_status,
        "commercial_status": comm_status,
        "settlement_status": comp_result.get("settlement_status"),
        "source_digest_verified": source_verified,
        "comparison_digest": digest,
        "comparison_file": str(comp_json_path),
        "artifact_type": artifact_type,
        "artifact_file": str(artifact_path),
        "blocking_issues_count": len(comp_result.get("blocking_issues") or []),
        "unresolved_evidence_count": len(comp_result.get("unresolved_evidence") or []),
        "artifact_summary": artifact_summary,
        "approval_verified": approval_info is not None,
        "manifest_file": str(manifest_path),
        "ledger_events": ledger_event_ids,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json", help="Path to invoice.json")
    ap.add_argument("vendor_json", help="Path to vendor.json")
    ap.add_argument("out_dir", help="Directory where pipeline artifacts will be written")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 if verification_status is BLOCKED")
    ap.add_argument("--with-approval", help="Optional path to signed approval receipt JSON")
    ap.add_argument("--require-approval", action="store_true", help="Require valid human approval to emit payment sheet")
    ap.add_argument("--ledger-db", help="Path to SQLite ledger database")
    ap.add_argument("--key-file", help="Path to signing key file")
    args = ap.parse_args()

    summary = run_pipeline(
        invoice_path=args.invoice_json,
        vendor_path=args.vendor_json,
        out_dir=args.out_dir,
        with_approval=args.with_approval,
        require_approval=args.require_approval,
        ledger_db=args.ledger_db,
        signing_key_file=args.key_file,
    )
    emit(summary)
    if args.strict and summary.get("verification_status") == STATE_BLOCKED:
        return 2
    return 0


if __name__ == "__main__":
    run_cli(main)
