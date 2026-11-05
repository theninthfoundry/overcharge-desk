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
from pathlib import Path

from common import (CENT, ToolError, emit, exact_str, is_safe_relative_path,
                    load_json, money_str, norm, num_str, parse_date, q2,
                    run_cli, sha256_file, to_decimal, write_json_atomic,
                    save_comparison_with_digest, hash_comparison_result,
                    STATE_VERIFIED, STATE_REVIEW_REQUIRED, STATE_BLOCKED,
                    STATUS_VERIFIED_MATCH, STATUS_VERIFIED_OVERCHARGE, STATUS_VERIFIED_UNDERCHARGE,
                    STATUS_SOURCE_DISCREPANCY, STATUS_UNMATCHED, STATUS_REQUIRES_HUMAN_REVIEW)

SCHEMA_VERSION = "2.0.0"
ZERO = to_decimal(0)
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def vendor_matches(invoice: dict, vendor: dict) -> bool:
    names = {norm(vendor.get("name", ""))} | {norm(a) for a in vendor.get("aliases", [])}
    names.discard("")
    return norm(invoice.get("vendor_name_as_written") or "") in names


def candidate_item_keys(description: str, rates: list) -> set:
    # Boundary Matching: Word-boundary SKU matching preventing substring false positives
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


def compare(invoice: dict, vendor: dict, base_dir: Path | str | None = None) -> dict:
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
    warnings: list[str] = []
    blocking_issues: list[str] = []
    unresolved_evidence: list[str] = []

    # Mandatory Source Integrity Verification (Fail-Closed Invariant)
    src = invoice.get("source_file")
    src_sha = invoice.get("source_sha256")
    src_verified = False

    if not src:
        blocking_issues.append("Invoice missing source_file")
    elif not is_safe_relative_path(str(src)):
        blocking_issues.append(f"source_file contains invalid or unsafe path: {src!r}")
    else:
        base = Path(base_dir) if base_dir else Path.cwd()
        src_path = base / src if not Path(src).is_absolute() else Path(src)
        if not (src_path.exists() and src_path.is_file()):
            blocking_issues.append(f"source_file not found on disk: {src}")
        elif not src_sha or not SHA_RE.match(str(src_sha)):
            blocking_issues.append(f"Invoice missing or malformed source_sha256: {src_sha!r}")
        else:
            calc_sha = sha256_file(str(src_path))
            if calc_sha.lower() != str(src_sha).lower():
                blocking_issues.append(
                    f"source_sha256 mismatch for {src}: calculated {calc_sha} != declared {src_sha}"
                )
            else:
                src_verified = True

    seen_line_nos = set()
    written_sum = ZERO
    written_sum_known = True

    # Verified metrics (only incremented when line is verified)
    m_inv = m_con = m_var = ZERO
    verified_overcharge = ZERO
    verified_undercharge = ZERO

    unmatched_sum = ZERO
    unmatched_sum_known = True
    unmatched_count = 0
    source_discrepancy_count = 0

    for position, ln in enumerate(lines_in, start=1):
        line_no = ln.get("line_no", position)
        if line_no in seen_line_nos:
            blocking_issues.append(f"Duplicate line_no {line_no}")
        seen_line_nos.add(line_no)

        desc = ln.get("description")
        source_ref = ln.get("source_ref") or f"line-{line_no}"
        written = None
        if ln.get("line_total") is not None:
            try:
                written_d = to_decimal(ln["line_total"], f"line {line_no} line_total")
                if written_d < ZERO:
                    blocking_issues.append(f"Line {line_no}: line_total cannot be negative, got {written_d}")
                written = q2(written_d)
                written_sum += written
            except ToolError as exc:
                blocking_issues.append(str(exc))
                written_sum_known = False
        else:
            written_sum_known = False

        base = {
            "line_no": line_no,
            "description": desc,
            "source_ref": source_ref
        }

        qty_raw, price_raw = ln.get("quantity"), ln.get("unit_price")
        rate = None
        qty = price = computed = None
        reason = None
        line_invalid = False

        if qty_raw is None or price_raw is None or not desc:
            reason = "missing description, quantity or unit price in invoice.json"
            unresolved_evidence.append(f"Line {line_no}: {reason}")
        else:
            try:
                qty = to_decimal(qty_raw, f"line {line_no} quantity")
                if qty <= ZERO:
                    blocking_issues.append(f"Line {line_no}: quantity must be positive (> 0), got {qty}")
                    line_invalid = True
            except ToolError as exc:
                blocking_issues.append(str(exc))
                line_invalid = True

            try:
                price = to_decimal(price_raw, f"line {line_no} unit_price")
                if price < ZERO:
                    blocking_issues.append(f"Line {line_no}: unit_price cannot be negative, got {price}")
                    line_invalid = True
            except ToolError as exc:
                blocking_issues.append(str(exc))
                line_invalid = True

            if qty is not None and price is not None and not line_invalid:
                computed = q2(qty * price)

        # Check internal line arithmetic parity: (written == computed)
        arithmetic_discrepancy = False
        if written is not None and computed is not None:
            if written != computed:
                arithmetic_discrepancy = True
                source_discrepancy_count += 1
                msg = (f"Line {line_no}: source arithmetic discrepancy: quantity ({num_str(qty)}) x "
                       f"unit price ({exact_str(price)}) = {money_str(computed)} "
                       f"but line total is written as {money_str(written)}")
                blocking_issues.append(msg)
                warnings.append(msg)

        # Attempt contract matching if description and rates exist
        keys = candidate_item_keys(desc, rates) if (desc and not line_invalid) else set()
        matched_key = None
        if not keys and not reason and not line_invalid:
            reason = "no contract item matches this description"
            unresolved_evidence.append(f"Line {line_no} ({desc!r}): no contract rate match")
        elif len(keys) > 1 and not reason and not line_invalid:
            reason = "description matches more than one contract item: " + ", ".join(sorted(keys))
            unresolved_evidence.append(f"Line {line_no} ({desc!r}): ambiguous match")
        elif len(keys) == 1 and not reason and not line_invalid:
            matched_key = next(iter(keys))
            inforce = rates_in_force(rates, matched_key, inv_date)
            if not inforce:
                reason = f"no rate in effect on {inv_date.isoformat()} for {matched_key}"
                unresolved_evidence.append(f"Line {line_no}: no rate active on {inv_date.isoformat()}")
            elif len(inforce) > 1:
                reason = f"contract has overlapping rates for {matched_key} on {inv_date.isoformat()}"
                blocking_issues.append(f"Line {line_no}: {reason}")
            else:
                rate = inforce[0]
                if rate.get("currency") != currency:
                    raise ToolError(
                        f"Currency differs on line {line_no}: invoice {currency}, "
                        f"contract {rate.get('currency')}. Not converting.", 3)

        # IF ARITHMETIC DISCREPANCY OR INVALID LINE: Line status MUST be SOURCE_DISCREPANCY (Critical Invariant)
        if arithmetic_discrepancy or line_invalid:
            if line_invalid and not arithmetic_discrepancy:
                source_discrepancy_count += 1
            lines_out.append({
                **base,
                "status": STATUS_SOURCE_DISCREPANCY,
                "verification_status": STATUS_SOURCE_DISCREPANCY,
                "contract_matching_status": "matched" if rate else "unmatched",
                "source_arithmetic_status": "DISCREPANCY",
                "item_key": rate["item_key"] if rate else matched_key,
                "clause_ref": rate.get("clause_ref") if rate else None,
                "quantity": num_str(qty) if qty is not None else (str(qty_raw) if qty_raw is not None else None),
                "invoiced_unit_price": exact_str(price) if price is not None else (str(price_raw) if price_raw is not None else None),
                "contract_unit_price": exact_str(to_decimal(rate["unit_price"])) if rate else None,
                "invoiced_line_total_as_written": money_str(written) if written is not None else None,
                "invoiced_line_total_computed": money_str(computed) if computed is not None else None,
                "line_total_matches": False,
                "discrepancy": (
                    f"quantity x price = {money_str(computed)} != written {money_str(written)}"
                    if arithmetic_discrepancy else
                    f"invalid numeric data on line {line_no}: quantity={qty_raw}, unit_price={price_raw}"
                ),
                "blocking": True
            })
            continue

        # IF NO CONTRACT RATE: Line is UNMATCHED
        if rate is None:
            unmatched_count += 1
            amount = written if written is not None else computed
            if amount is None:
                unmatched_sum_known = False
            else:
                unmatched_sum += amount
            lines_out.append({
                **base,
                "status": "unmatched",
                "verification_status": STATUS_UNMATCHED,
                "contract_matching_status": "unmatched",
                "source_arithmetic_status": "VERIFIED" if (written is not None and computed is not None and written == computed) else "INCOMPLETE",
                "unmatched_reason": reason,
                "invoiced_line_total_as_written": money_str(written) if written is not None else None,
                "invoiced_line_total_computed": money_str(computed) if computed is not None else None,
                "line_total_matches": True if (written is not None and computed is not None and written == computed) else None
            })
            continue

        # VERIFIED LINE: Arithmetic is sound AND contract rate is matched
        contract_price = to_decimal(rate["unit_price"], f"contract price of {rate['item_key']}")
        per_unit = price - contract_price
        line_var = q2(qty * per_unit)
        contract_total = q2(qty * contract_price)
        pct = None
        if contract_price != ZERO:
            pct = format(q2(per_unit / contract_price * 100), "f")

        if per_unit > ZERO:
            direction = "over"
            v_status = STATUS_VERIFIED_OVERCHARGE
            verified_overcharge += line_var
        elif per_unit < ZERO:
            direction = "under"
            v_status = STATUS_VERIFIED_UNDERCHARGE
            verified_undercharge += line_var
        else:
            direction = "match"
            v_status = STATUS_VERIFIED_MATCH

        m_inv += computed
        m_con += contract_total
        m_var += line_var

        lines_out.append({
            **base,
            "status": "matched",
            "verification_status": v_status,
            "contract_matching_status": "matched",
            "source_arithmetic_status": "VERIFIED",
            "item_key": rate["item_key"],
            "clause_ref": rate.get("clause_ref"),
            "quantity": num_str(qty),
            "unit": ln.get("unit", "unit"),
            "invoiced_unit_price": exact_str(price),
            "contract_unit_price": exact_str(contract_price),
            "variance_per_unit": exact_str(per_unit),
            "line_variance": money_str(line_var),
            "variance_pct": pct,
            "direction": direction,
            "contract_line_total": money_str(contract_total),
            "invoiced_line_total_computed": money_str(computed),
            "invoiced_line_total_as_written": money_str(written) if written is not None else None,
            "line_total_matches": True,
        })

    # Stated Total vs Sum of Written Lines
    complete = (unmatched_count == 0 and source_discrepancy_count == 0 and not blocking_issues)
    stated = invoice.get("stated_total")
    stated_d = q2(to_decimal(stated, "stated_total")) if stated is not None else None
    stated_ok = None
    if stated_d is not None and written_sum_known:
        stated_ok = (stated_d == q2(written_sum))
        if not stated_ok:
            msg = f"Stated total {money_str(stated_d)} differs from the sum of line totals as written, {money_str(written_sum)}"
            blocking_issues.append(msg)
            warnings.append(msg)

    # Determine System Verification State
    if blocking_issues or source_discrepancy_count > 0:
        verification_status = STATE_BLOCKED
        if source_discrepancy_count > 0:
            settlement_status = "PAYMENT_RECOMMENDATION_BLOCKED: SOURCE_DISCREPANCY"
        else:
            settlement_status = "PAYMENT_RECOMMENDATION_BLOCKED: INTEGRITY_ERRORS"
    elif unmatched_count > 0 or not complete:
        verification_status = STATE_REVIEW_REQUIRED
        settlement_status = "PAYMENT_RECOMMENDATION_PARTIAL: UNRESOLVED_LINES"
    else:
        verification_status = STATE_VERIFIED
        settlement_status = "GOODS_SUBTOTAL_RECONCILED: TAX_AND_FREIGHT_UNVERIFIED"

    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "verification_status": verification_status,
        "settlement_status": settlement_status,
        "case_id": invoice.get("case_id"),
        "vendor_id": vendor.get("vendor_id"),
        "contract_id": contract.get("contract_id"),
        "invoice_number": invoice.get("invoice_number"),
        "invoice_date": inv_date.isoformat(),
        "currency": currency,
        "source_file": src,
        "source_sha256": src_sha,
        "source_sha256_verified": src_verified,
        "rounding": "half-up to 2 decimals per line; totals add the rounded lines",
        "taxes_and_freight_unverified": True,
        "lines": lines_out,
        "totals": {
            "complete": complete,
            "verification_status": verification_status,
            "matched_invoiced": money_str(m_inv),
            "matched_per_contract": money_str(m_con),
            "variance_on_matched_lines": money_str(m_var),
            "verified_overcharge_total": money_str(verified_overcharge),
            "verified_undercharge_total": money_str(verified_undercharge),
            "unmatched_invoiced_as_written": money_str(unmatched_sum) if unmatched_sum_known else None,
            "invoiced_total": money_str(m_inv + unmatched_sum) if (unmatched_sum_known and source_discrepancy_count == 0) else None,
            "per_contract_total": money_str(m_con) if complete else None,
            "goods_subtotal_invoiced_written": money_str(written_sum) if written_sum_known else None,
            "goods_subtotal_contract": money_str(m_con) if complete else None,
            "stated_total_as_written": money_str(stated_d) if stated_d is not None else None,
            "sum_of_line_totals_as_written": money_str(written_sum) if written_sum_known else None,
            "stated_total_matches": stated_ok,
            "source_discrepancy_count": source_discrepancy_count,
            "unmatched_line_count": unmatched_count,
        },
        "blocking_issues": blocking_issues,
        "unresolved_evidence": unresolved_evidence,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("invoice_json")
    ap.add_argument("vendor_json")
    ap.add_argument("--out", help="also save the result to this file")
    ap.add_argument("--save-digest", action="store_true", help="write companion .sha256 digest file beside --out")
    args = ap.parse_args()
    result = compare(load_json(args.invoice_json), load_json(args.vendor_json))
    if args.out:
        if args.save_digest:
            save_comparison_with_digest(result, args.out)
        else:
            write_json_atomic(args.out, result)
    emit(result)
    return 0


if __name__ == "__main__":
    run_cli(main)
