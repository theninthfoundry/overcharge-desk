#!/usr/bin/env python3
"""Build blocked_review_report.csv from a BLOCKED compare.py result.

Usage:
    python tools/blocked_review_report.py COMPARE_JSON OUT_CSV [--digest DIGEST_FILE]

Rules:
- Strictly intended for investigative reporting of BLOCKED audits.
- Contains NO payable amounts, NO payment instructions, and NO recommended settlement.
- Validates the comparison result before producing the report.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import (STATE_BLOCKED, ToolError, emit, load_json, run_cli)
from validate_comparison import validate_comparison

COLUMNS = [
    "line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
    "invoiced_line_total_as_written", "invoiced_line_total_computed",
    "discrepancy_reason", "source_ref", "verification_status"
]


def safe_text(value) -> str:
    """Stop spreadsheet apps from executing formula payloads."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_blocked_rows(result: dict) -> tuple[list[list[str]], dict]:
    """Build investigative CSV rows from a BLOCKED comparison result."""
    issues = validate_comparison(result)
    if issues:
        raise ToolError(f"Cannot generate blocked review report for invalid comparison result: {'; '.join(issues)}", 2)

    v_status = result.get("verification_status")
    blocking = result.get("blocking_issues") or []
    lines = result.get("lines") or []
    disc_count = sum(1 for ln in lines if ln.get("status") == "SOURCE_DISCREPANCY" or ln.get("verification_status") == "SOURCE_DISCREPANCY")

    if v_status != STATE_BLOCKED and not blocking and disc_count == 0:
        raise ToolError(
            f"blocked_review_report only processes BLOCKED audits. Current status: {v_status}",
            2
        )

    rows: list[list[str]] = []
    for ln in lines:
        l_no = ln.get("line_no", "")
        desc = safe_text(ln.get("description", ""))
        qty = safe_text(ln.get("quantity") or "")
        inv_p = safe_text(ln.get("invoiced_unit_price") or "")
        con_p = safe_text(ln.get("contract_unit_price") or "")
        written = safe_text(ln.get("invoiced_line_total_as_written") or "")
        computed = safe_text(ln.get("invoiced_line_total_computed") or "")
        s_ref = safe_text(ln.get("source_ref") or "")
        line_v_status = safe_text(ln.get("verification_status") or ln.get("status") or "")

        disc_reason = ln.get("discrepancy") or ln.get("unmatched_reason") or ""
        if not disc_reason and ln.get("status") == "SOURCE_DISCREPANCY":
            disc_reason = "Source arithmetic mismatch or invalid numeric values"
        elif not disc_reason and line_v_status.startswith("VERIFIED"):
            disc_reason = "Line arithmetic sound, but audit blocked by invoice-level integrity issues"

        rows.append([
            str(l_no), desc, qty, inv_p, con_p,
            written, computed, safe_text(disc_reason), s_ref, line_v_status
        ])

    issues_summary = "; ".join(blocking) if blocking else f"{disc_count} discrepancy lines detected"
    summary_label = f"TOTAL (BLOCKED AUDIT: {disc_count} discrepancy lines, {len(blocking)} blocking issues)"
    summary_note = safe_text(
        f"INVESTIGATION EVIDENCE ONLY - NO PAYMENT AUTHORIZATION. Issues: {issues_summary}"
    )

    rows.append([
        "", summary_label, "", "", "",
        "", "", summary_note, "", "AUDIT_BLOCKED"
    ])

    summary = {
        "ok": True,
        "verification_status": STATE_BLOCKED,
        "artifact_type": "blocked_review_report",
        "has_payable_recommendation": False,
        "discrepancy_count": disc_count,
        "blocking_issues_count": len(blocking),
        "blocking_issues": blocking
    }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json", help="Path to comparison result JSON")
    ap.add_argument("out_csv", help="Path to output blocked_review_report.csv")
    ap.add_argument("--digest", help="Optional companion digest file")
    args = ap.parse_args()

    data = load_json(args.compare_json)
    digest_path = args.digest
    if not digest_path:
        auto_digest = Path(f"{args.compare_json}.sha256")
        if auto_digest.exists():
            digest_path = auto_digest

    if digest_path:
        issues = validate_comparison(data, companion_digest_file=digest_path)
        if issues:
            raise ToolError(f"Digest validation failed: {'; '.join(issues)}", 2)

    rows, summary = build_blocked_rows(data)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)

    emit(summary)
    return 0


if __name__ == "__main__":
    run_cli(main)
