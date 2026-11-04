#!/usr/bin/env python3
"""Build corrected_payment.csv from a saved compare.py result.

Usage:
    python tools/payment_sheet.py COMPARE_JSON OUT_CSV

Rules: over-billed lines pay the contract price and withhold the difference;
lines at the contract price or below it pay as invoiced; unmatched lines are
left unpaid-by-formula and marked for the owner. Nothing here moves money.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal

from common import ToolError, emit, load_json, money_str, q2, run_cli, to_decimal

COLUMNS = ["line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
           "invoiced_line_total", "payable_line_total", "withheld_amount", "note"]


def safe_text(value) -> str:
    """Stop spreadsheet apps from running text that starts like a formula."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_rows(result: dict):
    if not result.get("ok"):
        raise ToolError("Compare result is not an ok result; refusing to build a sheet")
    rows = []
    invoiced = payable = withheld = Decimal(0)
    unmatched = 0
    for ln in result["lines"]:
        if ln["status"] == "unmatched":
            unmatched += 1
            written = ln.get("invoiced_line_total_as_written")
            if written is not None:
                invoiced += to_decimal(written)
            rows.append([ln["line_no"], safe_text(ln.get("description")), "", "", "",
                         written or "", "", "",
                         safe_text("UNVERIFIED - owner to decide. " + (ln.get("unmatched_reason") or ""))])
            continue
        qty = to_decimal(ln["quantity"])
        inv_total = to_decimal(ln["invoiced_line_total_computed"])
        if ln["direction"] == "over":
            pay = q2(qty * to_decimal(ln["contract_unit_price"]))
            hold = to_decimal(ln["line_variance"])
            note = "Billed above contract rate: paying contract amount, difference withheld"
        elif ln["direction"] == "under":
            pay, hold = inv_total, Decimal(0)
            note = "Invoiced below contract rate: paying as invoiced"
        else:
            pay, hold = inv_total, Decimal(0)
            note = "Matches contract"
        invoiced += inv_total
        payable += pay
        withheld += hold
        rows.append([ln["line_no"], safe_text(ln["description"]), ln["quantity"], ln["invoiced_unit_price"],
                     ln["contract_unit_price"], money_str(inv_total), money_str(pay), money_str(hold), note])
    label = "TOTAL"
    note = "Draft for the owner. No payment has been made."
    if unmatched:
        label = f"TOTAL (INCOMPLETE: {unmatched} line(s) unverified)"
        note = "Payable covers verified lines only. " + note
    rows.append(["", label, "", "", "", money_str(invoiced), money_str(payable), money_str(withheld), note])
    summary = {"ok": True, "complete": unmatched == 0, "invoiced_total": money_str(invoiced),
               "payable_total": money_str(payable), "withheld_total": money_str(withheld),
               "unverified_lines": unmatched}
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("compare_json")
    ap.add_argument("out_csv")
    args = ap.parse_args()
    rows, summary = build_rows(load_json(args.compare_json))
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    summary["file"] = args.out_csv
    emit(summary)
    return 0


if __name__ == "__main__":
    run_cli(main)
