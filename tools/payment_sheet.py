#!/usr/bin/env python3
"""Build corrected_payment.csv from a fully VERIFIED compare.py result.

Usage:
    python tools/payment_sheet.py COMPARE_JSON OUT_CSV [--digest DIGEST_FILE]

Rules:
- Strictly restricted to fully VERIFIED comparison results.
- Refuses BLOCKED results (no payment recommendations under any circumstances).
- Refuses REVIEW_REQUIRED results (caller must use partial_review.py).
- Over-billed lines pay the contract price and withhold the difference.
- Lines at contract price or below it pay as invoiced.
- Taxes and freight are unverified per contract terms.
- Validates comparison result structure and math before generating sheet.
- Nothing here moves money or executes transactions.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from common import (STATE_VERIFIED, ToolError, emit, load_json, money_str,
                    q2, run_cli, to_decimal)
from validate_comparison import validate_comparison

COLUMNS = ["line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
           "invoiced_line_total", "payable_line_total", "withheld_amount", "note"]


def safe_text(value) -> str:
    """Stop spreadsheet apps from executing formula payloads."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_rows(result: dict, validate: bool = True) -> tuple[list[list[str]], dict]:
    """Build payment recommendation rows for a verified comparison result."""
    if not isinstance(result, dict) or not result.get("ok"):
        raise ToolError("Compare result is not an ok result; refusing to build a sheet")

    if validate:
        issues = validate_comparison(result)
        if issues:
            raise ToolError(
                f"PAYMENT_RECOMMENDATION_BLOCKED: Invalid comparison result: {'; '.join(issues)}",
                2
            )

    v_status = result.get("verification_status")
    blocking = result.get("blocking_issues") or []

    # FAIL-CLOSED: Refuse any result that is not fully VERIFIED
    if v_status != STATE_VERIFIED or blocking:
        issues_summary = "; ".join(blocking) if blocking else f"Audit verification status is {v_status}"
        raise ToolError(
            f"PAYMENT_RECOMMENDATION_BLOCKED: payment_sheet only generates corrected_payment.csv for fully VERIFIED audits. "
            f"Status is {v_status}. For REVIEW_REQUIRED audits use partial_review.py; for BLOCKED audits use blocked_review_report.py. "
            f"Issues: {issues_summary}",
            2
        )

    rows = []
    invoiced = payable = withheld = Decimal(0)
    lines = result.get("lines", [])

    for ln in lines:
        status = ln.get("status")
        line_no = ln.get("line_no", "")
        desc = safe_text(ln.get("description"))

        # Defensive check against unverified lines in payment sheet
        if status in ("unmatched", "SOURCE_DISCREPANCY") or ln.get("verification_status") in ("UNMATCHED", "SOURCE_DISCREPANCY"):
            raise ToolError(
                f"PAYMENT_RECOMMENDATION_REFUSED: Line {line_no} has status {status!r}; cannot produce a final payment sheet with unverified lines.",
                2
            )

        qty = to_decimal(ln["quantity"])
        inv_total = to_decimal(ln["invoiced_line_total_computed"])
        direction = ln.get("direction")

        if direction == "over" or ln.get("verification_status") == "VERIFIED_OVERCHARGE":
            pay = q2(qty * to_decimal(ln["contract_unit_price"]))
            hold = to_decimal(ln["line_variance"])
            note = "Billed above contract rate: paying contract amount, difference withheld"
        elif direction == "under" or ln.get("verification_status") == "VERIFIED_UNDERCHARGE":
            pay = inv_total
            hold = Decimal(0)
            note = "Invoiced below contract rate: paying as invoiced"
        else:
            pay = inv_total
            hold = Decimal(0)
            note = "Matches contract rate"

        invoiced += inv_total
        payable += pay
        withheld += hold

        rows.append([
            str(line_no), desc, str(ln["quantity"]), str(ln["invoiced_unit_price"]),
            str(ln["contract_unit_price"]), money_str(inv_total), money_str(pay), money_str(hold), note
        ])

    label = "TOTAL (GOODS ONLY - VERIFIED)"
    note = "Draft for owner review. No payment made. Taxes and freight are unverified per contract terms."
    rows.append(["", label, "", "", "", money_str(invoiced), money_str(payable), money_str(withheld), note])

    summary = {
        "ok": True,
        "verification_status": STATE_VERIFIED,
        "artifact_type": "corrected_payment",
        "complete": True,
        "invoiced_total": money_str(invoiced),
        "payable_total": money_str(payable),
        "withheld_total": money_str(withheld),
        "unverified_lines": 0,
        "taxes_and_freight_unverified": True
    }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json")
    ap.add_argument("out_csv")
    ap.add_argument("--digest", help="Optional companion digest file to verify")
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

    rows, summary = build_rows(data)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    summary["file"] = args.out_csv
    emit(summary)
    return 0


if __name__ == "__main__":
    run_cli(main)
