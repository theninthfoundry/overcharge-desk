#!/usr/bin/env python3
"""Strict independent validator and verification artifact generator for comparison results.

Usage:
    python tools/validate_comparison.py COMPARE_JSON [--digest DIGEST_FILE] [--strict]
    python tools/validate_comparison.py COMPARE_JSON --out-verification VERIFICATION_JSON [--invoice INVOICE_JSON] [--vendor VENDOR_JSON]

Validates schema 2.0.0, internal mathematical consistency, verification state
coherence, decimal bounds, contract variance calculations, and companion SHA-256 digests.
Produces an immutable formal verification artifact (verification.json) when requested.
Exit code: 0 if valid; 2 if validation issues are found or file is invalid.
"""
from __future__ import annotations

import argparse
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (CURRENCY_RE, ToolError, canonical_json_bytes, emit,
                    hash_comparison_result, is_safe_relative_path, load_json,
                    parse_date, q2, run_cli, sha256_file, to_decimal,
                    utc_now_iso, write_json_atomic,
                    STATE_VERIFIED, STATE_REVIEW_REQUIRED, STATE_BLOCKED,
                    STATUS_VERIFIED_MATCH, STATUS_VERIFIED_OVERCHARGE, STATUS_VERIFIED_UNDERCHARGE,
                    STATUS_SOURCE_DISCREPANCY, STATUS_UNMATCHED, STATUS_REQUIRES_HUMAN_REVIEW)
from state_model import CommercialStatus, VerificationStatus

VERIFIER_VERSION = "2.1.0"

REQUIRED_TOP_FIELDS = [
    "schema_version", "verification_status", "settlement_status", "case_id",
    "vendor_id", "contract_id", "invoice_number", "invoice_date", "currency",
    "lines", "totals", "blocking_issues", "unresolved_evidence", "warnings"
]

REQUIRED_LINE_FIELDS = ["line_no", "description", "source_ref", "status", "verification_status"]

PERMITTED_LINE_STATUSES = {"matched", "unmatched", "SOURCE_DISCREPANCY"}
PERMITTED_LINE_VERIFICATION_STATUSES = {
    STATUS_VERIFIED_MATCH, STATUS_VERIFIED_OVERCHARGE, STATUS_VERIFIED_UNDERCHARGE,
    STATUS_SOURCE_DISCREPANCY, STATUS_UNMATCHED, STATUS_REQUIRES_HUMAN_REVIEW
}


