#!/usr/bin/env python3
"""Build partial_review.csv from a REVIEW_REQUIRED compare.py result.

Usage:
    python tools/partial_review.py COMPARE_JSON OUT_CSV [--digest DIGEST_FILE]

Rules:
- Strictly intended for investigative review of REVIEW_REQUIRED audits with unresolved items.
- Clearly flags incomplete evidence and unresolved contract rates.
- Never presents itself as a final or approved payment recommendation.
- Refuses BLOCKED audits (directs caller to blocked_review_report.py).
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, ToolError, emit,
                    load_json, money_str, run_cli, to_decimal)
from validate_comparison import validate_comparison

COLUMNS = [
    "line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
    "invoiced_line_total", "contract_coverage_status", "unresolved_reason", "notes"
]


def safe_text(value) -> str:
    """Stop spreadsheet apps from executing formula payloads."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_partial_review_rows(result: dict) -> tuple[list[list[str]], dict]:
    """Build partial review CSV rows from a REVIEW_REQUIRED comparison result."""
    issues = validate_comparison(result)
    if issues:
        raise ToolError(f"Cannot generate partial review for invalid comparison result: {'; '.join(issues)}", 2)

    v_status = result.get("verification_status")
    if v_status == STATE_BLOCKED:
        raise ToolError(
            "Cannot generate partial review for BLOCKED audit; use blocked_review_report.py instead.",
            2
        )

    lines = result.get("lines") or []
    rows: list[list[str]] = []
    invoiced_sum = Decimal(0)
    unmatched_count = 0
    matched_count = 0

    for ln in lines:
        l_no = ln.get("line_no", "")
        desc = safe_text(ln.get("description", ""))
        qty = safe_text(ln.get("quantity") or "")
        inv_p = safe_text(ln.get("invoiced_unit_price") or "")
        con_p = safe_text(ln.get("contract_unit_price") or "")
        line_v_status = ln.get("verification_status") or ln.get("status") or ""

        written = ln.get("invoiced_line_total_as_written") or ln.get("invoiced_line_total_computed") or ""
        if written:
            try:
                invoiced_sum += to_decimal(written)
            except ToolError:
                pass

        if ln.get("status") == "unmatched" or line_v_status == "UNMATCHED":
            unmatched_count += 1
            reason = ln.get("unmatched_reason") or "No matching contract rate"
            rows.append([
                str(l_no), desc, qty, inv_p, con_p,
                safe_text(written), "UNMATCHED", safe_text(reason),
                safe_text("UNRESOLVED - requires owner decision")
            ])
        else:
            matched_count += 1
            direction = ln.get("direction", "match")
            note = f"Contract rate matched ({direction} billing). Not approved for final disbursement."
            rows.append([
                str(l_no), desc, qty, inv_p, con_p,
                safe_text(written), "COVERED_BY_CONTRACT", "",
                safe_text(note)
            ])

    summary_label = f"TOTAL (REVIEW REQUIRED: {unmatched_count} unverified line(s), {matched_count} contract-covered line(s))"
    summary_note = safe_text(
        "INVESTIGATION ARTIFACT ONLY. NOT A FINAL PAYMENT RECOMMENDATION. Unresolved items require owner review and are excluded from any settlement."
    )

    rows.append([
        "", summary_label, "", "", "",
        money_str(invoiced_sum), "REVIEW_REQUIRED", "", summary_note
    ])

    summary = {
        "ok": True,
        "verification_status": STATE_REVIEW_REQUIRED,
        "artifact_type": "partial_review",
        "has_final_payment_recommendation": False,
        "invoiced_total": money_str(invoiced_sum),
        "unmatched_lines": unmatched_count,
        "matched_lines": matched_count
    }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json", help="Path to comparison result JSON")
    ap.add_argument("out_csv", help="Path to output partial_review.csv")
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

    rows, summary = build_partial_review_rows(data)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)

    emit(summary)
    return 0


if __name__ == "__main__":
    run_cli(main)

