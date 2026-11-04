#!/usr/bin/env python3
"""Check a Reader-written invoice.json: structure and the invoice's own arithmetic.

Usage:
    python tools/check_invoice.py cases/<case_id>/invoice.json [--update]

Reports problems as plain facts. With --update, new problems are added to
extraction_issues (existing entries are kept, nothing is ever "fixed").
Exit code 0 even when issues are found (they are data); 2 only for bad files.
"""
from __future__ import annotations

import argparse

from common import (ToolError, emit, load_json, money_str, parse_date, q2,
                    run_cli, to_decimal, write_json_atomic)

TOP_FIELDS = ["case_id", "vendor_name_as_written", "invoice_number", "invoice_date",
              "currency", "stated_total", "source_file", "source_sha256"]
LINE_FIELDS = ["description", "quantity", "unit_price", "line_total"]


def find_issues(inv: dict) -> list:
    issues = []
    for f in TOP_FIELDS:
        if inv.get(f) in (None, ""):
            issues.append(f"Missing field: {f}")
    if inv.get("invoice_date"):
        try:
            parse_date(inv["invoice_date"], "invoice_date")
        except ToolError:
            issues.append(f"invoice_date is not YYYY-MM-DD: {inv['invoice_date']!r}")
    lines = inv.get("lines")
    if not isinstance(lines, list) or not lines:
        issues.append("Invoice has no lines")
        return issues
    total = None
    for i, ln in enumerate(lines, start=1):
        n = ln.get("line_no", i)
        vals = {}
        for f in LINE_FIELDS:
            if ln.get(f) in (None, ""):
                issues.append(f"Line {n}: missing {f}")
                continue
            if f != "description":
                try:
                    vals[f] = to_decimal(ln[f], f"line {n} {f}")
                except ToolError as exc:
                    issues.append(f"Line {n}: {exc}")
        if {"quantity", "unit_price", "line_total"} <= vals.keys():
            calc = q2(vals["quantity"] * vals["unit_price"])
            if calc != q2(vals["line_total"]):
                issues.append(f"Line {n}: quantity x unit price = {money_str(calc)} "
                              f"but line total is written as {money_str(vals['line_total'])}")
        if "line_total" in vals:
            total = (total or 0) + q2(vals["line_total"])
    if total is not None and inv.get("stated_total") not in (None, ""):
        try:
            stated = q2(to_decimal(inv["stated_total"], "stated_total"))
            if stated != q2(total):
                issues.append(f"Stated total {money_str(stated)} differs from the sum of line totals "
                              f"as written, {money_str(total)}")
        except ToolError as exc:
            issues.append(str(exc))
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json")
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args()
    inv = load_json(args.invoice_json)
    issues = find_issues(inv)
    added = 0
    if args.update:
        existing = inv.get("extraction_issues")
        if not isinstance(existing, list):
            existing = []
        for issue in issues:
            if issue not in existing:
                existing.append(issue)
                added += 1
        inv["extraction_issues"] = existing
        write_json_atomic(args.invoice_json, inv)
    emit({"ok": True, "issues": issues, "issues_added_to_file": added})
    return 0


if __name__ == "__main__":
    run_cli(main)

# Schema integrity and mathematical parity check

# Option to persist issues back into extraction records

# Flags discrepancies between unit prices and line totals
