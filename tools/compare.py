#!/usr/bin/env python3
"""Deterministic invoice-vs-contract comparison. All arithmetic is exact decimal.

Usage:
    python tools/compare.py INVOICE_JSON VENDOR_JSON [--out FILE]

Exit codes: 0 ok | 2 bad input | 3 vendor or currency problem (stop, do not guess)
Amounts are strings rounded half-up to 2 decimals per line; totals add the
rounded lines. Copy numbers from the output exactly; never recalculate them.
"""
from __future__ import annotations

import argparse
import re

from common import (ToolError, emit, exact_str, load_json, money_str, norm,
                    num_str, parse_date, q2, run_cli, to_decimal,
                    write_json_atomic)

ZERO = to_decimal(0)


def vendor_matches(invoice: dict, vendor: dict) -> bool:
    names = {norm(vendor.get("name", ""))} | {norm(a) for a in vendor.get("aliases", [])}
    names.discard("")
    return norm(invoice.get("vendor_name_as_written") or "") in names


def candidate_item_keys(description: str, rates: list) -> set:
    """Contract items this invoice description could mean (by exact label or SKU)."""
    n = norm(description)
    keys = set()
    for r in rates:
        labels = {norm(r.get("description", ""))} | {norm(a) for a in r.get("aliases", [])}
        labels.discard("")
        hit = n in labels
        sku = r.get("sku")
        if not hit and sku:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(sku) + r"(?![A-Za-z0-9])"
            hit = re.search(pattern, description, re.IGNORECASE) is not None
        if hit:
            keys.add(r["item_key"])
    return keys


def rates_in_force(rates: list, item_key: str, on) -> list:
    found = []
    for r in rates:
        if r.get("item_key") != item_key:
            continue
        start = parse_date(r.get("effective_from"), f"effective_from of {item_key}")
        end = parse_date(r["effective_to"], f"effective_to of {item_key}") if r.get("effective_to") else None
        if start <= on and (end is None or on <= end):
            found.append(r)
    return found


