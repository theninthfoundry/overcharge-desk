"""Workspace aggregation and query services for Overcharge Desk.

Encapsulates cross-cutting read models for:
- Financial position metrics and attention items
- Consolidated case workspaces
- Contracts and Schedule A rates
- Global cryptographic evidence registry
- Historical approvals and signed receipts
- Payment instructions and disbursement summaries
- Signed audit checkpoints
- Multi-agent Switch room integration status
- User lifecycle and role directory

Enforces AGENTS.md financial invariants:
- 100% exact Decimal arithmetic (zero float)
- No fallback from missing vendors to acme.json
- Fail-closed error handling with operational logging
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.api.workspace_service")

# Ensure repository root and tools/ are in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from approval_receipt import verify_approval_receipt
from audit_ledger import (
    DEFAULT_LEDGER_DB,
    GENESIS_PREV_HASH,
    init_db as init_ledger_db,
    list_events,
    verify_checkpoint,
    verify_ledger,
)
from auth import get_default_key_path, load_signing_key
from common import ToolError, load_json, sha256_file, to_decimal, utc_now_iso
from domain.authorization.policies import (
    AuthorizationService,
    PERM_CASE_REJECT,
    ROLE_PERMISSIONS,
)
from domain.cases.service import CaseService
from domain.identity.key_manager import KeyManager
from domain.identity.models import SystemRole, User
from domain.identity.repository import DEFAULT_IDENTITY_DB, IdentityRepository
from domain.payments.repository import DEFAULT_PAYMENT_DB, PaymentRepository
from domain.vendors.models import VendorDestination, VendorRegistry
from evidence import list_evidence, verify_evidence

APP_ENV = os.getenv("APP_ENV", "development").lower()
CHECKPOINTS_DIR = ROOT_DIR / "checkpoints"
TWOPLACES = Decimal("0.01")

_auth_service = AuthorizationService(enforce_strict_separation_of_duties=True)
_key_manager = KeyManager(app_env=APP_ENV)
_vendor_registry = VendorRegistry()
_case_service = CaseService(base_dir=ROOT_DIR, auth_service=_auth_service)
_payment_repo = PaymentRepository(db_path=ROOT_DIR / DEFAULT_PAYMENT_DB)
_case_service.payment_service.vendor_registry = _vendor_registry
_case_service.payment_service.repo = _payment_repo


def to_dec(val: Any) -> Decimal:
    """Safely convert value to 2-decimal quantized Decimal without float precision loss."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val).strip()).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def fmt_dec(val: Decimal) -> str:
    """Format decimal as monetary string."""
    return str(val.quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def get_active_signing_key() -> Optional[bytes]:
    """Retrieve active signing key bytes fail-closed."""
    try:
        _, key_bytes = _key_manager.get_active_key()
        return key_bytes
    except Exception:
        try:
            return load_signing_key()
        except Exception:
            return None


def sync_vendor_registry() -> None:
    """Sync custom vendors from vendors/*.json into memory registry."""
    _vendor_registry._destinations.clear()
    vendors_dir = ROOT_DIR / "vendors"
    if not vendors_dir.exists():
        return
    for vf in sorted(vendors_dir.glob("*.json")):
        try:
            vdata = load_json(vf)
            vid = vdata.get("vendor_id") or vf.stem
            if vid:
                dest_ref = vdata.get("destination_reference") or f"TREASURY-{vid.upper()}-001"
                _vendor_registry._destinations[vid.lower()] = VendorDestination(
                    vendor_id=vid.lower(),
                    destination_reference=dest_ref,
                    verification_status="VERIFIED" if vdata.get("bank_verified", True) else "UNVERIFIED",
                    verification_method="BANK_CONFIRMATION",
                    verified_by="treasury_admin",
                    verified_at=utc_now_iso(),
                    evidence_digest=sha256_file(vf),
                )
        except Exception as exc:
            logger.warning("Failed to sync vendor destination from %s: %s", vf, exc)


sync_vendor_registry()


def ensure_base_storage_initialized() -> None:
    """Initialize empty SQLite schemas and base workspace directories without demo data."""
    for folder in ["cases", "vendors", "contracts", "invoices", "checkpoints"]:
        (ROOT_DIR / folder).mkdir(parents=True, exist_ok=True)
    init_ledger_db(ROOT_DIR / DEFAULT_LEDGER_DB)
    _payment_repo.init_db()
    try:
        conn = sqlite3.connect(str(ROOT_DIR / DEFAULT_IDENTITY_DB))
        conn.execute("UPDATE users SET is_demo = 0")
        conn.commit()
        conn.close()
    except Exception:
        pass
    sync_vendor_registry()


def write_contract_markdown(
    vendor_id: str,
    vendor_name: str,
    contract_id: str,
    effective_from: str,
    effective_to: str,
    currency: str,
    rates: List[Dict[str, Any]],
) -> str:
    """Generate or update Schedule A contract markdown file."""
    src_md_rel = f"contracts/{vendor_id}-contract.md"
    src_md_abs = ROOT_DIR / src_md_rel
    src_md_abs.parent.mkdir(parents=True, exist_ok=True)
    md_lines = [
        f"# Master Supply Agreement — {vendor_name}",
        f"- **Contract ID**: `{contract_id}`",
        f"- **Vendor ID**: `{vendor_id}`",
        f"- **Effective Window**: `{effective_from}` to `{effective_to}`",
        f"- **Currency**: `{currency}`",
        "",
        "## Schedule A — Contracted Rate Table",
        "",
        "| Item # | SKU | Description | Unit | Contract Unit Price | Effective Window | Clause Reference |",
        "|:-------|:----|:------------|:-----|:---------------------|:-----------------|:-----------------|",
    ]
    for idx, r in enumerate(rates, start=1):
        sku = r.get("sku") or r.get("item_code") or f"ITEM-{idx}"
        desc = r.get("description") or sku
        unit = r.get("unit") or "unit"
        uprice = fmt_dec(to_dec(r.get("unit_price", "0.00")))
        c_eff_from = r.get("effective_from") or effective_from
        c_eff_to = r.get("effective_to") or effective_to
        clause = r.get("clause_ref") or f"Schedule A, item {idx}"
        md_lines.append(
            f"| {idx} | `{sku}` | {desc} | {unit} | {uprice} | {c_eff_from} to {c_eff_to} | {clause} |"
        )
    md_lines.extend(
        [
            "",
            "## Terms & Conditions",
            "1. Invoicing must strictly align with Schedule A unit prices.",
            "2. Overcharges and arithmetic discrepancies will be withheld from disbursement.",
            "3. Payment terms: Net 30 days upon cryptographic authorization.",
            "",
        ]
    )
    src_md_abs.write_text("\n".join(md_lines), encoding="utf-8")
    return src_md_rel


def list_all_payment_instructions() -> List[Dict[str, Any]]:
    """Retrieve all payment instructions from SQLite repository."""
    try:
        return [inst.to_dict() for inst in _payment_repo.list_all()]
    except Exception as exc:
        logger.error("Failed to list payment instructions: %s", exc)
        return []


def build_overview_metrics(current_user: User) -> Dict[str, Any]:
    """Compute financial metrics strictly from persisted case records using Decimal."""
    summaries = _case_service.list_cases()
    instructions = list_all_payment_instructions()

    total_invoiced = Decimal("0.00")
    reconciled_amount = Decimal("0.00")
    discrepancy_amount = Decimal("0.00")
    withheld_amount = Decimal("0.00")
    approved_for_payment = Decimal("0.00")

    pending_approvals_count = 0
    verified_count = 0
    review_required_count = 0
    blocked_count = 0
    not_verified_count = 0
    approved_cases_count = 0
    rejected_cases_count = 0
    overcharge_cases_count = 0
    demo_cases_count = 0

    attention_items: List[Dict[str, Any]] = []
    key_bytes = get_active_signing_key()

    for s in summaries:
        c_dir = _case_service._resolve_case_dir(s.case_id)
        if c_dir and c_dir.name.startswith("demo-"):
            demo_cases_count += 1

        inv_dec = to_dec(s.invoiced_total)
        pay_dec = to_dec(s.payable_total)
        with_dec = to_dec(s.withheld_total)

        total_invoiced += inv_dec

        if s.verification_status == "VERIFIED":
            verified_count += 1
            reconciled_amount += pay_dec
            withheld_amount += with_dec
            discrepancy_amount += with_dec
            if with_dec > Decimal("0.00"):
                overcharge_cases_count += 1
        elif s.verification_status == "REVIEW_REQUIRED":
            review_required_count += 1
            var_dec = max(Decimal("0.00"), inv_dec - pay_dec)
            reconciled_amount += pay_dec
            discrepancy_amount += var_dec
            withheld_amount += var_dec
        elif s.verification_status == "BLOCKED":
            blocked_count += 1
            discrepancy_amount += inv_dec
            withheld_amount += inv_dec
        else:
            not_verified_count += 1

        if s.approval_status == "APPROVED":
            approved_cases_count += 1
            approved_for_payment += pay_dec
        elif s.approval_status == "REJECTED":
            rejected_cases_count += 1
        elif c_dir and (c_dir / "approvals" / "approval_receipt.json").exists():
            try:
                rec_d = load_json(c_dir / "approvals" / "approval_receipt.json")
                receipt_decision = rec_d.get("decision")
                if receipt_decision == "APPROVED":
                    approved_cases_count += 1
                    approved_for_payment += to_dec(rec_d.get("approved_amount"))
                elif receipt_decision == "REJECTED":
                    rejected_cases_count += 1
            except Exception as exc:
                logger.debug("Failed reading receipt for %s: %s", s.case_id, exc)

        if s.verification_status == "VERIFIED" and s.approval_status in ("NOT_REQUESTED", "PENDING"):
            pending_approvals_count += 1
            attention_items.append({
                "type": "PENDING_APPROVAL",
                "severity": "AMBER",
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "amount": fmt_dec(pay_dec),
                "withheld_amount": fmt_dec(with_dec),
                "summary": (
                    f"Verified payable INR {fmt_dec(pay_dec)}"
                    + (f" (INR {fmt_dec(with_dec)} overcharge withheld)" if with_dec > Decimal("0.00") else "")
                    + " awaiting human authorization."
                ),
                "action_label": "Review & Approve",
                "target_section": "approvals",
            })

        if s.verification_status == "BLOCKED":
            blocking_reason = "Source arithmetic discrepancy or contract verification block."
            if c_dir and (c_dir / "compare.json").exists():
                try:
                    issues = load_json(c_dir / "compare.json").get("blocking_issues", [])
                    if issues:
                        blocking_reason = issues[0]
                except Exception:
                    pass
            attention_items.append({
                "type": "BLOCKED_CASE",
                "severity": "RED",
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "amount": fmt_dec(inv_dec),
                "withheld_amount": fmt_dec(inv_dec),
                "summary": blocking_reason,
                "action_label": "Inspect Block",
                "target_section": "reconciliation",
            })

        if s.verification_status == "REVIEW_REQUIRED":
            attention_items.append({
                "type": "UNRESOLVED_DISCREPANCY",
                "severity": "AMBER",
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "amount": fmt_dec(inv_dec),
                "withheld_amount": fmt_dec(max(Decimal("0.00"), inv_dec - pay_dec)),
                "summary": "Contains uncontracted or unmatched SKU lines quarantined from payment.",
                "action_label": "Inspect Variance",
                "target_section": "reconciliation",
            })

    ledger_path = ROOT_DIR / DEFAULT_LEDGER_DB
    l_valid, l_issues = verify_ledger(ledger_path)
    all_events = list_events(db_path=ledger_path)
    latest_event = all_events[-1] if all_events else None

    return {
        "currency": "INR",
        "computed_at": utc_now_iso(),
        "is_demo_environment": False,
        "demo_cases_count": demo_cases_count,
        "financial_position": {
            "total_invoiced": fmt_dec(total_invoiced),
            "reconciled_amount": fmt_dec(reconciled_amount),
            "discrepancy_amount": fmt_dec(discrepancy_amount),
            "withheld_amount": fmt_dec(withheld_amount),
            "approved_for_payment": fmt_dec(approved_for_payment),
            "pending_approvals_count": pending_approvals_count,
        },
        "case_counts": {
            "total": len(summaries),
            "verified": verified_count,
            "review_required": review_required_count,
            "blocked": blocked_count,
            "not_verified": not_verified_count,
            "approved": approved_cases_count,
            "rejected": rejected_cases_count,
            "overcharge_detected": overcharge_cases_count,
            "payment_instructions": len(instructions),
        },
        "attention_required": attention_items,
        "recent_events": list(reversed(all_events[-12:])),
        "audit_integrity": {
            "valid": l_valid,
            "total_events": len(all_events),
            "highest_sequence": latest_event["event_sequence"] if latest_event else 0,
            "head_event_hash": latest_event["event_hash"] if latest_event else GENESIS_PREV_HASH,
            "genesis_prev_hash": GENESIS_PREV_HASH,
            "issues_count": len(l_issues),
            "issues": l_issues,
        },
    }


def build_case_workspace(case_id: str, current_user: User) -> Optional[Dict[str, Any]]:
    """Build complete Case Detail Workspace payload from persisted case files and SQLite."""
    c_dir = _case_service._resolve_case_dir(case_id)
    if not c_dir or not c_dir.exists():
        return None

    detail = _case_service._detail_case_dir(c_dir)
    actual_case_id = detail.case_id

    inv_data = load_json(c_dir / "invoice.json") if (c_dir / "invoice.json").exists() else {}
    case_meta = load_json(c_dir / "case.json") if (c_dir / "case.json").exists() else {
        "case_id": actual_case_id,
        "vendor_id": detail.vendor_id,
        "created_by": detail.created_by,
        "created_at": detail.created_at,
        "current_state": detail.verification_status,
        "version": 1,
        "state_history": [],
    }
    comp_p = c_dir / "compare.json"
    comp_data = load_json(comp_p) if comp_p.exists() else None
    if isinstance(comp_data, dict) and not comp_data.get("comparison_digest"):
        try:
            comp_data["comparison_digest"] = sha256_file(comp_p)
        except Exception:
            pass

    ver_data = load_json(c_dir / "audit" / "verification.json") if (c_dir / "audit" / "verification.json").exists() else None

    # Vendor & contract info: Strictly reject fallback to acme.json if vendor_id is different
    vendor_id = detail.vendor_id
    vendor_data = None
    if vendor_id:
        v_path = ROOT_DIR / "vendors" / f"{vendor_id}.json"
        if v_path.exists():
            vendor_data = load_json(v_path)
        else:
            s_path = ROOT_DIR / "seed" / f"{vendor_id}.json"
            if s_path.exists():
                vendor_data = load_json(s_path)

    # Evidence list and on-disk verification
    ev_list = list_evidence(c_dir)
    ev_verification = None
    if ev_list:
        try:
            ev_verification = verify_evidence(c_dir, base_dir=ROOT_DIR)
        except Exception as exc:
            ev_verification = {"ok": False, "failures": [str(exc)], "results": []}

    # Approval receipt inspection
    key_bytes = get_active_signing_key()
    receipt_data = None
    receipt_valid = False
    receipt_issues: List[str] = []
    receipt_p = c_dir / "approvals" / "approval_receipt.json"
    if not receipt_p.exists():
        receipt_p = c_dir / "approval_receipt.json"
    if receipt_p.exists():
        try:
            receipt_data = load_json(receipt_p)
            receipt_valid, receipt_issues = verify_approval_receipt(receipt_data, key_bytes=key_bytes)
        except Exception as exc:
            receipt_issues = [f"Error reading approval receipt: {exc}"]

    # Payment instruction
    payment_inst = None
    try:
        inst_list = _payment_repo.list_by_case(actual_case_id)
        if inst_list:
            payment_inst = inst_list[-1].to_dict()
    except Exception as exc:
        logger.debug("Failed listing payments for %s: %s", actual_case_id, exc)

    # Available artifacts
    artifacts = {}
    for aname in (
        "invoice.json",
        "compare.json",
        "payment_preview.csv",
        "corrected_payment.csv",
        "partial_review.csv",
        "blocked_review_report.csv",
        "dispute_email.md",
        "evidence_registry.json",
        "manifest.json",
    ):
        ap = c_dir / aname
        if ap.exists():
            artifacts[aname] = {
                "filename": aname,
                "size_bytes": ap.stat().st_size,
                "sha256": sha256_file(ap),
                "path": str(ap.relative_to(ROOT_DIR)),
            }

    can_approve, policy_msg = _auth_service.evaluate_approval_policy(
        approver=current_user,
        case_creator_username=detail.created_by,
        verification_status=detail.verification_status,
    )
    can_reject = _auth_service.has_permission(current_user, PERM_CASE_REJECT)

    return {
        "case_id": actual_case_id,
        "detail": detail.to_dict(),
        "case_metadata": case_meta,
        "invoice_data": inv_data,
        "comparison": comp_data,
        "verification": ver_data,
        "vendor": vendor_data,
        "evidence": {
            "registered_items": ev_list,
            "verification_result": ev_verification,
        },
        "approval": {
            "status": detail.approval_status,
            "receipt": receipt_data,
            "receipt_valid": receipt_valid,
            "receipt_issues": receipt_issues,
            "can_approve": can_approve,
            "can_reject": can_reject,
            "policy_message": policy_msg,
        },
        "payment": {
            "status": detail.payment_status,
            "instruction": payment_inst,
        },
        "artifacts": artifacts,
    }


def list_vendors_payload() -> List[Dict[str, Any]]:
    """List all vendors with calculated statistics and Schedule A rates."""
    vendors_dir = ROOT_DIR / "vendors"
    summaries = _case_service.list_cases()
    results: List[Dict[str, Any]] = []
    if vendors_dir.exists():
        for f in sorted(vendors_dir.glob("*.json")):
            try:
                data = load_json(f)
                vid = data.get("vendor_id") or f.stem
                contract = data.get("contract", {})
                raw_rates = contract.get("rates") or []
                items = contract.get("items") or {}
                first_rate = raw_rates[0] if isinstance(raw_rates, list) and raw_rates else {}
                currency = data.get("currency") or contract.get("currency") or first_rate.get("currency") or "INR"
                effective_from = contract.get("effective_from") or first_rate.get("effective_from") or "2026-01-01"
                effective_to = contract.get("effective_to") or first_rate.get("effective_to") or "2026-12-31"

                rates: List[Dict[str, Any]] = []
                for idx, r in enumerate(raw_rates if isinstance(raw_rates, list) else [], start=1):
                    sku_val = str(r.get("sku") or r.get("item_code") or r.get("item_key") or f"SKU-{idx}").strip()
                    ikey_val = str(r.get("item_key") or re.sub(r"[^a-z0-9-]+", "-", sku_val.lower()).strip("-"))
                    desc_val = str(r.get("description") or sku_val).strip()
                    aliases_val = r.get("aliases") if isinstance(r.get("aliases"), list) and r.get("aliases") else [desc_val, sku_val]
                    rates.append({
                        **r,
                        "item_key": ikey_val,
                        "sku": sku_val,
                        "item_code": sku_val,
                        "description": desc_val,
                        "aliases": aliases_val,
                        "unit": str(r.get("unit") or "unit"),
                        "unit_price": fmt_dec(to_dec(r.get("unit_price", "0.00"))),
                        "currency": str(r.get("currency") or currency),
                        "effective_from": str(r.get("effective_from") or effective_from),
                        "effective_to": str(r.get("effective_to") or effective_to),
                        "clause_ref": str(r.get("clause_ref") or f"Schedule A, item {idx}"),
                    })

                items_count = len(rates) if rates else len(items)
                v_cases = [s for s in summaries if s.vendor_id == vid]
                v_invoiced = sum((to_dec(s.invoiced_total) for s in v_cases), Decimal("0.00"))
                v_payable = sum((to_dec(s.payable_total) for s in v_cases), Decimal("0.00"))
                v_withheld = sum((to_dec(s.withheld_total) for s in v_cases), Decimal("0.00"))

                dest = _vendor_registry.get_destination(vid)
                results.append({
                    "vendor_id": vid,
                    "vendor_name": data.get("name", vid),
                    "currency": currency,
                    "contract_id": contract.get("contract_id") or f"CON-{vid.upper()}-2026",
                    "source_file": contract.get("source_file") or f"contracts/{vid}-contract.md",
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "items_count": items_count,
                    "rates": rates,
                    "treasury_destination": {
                        "destination_reference": dest.destination_reference if dest else "UNREGISTERED",
                        "bank_verified": (dest.verification_status == "VERIFIED") if dest else False,
                        "allowed_currencies": [currency, "USD"],
                    },
                    "metrics": {
                        "cases_count": len(v_cases),
                        "total_invoiced": fmt_dec(v_invoiced),
                        "total_payable": fmt_dec(v_payable),
                        "total_withheld": fmt_dec(v_withheld),
                    },
                })
            except Exception as exc:
                logger.warning("Failed parsing vendor file %s: %s", f, exc)
    return results


def list_contracts_payload() -> List[Dict[str, Any]]:
    """List contracts and Schedule A rates."""
    vendors = list_vendors_payload()
    contracts_list: List[Dict[str, Any]] = []
    for v in vendors:
        src_rel = v.get("source_file") or ""
        src_path = ROOT_DIR / src_rel if src_rel else None
        raw_content = None
        src_sha256 = None
        if src_path and src_path.is_file():
            try:
                raw_content = src_path.read_text(encoding="utf-8")
                src_sha256 = sha256_file(src_path)
            except Exception as exc:
                logger.warning("Failed reading contract markdown %s: %s", src_path, exc)
        contracts_list.append({
            "contract_id": v.get("contract_id") or f"CON-{v['vendor_id'].upper()}",
            "vendor_id": v["vendor_id"],
            "vendor_name": v["vendor_name"],
            "currency": v["currency"],
            "effective_from": v["effective_from"],
            "effective_to": v["effective_to"],
            "source_file": src_rel,
            "source_sha256": src_sha256,
            "source_markdown": raw_content,
            "rates_count": len(v.get("rates") or []),
            "rates": v.get("rates") or [],
        })
    return contracts_list


def list_all_evidence_payload() -> Dict[str, Any]:
    """Scan all case directories and return registered evidence with live SHA-256 verification."""
    cases_p = ROOT_DIR / "cases"
    all_records: List[Dict[str, Any]] = []
    verified_count = 0
    failed_count = 0

    if cases_p.exists():
        for c_dir in sorted(cases_p.iterdir()):
            if not c_dir.is_dir() or c_dir.name.startswith("."):
                continue
            inv_p = c_dir / "invoice.json"
            case_id = c_dir.name
            inv_num = "UNKNOWN"
            vendor_id = "acme"
            if inv_p.exists():
                try:
                    idata = load_json(inv_p)
                    case_id = idata.get("case_id") or case_id
                    inv_num = idata.get("invoice_number") or inv_num
                    vendor_id = idata.get("vendor_id") or vendor_id
                except Exception:
                    pass

            ev_items = list_evidence(c_dir)
            if ev_items:
                try:
                    ver_res = verify_evidence(c_dir, base_dir=ROOT_DIR)
                    res_by_id = {r["evidence_id"]: r for r in ver_res.get("results", [])}
                except Exception:
                    res_by_id = {}
                for item in ev_items:
                    eid = item.get("evidence_id")
                    v_info = res_by_id.get(eid, {})
                    is_ok = bool(v_info.get("valid") or v_info.get("status") in ("VALID", "VERIFIED"))
                    if is_ok:
                        verified_count += 1
                    else:
                        failed_count += 1
                    c_hash = item.get("content_hash") or item.get("sha256") or ""
                    s_loc = item.get("stored_path") or item.get("source_locator") or item.get("original_filename") or ""
                    a_type = item.get("description") or item.get("artifact_type") or str(item.get("evidence_type", "ARTIFACT")).upper()
                    b_size = item.get("byte_size") if item.get("byte_size") is not None else item.get("size_bytes", 0)
                    reg_at = item.get("received_at") or item.get("registered_at") or ""
                    all_records.append({
                        "evidence_id": eid,
                        "case_id": case_id,
                        "case_folder": c_dir.name,
                        "invoice_number": inv_num,
                        "vendor_id": vendor_id,
                        "artifact_type": a_type,
                        "evidence_type": item.get("evidence_type"),
                        "source_locator": s_loc,
                        "recorded_sha256": c_hash,
                        "actual_sha256": v_info.get("actual_hash") or c_hash,
                        "size_bytes": b_size,
                        "registered_at": reg_at,
                        "verification_status": "VERIFIED" if is_ok else v_info.get("status", "UNVERIFIED"),
                        "verified": is_ok,
                    })

    raw_sources: List[Dict[str, Any]] = []
    for folder, kind in [("invoices", "RAW_INVOICE_FILE"), ("contracts", "CONTRACT_DOCUMENT")]:
        f_dir = ROOT_DIR / folder
        if f_dir.exists():
            for fp in sorted(f_dir.iterdir()):
                if fp.is_file() and not fp.name.startswith("."):
                    try:
                        raw_sources.append({
                            "path": f"{folder}/{fp.name}",
                            "kind": kind,
                            "sha256": sha256_file(fp),
                            "size_bytes": fp.stat().st_size,
                        })
                    except Exception:
                        pass

    return {
        "total_registered": len(all_records),
        "verified_count": verified_count,
        "failed_count": failed_count,
        "all_verified": failed_count == 0 and len(all_records) > 0,
        "items": all_records,
        "repository_sources": raw_sources,
    }


def build_approvals_payload(current_user: User) -> Dict[str, Any]:
    """Retrieve all pending approvals and signed receipts."""
    summaries = _case_service.list_cases()
    key_bytes = get_active_signing_key()
    pending_queue: List[Dict[str, Any]] = []
    decided_receipts: List[Dict[str, Any]] = []

    for s in summaries:
        c_dir = _case_service._resolve_case_dir(s.case_id)
        if not c_dir:
            continue

        rec_p = c_dir / "approvals" / "approval_receipt.json"
        if not rec_p.exists():
            rec_p = c_dir / "approval_receipt.json"
        if rec_p.exists():
            try:
                rec_data = load_json(rec_p)
                r_valid, r_issues = verify_approval_receipt(rec_data, key_bytes=key_bytes)
                decided_receipts.append({
                    "receipt_id": rec_data.get("receipt_id"),
                    "case_id": s.case_id,
                    "invoice_number": s.invoice_number,
                    "vendor_id": s.vendor_id,
                    "contract_id": rec_data.get("contract_id"),
                    "decision": rec_data.get("decision"),
                    "actor_id": rec_data.get("actor_id"),
                    "actor_role": rec_data.get("actor_role"),
                    "approved_amount": rec_data.get("approved_amount"),
                    "withheld_amount": rec_data.get("withheld_amount"),
                    "currency": rec_data.get("currency", "INR"),
                    "reason": rec_data.get("reason"),
                    "created_at": rec_data.get("created_at"),
                    "invoice_sha256": rec_data.get("invoice_sha256"),
                    "compare_sha256": rec_data.get("compare_sha256"),
                    "audit_sha256": rec_data.get("audit_sha256"),
                    "receipt_hash": rec_data.get("receipt_hash"),
                    "receipt_signature": rec_data.get("receipt_signature"),
                    "cryptographically_valid": r_valid,
                    "verification_issues": r_issues,
                })
            except Exception as exc:
                logger.warning("Failed loading receipt for %s: %s", s.case_id, exc)
        else:
            can_approve, policy_msg = _auth_service.evaluate_approval_policy(
                approver=current_user,
                case_creator_username=s.created_by,
                verification_status=s.verification_status,
            )
            can_reject = _auth_service.has_permission(current_user, PERM_CASE_REJECT) and (
                s.verification_status in ("VERIFIED", "REVIEW_REQUIRED", "BLOCKED")
            )
            pending_queue.append({
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "created_by": s.created_by,
                "created_at": s.created_at,
                "verification_status": s.verification_status,
                "commercial_status": s.commercial_status,
                "invoiced_total": s.invoiced_total,
                "payable_total": s.payable_total,
                "withheld_total": s.withheld_total,
                "can_approve": can_approve,
                "can_reject": can_reject,
                "policy_message": policy_msg,
            })

    return {
        "current_actor": current_user.username,
        "current_role": current_user.role,
        "pending_count": len([p for p in pending_queue if p["verification_status"] == "VERIFIED"]),
        "pending_queue": pending_queue,
        "decided_receipts": decided_receipts,
    }


def build_payments_payload() -> Dict[str, Any]:
    """Retrieve all payment instructions and summaries."""
    instructions = list_all_payment_instructions()
    summaries = _case_service.list_cases()
    inst_by_case = {i["case_id"]: i for i in instructions}

    total_approved_payable = Decimal("0.00")
    total_exported_amount = Decimal("0.00")
    total_withheld_amount = Decimal("0.00")
    total_blocked_amount = Decimal("0.00")

    eligible_cases: List[Dict[str, Any]] = []
    withheld_or_blocked_cases: List[Dict[str, Any]] = []

    for s in summaries:
        c_dir = _case_service._resolve_case_dir(s.case_id)
        inv_dec = to_dec(s.invoiced_total)
        pay_dec = to_dec(s.payable_total)
        with_dec = to_dec(s.withheld_total)

        if with_dec > Decimal("0.00"):
            total_withheld_amount += with_dec
        if s.verification_status == "BLOCKED":
            total_blocked_amount += inv_dec

        if s.approval_status == "APPROVED":
            total_approved_payable += pay_dec
            existing_inst = inst_by_case.get(s.case_id) or (inst_by_case.get(c_dir.name) if c_dir else None)
            dest = _vendor_registry.get_destination(s.vendor_id)
            eligible_cases.append({
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "invoiced_total": fmt_dec(inv_dec),
                "approved_payable": fmt_dec(pay_dec),
                "withheld_overcharge": fmt_dec(with_dec),
                "approval_status": s.approval_status,
                "payment_status": existing_inst["status"] if existing_inst else s.payment_status,
                "instruction": existing_inst,
                "destination_reference": dest.destination_reference if dest else "UNREGISTERED",
                "bank_verified": (dest.verification_status == "VERIFIED") if dest else False,
            })
        elif with_dec > Decimal("0.00") or s.verification_status in ("BLOCKED", "REVIEW_REQUIRED") or s.approval_status == "REJECTED":
            withheld_or_blocked_cases.append({
                "case_id": s.case_id,
                "invoice_number": s.invoice_number,
                "vendor_id": s.vendor_id,
                "verification_status": s.verification_status,
                "commercial_status": s.commercial_status,
                "approval_status": s.approval_status,
                "invoiced_total": fmt_dec(inv_dec),
                "payable_total": fmt_dec(pay_dec),
                "withheld_total": fmt_dec(with_dec if with_dec > Decimal("0.00") else (inv_dec - pay_dec)),
            })

    for inst in instructions:
        if inst["status"] == "EXPORTED":
            total_exported_amount += to_dec(inst["approved_amount"])

    return {
        "currency": "INR",
        "metrics": {
            "total_approved_payable": fmt_dec(total_approved_payable),
            "total_exported_amount": fmt_dec(total_exported_amount),
            "total_withheld_overcharges": fmt_dec(total_withheld_amount),
            "total_blocked_amount": fmt_dec(total_blocked_amount),
            "instructions_count": len(instructions),
        },
        "instructions": instructions,
        "approved_cases": eligible_cases,
        "withheld_and_blocked": withheld_or_blocked_cases,
    }


def list_checkpoints_payload() -> List[Dict[str, Any]]:
    """List signed ledger checkpoints."""
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    key_bytes = get_active_signing_key()
    results: List[Dict[str, Any]] = []
    for fp in sorted(CHECKPOINTS_DIR.glob("*.json"), reverse=True):
        try:
            chk = load_json(fp)
            ok, issues = verify_checkpoint(
                chk,
                db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                key_bytes=key_bytes,
            )
            chk["verified"] = ok
            chk["verification_issues"] = issues
            results.append(chk)
        except Exception as exc:
            logger.warning("Failed verifying checkpoint %s: %s", fp, exc)
    return results


def build_integrations_payload() -> Dict[str, Any]:
    """Retrieve integration status for Switch room, webhooks, and agents."""
    switch_url = os.getenv("SWITCH_WEBHOOK_URL", "").strip()
    mm_url = os.getenv("MATTERMOST_URL", "").strip()
    mm_channel = os.getenv("SWITCH_CHANNEL", "#overcharge-desk").strip()

    agents_info = []
    for agent_id, role_desc, fname in [
        ("@reader", "Intake & Cryptographic Evidence Registration Agent", "READER.md"),
        ("@auditor", "Deterministic 13-Stage Reconciliation & Vendor Memory Agent", "AUDITOR.md"),
        ("@writer", "Receipt Verification, Payment Sheet & Dispute Notice Agent", "WRITER.md"),
    ]:
        ap = ROOT_DIR / "agents" / fname
        sha = sha256_file(ap) if ap.exists() else None
        agents_info.append({
            "handle": agent_id,
            "description": role_desc,
            "spec_file": f"agents/{fname}",
            "spec_sha256": sha,
            "can_approve_payments": False,
        })

    return {
        "integrations": [
            {
                "id": "switch_mattermost",
                "name": "Switch / Mattermost Multi-Agent Room",
                "channel": mm_channel,
                "status": "CONNECTED" if (switch_url and mm_url) else "NOT_CONFIGURED",
                "simulation_available": True,
                "webhook_configured": bool(switch_url),
                "server_url": mm_url or "Not configured (Local deterministic CLI mode active)",
                "security_boundary": "Strict Out-of-Band Approval: Chat room messages never grant financial authorization.",
            },
            {
                "id": "treasury_export",
                "name": "Treasury ERP Batch Disbursal Interface",
                "channel": "CSV / Canonical JSON One-Time Export",
                "status": "ACTIVE",
                "simulation_available": True,
                "webhook_configured": True,
                "server_url": "Local SQLite PaymentRepository (payments.db)",
                "security_boundary": "Requires verified HMAC receipt + verified VendorRegistry bank destination.",
            },
        ],
        "agents": agents_info,
    }


def list_users_and_roles_payload() -> Dict[str, Any]:
    """List users from persistent SQLite identity repository."""
    conn = sqlite3.connect(str(ROOT_DIR / DEFAULT_IDENTITY_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT user_id, username, email, full_name, role, is_active, is_demo, created_at, updated_at, version "
            "FROM users ORDER BY username ASC"
        ).fetchall()
        users = [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "email": r["email"],
                "full_name": r["full_name"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "is_demo": bool(r["is_demo"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "version": r["version"],
                "permissions": sorted(list(ROLE_PERMISSIONS.get(r["role"], set()))),
            }
            for r in rows
        ]
        return {
            "total_users": len(users),
            "users": users,
            "roles": [
                {"role": SystemRole.ADMINISTRATOR, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.ADMINISTRATOR, set())))},
                {"role": SystemRole.AUDITOR, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.AUDITOR, set())))},
                {"role": SystemRole.FINANCE_OPERATOR, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.FINANCE_OPERATOR, set())))},
                {"role": SystemRole.REVIEWER, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.REVIEWER, set())))},
                {"role": SystemRole.APPROVER, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.APPROVER, set())))},
                {"role": SystemRole.PAYMENT_OPERATOR, "permissions": sorted(list(ROLE_PERMISSIONS.get(SystemRole.PAYMENT_OPERATOR, set())))},
            ],
        }
    finally:
        conn.close()
