#!/usr/bin/env python3
"""Canonical Controlled Reconciliation Pipeline for Overcharge Desk.

Usage:
    python tools/pipeline.py INVOICE_JSON VENDOR_JSON OUT_DIR [--strict]

Executes the formal 9-stage verification pipeline:
  1. Load invoice JSON.
  2. Validate invoice schema and structure.
  3. Resolve source path safely (preventing cross-platform traversal).
  4. Verify source file existence on disk.
  5. Recalculate SHA-256 digest of source file.
  6. Verify source digest against invoice declaration.
  7. Run deterministic contract comparison.
  8. Validate comparison result JSON and record canonical SHA-256 digest.
  9. Route to the strictly authorized artifact generator:
     - VERIFIED        -> corrected_payment.csv
     - REVIEW_REQUIRED -> partial_review.csv
     - BLOCKED         -> blocked_review_report.csv

Exit codes: 0 ok | 2 pipeline blocked or integrity failure | 3 vendor/currency problem.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
                    ToolError, emit, is_safe_relative_path, load_json,
                    run_cli, save_comparison_with_digest, sha256_file)
from check_invoice import find_issues
from compare import compare
from validate_comparison import validate_comparison
from payment_sheet import COLUMNS as PAYMENT_COLUMNS, build_rows as build_payment_rows
from partial_review import COLUMNS as PARTIAL_COLUMNS, build_partial_review_rows
from blocked_review_report import COLUMNS as BLOCKED_COLUMNS, build_blocked_rows


def run_pipeline(invoice_path: Path | str, vendor_path: Path | str, out_dir: Path | str, base_dir: Path | str | None = None) -> dict:
    """Execute the end-to-end controlled reconciliation pipeline."""
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else Path.cwd()

    # Stage 1: Load invoice
    inv = load_json(invoice_path)
    vendor = load_json(vendor_path)

    # Stage 2: Validate invoice schema and fields
    invoice_issues = find_issues(inv, base_dir=base)

    # Stage 3, 4, 5, 6: Source verification
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

    # Stage 7: Run deterministic comparison
    comp_result = compare(inv, vendor, base_dir=base)

    # If top-level invoice issues existed, append to blocking issues and ensure BLOCKED
    if invoice_issues:
        for issue in invoice_issues:
            if issue not in comp_result["blocking_issues"]:
                comp_result["blocking_issues"].append(issue)
        comp_result["verification_status"] = STATE_BLOCKED
        comp_result["settlement_status"] = "PAYMENT_RECOMMENDATION_BLOCKED: INTEGRITY_ERRORS"
        comp_result["totals"]["complete"] = False

    # Stage 8: Save comparison result and companion digest
    comp_json_path = out_p / "compare.json"
    digest = save_comparison_with_digest(comp_result, comp_json_path)

    # Validate comparison result
    comp_issues = validate_comparison(comp_result, companion_digest_file=out_p / "compare.json.sha256")
    if comp_issues:
        raise ToolError(f"Comparison result failed validation: {'; '.join(comp_issues)}", 2)

    v_status = comp_result.get("verification_status")

    # Stage 9: Route to the authorized artifact generator
    artifact_type: str
    artifact_path: Path
    artifact_summary: dict

    if v_status == STATE_VERIFIED:
        artifact_type = "corrected_payment"
        artifact_path = out_p / "corrected_payment.csv"
        rows, artifact_summary = build_payment_rows(comp_result)
        with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(PAYMENT_COLUMNS)
            writer.writerows(rows)

    elif v_status == STATE_REVIEW_REQUIRED:
        artifact_type = "partial_review"
        artifact_path = out_p / "partial_review.csv"
        rows, artifact_summary = build_partial_review_rows(comp_result)
        with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(PARTIAL_COLUMNS)
            writer.writerows(rows)

    else:  # STATE_BLOCKED
        artifact_type = "blocked_review_report"
        artifact_path = out_p / "blocked_review_report.csv"
        rows, artifact_summary = build_blocked_rows(comp_result)
        with open(artifact_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(BLOCKED_COLUMNS)
            writer.writerows(rows)

    return {
        "ok": True,
        "pipeline_status": "COMPLETED",
        "verification_status": v_status,
        "settlement_status": comp_result.get("settlement_status"),
        "source_digest_verified": source_verified,
        "comparison_digest": digest,
        "comparison_file": str(comp_json_path),
        "artifact_type": artifact_type,
        "artifact_file": str(artifact_path),
        "blocking_issues_count": len(comp_result.get("blocking_issues") or []),
        "unresolved_evidence_count": len(comp_result.get("unresolved_evidence") or []),
        "artifact_summary": artifact_summary
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json", help="Path to invoice.json")
    ap.add_argument("vendor_json", help="Path to vendor.json")
    ap.add_argument("out_dir", help="Directory where pipeline artifacts will be written")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 if verification_status is BLOCKED")
    args = ap.parse_args()

    summary = run_pipeline(args.invoice_json, args.vendor_json, args.out_dir)
    emit(summary)
    if args.strict and summary.get("verification_status") == STATE_BLOCKED:
        return 2
    return 0


if __name__ == "__main__":
    run_cli(main)

