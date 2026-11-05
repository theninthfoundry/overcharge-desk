#!/usr/bin/env python3
"""Check a Reader-written invoice.json: structure, source integrity, and internal arithmetic.

Usage:
    python tools/check_invoice.py cases/<case_id>/invoice.json [--update] [--strict]

Reports problems as plain facts. With --update, new problems are added to
extraction_issues (existing entries are kept, nothing is ever "fixed").
Exit code: 0 normally (issues reported as data); 2 if --strict and issues found, or file error.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import (CASE_ID_RE, CURRENCY_RE, ToolError, emit, is_safe_relative_path,
                    load_json, money_str, parse_date, q2, run_cli, sha256_file,
                    to_decimal, write_json_atomic)

TOP_FIELDS = ["case_id", "vendor_name_as_written", "invoice_number", "invoice_date",
              "currency", "stated_total", "source_file", "source_sha256"]
LINE_FIELDS = ["description", "quantity", "unit", "unit_price", "line_total"]
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def find_issues(inv: dict, base_dir: Path | str | None = None) -> list[str]:
    # Pure Inspection: Validates structure and arithmetic parity without modifying source facts
    issues: list[str] = []
    
    # 1. Top-level required fields
    for f in TOP_FIELDS:
        val = inv.get(f)
        if val in (None, ""):
            issues.append(f"Missing field: {f}")

    if inv.get("case_id") and not CASE_ID_RE.match(str(inv["case_id"])):
        issues.append(f"case_id format invalid: {inv['case_id']!r} (expected OC-YYYYMMDD-NN)")

    if inv.get("currency") and not CURRENCY_RE.match(str(inv["currency"])):
        issues.append(f"currency must be 3-letter ISO code: {inv['currency']!r}")

    if inv.get("invoice_date"):
        try:
            parse_date(inv["invoice_date"], "invoice_date")
        except ToolError:
            issues.append(f"invoice_date is not YYYY-MM-DD: {inv['invoice_date']!r}")

    # 2. Source file and fingerprint verification
    src = inv.get("source_file")
    src_sha = inv.get("source_sha256")
    if src_sha and not SHA_RE.match(str(src_sha)):
        issues.append(f"source_sha256 must be a 64-character hex digest: {src_sha!r}")

    if src:
        if not is_safe_relative_path(str(src)):
            issues.append(f"source_file contains invalid or unsafe path: {src!r}")
        else:
            base = Path(base_dir) if base_dir else Path.cwd()
            src_path = base / src if not Path(src).is_absolute() else Path(src)
            if src_path.exists() and src_path.is_file():
                calc_sha = sha256_file(str(src_path))
                if src_sha and calc_sha.lower() != str(src_sha).lower():
                    issues.append(
                        f"source_sha256 mismatch for {src}: calculated {calc_sha} != declared {src_sha}"
                    )
            else:
                issues.append(f"source_file not found on disk: {src}")

    # 3. Lines validation
    lines = inv.get("lines")
    if not isinstance(lines, list) or not lines:
        issues.append("Invoice has no lines")
        return issues

    seen_line_nos = set()
    total = None
    for i, ln in enumerate(lines, start=1):
        n = ln.get("line_no", i)
        if n in seen_line_nos:
            issues.append(f"Duplicate line_no: {n}")
        seen_line_nos.add(n)

        # Field presence
        for f in LINE_FIELDS:
            if ln.get(f) in (None, ""):
                issues.append(f"Line {n}: missing {f}")

        # Quantity
        qty = None
        if ln.get("quantity") is not None:
            try:
                qty = to_decimal(ln["quantity"], f"line {n} quantity")
                if qty <= 0:
                    issues.append(f"Line {n}: quantity must be positive (> 0), got {qty}")
            except ToolError as exc:
                issues.append(str(exc))

        # Unit price
        price = None
        if ln.get("unit_price") is not None:
            try:
                price = to_decimal(ln["unit_price"], f"line {n} unit_price")
                if price < 0:
                    issues.append(f"Line {n}: unit_price cannot be negative, got {price}")
            except ToolError as exc:
                issues.append(str(exc))

        # Line total
        lt = None
        if ln.get("line_total") is not None:
            try:
                lt = to_decimal(ln["line_total"], f"line {n} line_total")
                if lt < 0:
                    issues.append(f"Line {n}: line_total cannot be negative, got {lt}")
                else:
                    total = (total or 0) + q2(lt)
            except ToolError as exc:
                issues.append(str(exc))

        # Internal line arithmetic parity
        if qty is not None and price is not None and lt is not None and qty > 0 and price >= 0:
            calc = q2(qty * price)
            if calc != q2(lt):
                issues.append(
                    f"Line {n}: quantity x unit price = {money_str(calc)} "
                    f"but line total is written as {money_str(lt)}"
                )

    # 4. Stated total validation
    if total is not None and inv.get("stated_total") not in (None, ""):
        try:
            stated = q2(to_decimal(inv["stated_total"], "stated_total"))
            if stated != q2(total):
                issues.append(
                    f"Stated total {money_str(stated)} differs from the sum of line totals "
                    f"as written, {money_str(total)}"
                )
        except ToolError as exc:
            issues.append(str(exc))

    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json")
    ap.add_argument("--update", action="store_true", help="Add new issues into extraction_issues in file")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 if any issues are found")
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
    emit({"ok": True, "issues": issues, "issues_count": len(issues), "issues_added_to_file": added})
    if args.strict and issues:
        return 2
    return 0


if __name__ == "__main__":
    run_cli(main)
