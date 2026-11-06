#!/usr/bin/env python3
"""Unified Agent Command-Line Interface for Overcharge Desk (tools/desk.py).

Provides the deterministic financial and evidence operations for AI agents
operating inside Switch / Mattermost collaborative workflows.

Subcommands:
    intake    - Intake raw invoice and contract evidence, register source SHA-256 fingerprints.
    audit     - Run deterministic contract comparison, independent verification, and pre-approval preview.
    status    - Query 4-dimensional case status, line totals, and blocking discrepancies.
    history   - Inspect audit ledger event chain for a case, or query vendor history across all cases.
    finalize  - Verify cryptographic human approval receipt and release authorized corrected payment sheet.

Design Invariants:
    1. No Agent Approval: Financial authorization requires human owner execution via tools/approve.py.
       The 'approve' subcommand is strictly omitted from desk.py.
    2. Exact Decimal Math: Uses decimal.Decimal and half-up rounding (ROUND_HALF_UP).
    3. Deterministic Outputs: All commands print structured JSON to stdout and exit non-zero on failure.
    4. Non-Interactive: Never prompts on stdin.

Usage:
    python tools/desk.py intake INVOICE_FILE CONTRACT_FILE [--case-id ID] [--cases-dir DIR]
    python tools/desk.py audit CASE_ID [--cases-dir DIR]
    python tools/desk.py status CASE_ID [--cases-dir DIR]
    python tools/desk.py history [CASE_ID] [--vendor VENDOR_ID] [--ledger-db DB]
    python tools/desk.py finalize CASE_ID [--cases-dir DIR]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure tools directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common import (CASE_ID_RE, CURRENCY_RE, STATE_BLOCKED, STATE_REVIEW_REQUIRED,
                    STATE_VERIFIED, ToolError, canonical_json_bytes, emit,
                    exact_str, load_json, money_str, num_str, parse_date,
                    run_cli, sha256_file, to_decimal, utc_now_iso,
                    write_json_atomic)
from check_invoice import find_issues
from compare import compare
from evidence import get_evidence_digest_map, load_registry, register_evidence, verify_evidence
from audit_ledger import DEFAULT_LEDGER_DB, list_events
from approval_receipt import verify_approval_receipt
from auth import ensure_signing_key, get_default_key_path, load_signing_key
from pipeline import run_pipeline


def _get_ledger_head(db_path: Path | str) -> str:
    """Return the SHA-256 hash of the latest event in the audit ledger."""
    p = Path(db_path)
    if not p.exists():
        return "0" * 64
    try:
        events = list_events(db_path=p)
        if events:
            return events[-1].get("event_hash", "0" * 64)
    except Exception:
        pass
    return "0" * 64


def _resolve_case_path(case_arg: str, cases_dir: Path) -> Path:
    """Resolve case directory path."""
    p = Path(case_arg)
    if p.is_dir():
        return p.resolve()
    candidate = cases_dir / case_arg
    if candidate.is_dir():
        return candidate.resolve()
    # If case_arg is an ID without existing dir, return expected path
    return candidate.resolve()


DEMO_CASE_MAP = {
    "demo-clean": "OC-20261001-01",
    "demo-overcharge": "OC-20261106-01",
    "demo-review": "OC-20261201-01",
    "demo-blocked": "OC-20261103-01",
    "demo-tampering": "OC-20261001-01",
    "demo-ledger-failure": "OC-20261001-01",
}

MAX_QUANTITY_DECIMALS = 4
MAX_CURRENCY_DECIMALS = 2


def _parse_strict_decimal(
    raw_val: str,
    field_name: str,
    max_decimals: int,
    allow_zero: bool = True,
) -> Decimal:
    """Parse a string into an exact Decimal with strict precision and finiteness bounds."""
    if raw_val is None or not str(raw_val).strip():
        raise ToolError(f"Missing numeric value for {field_name}", 2)
    cleaned = str(raw_val).strip().replace(",", "")
    # Reject scientific notation or non-standard tokens if needed, and delegate to to_decimal
    d = to_decimal(cleaned, field_name)
    if allow_zero:
        if d < Decimal("0"):
            raise ToolError(f"{field_name} cannot be negative: {raw_val!r}", 2)
    else:
        if d <= Decimal("0"):
            raise ToolError(f"{field_name} must be strictly positive (> 0): {raw_val!r}", 2)

    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp < -max_decimals:
        raise ToolError(
            f"{field_name} exceeds maximum supported precision ({max_decimals} decimal places): {raw_val!r}",
            2,
        )
    return d


def parse_txt_invoice(
    text_content: str,
    source_filename: str,
    source_sha256: str,
    case_id: str,
    vendor_id: Optional[str] = None,
) -> dict:
    """Deterministically parse plain text invoices into structured invoice dictionary using exact Decimal arithmetic.

    Never uses binary floating-point (float). Rejects missing identifiers, invalid ISO dates,
    NaN/Infinity, negative values, and unsupported decimal precision.
    """
    import re
    lines = [l.strip() for l in text_content.splitlines() if l.strip()]
    if not lines:
        raise ToolError(f"Invoice text file is empty: {source_filename}", 2)

    vendor_match = re.search(r"^\s*Vendor\s*:\s*(.+)$", text_content, re.MULTILINE | re.IGNORECASE)
    if vendor_match:
        vendor_name = vendor_match.group(1).strip()
    else:
        vendor_raw = lines[0].strip()
        vendor_name = vendor_raw.title() if vendor_raw.isupper() else vendor_raw

    if not vendor_name:
        raise ToolError(f"Missing vendor name in invoice text: {source_filename}", 2)

    resolved_vendor_id = (vendor_id or "").strip()
    if not resolved_vendor_id:
        raise ToolError(
            f"Missing vendor_id when parsing {source_filename}; refusing to default vendor identity",
            2,
        )

    inv_no_match = re.search(
        r"(?:Invoice\s*(?:No|Number|#)|INVOICE\s*#)\s*:?\s*([A-Za-z0-9\-]+)",
        text_content,
        re.IGNORECASE,
    )
    if not inv_no_match or not inv_no_match.group(1).strip():
        raise ToolError(f"Missing Invoice No / Invoice Number in {source_filename}", 2)
    inv_number = inv_no_match.group(1).strip()

    date_match = re.search(
        r"(?:Invoice\s*)?Date\s*:?\s*(\S+)",
        text_content,
        re.IGNORECASE,
    )
    if not date_match or not date_match.group(1).strip():
        raise ToolError(f"Missing Invoice Date in {source_filename}", 2)
    inv_date_raw = date_match.group(1).strip()
    parse_date(inv_date_raw, "invoice_date")
    inv_date = inv_date_raw

    curr_match = re.search(r"Currency\s*:?\s*([A-Za-z]{3})\b", text_content, re.IGNORECASE)
    if curr_match:
        currency = curr_match.group(1).upper()
    elif "INR" in text_content:
        currency = "INR"
    else:
        raise ToolError(f"Missing 3-letter ISO currency in {source_filename}", 2)

    if not CURRENCY_RE.match(currency):
        raise ToolError(f"Invalid currency code in {source_filename}: {currency!r}", 2)

    tot_match = re.search(
        r"^\s*(?:Stated\s+Invoice\s+Total|Total)(?:\s*\([A-Z]{3}\))?\s*:\s*(\S+)",
        text_content,
        re.MULTILINE | re.IGNORECASE,
    )
    if not tot_match:
        raise ToolError(f"Missing stated Total in {source_filename}", 2)
    stated_total_d = _parse_strict_decimal(
        tot_match.group(1),
        "stated_total",
        max_decimals=MAX_CURRENCY_DECIMALS,
        allow_zero=True,
    )

    line_items = []
    for line in lines:
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 6 and parts[0].isdigit():
                line_no = int(parts[0])
                desc = parts[1]
                if not desc:
                    raise ToolError(f"Line {line_no}: empty description in {source_filename}", 2)
                qty_d = _parse_strict_decimal(
                    parts[2],
                    f"line {line_no} quantity",
                    max_decimals=MAX_QUANTITY_DECIMALS,
                    allow_zero=False,
                )
                unit = parts[3] or "unit"
                unit_price_d = _parse_strict_decimal(
                    parts[4],
                    f"line {line_no} unit_price",
                    max_decimals=MAX_CURRENCY_DECIMALS,
                    allow_zero=True,
                )
                line_total_d = _parse_strict_decimal(
                    parts[5],
                    f"line {line_no} line_total",
                    max_decimals=MAX_CURRENCY_DECIMALS,
                    allow_zero=True,
                )
                line_items.append({
                    "line_no": line_no,
                    "description": desc,
                    "quantity": num_str(qty_d),
                    "unit": unit,
                    "unit_price": exact_str(unit_price_d),
                    "line_total": money_str(line_total_d),
                    "source_ref": f"invoices/{source_filename}, line {line_no}",
                })

    if not line_items:
        raise ToolError(f"No valid line items found in {source_filename}", 2)

    return {
        "case_id": case_id,
        "vendor_id": resolved_vendor_id,
        "vendor_name_as_written": vendor_name,
        "invoice_number": inv_number,
        "invoice_date": inv_date,
        "currency": currency,
        "lines": line_items,
        "stated_total": money_str(stated_total_d),
        "source_file": f"invoices/{source_filename}",
        "source_sha256": source_sha256,
        "extraction_issues": [],
        "extracted_at": utc_now_iso(),
    }


# -----------------------------------------------------------------------------
# Subcommand: intake
# -----------------------------------------------------------------------------
def run_intake(
    invoice_path: Path | str,
    contract_path: Path | str,
    case_id: Optional[str] = None,
    cases_dir: Path | str = "cases",
    base_dir: Path | str = ".",
) -> dict:
    """Intake raw invoice and contract evidence into a new or existing case folder.

    Enforces append-only evidence provenance: refuses to overwrite an existing case
    if the incoming invoice or contract SHA-256 differs from registered evidence.
    """
    root = Path(base_dir).resolve()
    inv_p = Path(invoice_path)
    if not inv_p.is_absolute():
        inv_p = root / inv_p
    con_p = Path(contract_path)
    if not con_p.is_absolute():
        con_p = root / con_p

    if not inv_p.exists():
        raise ToolError(f"Invoice source file not found: {inv_p}", 2)
    if not con_p.exists():
        raise ToolError(f"Contract source file not found: {con_p}", 2)

    c_base = Path(cases_dir)
    if not c_base.is_absolute():
        c_base = root / c_base

    # Compute source digests upfront
    inv_sha = sha256_file(inv_p)
    con_sha = sha256_file(con_p)

    vendor_data = {}
    if con_p.suffix.lower() == ".json":
        try:
            vendor_data = load_json(con_p)
        except Exception:
            pass
    vendor_id = vendor_data.get("vendor_id")
    if not vendor_id:
        stem = con_p.stem.lower()
        if stem.endswith("-contract"):
            vendor_id = stem[: -len("-contract")]
        else:
            vendor_id = stem

    # Determine canonical case_id and case_dir
    dir_name = case_id
    canonical_id = None
    if case_id:
        if case_id in DEMO_CASE_MAP:
            dir_name = case_id
            canonical_id = DEMO_CASE_MAP[case_id]
        elif CASE_ID_RE.match(case_id):
            dir_name = case_id
            canonical_id = case_id
        else:
            dir_name = case_id
            existing_reg = c_base / case_id / "evidence_registry.json"
            if existing_reg.exists():
                try:
                    reg_d = load_json(existing_reg)
                    canonical_id = reg_d.get("case_id")
                except Exception:
                    pass

    inv_data = None
    if inv_p.suffix.lower() == ".json":
        try:
            inv_data = load_json(inv_p)
            if not canonical_id:
                canonical_id = inv_data.get("case_id")
        except Exception:
            pass

    if not canonical_id:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        from next_case_id import next_id
        canonical_id = next_id(c_base, today)
        if not dir_name:
            dir_name = canonical_id

    case_dir = c_base / dir_name

    # P0.1 Guard: Refuse re-intake into an existing case if source_invoice or vendor_contract hash differs
    if case_dir.exists():
        reg_file = case_dir / "evidence_registry.json"
        if reg_file.exists():
            existing_reg = load_registry(case_dir)
            for item in existing_reg.get("evidence", []):
                if item.get("superseded_by"):
                    continue
                etype = item.get("evidence_type")
                ehash = str(item.get("content_hash", "")).lower()
                if etype == "source_invoice" and ehash and ehash != inv_sha.lower():
                    raise ToolError(
                        f"Re-intake refused (EVIDENCE_MUTATION_REFUSED): Case '{canonical_id}' already has "
                        f"registered source_invoice ({item.get('original_filename')}) with SHA-256 {ehash} "
                        f"!= incoming SHA-256 {inv_sha}. Create a new case for modified documents.",
                        4,
                    )
                if etype == "vendor_contract" and ehash and ehash != con_sha.lower():
                    raise ToolError(
                        f"Re-intake refused (EVIDENCE_MUTATION_REFUSED): Case '{canonical_id}' already has "
                        f"registered vendor_contract ({item.get('original_filename')}) with SHA-256 {ehash} "
                        f"!= incoming SHA-256 {con_sha}. Create a new case for modified contracts.",
                        4,
                    )
        existing_inv_json = case_dir / "invoice.json"
        if existing_inv_json.exists() and inv_p.resolve() != existing_inv_json.resolve():
            try:
                old_inv = load_json(existing_inv_json)
                old_src_sha = str(old_inv.get("source_sha256", "")).lower()
                if old_src_sha and len(old_src_sha) == 64 and old_src_sha != inv_sha.lower():
                    # If the input is a raw source file whose SHA differs from the case's declared source_sha256
                    if inv_p.suffix.lower() != ".json" or (
                        str(inv_data.get("source_sha256", "")).lower() != old_src_sha
                    ):
                        raise ToolError(
                            f"Re-intake refused (EVIDENCE_MUTATION_REFUSED): Case '{canonical_id}' is bound "
                            f"to source_sha256 {old_src_sha}, which differs from incoming file.",
                            4,
                        )
            except ToolError:
                raise
            except Exception:
                pass

    case_dir.mkdir(parents=True, exist_ok=True)

    # Copy files into case directory if not already there
    dest_inv = case_dir / inv_p.name
    if dest_inv.resolve() != inv_p.resolve():
        shutil.copy2(inv_p, dest_inv)

    dest_con = case_dir / con_p.name
    if dest_con.resolve() != con_p.resolve():
        shutil.copy2(con_p, dest_con)

    # Generate or update canonical invoice.json
    canonical_inv = case_dir / "invoice.json"
    if inv_data is not None:
        inv_data["case_id"] = canonical_id
        inv_data["vendor_id"] = vendor_id
        if "source_sha256" not in inv_data or not inv_data["source_sha256"]:
            inv_data["source_sha256"] = inv_sha
        write_json_atomic(canonical_inv, inv_data)
    elif inv_p.suffix.lower() == ".txt":
        txt_content = inv_p.read_text(encoding="utf-8")
        inv_data = parse_txt_invoice(
            text_content=txt_content,
            source_filename=inv_p.name,
            source_sha256=inv_sha,
            case_id=canonical_id,
            vendor_id=vendor_id,
        )
        write_json_atomic(canonical_inv, inv_data)

    # Register evidence in tamper-evident registry
    reg1 = register_evidence(
        case_dir=case_dir,
        file_path=dest_inv,
        evidence_type="source_invoice",
        case_id=canonical_id,
        description=f"Source invoice from {inv_p.name}",
    )
    reg2 = register_evidence(
        case_dir=case_dir,
        file_path=dest_con,
        evidence_type="vendor_contract",
        case_id=canonical_id,
        description=f"Vendor contract from {con_p.name}",
    )
    reg3 = None
    if canonical_inv.exists():
        reg3 = register_evidence(
            case_dir=case_dir,
            file_path=canonical_inv,
            evidence_type="extracted_invoice",
            case_id=canonical_id,
            description="Deterministic extracted invoice JSON",
        )

    ev_list = [r["evidence_id"] for r in [reg1, reg2, reg3] if r and "evidence_id" in r]

    return {
        "ok": True,
        "case_id": canonical_id,
        "case_dir": str(case_dir),
        "invoice_file": str(dest_inv),
        "contract_file": str(dest_con),
        "source_sha256": inv_sha,
        "contract_sha256": con_sha,
        "evidence_registered": ev_list,
        "status": "INTAKE_COMPLETED",
    }


# -----------------------------------------------------------------------------
# Subcommand: audit
# -----------------------------------------------------------------------------
def run_audit(
    case_arg: str,
    cases_dir: Path | str = "cases",
    base_dir: Path | str = ".",
    ledger_db: Optional[Path | str] = None,
) -> dict:
    """Execute deterministic comparison, independent verification, and emit pre-approval preview."""
    root = Path(base_dir).resolve()
    c_base = Path(cases_dir) if Path(cases_dir).is_absolute() else root / cases_dir
    case_dir = _resolve_case_path(case_arg, c_base)

    if not case_dir.exists():
        raise ToolError(f"Case directory not found: {case_dir}", 2)

    inv_file = case_dir / "invoice.json"
    if not inv_file.exists():
        raise ToolError(f"invoice.json not found in case directory: {case_dir}", 2)

    inv_data = load_json(inv_file)
    case_id = inv_data.get("case_id", case_dir.name)
    vendor_id = inv_data.get("vendor_id", "acme")

    # Locate contract/vendor seed file
    vendor_file = root / "vendors" / f"{vendor_id}.json"
    if not vendor_file.exists():
        vendor_file = root / "seed" / f"{vendor_id}.json"
    if not vendor_file.exists():
        # Check inside case_dir for any json contract
        cand = list(case_dir.glob("*.json"))
        for c in cand:
            if c.name != "invoice.json" and c.name != "evidence_registry.json":
                vendor_file = c
                break

    if not vendor_file.exists():
        raise ToolError(f"Contract file for vendor '{vendor_id}' not found", 3)

    db_path = Path(ledger_db) if ledger_db else root / "ledger.db"

    # Execute deterministic pipeline pass 1 (Pre-approval preview mode)
    pipeline_res = run_pipeline(
        invoice_path=inv_file,
        vendor_path=vendor_file,
        out_dir=case_dir,
        base_dir=root,
        require_approval=False,
        ledger_db=db_path,
        record_ledger_events=True,
    )

    v_status = pipeline_res.get("verification_status")
    comm_status = pipeline_res.get("commercial_status")
    totals = pipeline_res.get("totals", {})

    # Extract cryptographic hashes
    comp_json = case_dir / "compare.json"
    comp_sha = sha256_file(comp_json) if comp_json.exists() else "0" * 64
    inv_sha = inv_data.get("source_sha256") or sha256_file(inv_file)

    vrf_json = case_dir / "audit" / "verification.json"
    vrf_id = "UNKNOWN"
    if vrf_json.exists():
        try:
            vrf_data = load_json(vrf_json)
            vrf_id = vrf_data.get("verification_id", "UNKNOWN")
        except Exception:
            pass

    ledger_head = _get_ledger_head(db_path)

    lines = inv_data.get("lines", [])
    summary = pipeline_res.get("artifact_summary", {})
    comp_json_data = load_json(comp_json) if comp_json.exists() else {}
    comp_totals = comp_json_data.get("totals", {})

    payable_str = summary.get("payable_total") or money_str(to_decimal(comp_totals.get("per_contract_total", comp_totals.get("matched_per_contract", "0"))))
    withheld_str = summary.get("withheld_total") or money_str(to_decimal(comp_totals.get("variance_on_matched_lines", "0")))

    result = {
        "ok": v_status == STATE_VERIFIED,
        "case_id": case_id,
        "verification_status": v_status,
        "commercial_status": comm_status,
        "invoice_sha256": inv_sha,
        "compare_sha256": comp_sha,
        "verification_id": vrf_id,
        "ledger_head": ledger_head,
        "payable_goods_subtotal": payable_str,
        "withheld_goods_variance": withheld_str,
        "lines_total_count": len(lines),
        "source_discrepancy_count": totals.get("source_discrepancy_count", 0),
        "preview_file": str(case_dir / pipeline_res.get("artifact_file", "payment_preview.csv")),
        "blocking_issues": pipeline_res.get("blocking_issues", []),
    }

    if v_status != STATE_VERIFIED:
        # Exit code 2 per specification on blocked/discrepant verification
        emit(result)
        sys.exit(2)

    return result


# -----------------------------------------------------------------------------
# Subcommand: status
# -----------------------------------------------------------------------------
def run_status(
    case_arg: str,
    cases_dir: Path | str = "cases",
    base_dir: Path | str = ".",
) -> dict:
    """Retrieve 4-dimensional state model, financial totals, and artifact inventory."""
    root = Path(base_dir).resolve()
    c_base = Path(cases_dir) if Path(cases_dir).is_absolute() else root / cases_dir
    case_dir = _resolve_case_path(case_arg, c_base)

    if not case_dir.exists():
        raise ToolError(f"Case directory not found: {case_dir}", 2)

    comp_file = case_dir / "comparison" / "compare.json"
    if not comp_file.exists():
        comp_file = case_dir / "compare.json"

    if not comp_file.exists():
        # Case has been intaken but not yet audited
        inv_file = case_dir / "invoice.json"
        if not inv_file.exists():
            raise ToolError(f"Missing invoice.json in case directory: {case_dir}", 2)
        inv_data = load_json(inv_file)
        return {
            "ok": True,
            "case_id": inv_data.get("case_id", case_dir.name),
            "verification_status": "UNVERIFIED",
            "commercial_status": "PENDING_AUDIT",
            "approval_status": "NONE",
            "payment_status": "PENDING_AUDIT",
            "invoiced_total": str(inv_data.get("stated_total", "0.00")),
            "payable_amount": "0.00",
            "withheld_amount": "0.00",
            "blocking_issues": [],
        }

    comp_data = load_json(comp_file)
    case_id = comp_data.get("case_id", case_dir.name)
    v_status = comp_data.get("verification_status", "UNVERIFIED")
    comm_status = comp_data.get("commercial_status", "UNKNOWN")
    totals = comp_data.get("totals", {})

    # Check approval status
    receipt_file = case_dir / "approvals" / "approval_receipt.json"
    if not receipt_file.exists():
        receipt_file = case_dir / "approval_receipt.json"

    approval_status = "NONE"
    receipt_data = None
    if receipt_file.exists():
        try:
            receipt_data = load_json(receipt_file)
            approval_status = receipt_data.get("decision", "PENDING")
        except Exception:
            approval_status = "RECEIPT_INVALID"

    # Check payment recommendation status
    corrected_sheet = case_dir / "corrected_payment.csv"
    preview_sheet = case_dir / "payment_preview.csv"
    blocked_sheet = case_dir / "blocked_review_report.csv"

    if corrected_sheet.exists() and approval_status == "APPROVED":
        payment_status = "AUTHORIZED"
    elif approval_status == "APPROVED":
        payment_status = "APPROVED_PENDING_RELEASE"
    elif v_status == STATE_BLOCKED or blocked_sheet.exists():
        payment_status = "BLOCKED"
    elif preview_sheet.exists():
        payment_status = "PREVIEW_ONLY"
    else:
        payment_status = "PENDING_ACTION"

    payable_str = money_str(to_decimal(totals.get("per_contract_total", totals.get("matched_per_contract", "0"))))
    withheld_str = money_str(to_decimal(totals.get("variance_on_matched_lines", "0")))
    invoiced_str = money_str(to_decimal(totals.get("invoiced_total", totals.get("stated_total_as_written", "0"))))

    return {
        "ok": True,
        "case_id": case_id,
        "verification_status": v_status,
        "commercial_status": comm_status,
        "approval_status": approval_status,
        "payment_status": payment_status,
        "invoiced_total": invoiced_str,
        "payable_amount": payable_str,
        "withheld_amount": withheld_str,
        "taxes_and_freight_unverified": comp_data.get("taxes_and_freight_unverified", True),
        "blocking_issues": comp_data.get("blocking_issues", []),
        "receipt_id": receipt_data.get("receipt_id") if receipt_data else None,
        "receipt_hash": receipt_data.get("receipt_hash") if receipt_data else None,
    }


# -----------------------------------------------------------------------------
# Subcommand: history
# -----------------------------------------------------------------------------
def run_history(
    case_arg: Optional[str] = None,
    vendor_id: Optional[str] = None,
    cases_dir: Path | str = "cases",
    base_dir: Path | str = ".",
    ledger_db: Optional[Path | str] = None,
) -> dict:
    """Query case audit trail or retrieve vendor case history across the entire ledger."""
    root = Path(base_dir).resolve()
    db_path = Path(ledger_db) if ledger_db else root / "ledger.db"
    c_base = Path(cases_dir) if Path(cases_dir).is_absolute() else root / cases_dir

    if vendor_id:
        # Vendor Memory Mode: Query all prior cases, overcharges, and outcomes for this vendor
        target_vendor = vendor_id.lower().strip()
        prior_cases = []
        total_withheld = Decimal("0.00")

        # Scan cases directory
        if c_base.exists():
            for c_dir in sorted(c_base.iterdir()):
                if not c_dir.is_dir():
                    continue
                inv_p = c_dir / "invoice.json"
                if not inv_p.exists():
                    continue
                try:
                    inv_d = load_json(inv_p)
                except Exception:
                    continue

                v_id = inv_d.get("vendor_id", "")
                v_name = inv_d.get("vendor_name_as_written", "")
                if target_vendor not in v_id.lower() and target_vendor not in v_name.lower():
                    continue

                cid = inv_d.get("case_id", c_dir.name)
                inv_num = inv_d.get("invoice_number", "UNKNOWN")
                inv_date = inv_d.get("invoice_date", "UNKNOWN")

                # Read compare and approval results
                comp_p = c_dir / "compare.json"
                c_status = "UNKNOWN"
                v_status = "UNVERIFIED"
                invoiced_amt = "0.00"
                payable_amt = "0.00"
                withheld_amt = "0.00"

                if comp_p.exists():
                    try:
                        cd = load_json(comp_p)
                        v_status = cd.get("verification_status", "UNKNOWN")
                        c_status = cd.get("commercial_status", "UNKNOWN")
                        t = cd.get("totals", {})
                        invoiced_amt = money_str(to_decimal(t.get("invoiced_total", "0")))
                        payable_amt = money_str(to_decimal(t.get("per_contract_total", "0")))
                        w_dec = to_decimal(t.get("variance_on_matched_lines", "0"))
                        withheld_amt = money_str(w_dec)
                        total_withheld += w_dec
                    except Exception:
                        pass

                # Check approval receipt
                app_receipt = c_dir / "approvals" / "approval_receipt.json"
                outcome = "PENDING_AUDIT"
                if app_receipt.exists():
                    try:
                        rd = load_json(app_receipt)
                        outcome = rd.get("decision", "APPROVED")
                    except Exception:
                        outcome = "APPROVED"
                elif v_status == STATE_BLOCKED:
                    outcome = "BLOCKED"
                elif v_status == STATE_VERIFIED:
                    outcome = "AWAITING_APPROVAL"

                prior_cases.append({
                    "case_id": cid,
                    "invoice_number": inv_num,
                    "invoice_date": inv_date,
                    "verification_status": v_status,
                    "commercial_status": c_status,
                    "outcome": outcome,
                    "invoiced_amount": invoiced_amt,
                    "payable_amount": payable_amt,
                    "withheld_amount": withheld_amt,
                })

        return {
            "ok": True,
            "vendor_id": target_vendor,
            "prior_cases_count": len(prior_cases),
            "prior_cases": prior_cases,
            "total_overcharges_withheld": money_str(total_withheld),
        }

    elif case_arg:
        # Single Case Ledger History Mode
        case_dir = _resolve_case_path(case_arg, c_base)
        target_case_id = case_dir.name
        inv_p = case_dir / "invoice.json"
        if inv_p.exists():
            try:
                target_case_id = load_json(inv_p).get("case_id", target_case_id)
            except Exception:
                pass

        events = list_events(case_id=target_case_id, db_path=db_path) if db_path.exists() else []
        return {
            "ok": True,
            "case_id": target_case_id,
            "events_count": len(events),
            "events": events,
        }

    else:
        # Full ledger overview
        events = list_events(db_path=db_path) if db_path.exists() else []
        return {
            "ok": True,
            "total_ledger_events": len(events),
            "recent_events": events[-20:],
        }


# -----------------------------------------------------------------------------
# Subcommand: finalize
# -----------------------------------------------------------------------------
def run_finalize(
    case_arg: str,
    cases_dir: Path | str = "cases",
    base_dir: Path | str = ".",
    signing_key_file: Optional[Path | str] = None,
    ledger_db: Optional[Path | str] = None,
) -> dict:
    """Verify cryptographic human approval receipt and release authorized payment sheet."""
    root = Path(base_dir).resolve()
    c_base = Path(cases_dir) if Path(cases_dir).is_absolute() else root / cases_dir
    case_dir = _resolve_case_path(case_arg, c_base)

    if not case_dir.exists():
        raise ToolError(f"Case directory not found: {case_dir}", 2)

    inv_file = case_dir / "invoice.json"
    if not inv_file.exists():
        raise ToolError(f"invoice.json not found in case directory: {case_dir}", 2)

    inv_data = load_json(inv_file)
    case_id = inv_data.get("case_id", case_dir.name)
    vendor_id = inv_data.get("vendor_id", "acme")

    vendor_file = root / "vendors" / f"{vendor_id}.json"
    if not vendor_file.exists():
        vendor_file = root / "seed" / f"{vendor_id}.json"
    if not vendor_file.exists():
        raise ToolError(f"Contract file for vendor '{vendor_id}' not found", 3)

    # 1. Require signed approval receipt: Fail-closed if absent
    receipt_p = case_dir / "approvals" / "approval_receipt.json"
    if not receipt_p.exists():
        receipt_p = case_dir / "approval_receipt.json"

    if not receipt_p.exists():
        raise ToolError(
            f"Finalization refused: No signed human approval receipt found for case '{case_id}'. "
            "Human authorization via tools/approve.py is mandatory before payment release.",
            4,
        )

    # 2. Verify on-disk evidence registry before finalization (fail-closed if any artifact was tampered)
    if (case_dir / "evidence_registry.json").exists():
        ev_verify = verify_evidence(case_dir, base_dir=root, key_file=signing_key_file)
        if not ev_verify["ok"]:
            raise ToolError(
                f"Finalization refused: Evidence integrity verification failed: {ev_verify['failures']}",
                4,
            )
        current_pre_approval_digests = get_evidence_digest_map(
            case_dir,
            active_only=True,
            pre_approval_only=True,
        )
    else:
        current_pre_approval_digests = None

    # 3. Cryptographic verification of approval receipt against current case & evidence state
    receipt_data = load_json(receipt_p)
    key_path = Path(signing_key_file) if signing_key_file else get_default_key_path()
    key_bytes = ensure_signing_key(key_path)

    expected_inv_sha = inv_data.get("source_sha256")
    expected_cmp_sha = None
    comp_sha_file = case_dir / "compare.json.sha256"
    if comp_sha_file.exists():
        expected_cmp_sha = comp_sha_file.read_text(encoding="utf-8").strip()

    app_valid, app_issues = verify_approval_receipt(
        receipt_data,
        key_bytes,
        expected_case_id=case_id,
        expected_compare_sha=expected_cmp_sha,
        expected_invoice_sha=expected_inv_sha,
        expected_evidence_digest_set=current_pre_approval_digests,
    )
    if not app_valid:
        raise ToolError(
            f"Finalization refused: Approval receipt cryptographic verification failed: {'; '.join(app_issues)}",
            4,
        )

    if receipt_data.get("decision") != "APPROVED":
        raise ToolError(
            f"Finalization refused: Case '{case_id}' decision is '{receipt_data.get('decision')}'. "
            "Payment sheets cannot be issued for rejected or unapproved cases.",
            4,
        )

    # 4. Execute deterministic pipeline pass 2 with verified approval receipt
    db_path = Path(ledger_db) if ledger_db else root / "ledger.db"
    res2 = run_pipeline(
        invoice_path=inv_file,
        vendor_path=vendor_file,
        out_dir=case_dir,
        base_dir=root,
        with_approval=receipt_p,
        require_approval=True,
        signing_key_file=key_path,
        ledger_db=db_path,
    )

    corrected_csv = case_dir / "corrected_payment.csv"
    if not corrected_csv.exists():
        raise ToolError("Finalization failed: corrected_payment.csv was not produced", 2)

    summary = res2.get("artifact_summary", {})
    payable_str = summary.get("payable_total") or receipt_data.get("approved_amount", "0.00")
    withheld_str = summary.get("withheld_total") or receipt_data.get("withheld_amount", "0.00")

    return {
        "ok": True,
        "case_id": case_id,
        "payment_status": "AUTHORIZED",
        "payable_amount": payable_str,
        "withheld_amount": withheld_str,
        "payment_sheet": str(corrected_csv),
        "receipt_id": receipt_data.get("receipt_id"),
        "receipt_hash": receipt_data.get("receipt_hash") or receipt_data.get("receipt_signature"),
        "authenticated_actor": receipt_data.get("actor_id"),
    }


# -----------------------------------------------------------------------------
# Main CLI Dispatcher
# -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # intake
    p_intake = sub.add_parser("intake", help="Intake raw invoice and contract into case")
    p_intake.add_argument("invoice", help="Path to invoice file (.json or .txt)")
    p_intake.add_argument("contract", help="Path to contract / vendor file (.json or .md)")
    p_intake.add_argument("--case-id", help="Explicit case identifier")
    p_intake.add_argument("--cases-dir", default="cases", help="Cases base directory")

    # audit
    p_audit = sub.add_parser("audit", help="Run deterministic audit and emit pre-approval preview")
    p_audit.add_argument("case", help="Case ID or path (e.g. 'demo-overcharge')")
    p_audit.add_argument("--cases-dir", default="cases", help="Cases base directory")
    p_audit.add_argument("--ledger-db", help="Path to ledger.db")

    # status
    p_status = sub.add_parser("status", help="Get 4-dimensional case status and totals")
    p_status.add_argument("case", help="Case ID or path")
    p_status.add_argument("--cases-dir", default="cases", help="Cases base directory")

    # history
    p_history = sub.add_parser("history", help="Query case audit trail or vendor history")
    p_history.add_argument("case", nargs="?", help="Optional Case ID or path")
    p_history.add_argument("--vendor", help="Vendor ID to query historical cases and outcomes")
    p_history.add_argument("--cases-dir", default="cases", help="Cases base directory")
    p_history.add_argument("--ledger-db", help="Path to ledger.db")

    # finalize
    p_finalize = sub.add_parser("finalize", help="Verify approval and generate corrected payment sheet")
    p_finalize.add_argument("case", help="Case ID or path")
    p_finalize.add_argument("--cases-dir", default="cases", help="Cases base directory")
    p_finalize.add_argument("--key-file", help="Path to signing key file")
    p_finalize.add_argument("--ledger-db", help="Path to ledger.db")

    # NOTE: NO 'approve' subcommand is registered. Agents cannot approve.

    args = ap.parse_args()

    if args.cmd == "intake":
        res = run_intake(
            invoice_path=args.invoice,
            contract_path=args.contract,
            case_id=args.case_id,
            cases_dir=args.cases_dir,
        )
        emit(res)
        return 0

    elif args.cmd == "audit":
        res = run_audit(
            case_arg=args.case,
            cases_dir=args.cases_dir,
            ledger_db=args.ledger_db,
        )
        emit(res)
        return 0

    elif args.cmd == "status":
        res = run_status(
            case_arg=args.case,
            cases_dir=args.cases_dir,
        )
        emit(res)
        return 0

    elif args.cmd == "history":
        res = run_history(
            case_arg=args.case,
            vendor_id=args.vendor,
            cases_dir=args.cases_dir,
            ledger_db=args.ledger_db,
        )
        emit(res)
        return 0

    elif args.cmd == "finalize":
        res = run_finalize(
            case_arg=args.case,
            cases_dir=args.cases_dir,
            signing_key_file=args.key_file,
            ledger_db=args.ledger_db,
        )
        emit(res)
        return 0

    return 2


if __name__ == "__main__":
    run_cli(main)
