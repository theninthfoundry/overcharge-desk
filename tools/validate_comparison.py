#!/usr/bin/env python3
"""Strict independent validator for comparison-result JSON.

Usage:
    python tools/validate_comparison.py COMPARE_JSON [--digest DIGEST_FILE] [--strict]

Validates schema 2.0.0, internal mathematical consistency, verification state
coherence, decimal bounds, contract variance calculations, and companion SHA-256 digests.
Exit code: 0 if valid; 2 if validation issues are found or file is invalid.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from common import (CURRENCY_RE, ToolError, emit, hash_comparison_result,
                    load_json, parse_date, q2, run_cli, to_decimal,
                    STATE_VERIFIED, STATE_REVIEW_REQUIRED, STATE_BLOCKED,
                    STATUS_VERIFIED_MATCH, STATUS_VERIFIED_OVERCHARGE, STATUS_VERIFIED_UNDERCHARGE,
                    STATUS_SOURCE_DISCREPANCY, STATUS_UNMATCHED, STATUS_REQUIRES_HUMAN_REVIEW)

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

    for idx, ln in enumerate(lines, start=1):
        if not isinstance(ln, dict):
            issues.append(f"Line {idx}: must be a dictionary")
            continue

        for rf in REQUIRED_LINE_FIELDS:
            if ln.get(rf) in (None, ""):
                issues.append(f"Line {idx}: missing required field {rf}")

        l_no = ln.get("line_no")
        if l_no in seen_lines:
            issues.append(f"Line {idx}: duplicate line_no {l_no}")
        seen_lines.add(l_no)

        status = ln.get("status")
        line_v_status = ln.get("verification_status")

        if status not in PERMITTED_LINE_STATUSES:
            issues.append(f"Line {l_no}: invalid status {status!r}")
        if line_v_status not in PERMITTED_LINE_VERIFICATION_STATUSES:
            issues.append(f"Line {l_no}: invalid verification_status {line_v_status!r}")

        # SOURCE DISCREPANCY LINE
        if status == STATUS_SOURCE_DISCREPANCY or line_v_status == STATUS_SOURCE_DISCREPANCY:
            count_discrepancy += 1
            if not ln.get("blocking"):
                issues.append(f"Line {l_no}: SOURCE_DISCREPANCY line must have blocking=True")
            if not ln.get("discrepancy"):
                issues.append(f"Line {l_no}: SOURCE_DISCREPANCY line missing discrepancy reason")
            continue

        # UNMATCHED LINE
        if status == STATUS_UNMATCHED or line_v_status == STATUS_UNMATCHED or status == "unmatched":
            count_unmatched += 1
            if not ln.get("unmatched_reason"):
                issues.append(f"Line {l_no}: unmatched line missing unmatched_reason")
            continue

        # VERIFIED MATCHED LINE
        if status == "matched":
            try:
                qty = to_decimal(ln.get("quantity"), f"line {l_no} quantity")
                inv_p = to_decimal(ln.get("invoiced_unit_price"), f"line {l_no} invoiced_unit_price")
                con_p = to_decimal(ln.get("contract_unit_price"), f"line {l_no} contract_unit_price")
                line_var = to_decimal(ln.get("line_variance"), f"line {l_no} line_variance")
                con_total = to_decimal(ln.get("contract_line_total"), f"line {l_no} contract_line_total")
                inv_computed = to_decimal(ln.get("invoiced_line_total_computed"), f"line {l_no} invoiced_line_total_computed")

                if qty <= 0:
                    issues.append(f"Line {l_no}: quantity must be positive (> 0), got {qty}")
                if inv_p < 0:
                    issues.append(f"Line {l_no}: invoiced_unit_price cannot be negative, got {inv_p}")
                if con_p < 0:
                    issues.append(f"Line {l_no}: contract_unit_price cannot be negative, got {con_p}")

                # Arithmetic parity: Qty x InvoicedUnitPrice == Computed
                calc_inv = q2(qty * inv_p)
                if calc_inv != inv_computed:
                    issues.append(f"Line {l_no}: arithmetic parity mismatch: {qty} x {inv_p} = {calc_inv} != computed {inv_computed}")

                # Contract total parity: Qty x ContractUnitPrice == ContractTotal
                calc_con = q2(qty * con_p)
                if calc_con != con_total:
                    issues.append(f"Line {l_no}: contract total mismatch: {qty} x {con_p} = {calc_con} != recorded {con_total}")

                # Variance parity: Qty x (InvoicedUnitPrice - ContractUnitPrice) == LineVariance
                calc_var = q2(qty * (inv_p - con_p))
                if calc_var != line_var:
                    issues.append(f"Line {l_no}: variance mismatch: {qty} x ({inv_p} - {con_p}) = {calc_var} != recorded {line_var}")

                sum_m_inv += inv_computed
                sum_m_con += con_total
                sum_m_var += line_var
                if line_var > 0:
                    sum_over += line_var
                elif line_var < 0:
                    sum_under += line_var

            except ToolError as exc:
                issues.append(f"Line {l_no}: numeric validation failure: {exc}")

    # 4. Totals reconciliation
    try:
        if "matched_invoiced" in totals and totals["matched_invoiced"] is not None:
            tot_inv = to_decimal(totals["matched_invoiced"], "totals.matched_invoiced")
            if tot_inv != sum_m_inv:
                issues.append(f"Totals mismatch: matched_invoiced {tot_inv} != sum of lines {sum_m_inv}")

        if "matched_per_contract" in totals and totals["matched_per_contract"] is not None:
            tot_con = to_decimal(totals["matched_per_contract"], "totals.matched_per_contract")
            if tot_con != sum_m_con:
                issues.append(f"Totals mismatch: matched_per_contract {tot_con} != sum of lines {sum_m_con}")

        if "variance_on_matched_lines" in totals and totals["variance_on_matched_lines"] is not None:
            tot_var = to_decimal(totals["variance_on_matched_lines"], "totals.variance_on_matched_lines")
            if tot_var != sum_m_var:
                issues.append(f"Totals mismatch: variance_on_matched_lines {tot_var} != sum of lines {sum_m_var}")

        if "verified_overcharge_total" in totals and totals["verified_overcharge_total"] is not None:
            tot_over = to_decimal(totals["verified_overcharge_total"], "totals.verified_overcharge_total")
            if tot_over != sum_over:
                issues.append(f"Totals mismatch: verified_overcharge_total {tot_over} != calculated {sum_over}")

        if "verified_undercharge_total" in totals and totals["verified_undercharge_total"] is not None:
            tot_under = to_decimal(totals["verified_undercharge_total"], "totals.verified_undercharge_total")
            if tot_under != sum_under:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json", help="Path to comparison result JSON")
    ap.add_argument("--digest", help="Optional path to companion .sha256 digest file")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 if any issues are found")
    args = ap.parse_args()

    data = load_json(args.compare_json)
    digest_file = args.digest
    if not digest_file:
        auto_digest = Path(f"{args.compare_json}.sha256")
        if auto_digest.exists():
            digest_file = auto_digest

    issues = validate_comparison(data, companion_digest_file=digest_file)
    emit({"ok": len(issues) == 0, "issues": issues, "issues_count": len(issues)})
    if args.strict and issues:
        return 2
    return 0


if __name__ == "__main__":
    run_cli(main)

