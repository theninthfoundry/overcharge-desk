#!/usr/bin/env python3
"""Build corrected_payment.csv from a verified compare.py result.

Usage:
    python tools/payment_sheet.py COMPARE_JSON OUT_CSV [--allow-blocked-draft]

Rules:
- If the compare result is BLOCKED, payment recommendation is strictly refused.
- Over-billed lines pay the contract price and withhold the difference.
- Lines at contract price or below it pay as invoiced.
- Unmatched lines and discrepancy lines are unverified and excluded from payable sums.
- Taxes and freight are unverified per contract terms.
- Nothing here moves money or executes transactions.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal

from common import (STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATUS_SOURCE_DISCREPANCY,
                    STATUS_UNMATCHED, ToolError, emit, load_json, money_str, q2,
                    run_cli, to_decimal)

COLUMNS = ["line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
           "invoiced_line_total", "payable_line_total", "withheld_amount", "note"]


def safe_text(value) -> str:
    """Stop spreadsheet apps from executing formula payloads."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_rows(result: dict, allow_blocked_draft: bool = False):
    if not result.get("ok"):
        raise ToolError("Compare result is not an ok result; refusing to build a sheet")

    v_status = result.get("verification_status")
    blocking = result.get("blocking_issues") or []

    # FAIL-CLOSED: Refuse to generate an approval payment sheet on a blocked audit
    if (v_status == STATE_BLOCKED or blocking) and not allow_blocked_draft:
        issues_summary = "; ".join(blocking) if blocking else "Source arithmetic discrepancy or integrity failure"
        raise ToolError(
            f"PAYMENT_RECOMMENDATION_BLOCKED: Cannot generate payment sheet for blocked audit. Issues: {issues_summary}",
            2
        )

    rows = []
    invoiced = payable = withheld = Decimal(0)
    unmatched_count = 0
    discrepancy_count = 0

    for ln in result.get("lines", []):
        status = ln.get("status")
        line_no = ln.get("line_no", "")
        desc = safe_text(ln.get("description"))

        # 1. Source Discrepancy Lines
        if status in ("SOURCE_DISCREPANCY", "source_discrepancy") or ln.get("verification_status") == STATUS_SOURCE_DISCREPANCY:
            discrepancy_count += 1
            written = ln.get("invoiced_line_total_as_written") or ""
            rows.append([
                line_no, desc, ln.get("quantity") or "", ln.get("invoiced_unit_price") or "",
                ln.get("contract_unit_price") or "", written, "", "",
                safe_text("BLOCKED - SOURCE DISCREPANCY: " + (ln.get("discrepancy") or "arithmetic mismatch"))
            ])
            continue

        # 2. Unmatched Lines
        if status in ("unmatched", "UNMATCHED") or ln.get("verification_status") == STATUS_UNMATCHED:
            unmatched_count += 1
            written = ln.get("invoiced_line_total_as_written")
            if written is not None:
                try:
                    invoiced += to_decimal(written)
                except ToolError:
                    pass
            rows.append([
                line_no, desc, "", "", "",
                written or "", "", "",
                safe_text("UNVERIFIED - UNMATCHED: " + (ln.get("unmatched_reason") or "owner to decide"))
            ])
            continue

        # 3. Verified Lines (VERIFIED_OVERCHARGE, VERIFIED_UNDERCHARGE, VERIFIED_MATCH, or legacy matched)
        qty = to_decimal(ln["quantity"])
        inv_total = to_decimal(ln["invoiced_line_total_computed"])
        direction = ln.get("direction")

        if direction == "over" or status == "VERIFIED_OVERCHARGE":
            pay = q2(qty * to_decimal(ln["contract_unit_price"]))
            hold = to_decimal(ln["line_variance"])
            note = "Billed above contract rate: paying contract amount, difference withheld"
        elif direction == "under" or status == "VERIFIED_UNDERCHARGE":
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
            line_no, desc, ln["quantity"], ln["invoiced_unit_price"],
            ln["contract_unit_price"], money_str(inv_total), money_str(pay), money_str(hold), note
        ])

    # Summary row construction
    note = "Draft for owner review. No payment made. Taxes and freight are unverified per contract terms."
    if v_status == STATE_BLOCKED or discrepancy_count > 0:
        label = f"TOTAL (BLOCKED: {discrepancy_count} discrepancy line(s) detected)"
        note = "PAYMENT BLOCKED DUE TO SOURCE DISCREPANCY. " + note
    elif unmatched_count > 0:
        label = f"TOTAL (GOODS ONLY - INCOMPLETE: {unmatched_count} unverified line(s))"
        note = "Payable covers verified goods lines only. " + note
    else:
        label = "TOTAL (GOODS ONLY - VERIFIED)"

    rows.append(["", label, "", "", "", money_str(invoiced), money_str(payable), money_str(withheld), note])

    complete = (unmatched_count == 0 and discrepancy_count == 0 and v_status == "VERIFIED")
    summary = {
        "ok": True,
        "verification_status": v_status or ("VERIFIED" if complete else "REVIEW_REQUIRED"),
        "complete": complete,
        "invoiced_total": money_str(invoiced),
        "payable_total": money_str(payable),
        "withheld_total": money_str(withheld),
        "unverified_lines": unmatched_count + discrepancy_count,
        "taxes_and_freight_unverified": True
    }
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json")
    ap.add_argument("out_csv")
    ap.add_argument("--allow-blocked-draft", action="store_true",
                    help="Allow generating a blocked draft CSV even if verification failed")
    args = ap.parse_args()
    rows, summary = build_rows(load_json(args.compare_json), allow_blocked_draft=args.allow_blocked_draft)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    summary["file"] = args.out_csv
    emit(summary)
    return 0


if __name__ == "__main__":
    run_cli(main)