def compare(invoice: dict, vendor: dict) -> dict:
    if not vendor_matches(invoice, vendor):
        raise ToolError(
            f"Invoice vendor {invoice.get('vendor_name_as_written')!r} does not match "
            f"the name or aliases of vendor {vendor.get('vendor_id')!r}", 3)
    currency = invoice.get("currency")
    if not currency:
        raise ToolError("Invoice currency is missing; refusing to assume one", 3)
    inv_date = parse_date(invoice.get("invoice_date"), "invoice_date")
    contract = vendor.get("contract") or {}
    rates = contract.get("rates") or []
    if not rates:
        raise ToolError("Vendor has no contract rates on file", 3)
    lines_in = invoice.get("lines") or []
    if not lines_in:
        raise ToolError("Invoice has no lines")

    lines_out = []
    warnings = []
    m_inv = m_con = m_var = ZERO
    unmatched_sum = ZERO
    unmatched_sum_known = True
    written_sum = ZERO
    written_sum_known = True

    for position, ln in enumerate(lines_in, start=1):
        line_no = ln.get("line_no", position)
        desc = ln.get("description")
        written = None
        if ln.get("line_total") is not None:
            written = q2(to_decimal(ln["line_total"], f"line {line_no} line_total"))
        if written is None:
            written_sum_known = False
        else:
            written_sum += written

        base = {"line_no": line_no, "description": desc}
        qty_raw, price_raw = ln.get("quantity"), ln.get("unit_price")
        reason = None
        rate = None
        qty = price = computed = None

        if qty_raw is None or price_raw is None or not desc:
            reason = "missing description, quantity or unit price in invoice.json"
        else:
            qty = to_decimal(qty_raw, f"line {line_no} quantity")
            price = to_decimal(price_raw, f"line {line_no} unit_price")
            computed = q2(qty * price)
            keys = candidate_item_keys(desc, rates)
            if not keys:
                reason = "no contract item matches this description"
            elif len(keys) > 1:
                reason = "description matches more than one contract item: " + ", ".join(sorted(keys))
            else:
                key = next(iter(keys))
                inforce = rates_in_force(rates, key, inv_date)
                if not inforce:
                    reason = f"no rate in effect on {inv_date.isoformat()} for {key}"
                elif len(inforce) > 1:
                    reason = f"contract has overlapping rates for {key} on {inv_date.isoformat()}"
                else:
                    rate = inforce[0]
                    if rate.get("currency") != currency:
                        raise ToolError(
                            f"Currency differs on line {line_no}: invoice {currency}, "
                            f"contract {rate.get('currency')}. Not converting.", 3)

        if rate is None:
            amount = written if written is not None else computed
            if amount is None:
                unmatched_sum_known = False
            else:
                unmatched_sum += amount
            lines_out.append({**base, "status": "unmatched", "unmatched_reason": reason,
                              "invoiced_line_total_as_written": money_str(written) if written is not None else None})
            continue

        contract_price = to_decimal(rate["unit_price"], f"contract price of {rate['item_key']}")
        per_unit = price - contract_price
        line_var = q2(qty * per_unit)
        contract_total = q2(qty * contract_price)
        pct = None
        if contract_price != 0:
            pct = format(q2(per_unit / contract_price * 100), "f")
        direction = "over" if per_unit > 0 else "under" if per_unit < 0 else "match"
        total_ok = None if written is None else (written == computed)
        if total_ok is False:
            warnings.append(f"Line {line_no}: quantity x unit price = {money_str(computed)} "
                            f"but line total is written as {money_str(written)}")
        m_inv += computed
        m_con += contract_total
        m_var += line_var
        lines_out.append({
            **base, "status": "matched", "item_key": rate["item_key"], "clause_ref": rate.get("clause_ref"),
            "quantity": num_str(qty), "invoiced_unit_price": exact_str(price),
            "contract_unit_price": exact_str(contract_price), "variance_per_unit": exact_str(per_unit),
            "line_variance": money_str(line_var), "variance_pct": pct, "direction": direction,
            "contract_line_total": money_str(contract_total),
            "invoiced_line_total_computed": money_str(computed),
            "invoiced_line_total_as_written": money_str(written) if written is not None else None,
            "line_total_matches": total_ok,
        })

    complete = not any(l["status"] == "unmatched" for l in lines_out)
    stated = invoice.get("stated_total")
    stated_d = q2(to_decimal(stated, "stated_total")) if stated is not None else None
    stated_ok = None
    if stated_d is not None and written_sum_known:
        stated_ok = stated_d == q2(written_sum)
        if not stated_ok:
            warnings.append(f"Stated total {money_str(stated_d)} differs from the sum of line totals "
                            f"as written, {money_str(written_sum)}")

    return {
        "ok": True,
        "case_id": invoice.get("case_id"),
        "vendor_id": vendor.get("vendor_id"),
        "contract_id": contract.get("contract_id"),
        "invoice_number": invoice.get("invoice_number"),
        "invoice_date": inv_date.isoformat(),
        "currency": currency,
        "rounding": "half-up to 2 decimals per line; totals add the rounded lines",
        "lines": lines_out,
        "totals": {
            "complete": complete,
            "matched_invoiced": money_str(m_inv),
            "matched_per_contract": money_str(m_con),
            "variance_on_matched_lines": money_str(m_var),
            "unmatched_invoiced_as_written": money_str(unmatched_sum) if unmatched_sum_known else None,
            "invoiced_total": money_str(m_inv + unmatched_sum) if unmatched_sum_known else None,
            "per_contract_total": money_str(m_con) if complete else None,
            "stated_total_as_written": money_str(stated_d) if stated_d is not None else None,
            "sum_of_line_totals_as_written": money_str(written_sum) if written_sum_known else None,
            "stated_total_matches": stated_ok,
        },
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json")
    ap.add_argument("vendor_json")
    ap.add_argument("--out", help="also save the result to this file")
    args = ap.parse_args()
    result = compare(load_json(args.invoice_json), load_json(args.vendor_json))
    if args.out:
        write_json_atomic(args.out, result)
    emit(result)
    return 0


if __name__ == "__main__":
    run_cli(main)

# Evaluates rate schedules active on invoice date

# Per-unit and extended line total variance calculations

# Computes directional drift: over, under, or match