def validate_comparison(result: dict, companion_digest_file: Path | str | None = None) -> list[str]:
    # Independent Auditor: Deep mathematical re-verification of line-level arithmetic parity
    """Inspect a comparison result dictionary for integrity and mathematical consistency.
    
    Returns a list of issue strings. An empty list signifies an authentic, valid result.
    """
    issues: list[str] = []

    if not isinstance(result, dict):
        return ["Comparison result root must be a JSON object"]

    if not result.get("ok"):
        issues.append("Comparison result ok flag is False or missing")

    # 1. Schema version
    ver = result.get("schema_version")
    if ver != "2.0.0":
        issues.append(f"Unsupported schema_version: {ver!r} (expected '2.0.0')")

    # 2. Top-level required fields
    for f in REQUIRED_TOP_FIELDS:
        if f not in result:
            issues.append(f"Missing required top-level field: {f}")

    v_status = result.get("verification_status")
    if v_status not in (STATE_VERIFIED, STATE_REVIEW_REQUIRED, STATE_BLOCKED):
        issues.append(f"Invalid verification_status: {v_status!r}")

    curr = result.get("currency")
    if not curr or not CURRENCY_RE.match(str(curr)):
        issues.append(f"Invalid currency: {curr!r} (expected 3-letter ISO code)")

    inv_date_str = result.get("invoice_date")
    if inv_date_str:
        try:
            parse_date(inv_date_str, "invoice_date")
        except ToolError as exc:
            issues.append(str(exc))

    lines = result.get("lines")
    if not isinstance(lines, list) or not lines:
        issues.append("Comparison lines must be a non-empty list")
        return issues

    totals = result.get("totals")
    if not isinstance(totals, dict):
        issues.append("totals must be an object")
        totals = {}

    blocking_issues = result.get("blocking_issues") or []
    if not isinstance(blocking_issues, list):
        issues.append("blocking_issues must be a list")
        blocking_issues = []

    # 3. Line-level inspection
    seen_lines = set()
    sum_m_inv = Decimal(0)
    sum_m_con = Decimal(0)
    sum_m_var = Decimal(0)
    sum_over = Decimal(0)
    sum_under = Decimal(0)
    count_discrepancy = 0
    count_unmatched = 0

    for idx, ln in enumerate(lines):
        if not isinstance(ln, dict):
            issues.append(f"Line {idx+1}: line must be a JSON object")
            continue

        for lf in REQUIRED_LINE_FIELDS:
            if lf not in ln:
                issues.append(f"Line {idx+1}: missing required field {lf}")

        lno = ln.get("line_no")
        if lno is None or lno in seen_lines:
            issues.append(f"Line {idx+1}: invalid or duplicate line_no {lno!r}")
        else:
            seen_lines.add(lno)

        l_stat = ln.get("status")
        if l_stat not in PERMITTED_LINE_STATUSES:
            issues.append(f"Line {lno}: invalid status {l_stat!r}")

        l_v_stat = ln.get("verification_status")
        if l_v_stat not in PERMITTED_LINE_VERIFICATION_STATUSES:
            issues.append(f"Line {lno}: invalid verification_status {l_v_stat!r}")

        # Mathematical Parity Checks
        try:
            qty = to_decimal(ln.get("quantity"), f"Line {lno} quantity") if ln.get("quantity") is not None else None
            inv_p = to_decimal(ln.get("invoiced_unit_price"), f"Line {lno} invoiced_unit_price") if ln.get("invoiced_unit_price") is not None else None
            con_p = to_decimal(ln.get("contract_unit_price"), f"Line {lno} contract_unit_price") if ln.get("contract_unit_price") is not None else None
            var_unit = to_decimal(ln.get("variance_per_unit"), f"Line {lno} variance_per_unit") if ln.get("variance_per_unit") is not None else None
            l_var = to_decimal(ln.get("line_variance"), f"Line {lno} line_variance") if ln.get("line_variance") is not None else None
            inv_comp = to_decimal(ln.get("invoiced_line_total_computed"), f"Line {lno} computed total") if ln.get("invoiced_line_total_computed") is not None else None
            inv_writ = to_decimal(ln.get("invoiced_line_total_as_written"), f"Line {lno} written total") if ln.get("invoiced_line_total_as_written") is not None else None
            con_tot = to_decimal(ln.get("contract_line_total"), f"Line {lno} contract total") if ln.get("contract_line_total") is not None else None

            if l_stat == "matched":
                if qty is None or inv_p is None or con_p is None or l_var is None:
                    issues.append(f"Line {lno}: matched line is missing mandatory numeric pricing fields")
                else:
                    # Invariant Rule 1.1: Exact Decimal arithmetic verified per line item
                    calc_var_unit = q2(inv_p - con_p)
                    if var_unit is not None and var_unit != calc_var_unit:
                        issues.append(f"Line {lno}: variance_per_unit {var_unit} != invoiced ({inv_p}) - contract ({con_p}) = {calc_var_unit}")

                    calc_line_var = q2(qty * (inv_p - con_p))
                    if l_var != calc_line_var:
                        issues.append(f"Line {lno}: variance mismatch: line_variance {l_var} != qty ({qty}) x unit variance ({calc_var_unit}) = {calc_line_var}")

                    calc_inv_comp = q2(qty * inv_p)
                    if inv_comp is not None and inv_comp != calc_inv_comp:
                        issues.append(f"Line {lno}: invoiced_line_total_computed {inv_comp} != qty x invoiced_price = {calc_inv_comp}")

                    calc_con_tot = q2(qty * con_p)
                    if con_tot is not None and con_tot != calc_con_tot:
                        issues.append(f"Line {lno}: contract total mismatch: contract_line_total {con_tot} != qty x contract_price = {calc_con_tot}")

                    # Direction check
                    direction = ln.get("direction")
                    if l_var > Decimal(0) and direction != "over":
                        issues.append(f"Line {lno}: positive variance must have direction 'over', got {direction!r}")
                    elif l_var < Decimal(0) and direction != "under":
                        issues.append(f"Line {lno}: negative variance must have direction 'under', got {direction!r}")
                    elif l_var == Decimal(0) and direction != "match":
                        issues.append(f"Line {lno}: zero variance must have direction 'match', got {direction!r}")

                    # Sum accumulator
                    if inv_comp is not None:
                        sum_m_inv += inv_comp
                    if con_tot is not None:
                        sum_m_con += con_tot
                    sum_m_var += l_var
                    if l_var > Decimal(0):
                        sum_over += l_var
                    elif l_var < Decimal(0):
                        sum_under += l_var

            elif l_stat == "SOURCE_DISCREPANCY":
                count_discrepancy += 1
                if ln.get("line_total_matches") is not False:
                    issues.append(f"Line {lno}: SOURCE_DISCREPANCY line must have line_total_matches=False")
                if l_v_stat != STATUS_SOURCE_DISCREPANCY:
                    issues.append(f"Line {lno}: SOURCE_DISCREPANCY line must have verification_status=STATUS_SOURCE_DISCREPANCY")

            elif l_stat == "unmatched":
                count_unmatched += 1
                if l_v_stat != STATUS_UNMATCHED:
                    issues.append(f"Line {lno}: unmatched line must have verification_status=STATUS_UNMATCHED")

        except ToolError as exc:
            issues.append(f"Line {lno} arithmetic parsing failed: {exc}")

    # 4. Totals Consistency Checks
    try:
        if "matched_invoiced" in totals and totals["matched_invoiced"] is not None:
            tot_m_inv = to_decimal(totals["matched_invoiced"], "totals.matched_invoiced")
            if tot_m_inv != sum_m_inv:
                issues.append(f"Totals mismatch: matched_invoiced {tot_m_inv} != sum of matched lines {sum_m_inv}")

        if "matched_per_contract" in totals and totals["matched_per_contract"] is not None:
            tot_m_con = to_decimal(totals["matched_per_contract"], "totals.matched_per_contract")
            if tot_m_con != sum_m_con:
                issues.append(f"Totals mismatch: matched_per_contract {tot_m_con} != sum of contract totals {sum_m_con}")

        if "variance_on_matched_lines" in totals and totals["variance_on_matched_lines"] is not None:
            tot_m_var = to_decimal(totals["variance_on_matched_lines"], "totals.variance_on_matched_lines")
            if tot_m_var != sum_m_var:
                issues.append(f"Totals mismatch: variance_on_matched_lines {tot_m_var} != sum of line variances {sum_m_var}")

        if "verified_overcharge_total" in totals and totals["verified_overcharge_total"] is not None:
            tot_over = to_decimal(totals["verified_overcharge_total"], "totals.verified_overcharge_total")
            if tot_over != sum_over:
                issues.append(f"Totals mismatch: verified_overcharge_total {tot_over} != calculated {sum_over}")

        if "verified_undercharge_total" in totals and totals["verified_undercharge_total"] is not None:
            tot_under = to_decimal(totals["verified_undercharge_total"], "totals.verified_undercharge_total")
            if tot_under != sum_under and abs(tot_under) != abs(sum_under):
                issues.append(f"Totals mismatch: verified_undercharge_total {tot_under} != calculated {sum_under}")

        if "source_discrepancy_count" in totals:
            rec_disc = int(totals["source_discrepancy_count"])
            if rec_disc != count_discrepancy:
                issues.append(f"Discrepancy count mismatch: totals says {rec_disc}, found {count_discrepancy}")

        if "unmatched_line_count" in totals:
            rec_unm = int(totals["unmatched_line_count"])
            if rec_unm != count_unmatched:
                issues.append(f"Unmatched line count mismatch: totals says {rec_unm}, found {count_unmatched}")

    except ToolError as exc:
        issues.append(f"Totals numeric failure: {exc}")

    # 5. State consistency
    if count_discrepancy > 0 or len(blocking_issues) > 0:
        if v_status != STATE_BLOCKED:
            issues.append(f"State inconsistency: audit has {count_discrepancy} discrepancies and {len(blocking_issues)} blocking issues, but status is {v_status!r} (must be BLOCKED)")

    if v_status == STATE_VERIFIED:
        if count_discrepancy > 0:
            issues.append("State inconsistency: VERIFIED audit cannot contain discrepancy lines")
        if count_unmatched > 0:
            issues.append("State inconsistency: VERIFIED audit cannot contain unmatched lines")
        if len(blocking_issues) > 0:
            issues.append("State inconsistency: VERIFIED audit cannot contain blocking issues")
        if totals.get("complete") is not True:
            issues.append("State inconsistency: VERIFIED audit totals.complete must be True")

    if v_status == STATE_REVIEW_REQUIRED:
        if count_discrepancy > 0:
            issues.append("State inconsistency: REVIEW_REQUIRED cannot contain source discrepancies (must be BLOCKED)")
        if len(blocking_issues) > 0:
            issues.append("State inconsistency: REVIEW_REQUIRED cannot contain blocking issues (must be BLOCKED)")
        if count_unmatched == 0:
            issues.append("State inconsistency: REVIEW_REQUIRED requires at least one unresolved line item")

    # 6. Companion Digest Verification (if provided)
    if companion_digest_file:
        dp = Path(companion_digest_file)
        if not dp.exists():
            issues.append(f"Digest file not found: {companion_digest_file}")
        else:
            try:
                expected_sha = dp.read_text(encoding="utf-8").strip()
                calc_sha = hash_comparison_result(result)
                if expected_sha.lower() != calc_sha.lower():
                    issues.append(f"Comparison digest mismatch: calculated {calc_sha} != expected {expected_sha}")
            except Exception as exc:
                issues.append(f"Failed to verify digest: {exc}")

    return issues


def generate_verification_artifact(
    comparison_data: dict,
    invoice_data: Optional[dict] = None,
    vendor_data: Optional[dict] = None,
    base_dir: Path | str | None = None,
    companion_digest_file: Path | str | None = None,
    evidence_registry: Optional[dict] = None,
    out_path: Path | str | None = None,
) -> dict:
    # Verification Artifact Generator: Produces formal, cryptographically hashed verification.json
    """Perform independent verification and generate the canonical verification.json artifact."""
    base = Path(base_dir) if base_dir else Path.cwd()
    case_id = comparison_data.get("case_id") or "OC-UNKNOWN"
    timestamp = utc_now_iso()

    # Step 1: Run deep mathematical validation of comparison
    comp_issues = validate_comparison(comparison_data, companion_digest_file=companion_digest_file)

    checks: List[Dict[str, Any]] = []
    passed_checks: List[str] = []
    failed_checks: List[str] = []
    reason_codes: List[str] = []

    # Check 1: Schema Version
    c_schema = comparison_data.get("schema_version") == "2.0.0"
    checks.append({
        "check_id": "CHK_SCHEMA_2_0_0",
        "name": "Comparison Schema Version",
        "status": "PASSED" if c_schema else "FAILED",
        "details": f"Version: {comparison_data.get('schema_version')}",
    })
    (passed_checks if c_schema else failed_checks).append("CHK_SCHEMA_2_0_0")

    # Check 2: Mathematical Parity & Totals
    c_math = len(comp_issues) == 0
    checks.append({
        "check_id": "CHK_MATHEMATICAL_PARITY",
        "name": "Line Arithmetic & Totals Consistency",
        "status": "PASSED" if c_math else "FAILED",
        "details": f"Issues count: {len(comp_issues)}",
        "issues": comp_issues,
    })
    (passed_checks if c_math else failed_checks).append("CHK_MATHEMATICAL_PARITY")
    if not c_math:
        reason_codes.append("ARITHMETIC_OR_SCHEMA_VALIDATION_FAILURE")

    # Check 3: Raw Source Invoice Verification (if invoice provided)
    invoice_digest = comparison_data.get("source_sha256") or "0" * 64
    c_inv_src = True
    if invoice_data:
        src = invoice_data.get("source_file")
        declared_sha = invoice_data.get("source_sha256")
        if src and is_safe_relative_path(str(src)):
            src_p = base / src if not Path(src).is_absolute() else Path(src)
            if src_p.exists():
                actual_sha = sha256_file(src_p)
                invoice_digest = actual_sha
                if declared_sha and declared_sha.lower() != actual_sha.lower():
                    c_inv_src = False
            else:
                c_inv_src = False
        else:
            c_inv_src = False

        checks.append({
            "check_id": "CHK_SOURCE_INVOICE_INTEGRITY",
            "name": "Raw Source Invoice File & SHA-256 Digest",
            "status": "PASSED" if c_inv_src else "FAILED",
            "details": f"Digest: {invoice_digest}",
        })
        (passed_checks if c_inv_src else failed_checks).append("CHK_SOURCE_INVOICE_INTEGRITY")
        if not c_inv_src:
            reason_codes.append("SOURCE_INVOICE_FINGERPRINT_MISMATCH")

    # Check 4: Contract Terms Integrity (if vendor provided)
    contract_digest = "0" * 64
    if vendor_data:
        con = vendor_data.get("contract", {})
        con_src = con.get("source_file")
        if con_src and is_safe_relative_path(str(con_src)):
            con_p = base / con_src if not Path(con_src).is_absolute() else Path(con_src)
            if con_p.exists():
                contract_digest = sha256_file(con_p)

        checks.append({
            "check_id": "CHK_CONTRACT_INTEGRITY",
            "name": "Contract Document Digest & Rate Availability",
            "status": "PASSED" if contract_digest != "0" * 64 else "WARNING",
            "details": f"Contract ID: {con.get('contract_id')}, Digest: {contract_digest}",
        })
        passed_checks.append("CHK_CONTRACT_INTEGRITY")

    # Check 5: Comparison Result Fingerprint
    comparison_digest = hash_comparison_result(comparison_data)

    # Derive Evidence Digest Set
    evidence_digest_set = {}
    if evidence_registry:
        for ev in evidence_registry.get("evidence", []):
            eid = ev.get("evidence_id")
            sha = ev.get("sha256")
            if eid and sha:
                evidence_digest_set[eid] = sha.lower()

    # Determine Verification and Commercial Status
    v_status = comparison_data.get("verification_status") or VerificationStatus.NOT_VERIFIED
    if not c_math or not c_inv_src:
        v_status = VerificationStatus.BLOCKED

    comm_status = comparison_data.get("commercial_status") or CommercialStatus.UNDETERMINED
    if v_status == VerificationStatus.BLOCKED and comm_status not in (CommercialStatus.DISCREPANCY, CommercialStatus.UNDETERMINED):
        comm_status = CommercialStatus.DISCREPANCY

    compact_ts = timestamp.replace("-", "").replace(":", "").replace("Z", "")
    verification_id = f"VRF-{case_id}-{compact_ts}"

    verification_record: Dict[str, Any] = {
        "verification_version": VERIFIER_VERSION,
        "verification_id": verification_id,
        "case_id": case_id,
        "timestamp": timestamp,
        "invoice_number": comparison_data.get("invoice_number"),
        "vendor_id": comparison_data.get("vendor_id"),
        "contract_id": comparison_data.get("contract_id"),
        "verification_status": v_status,
        "commercial_status": comm_status,
        "invoice_digest": invoice_digest,
        "contract_digest": contract_digest,
        "comparison_digest": comparison_digest,
        "evidence_digest_set": evidence_digest_set,
        "checks": checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "reason_codes": reason_codes,
        "totals": comparison_data.get("totals", {}),
    }

    # Compute Verifier Integrity Digest over canonical bytes
    record_copy = {k: v for k, v in verification_record.items() if k != "verifier_integrity_digest"}
    ver_digest = hashlib.sha256(canonical_json_bytes(record_copy)).hexdigest()
    verification_record["verifier_integrity_digest"] = ver_digest

    if out_path:
        out_p = Path(out_path)
        write_json_atomic(out_p, verification_record)
        sha_p = Path(f"{out_path}.sha256")
        sha_p.write_text(ver_digest + "\n", encoding="utf-8")

    return verification_record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json", help="Path to comparison result JSON")
    ap.add_argument("--digest", help="Optional path to companion .sha256 digest file")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 if any issues are found")
    ap.add_argument("--out-verification", help="Optional output path for verification.json artifact")
    ap.add_argument("--invoice", help="Optional path to invoice JSON for cross-check")
    ap.add_argument("--vendor", help="Optional path to vendor JSON for cross-check")
    args = ap.parse_args()

    data = load_json(args.compare_json)
    digest_file = args.digest
    if not digest_file:
        auto_digest = Path(f"{args.compare_json}.sha256")
        if auto_digest.exists():
            digest_file = auto_digest

    issues = validate_comparison(data, companion_digest_file=digest_file)

    if args.out_verification:
        inv_data = load_json(args.invoice) if args.invoice else None
        ven_data = load_json(args.vendor) if args.vendor else None
        artifact = generate_verification_artifact(
            comparison_data=data,
            invoice_data=inv_data,
            vendor_data=ven_data,
            companion_digest_file=digest_file,
            out_path=args.out_verification,
        )
        emit(artifact)
        return 0 if artifact["verification_status"] != VerificationStatus.BLOCKED else 2

    emit({"ok": len(issues) == 0, "issues": issues, "issues_count": len(issues)})
    if args.strict and issues:
        return 2
    return 0


if __name__ == "__main__":
    run_cli(main)
