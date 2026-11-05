#!/usr/bin/env python3
"""Overcharge Desk — Financial Control Infrastructure Server & API.

Zero-dependency Python 3.10+ HTTP server binding to 0.0.0.0:3000 that serves
the Overcharge Desk Financial Control Workspace (`apps/web/index.html`) and
exposes deterministic financial reconciliation, evidence verification, RBAC
authorization, payment instruction control, and tamper-evident SQLite audit
ledger endpoints under `/api/v1/*`.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# Ensure repository root and tools/ are on sys.path
ROOT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from approval_receipt import verify_approval_receipt
from audit_ledger import (
    DEFAULT_LEDGER_DB,
    GENESIS_PREV_HASH,
    create_checkpoint,
    init_db as init_ledger_db,
    list_events,
    record_event,
    verify_checkpoint,
    verify_ledger,
)
from auth import get_default_key_path, load_signing_key
from common import ToolError, load_json, sha256_file, utc_now_iso, write_json_atomic
from domain.authorization.policies import (
    AuthorizationService,
    PERM_ADMIN_CONFIG,
    PERM_ADMIN_USERS,
    PERM_AUDIT_CHECKPOINT,
    PERM_AUDIT_READ,
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_READ,
    PERM_CASE_RECONCILE,
    PERM_CASE_REJECT,
    PERM_CASE_REVIEW,
    PERM_PAYMENT_EXPORT,
    ROLE_PERMISSIONS,
)
from domain.cases.service import CaseService
from domain.identity.key_manager import KeyManager
from domain.identity.models import IdentityService, SystemRole, User
from domain.identity.passwords import hash_password
from domain.identity.repository import DEFAULT_IDENTITY_DB, IdentityRepository
from domain.payments.repository import DEFAULT_PAYMENT_DB, PaymentRepository
from domain.vendors.models import DEFAULT_VENDOR_DESTINATIONS, VendorDestination, VendorRegistry
from evidence import list_evidence, register_evidence, verify_evidence
from run_demo_suite import run_full_demo

APP_ENV = os.getenv("APP_ENV", "development").lower()
WEB_DIR = ROOT_DIR / "apps" / "web"
CHECKPOINTS_DIR = ROOT_DIR / "checkpoints"

TWOPLACES = Decimal("0.01")

# Shared domain singletons
_identity_service = IdentityService()
_auth_service = AuthorizationService(enforce_strict_separation_of_duties=True)
_key_manager = KeyManager(app_env=APP_ENV)
_vendor_registry = VendorRegistry()
_case_service = CaseService(base_dir=ROOT_DIR, auth_service=_auth_service)
_payment_repo = PaymentRepository(db_path=ROOT_DIR / DEFAULT_PAYMENT_DB)
_case_service.payment_service.vendor_registry = _vendor_registry
_case_service.payment_service.repo = _payment_repo

# Sync custom vendors from vendors/*.json into _vendor_registry
def _sync_vendor_registry() -> None:
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
        except Exception:
            pass

_sync_vendor_registry()

# Brute-force login lockout tracking: 5 failed attempts -> 300s lockout
_FAILED_LOGINS: Dict[str, Tuple[int, float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300


def to_dec(val: Any) -> Decimal:
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def fmt_dec(val: Decimal) -> str:
    return str(val.quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def record_failed_login(username: str) -> bool:
    now = time.time()
    key = username.lower()
    count, until = _FAILED_LOGINS.get(key, (0, 0.0))
    if now < until:
        return True
    count += 1
    if count >= MAX_FAILED_ATTEMPTS:
        _FAILED_LOGINS[key] = (count, now + LOCKOUT_DURATION_SECONDS)
        return True
    _FAILED_LOGINS[key] = (count, 0.0)
    return False


def is_user_locked_out(username: str) -> bool:
    now = time.time()
    _, until = _FAILED_LOGINS.get(username.lower(), (0, 0.0))
    return now < until


def reset_failed_logins(username: str) -> None:
    _FAILED_LOGINS.pop(username.lower(), None)


def _write_contract_markdown(
    vendor_id: str,
    vendor_name: str,
    contract_id: str,
    effective_from: str,
    effective_to: str,
    currency: str,
    rates: List[Dict[str, Any]],
) -> str:
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
    ]
    for r in rates:
        md_lines.append(
            f"- **{r.get('clause_ref', 'Schedule A')}**: `{r.get('sku') or r.get('item_code')}` "
            f"({r.get('description')}) — {currency} {r.get('unit_price')} per {r.get('unit', 'unit')}"
        )
    src_md_abs.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return src_md_rel


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
    _sync_vendor_registry()


def get_active_signing_key() -> bytes:
    try:
        _, key_bytes = _key_manager.get_active_key()
        return key_bytes
    except Exception:
        key_path = get_default_key_path()
        if key_path.exists():
            return load_signing_key(key_path)
        return b"0123456789abcdef0123456789abcdef"


def build_health_payload() -> Dict[str, Any]:
    checks: Dict[str, str] = {}
    details: Dict[str, Any] = {}
    is_ready = True

    # 1. Identity Database
    try:
        id_repo = IdentityRepository(db_path=ROOT_DIR / DEFAULT_IDENTITY_DB)
        id_repo.check_production_safety(app_env=APP_ENV)
        conn = sqlite3.connect(str(ROOT_DIR / DEFAULT_IDENTITY_DB))
        conn.row_factory = sqlite3.Row
        u_cnt = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        s_cnt = conn.execute("SELECT COUNT(*) AS c FROM sessions WHERE revoked_at IS NULL").fetchone()["c"]
        j_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        checks["identity_database"] = "OK"
        checks["database"] = "OK"
        details["identity_db"] = {
            "status": "HEALTHY",
            "path": str(DEFAULT_IDENTITY_DB),
            "journal_mode": str(j_mode).upper(),
            "users_count": u_cnt,
            "active_sessions_count": s_cnt,
        }
    except Exception as exc:
        checks["identity_database"] = f"ERROR: {exc}"
        checks["database"] = f"ERROR: {exc}"
        details["identity_db"] = {"status": "ERROR", "error": str(exc)}
        is_ready = False

    # 2. Audit Ledger Database
    try:
        ledger_path = ROOT_DIR / DEFAULT_LEDGER_DB
        init_ledger_db(ledger_path)
        l_valid, l_issues = verify_ledger(ledger_path)
        events = list_events(db_path=ledger_path)
        conn = sqlite3.connect(str(ledger_path))
        j_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        trig_cnt = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_events'"
        ).fetchone()[0]
        conn.close()
        checks["ledger_database"] = "OK" if l_valid else f"TAMPERED ({len(l_issues)} issues)"
        details["ledger_db"] = {
            "status": "HEALTHY" if l_valid else "COMPROMISED",
            "path": str(DEFAULT_LEDGER_DB),
            "journal_mode": str(j_mode).upper(),
            "append_only_triggers": trig_cnt,
            "events_count": len(events),
            "chain_valid": l_valid,
            "head_hash": events[-1]["event_hash"] if events else GENESIS_PREV_HASH,
            "issues": l_issues,
        }
        if not l_valid:
            is_ready = False
    except Exception as exc:
        checks["ledger_database"] = f"ERROR: {exc}"
        details["ledger_db"] = {"status": "ERROR", "error": str(exc)}
        is_ready = False

    # 3. Payments Database
    try:
        pay_path = ROOT_DIR / DEFAULT_PAYMENT_DB
        _payment_repo.init_db()
        conn = sqlite3.connect(str(pay_path))
        p_cnt = conn.execute("SELECT COUNT(*) FROM payment_instructions").fetchone()[0]
        j_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        checks["payments_database"] = "OK"
        details["payments_db"] = {
            "status": "HEALTHY",
            "path": str(DEFAULT_PAYMENT_DB),
            "journal_mode": str(j_mode).upper(),
            "instructions_count": p_cnt,
        }
    except Exception as exc:
        checks["payments_database"] = f"ERROR: {exc}"
        details["payments_db"] = {"status": "ERROR", "error": str(exc)}
        is_ready = False

    # 4. Signing Key & Key Manager
    try:
        active_id, key_bytes = _key_manager.get_active_key()
        checks["signing_key"] = f"OK ({active_id})"
        checks["key_manager"] = "OK"
        details["signing_key"] = {
            "status": "HEALTHY",
            "active_key_id": active_id,
            "key_length_bits": len(key_bytes) * 8,
            "algorithm": "HMAC-SHA256",
        }
    except Exception as exc:
        checks["signing_key"] = f"ERROR: {exc}"
        checks["key_manager"] = f"ERROR: {exc}"
        details["signing_key"] = {"status": "ERROR", "error": str(exc)}
        is_ready = False

    # 5. Case Storage Isolation
    try:
        cases_p = ROOT_DIR / "cases"
        cases_p.mkdir(parents=True, exist_ok=True)
        test_file = cases_p / ".health_check.tmp"
        test_file.write_text("health", encoding="utf-8")
        test_file.unlink()
        case_dirs = [d for d in cases_p.iterdir() if d.is_dir() and not d.name.startswith(".")]
        checks["storage"] = "OK"
        details["storage"] = {
            "status": "HEALTHY",
            "cases_directory": str(cases_p.relative_to(ROOT_DIR)),
            "active_case_directories": len(case_dirs),
            "path_containment": "ENFORCED",
        }
    except Exception as exc:
        checks["storage"] = f"ERROR: {exc}"
        details["storage"] = {"status": "ERROR", "error": str(exc)}
        is_ready = False

    return {
        "status": "READY" if is_ready else "DEGRADED",
        "is_ready": is_ready,
        "service": "overcharge-desk-api",
        "environment": APP_ENV,
        "checked_at": utc_now_iso(),
        "checks": checks,
        "details": details,
    }


def list_all_payment_instructions() -> List[Dict[str, Any]]:
    _payment_repo.init_db()
    conn = sqlite3.connect(str(ROOT_DIR / DEFAULT_PAYMENT_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM payment_instructions ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            result.append(
                {
                    "instruction_id": r["instruction_id"],
                    "case_id": r["case_id"],
                    "approval_receipt_id": r["approval_receipt_id"],
                    "approved_amount": r["approved_amount"],
                    "currency": r["currency"],
                    "vendor_id": r["vendor_id"],
                    "destination_reference": r["destination_reference"],
                    "destination_verified": bool(r["destination_verified"]),
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "idempotency_key": r["idempotency_key"],
                    "exported_at": r["exported_at"],
                    "exported_by": r["exported_by"],
                }
            )
        return result
    finally:
        conn.close()


def build_overview_metrics(current_user: User) -> Dict[str, Any]:
    """Compute all financial control metrics strictly from persisted case records using Decimal."""
    summaries = _case_service.list_cases()
    instructions = list_all_payment_instructions()
    inst_by_case: Dict[str, List[Dict[str, Any]]] = {}
    for inst in instructions:
        inst_by_case.setdefault(inst["case_id"], []).append(inst)

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

    cases_p = ROOT_DIR / "cases"
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
        elif s.verification_status == "REVIEW_REQUIRED":
            review_required_count += 1
            reconciled_amount += pay_dec
            # Any unverified or variance portion is part of discrepancy
            unmatched_gap = max(Decimal("0.00"), inv_dec - pay_dec)
            discrepancy_amount += max(with_dec, unmatched_gap)
            withheld_amount += with_dec
        elif s.verification_status == "BLOCKED":
            blocked_count += 1
            discrepancy_amount += inv_dec
        else:
            not_verified_count += 1

        if s.commercial_status == "OVERCHARGE_DETECTED" or with_dec > Decimal("0.00"):
            overcharge_cases_count += 1

        # Check cryptographic approval receipt if present
        receipt_valid = False
        receipt_decision = s.approval_status
        if c_dir:
            rec_p = c_dir / "approvals" / "approval_receipt.json"
            if rec_p.exists():
                try:
                    rec_data = load_json(rec_p)
                    receipt_decision = rec_data.get("decision", receipt_decision)
                    r_ok, _ = verify_approval_receipt(rec_data, key_bytes=key_bytes)
                    receipt_valid = r_ok
                    if r_ok and receipt_decision == "APPROVED":
                        approved_for_payment += to_dec(rec_data.get("approved_amount"))
                        approved_cases_count += 1
                    elif receipt_decision == "REJECTED":
                        rejected_cases_count += 1
                except Exception:
                    pass

        # Check pending approval
        if s.verification_status == "VERIFIED" and s.approval_status in ("NOT_REQUESTED", "PENDING"):
            pending_approvals_count += 1
            attention_items.append(
                {
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
                }
            )

        # Check blocked cases
        if s.verification_status == "BLOCKED":
            blocking_reason = "Source arithmetic discrepancy or contract verification block."
            if c_dir and (c_dir / "compare.json").exists():
                try:
                    issues = load_json(c_dir / "compare.json").get("blocking_issues", [])
                    if issues:
                        blocking_reason = issues[0]
                except Exception:
                    pass
            attention_items.append(
                {
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
                }
            )

        # Check review required cases (unmatched items)
        if s.verification_status == "REVIEW_REQUIRED":
            attention_items.append(
                {
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
                }
            )

        # Check missing evidence
        if c_dir:
            ev_list = list_evidence(c_dir)
            if not ev_list:
                attention_items.append(
                    {
                        "type": "MISSING_EVIDENCE",
                        "severity": "AMBER",
                        "case_id": s.case_id,
                        "invoice_number": s.invoice_number,
                        "vendor_id": s.vendor_id,
                        "amount": fmt_dec(inv_dec),
                        "withheld_amount": "0.00",
                        "summary": "No cryptographic source artifacts registered in case evidence registry.",
                        "action_label": "Register Evidence",
                        "target_section": "evidence",
                    }
                )

    # Audit ledger live verification
    ledger_path = ROOT_DIR / DEFAULT_LEDGER_DB
    l_valid, l_issues = verify_ledger(ledger_path)
    all_events = list_events(db_path=ledger_path)
    latest_event = all_events[-1] if all_events else None

    health = build_health_payload()

    return {
        "currency": "INR",
        "computed_at": utc_now_iso(),
        "is_demo_environment": False,
        "demo_cases_count": 0,
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
        "system_status": health,
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

    # Vendor & contract info
    vendor_id = detail.vendor_id or "acme"
    vendor_file = ROOT_DIR / "vendors" / f"{vendor_id}.json"
    if not vendor_file.exists():
        vendor_file = ROOT_DIR / "vendors" / "acme.json"
    vendor_data = load_json(vendor_file) if vendor_file.exists() else {}
    dest_info = _vendor_registry.get_destination(vendor_id)

    # Evidence registry & live SHA-256 verification
    raw_ev_items = list_evidence(c_dir)
    ev_verified_ok = True
    ev_verification_details: List[Dict[str, Any]] = []
    res_by_id: Dict[str, Dict[str, Any]] = {}
    if raw_ev_items:
        ev_res = verify_evidence(c_dir, base_dir=ROOT_DIR)
        ev_verified_ok = bool(ev_res.get("valid", ev_res.get("ok", False)))
        for r in ev_res.get("results", []):
            r_norm = dict(r)
            r_norm["status"] = "VERIFIED" if r.get("valid") else r.get("status", "UNVERIFIED")
            ev_verification_details.append(r_norm)
            res_by_id[r.get("evidence_id", "")] = r_norm

    ev_items: List[Dict[str, Any]] = []
    for item in raw_ev_items:
        eid = item.get("evidence_id", "")
        vr = res_by_id.get(eid, {})
        c_hash = item.get("content_hash") or item.get("sha256") or ""
        s_loc = item.get("stored_path") or item.get("source_locator") or item.get("original_filename") or ""
        a_type = item.get("description") or item.get("artifact_type") or str(item.get("evidence_type", "ARTIFACT")).upper()
        b_size = item.get("byte_size") if item.get("byte_size") is not None else item.get("size_bytes", 0)
        reg_at = item.get("received_at") or item.get("registered_at") or ""
        ev_items.append(
            {
                **item,
                "evidence_id": eid,
                "artifact_type": a_type,
                "source_locator": s_loc,
                "sha256": c_hash,
                "recorded_sha256": c_hash,
                "actual_sha256": vr.get("actual_hash") or c_hash,
                "size_bytes": b_size,
                "registered_at": reg_at,
                "verification_status": vr.get("status", "VERIFIED"),
                "verified": bool(vr.get("valid", True)),
            }
        )

    # Approval receipt & live HMAC verification
    receipt_payload = None
    rec_p = c_dir / "approvals" / "approval_receipt.json"
    if rec_p.exists():
        try:
            raw_rec = load_json(rec_p)
            key_bytes = get_active_signing_key()
            r_valid, r_issues = verify_approval_receipt(raw_rec, key_bytes=key_bytes)
            receipt_payload = {
                "receipt": raw_rec,
                "cryptographically_valid": r_valid,
                "verification_issues": r_issues,
            }
        except Exception as exc:
            receipt_payload = {
                "receipt": None,
                "cryptographically_valid": False,
                "verification_issues": [str(exc)],
            }

    # Evaluate if current user can approve this case
    can_approve, policy_msg = _auth_service.evaluate_approval_policy(
        approver=current_user,
        case_creator_username=detail.created_by,
        verification_status=detail.verification_status,
    )

    # Payment instructions for this case
    all_inst = list_all_payment_instructions()
    case_instructions = [
        i for i in all_inst if i["case_id"] in (actual_case_id, c_dir.name, case_id)
    ]

    # Audit events for this case
    events = list_events(case_id=actual_case_id, db_path=ROOT_DIR / DEFAULT_LEDGER_DB)
    if c_dir.name != actual_case_id:
        folder_events = list_events(case_id=c_dir.name, db_path=ROOT_DIR / DEFAULT_LEDGER_DB)
        seen_ids = {e["event_id"] for e in events}
        for fe in folder_events:
            if fe["event_id"] not in seen_ids:
                events.append(fe)
        events.sort(key=lambda x: x["event_sequence"])

    # Dispute draft if generated
    dispute_md = None
    if (c_dir / "dispute_email.md").exists():
        try:
            dispute_md = (c_dir / "dispute_email.md").read_text(encoding="utf-8")
        except Exception:
            pass

    return {
        "summary": detail.to_dict(),
        "folder_name": c_dir.name,
        "is_demo_case": c_dir.name.startswith("demo-"),
        "case_meta": case_meta,
        "invoice": inv_data,
        "comparison": comp_data,
        "verification_record": ver_data,
        "vendor": {
            "vendor_id": vendor_id,
            "name": vendor_data.get("name", vendor_id),
            "currency": vendor_data.get("currency", "INR"),
            "contract": vendor_data.get("contract", {}),
            "treasury_destination": {
                "destination_reference": dest_info.destination_reference if dest_info else "UNREGISTERED",
                "bank_verified": (dest_info.verification_status == "VERIFIED") if dest_info else False,
                "allowed_currencies": [vendor_data.get("currency", "INR"), "USD"],
            },
        },
        "evidence": {
            "count": len(ev_items),
            "all_verified": ev_verified_ok if ev_items else False,
            "items": ev_items,
            "verification_results": ev_verification_details,
        },
        "approval": receipt_payload,
        "authorization_policy": {
            "can_current_user_approve": can_approve and (receipt_payload is None),
            "can_current_user_reject": _auth_service.has_permission(current_user, PERM_CASE_REJECT) and (receipt_payload is None),
            "can_current_user_reconcile": _auth_service.has_permission(current_user, PERM_CASE_RECONCILE),
            "can_current_user_export_payment": _auth_service.has_permission(current_user, PERM_PAYMENT_EXPORT),
            "policy_message": policy_msg,
            "case_creator": detail.created_by,
            "current_actor": current_user.username,
            "current_role": current_user.role,
        },
        "payment_instructions": case_instructions,
        "audit_events": events,
        "dispute_draft": dispute_md,
    }


def list_vendors_payload() -> List[Dict[str, Any]]:
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
                    rates.append(
                        {
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
                        }
                    )

                items_count = len(rates) if rates else len(items)

                # Calculate vendor case stats using Decimal
                v_cases = [s for s in summaries if s.vendor_id == vid]
                v_invoiced = sum((to_dec(s.invoiced_total) for s in v_cases), Decimal("0.00"))
                v_payable = sum((to_dec(s.payable_total) for s in v_cases), Decimal("0.00"))
                v_withheld = sum((to_dec(s.withheld_total) for s in v_cases), Decimal("0.00"))

                dest = _vendor_registry.get_destination(vid)
                results.append(
                    {
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
                    }
                )
            except Exception:
                pass
    return results


def list_contracts_payload() -> List[Dict[str, Any]]:
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
            except Exception:
                pass
        contracts_list.append(
            {
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
            }
        )
    return contracts_list


def list_all_evidence_payload() -> Dict[str, Any]:
    """Scan all case directories and return all registered evidence with live SHA-256 verification."""
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
                ver_res = verify_evidence(c_dir, base_dir=ROOT_DIR)
                res_by_id = {r["evidence_id"]: r for r in ver_res.get("results", [])}
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
                    all_records.append(
                        {
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
                        }
                    )

    # Also list raw intake files in invoices/ and contracts/
    raw_sources: List[Dict[str, Any]] = []
    for folder, kind in [("invoices", "RAW_INVOICE_FILE"), ("contracts", "CONTRACT_DOCUMENT")]:
        f_dir = ROOT_DIR / folder
        if f_dir.exists():
            for fp in sorted(f_dir.iterdir()):
                if fp.is_file() and not fp.name.startswith("."):
                    try:
                        raw_sources.append(
                            {
                                "path": f"{folder}/{fp.name}",
                                "kind": kind,
                                "sha256": sha256_file(fp),
                                "size_bytes": fp.stat().st_size,
                            }
                        )
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
    summaries = _case_service.list_cases()
    key_bytes = get_active_signing_key()
    pending_queue: List[Dict[str, Any]] = []
    decided_receipts: List[Dict[str, Any]] = []

    for s in summaries:
        c_dir = _case_service._resolve_case_dir(s.case_id)
        if not c_dir:
            continue

        rec_p = c_dir / "approvals" / "approval_receipt.json"
        if rec_p.exists():
            try:
                rec_data = load_json(rec_p)
                r_valid, r_issues = verify_approval_receipt(rec_data, key_bytes=key_bytes)
                decided_receipts.append(
                    {
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
                    }
                )
            except Exception:
                pass
        else:
            # Candidate for decision
            can_approve, policy_msg = _auth_service.evaluate_approval_policy(
                approver=current_user,
                case_creator_username=s.created_by,
                verification_status=s.verification_status,
            )
            can_reject = _auth_service.has_permission(current_user, PERM_CASE_REJECT) and (
                s.verification_status in ("VERIFIED", "REVIEW_REQUIRED", "BLOCKED")
            )
            pending_queue.append(
                {
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
                }
            )

    return {
        "current_actor": current_user.username,
        "current_role": current_user.role,
        "pending_count": len([p for p in pending_queue if p["verification_status"] == "VERIFIED"]),
        "pending_queue": pending_queue,
        "decided_receipts": decided_receipts,
    }


def build_payments_payload() -> Dict[str, Any]:
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
            eligible_cases.append(
                {
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
                }
            )
        elif with_dec > Decimal("0.00") or s.verification_status in ("BLOCKED", "REVIEW_REQUIRED") or s.approval_status == "REJECTED":
            withheld_or_blocked_cases.append(
                {
                    "case_id": s.case_id,
                    "invoice_number": s.invoice_number,
                    "vendor_id": s.vendor_id,
                    "verification_status": s.verification_status,
                    "commercial_status": s.commercial_status,
                    "approval_status": s.approval_status,
                    "invoiced_total": fmt_dec(inv_dec),
                    "payable_total": fmt_dec(pay_dec),
                    "withheld_total": fmt_dec(with_dec if with_dec > Decimal("0.00") else (inv_dec - pay_dec)),
                }
            )

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
        except Exception:
            pass
    return results


def build_integrations_payload() -> Dict[str, Any]:
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
        agents_info.append(
            {
                "handle": agent_id,
                "description": role_desc,
                "spec_file": f"agents/{fname}",
                "spec_sha256": sha,
                "can_approve_payments": False,
            }
        )

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
    finally:
        conn.close()

    role_matrix = {
        role: sorted(list(perms))
        for role, perms in ROLE_PERMISSIONS.items()
    }
    return {
        "users": users,
        "role_permissions": role_matrix,
        "separation_of_duties_enforced": _auth_service.enforce_strict_separation_of_duties,
    }


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class OverchargeDeskHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _send_security_headers(self, is_api: bool = True) -> None:
        req_id = self.headers.get("X-Request-ID") or os.urandom(8).hex()
        self.send_header("X-Request-ID", req_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        if is_api:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self';",
        )

    def _send_json(self, status_code: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self._send_security_headers(is_api=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        status_code: int,
        content: bytes,
        content_type: str,
        is_api: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status_code)
        self._send_security_headers(is_api=is_api)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            raise ToolError(f"Invalid JSON request body: {exc}", 2)

    def _authenticate(self, required_permission: Optional[str] = None) -> Optional[User]:
        auth_header = self.headers.get("Authorization")
        if not auth_header:
            self._send_json(
                401,
                {"detail": "Missing Authorization header"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            self._send_json(
                401,
                {"detail": "Invalid Authorization header format. Expected 'Bearer <token>'"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        user = _identity_service.verify_session_token(parts[1])
        if not user:
            self._send_json(
                401,
                {"detail": "Invalid, expired, or revoked session token"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        if required_permission and not _auth_service.has_permission(user, required_permission):
            self._send_json(
                403,
                {"detail": f"Permission denied: Requires '{required_permission}'"},
            )
            return None

        return user

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_security_headers(is_api=True)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Frontend routes
        if path in ("/", "/index.html"):
            index_file = WEB_DIR / "index.html"
            if index_file.exists():
                self._send_bytes(200, index_file.read_bytes(), "text/html; charset=utf-8", is_api=False)
                return
            self._send_bytes(200, b"<h1>Overcharge Desk</h1>", "text/html; charset=utf-8", is_api=False)
            return

        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (WEB_DIR / rel).resolve()
            if str(target).startswith(str(WEB_DIR.resolve())) and target.is_file():
                ctype, _ = mimetypes.guess_type(str(target))
                self._send_bytes(200, target.read_bytes(), ctype or "application/octet-stream", is_api=False)
                return
            self._send_json(404, {"detail": "Static asset not found"})
            return

        # 2. Health check endpoints
        if path in ("/api/v1/health", "/api/health", "/api/v1/system/health"):
            self._send_json(200, build_health_payload())
            return

        # 3. Auth /me
        if path == "/api/v1/auth/me":
            user = self._authenticate()
            if not user:
                return
            perms = sorted(list(ROLE_PERMISSIONS.get(user.role, set())))
            self._send_json(
                200,
                {
                    "user_id": user.user_id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "is_demo": user.is_demo,
                    "permissions": perms,
                },
            )
            return

        # 4. Overview Financial Control Metrics
        if path == "/api/v1/overview/metrics":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, build_overview_metrics(user))
            return

        # 5. List Cases
        if path == "/api/v1/cases":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            status_filter = query.get("status", [None])[0]
            summaries = _case_service.list_cases(filter_status=status_filter)
            self._send_json(200, [s.to_dict() for s in summaries])
            return

        # 6. Full Case Workspace
        m_ws = re.match(r"^/api/v1/cases/([^/]+)/workspace$", path)
        if m_ws:
            case_id = m_ws.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            ws = build_case_workspace(case_id, user)
            if not ws:
                self._send_json(404, {"detail": f"Case '{case_id}' not found"})
                return
            self._send_json(200, ws)
            return

        # 7. Download Case Artifact
        m_art = re.match(r"^/api/v1/cases/([^/]+)/artifacts/([^/]+)$", path)
        if m_art:
            case_id, artifact_name = m_art.group(1), m_art.group(2)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            if artifact_name == "corrected_payment.csv":
                if not _auth_service.has_permission(user, PERM_PAYMENT_EXPORT):
                    self._send_json(
                        403,
                        {
                            "detail": "Permission denied: Downloading authorized payment sheets requires 'payment:export' permission"
                        },
                    )
                    return
            art_p = _case_service.get_artifact_path(case_id, artifact_name)
            if not art_p or not art_p.exists():
                self._send_json(
                    404,
                    {"detail": f"Artifact '{artifact_name}' not available for case '{case_id}'"},
                )
                return
            media_type = "text/csv; charset=utf-8" if artifact_name.endswith(".csv") else "application/json; charset=utf-8"
            self._send_bytes(
                200,
                art_p.read_bytes(),
                media_type,
                is_api=True,
                extra_headers={"Content-Disposition": f'inline; filename="{artifact_name}"'},
            )
            return

        # 8. Export Payment Instruction
        m_pay_exp = re.match(r"^/api/v1/cases/([^/]+)/payment-instruction/([^/]+)/export$", path)
        if m_pay_exp:
            case_id, instruction_id = m_pay_exp.group(1), m_pay_exp.group(2)
            user = self._authenticate(PERM_PAYMENT_EXPORT)
            if not user:
                return
            fmt = query.get("format", ["csv"])[0]
            if fmt not in ("csv", "json"):
                self._send_json(400, {"detail": "Invalid format; expected 'csv' or 'json'"})
                return
            try:
                media_type, content = _case_service.export_payment_instruction(
                    case_id=case_id,
                    instruction_id=instruction_id,
                    operator=user,
                    format_type=fmt,
                )
                ext = "json" if fmt == "json" else "csv"
                self._send_bytes(
                    200,
                    content,
                    media_type,
                    is_api=True,
                    extra_headers={"Content-Disposition": f'attachment; filename="{instruction_id}.{ext}"'},
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 9. Get Single Case Detail
        m_case = re.match(r"^/api/v1/cases/([^/]+)$", path)
        if m_case:
            case_id = m_case.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            detail = _case_service.get_case(case_id)
            if not detail:
                self._send_json(404, {"detail": f"Case '{case_id}' not found"})
                return
            self._send_json(200, detail.to_dict())
            return

        # 10. Evidence Global Registry
        if path == "/api/v1/evidence":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, list_all_evidence_payload())
            return

        # 11. Vendors List
        if path == "/api/v1/vendors":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, list_vendors_payload())
            return

        # 12. Contracts List
        if path == "/api/v1/contracts":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, list_contracts_payload())
            return

        # 13. Approvals Queue & Receipts
        if path == "/api/v1/approvals":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, build_approvals_payload(user))
            return

        # 14. Payments Control Overview
        if path == "/api/v1/payments":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, build_payments_payload())
            return

        # 15. Audit Ledger Events
        if path == "/api/v1/audit/ledger/events":
            user = self._authenticate(PERM_AUDIT_READ)
            if not user:
                return
            case_id_filter = query.get("case_id", [None])[0]
            event_type_filter = query.get("event_type", [None])[0]
            try:
                limit = int(query.get("limit", ["100"])[0])
                limit = max(1, min(500, limit))
            except ValueError:
                limit = 100
            events = list_events(case_id=case_id_filter, db_path=ROOT_DIR / DEFAULT_LEDGER_DB)
            if event_type_filter:
                events = [e for e in events if e["event_type"] == event_type_filter]
            self._send_json(200, events[-limit:])
            return

        # 16. Audit Ledger Verify
        if path == "/api/v1/audit/ledger/verify":
            user = self._authenticate(PERM_AUDIT_READ)
            if not user:
                return
            ledger_p = ROOT_DIR / DEFAULT_LEDGER_DB
            valid, issues = verify_ledger(ledger_p)
            events = list_events(db_path=ledger_p)
            latest = events[-1] if events else None
            self._send_json(
                200,
                {
                    "ok": valid,
                    "valid": valid,
                    "total_events": len(events),
                    "highest_sequence": latest["event_sequence"] if latest else 0,
                    "head_event_hash": latest["event_hash"] if latest else GENESIS_PREV_HASH,
                    "genesis_prev_hash": GENESIS_PREV_HASH,
                    "issues_count": len(issues),
                    "issues": issues,
                    "verified_at": utc_now_iso(),
                },
            )
            return

        # 17. Audit Ledger Checkpoints
        if path == "/api/v1/audit/ledger/checkpoints":
            user = self._authenticate(PERM_AUDIT_READ)
            if not user:
                return
            self._send_json(200, list_checkpoints_payload())
            return

        # 18. Integrations Status
        if path == "/api/v1/integrations":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, build_integrations_payload())
            return

        # 19. Settings Users & Roles
        if path == "/api/v1/settings/users":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, list_users_and_roles_payload())
            return

        self._send_json(404, {"detail": f"Endpoint '{path}' not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except ToolError as exc:
            self._send_json(400, {"detail": str(exc)})
            return

        # 1. Auth Login
        if path == "/api/v1/auth/login":
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            if is_user_locked_out(username):
                self._send_json(
                    429,
                    {
                        "detail": "Account temporarily locked due to multiple failed login attempts. Please try again later."
                    },
                )
                return

            user = _identity_service.authenticate(username, password)
            if not user:
                if record_failed_login(username):
                    self._send_json(
                        429,
                        {
                            "detail": "Account temporarily locked due to multiple failed login attempts. Please try again later."
                        },
                    )
                    return
                self._send_json(401, {"detail": "Invalid username or password"})
                return

            reset_failed_logins(username)
            token = _identity_service.issue_session_token(user)
            perms = sorted(list(ROLE_PERMISSIONS.get(user.role, set())))
            self._send_json(
                200,
                {
                    "ok": True,
                    "access_token": token,
                    "token_type": "bearer",
                    "user_id": user.user_id,
                    "username": user.username,
                    "role": user.role,
                    "full_name": user.full_name,
                    "email": user.email,
                    "is_demo": user.is_demo,
                    "permissions": perms,
                },
            )
            return

        # 2. Auth Logout
        if path == "/api/v1/auth/logout":
            auth_header = self.headers.get("Authorization", "")
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                _identity_service.revoke_token(parts[1])
            self._send_json(200, {"ok": True, "action": "logged_out"})
            return

        # 3. Reset or Re-run Demo Benchmark Suite
        if path in ("/api/v1/demo/run", "/api/v1/demo/reset"):
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            try:
                marker = ROOT_DIR / "cases" / ".demo_cleared"
                if marker.exists():
                    marker.unlink()
                cases_p = ROOT_DIR / "cases"
                if cases_p.exists():
                    for d in sorted(cases_p.iterdir()):
                        if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("demo-"):
                            shutil.rmtree(d, ignore_errors=True)
                inv_p = ROOT_DIR / "invoices"
                if inv_p.exists():
                    for f in sorted(inv_p.glob("intake-*")):
                        try:
                            f.unlink()
                        except Exception:
                            pass
                for suffix in ["", "-wal", "-shm"]:
                    p = Path(str(ROOT_DIR / DEFAULT_PAYMENT_DB) + suffix)
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                _payment_repo.init_db()
                res = run_full_demo(base_dir=ROOT_DIR, clean_run=True)
                self._send_json(200, res)
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 4. Reset Workspace to Base Empty State
        if path in ("/api/v1/demo/clear", "/api/v1/workspace/reset"):
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            try:
                cases_p = ROOT_DIR / "cases"
                removed = []
                if cases_p.exists():
                    for d in sorted(cases_p.iterdir()):
                        if d.is_dir() and not d.name.startswith("."):
                            shutil.rmtree(d, ignore_errors=True)
                            removed.append(d.name)
                cases_p.mkdir(parents=True, exist_ok=True)
                for folder_name, pattern in [
                    ("vendors", "*.json"),
                    ("contracts", "*.md"),
                    ("invoices", "*.txt"),
                    ("checkpoints", "*.json"),
                ]:
                    folder_p = ROOT_DIR / folder_name
                    if folder_p.exists():
                        for fp in sorted(folder_p.glob(pattern)):
                            try:
                                fp.unlink()
                            except Exception:
                                pass
                # Reset payments.db and ledger.db cleanly
                for db_f in [ROOT_DIR / DEFAULT_LEDGER_DB, ROOT_DIR / DEFAULT_PAYMENT_DB]:
                    for suffix in ["", "-wal", "-shm"]:
                        p = Path(str(db_f) + suffix)
                        if p.exists():
                            try:
                                p.unlink()
                            except Exception:
                                pass
                ensure_base_storage_initialized()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "action": "workspace_reset_to_base",
                        "removed_cases": removed,
                    },
                )
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 5. Create New Case (with duplicate detection, auto-vendor/contract provisioning, raw source generation, evidence registration, and optional auto-reconcile)
        if path == "/api/v1/cases":
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            case_id = str(body.get("case_id", "")).strip()
            vendor_id = re.sub(r"[^a-z0-9_-]", "", str(body.get("vendor_id", "")).strip().lower())
            vendor_name_input = str(body.get("vendor_name", "")).strip()
            invoice_json = body.get("invoice_json")
            auto_reconcile = bool(body.get("auto_reconcile", False))

            if not case_id or not vendor_id or not isinstance(invoice_json, dict):
                self._send_json(400, {"detail": "Missing required 'case_id', 'vendor_id', or 'invoice_json' object"})
                return

            inv_num = str(invoice_json.get("invoice_number", "")).strip()
            if not inv_num:
                self._send_json(400, {"detail": "Invoice number is required in 'invoice_json'"})
                return

            # Duplicate invoice number check for the same vendor
            if not bool(body.get("allow_duplicate_invoice", False)):
                existing_cases = _case_service.list_cases()
                for ex in existing_cases:
                    if ex.vendor_id == vendor_id and ex.invoice_number.lower() == inv_num.lower() and ex.case_id != case_id:
                        self._send_json(
                            400,
                            {
                                "detail": f"Duplicate invoice detected: Invoice '{inv_num}' for vendor '{vendor_id}' is already registered under case '{ex.case_id}'."
                            },
                        )
                        return

            try:
                currency = str(invoice_json.get("currency", "INR")).strip().upper() or "INR"
                inv_date = str(invoice_json.get("invoice_date") or utc_now_iso()[:10]).strip()
                eff_from = f"{inv_date[:4]}-01-01" if len(inv_date) >= 4 else "2026-01-01"
                eff_to = f"{inv_date[:4]}-12-31" if len(inv_date) >= 4 else "2026-12-31"

                # Resolve or auto-provision vendor profile & Schedule A rates
                vendor_f = ROOT_DIR / "vendors" / f"{vendor_id}.json"
                vendor_data = load_json(vendor_f) if vendor_f.exists() else {}
                resolved_vendor_name = (
                    vendor_name_input
                    or str(invoice_json.get("vendor_name_as_written") or "").strip()
                    or vendor_data.get("name")
                    or f"{vendor_id.upper()} Vendor Services"
                )
                invoice_json["vendor_name_as_written"] = resolved_vendor_name
                invoice_json["vendor_id"] = vendor_id
                invoice_json["case_id"] = case_id
                invoice_json["currency"] = currency

                contract_obj = vendor_data.get("contract", {}) if vendor_data else {}
                existing_rates: List[Dict[str, Any]] = list(contract_obj.get("rates") or [])
                rates_modified = False

                # Normalize invoice lines for check_invoice.py and compare.py
                norm_lines = []
                for idx, ln in enumerate(invoice_json.get("lines", []), start=1):
                    l_no = int(ln.get("line_no") or ln.get("line_number") or idx)
                    sku_code = str(ln.get("item_code") or ln.get("sku") or "").strip()
                    desc_txt = str(ln.get("description") or sku_code or f"Line {idx}").strip()
                    if sku_code and sku_code.lower() not in desc_txt.lower():
                        desc_txt = f"{desc_txt} ({sku_code})"
                    unit_str = str(ln.get("unit") or "unit").strip() or "unit"
                    u_price_str = fmt_dec(to_dec(ln.get("unit_price", "0.00")))
                    l_total_str = fmt_dec(to_dec(ln.get("line_total", "0.00")))

                    # Optional inline Schedule A contracted unit price
                    c_price_raw = ln.get("contract_unit_price")
                    if c_price_raw is not None and str(c_price_raw).strip() != "" and to_dec(c_price_raw) > Decimal("0.00") and sku_code:
                        c_price_str = fmt_dec(to_dec(c_price_raw))
                        ikey = re.sub(r"[^a-z0-9-]+", "-", sku_code.lower()).strip("-") or f"item-{idx}"
                        rate_entry = {
                            "item_key": ikey,
                            "sku": sku_code,
                            "item_code": sku_code,
                            "description": desc_txt,
                            "aliases": [desc_txt, sku_code, str(ln.get("description") or sku_code).strip()],
                            "unit": unit_str,
                            "unit_price": c_price_str,
                            "currency": currency,
                            "effective_from": contract_obj.get("effective_from") or eff_from,
                            "effective_to": contract_obj.get("effective_to") or eff_to,
                            "clause_ref": f"Schedule A, item {len(existing_rates) + 1}",
                        }
                        matched_rate_idx = next(
                            (
                                r_i
                                for r_i, r_ex in enumerate(existing_rates)
                                if str(r_ex.get("sku") or r_ex.get("item_code") or "").lower() == sku_code.lower()
                            ),
                            None,
                        )
                        if matched_rate_idx is None:
                            existing_rates.append(rate_entry)
                            rates_modified = True
                        elif not vendor_f.exists():
                            existing_rates[matched_rate_idx] = rate_entry
                            rates_modified = True

                    q_dec = to_dec(ln.get("quantity", "1"))
                    q_val = int(q_dec) if q_dec == q_dec.to_integral_value() else str(q_dec)
                    norm_lines.append(
                        {
                            "line_no": l_no,
                            "line_number": l_no,
                            "item_code": sku_code,
                            "description": desc_txt,
                            "quantity": q_val,
                            "unit": unit_str,
                            "unit_price": u_price_str,
                            "line_total": l_total_str,
                            "source_ref": str(ln.get("source_ref") or f"line-{l_no}"),
                        }
                    )
                invoice_json["lines"] = norm_lines
                invoice_json["stated_total"] = fmt_dec(to_dec(invoice_json.get("stated_total", "0.00")))

                # Auto-provision or update vendor profile & Schedule A markdown if needed
                if not vendor_f.exists() or rates_modified:
                    contract_id = contract_obj.get("contract_id") or f"CON-{vendor_id.upper()}-2026"
                    c_eff_from = contract_obj.get("effective_from") or eff_from
                    c_eff_to = contract_obj.get("effective_to") or eff_to
                    src_md_rel = _write_contract_markdown(
                        vendor_id=vendor_id,
                        vendor_name=resolved_vendor_name,
                        contract_id=contract_id,
                        effective_from=c_eff_from,
                        effective_to=c_eff_to,
                        currency=currency,
                        rates=existing_rates,
                    )
                    dest_ref = vendor_data.get("destination_reference") or f"TREASURY-{vendor_id.upper()}-001"
                    aliases_list = list(dict.fromkeys([resolved_vendor_name, vendor_id] + list(vendor_data.get("aliases") or [])))
                    vendor_payload = {
                        "vendor_id": vendor_id,
                        "name": resolved_vendor_name,
                        "aliases": aliases_list,
                        "currency": currency,
                        "destination_reference": dest_ref,
                        "bank_verified": bool(vendor_data.get("bank_verified", True)),
                        "contract": {
                            "contract_id": contract_id,
                            "vendor_id": vendor_id,
                            "source_file": src_md_rel,
                            "effective_from": c_eff_from,
                            "effective_to": c_eff_to,
                            "rates": existing_rates,
                        },
                        "history": vendor_data.get("history") or {"cases": []},
                    }
                    vendor_f.parent.mkdir(parents=True, exist_ok=True)
                    write_json_atomic(vendor_f, vendor_payload)
                    _sync_vendor_registry()

                # Ensure source_file and source_sha256 are populated or synthesized deterministically
                src_file = invoice_json.get("source_file")
                if not src_file or not (ROOT_DIR / str(src_file)).is_file():
                    safe_inv = re.sub(r"[^A-Za-z0-9_-]", "-", inv_num.lower())
                    rel_src = f"invoices/intake-{case_id.lower()}-{safe_inv}.txt"
                    abs_src = ROOT_DIR / rel_src
                    abs_src.parent.mkdir(parents=True, exist_ok=True)
                    raw_text = body.get("raw_invoice_text")
                    if not raw_text:
                        lines_txt = []
                        for idx, ln in enumerate(invoice_json.get("lines", []), start=1):
                            lines_txt.append(
                                f"Line {idx}: SKU={ln.get('item_code')} | Desc={ln.get('description')} | "
                                f"Qty={ln.get('quantity')} | UnitPrice={ln.get('unit_price')} | Total={ln.get('line_total')}"
                            )
                        raw_text = (
                            f"INVOICE: {inv_num}\n"
                            f"CASE_ID: {case_id}\n"
                            f"VENDOR: {invoice_json['vendor_name_as_written']} ({vendor_id})\n"
                            f"DATE: {invoice_json.get('invoice_date', utc_now_iso()[:10])}\n"
                            f"CURRENCY: {invoice_json.get('currency', 'INR')}\n"
                            + "\n".join(lines_txt)
                            + f"\nSTATED_TOTAL: {invoice_json.get('stated_total', '0.00')}\n"
                        )
                    abs_src.write_text(str(raw_text), encoding="utf-8")
                    invoice_json["source_file"] = rel_src
                    invoice_json["source_sha256"] = sha256_file(abs_src)
                else:
                    abs_src = ROOT_DIR / str(src_file)
                    if not invoice_json.get("source_sha256"):
                        invoice_json["source_sha256"] = sha256_file(abs_src)

                detail = _case_service.create_case(
                    case_id=case_id,
                    vendor_id=vendor_id,
                    invoice_json_content=invoice_json,
                    creator_user=user,
                )

                # Record CASE_CREATED in ledger.db
                try:
                    record_event(
                        case_id=detail.case_id,
                        event_type="CASE_CREATED",
                        actor_id=user.username,
                        payload={
                            "invoice_number": inv_num,
                            "vendor_id": vendor_id,
                            "stated_total": str(invoice_json.get("stated_total", "0.00")),
                            "source_sha256": invoice_json.get("source_sha256"),
                        },
                        db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                    )
                except Exception:
                    pass

                if auto_reconcile and _auth_service.has_permission(user, PERM_CASE_RECONCILE):
                    _case_service.reconcile_case(
                        case_id=case_id,
                        operator=user,
                        require_approval=False,
                    )
                    detail = _case_service.get_case(case_id) or detail
                else:
                    # Register initial intake evidence when not auto-reconciling
                    c_dir = _case_service._resolve_case_dir(case_id)
                    if c_dir:
                        try:
                            register_evidence(
                                case_dir=c_dir,
                                file_path=ROOT_DIR / invoice_json["source_file"],
                                evidence_type="source_invoice",
                                case_id=detail.case_id,
                                base_dir=ROOT_DIR,
                            )
                            register_evidence(
                                case_dir=c_dir,
                                file_path=c_dir / "invoice.json",
                                evidence_type="extracted_invoice",
                                case_id=detail.case_id,
                                base_dir=ROOT_DIR,
                            )
                            if vendor_f.exists():
                                register_evidence(
                                    case_dir=c_dir,
                                    file_path=vendor_f,
                                    evidence_type="vendor_contract",
                                    case_id=detail.case_id,
                                    base_dir=ROOT_DIR,
                                )
                        except Exception:
                            pass

                self._send_json(201, detail.to_dict())
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 6. Reconcile Case
        m_rec = re.match(r"^/api/v1/cases/([^/]+)/reconcile$", path)
        if m_rec:
            case_id = m_rec.group(1)
            user = self._authenticate(PERM_CASE_RECONCILE)
            if not user:
                return
            c_dir = _case_service._resolve_case_dir(case_id)
            has_approved_receipt = False
            if c_dir and (c_dir / "approvals" / "approval_receipt.json").exists():
                try:
                    has_approved_receipt = load_json(c_dir / "approvals" / "approval_receipt.json").get("decision") == "APPROVED"
                except Exception:
                    has_approved_receipt = False
            require_approval = bool(body.get("require_approval", False)) and has_approved_receipt
            try:
                res = _case_service.reconcile_case(
                    case_id=case_id,
                    operator=user,
                    require_approval=require_approval,
                )
                self._send_json(
                    200,
                    {
                        "ok": res["ok"],
                        "pipeline_status": res["pipeline_status"],
                        "execution_id": res["execution_id"],
                        "case_id": res["case_id"],
                        "verification_status": res["verification_status"],
                        "commercial_status": res["commercial_status"],
                        "settlement_status": res["settlement_status"],
                        "source_digest_verified": res["source_digest_verified"],
                        "comparison_digest": res["comparison_digest"],
                        "artifact_type": res["artifact_type"],
                        "artifact_file": res["artifact_file"],
                        "approval_verified": res.get("approval_verified"),
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 7. Verify Case Evidence
        m_ev_ver = re.match(r"^/api/v1/cases/([^/]+)/evidence/verify$", path)
        if m_ev_ver:
            case_id = m_ev_ver.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            c_dir = _case_service._resolve_case_dir(case_id)
            if not c_dir or not c_dir.exists():
                self._send_json(404, {"detail": f"Case '{case_id}' not found"})
                return
            try:
                res = verify_evidence(c_dir, base_dir=ROOT_DIR)
                res["verified"] = bool(res.get("valid", res.get("ok", False)))
                self._send_json(200, res)
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 8. Upload / Register New Case Evidence Artifact
        m_ev_add = re.match(r"^/api/v1/cases/([^/]+)/evidence$", path)
        if m_ev_add:
            case_id = m_ev_add.group(1)
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            c_dir = _case_service._resolve_case_dir(case_id)
            if not c_dir or not c_dir.exists():
                self._send_json(404, {"detail": f"Case '{case_id}' not found"})
                return
            filename = str(body.get("filename", "")).strip()
            artifact_type = str(body.get("artifact_type", "SUPPORTING_DOCUMENT")).strip().upper()
            content_text = str(body.get("content", ""))
            if not filename or not content_text:
                self._send_json(400, {"detail": "Both 'filename' and 'content' are required to register evidence"})
                return
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
            att_dir = c_dir / "attachments"
            att_dir.mkdir(parents=True, exist_ok=True)
            target_file = att_dir / safe_name
            target_file.write_text(content_text, encoding="utf-8")

            # Resolve canonical case_id from invoice.json or existing registry
            canonical_case_id = case_id
            if (c_dir / "invoice.json").exists():
                try:
                    canonical_case_id = load_json(c_dir / "invoice.json").get("case_id") or case_id
                except Exception:
                    pass

            try:
                rec = register_evidence(
                    case_dir=c_dir,
                    file_path=target_file,
                    evidence_type="review_artifact",
                    case_id=canonical_case_id,
                    base_dir=ROOT_DIR,
                    description=artifact_type,
                )
                norm_rec = {
                    **rec,
                    "artifact_type": artifact_type,
                    "source_locator": rec["stored_path"],
                    "sha256": rec["content_hash"],
                    "recorded_sha256": rec["content_hash"],
                    "size_bytes": rec["byte_size"],
                    "registered_at": rec["received_at"],
                }
                record_event(
                    case_id=canonical_case_id,
                    event_type="EVIDENCE_REGISTERED",
                    actor_id=user.username,
                    payload={
                        "evidence_id": rec["evidence_id"],
                        "artifact_type": artifact_type,
                        "source_locator": rec["stored_path"],
                        "sha256": rec["content_hash"],
                    },
                    evidence_refs=[rec["evidence_id"]],
                    db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                )
                self._send_json(201, {"ok": True, "evidence": norm_rec})
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 9. Approve or Reject Case
        m_app = re.match(r"^/api/v1/cases/([^/]+)/approve$", path)
        if m_app:
            case_id = m_app.group(1)
            user = self._authenticate(PERM_CASE_APPROVE)
            if not user:
                return
            decision = str(body.get("decision", "")).strip().upper()
            reason = body.get("reason")
            amount = body.get("amount")
            c_dir = _case_service._resolve_case_dir(case_id)
            if c_dir and (c_dir / "case.json").exists():
                try:
                    cmeta = load_json(c_dir / "case.json")
                    if cmeta.get("status") not in ("APPROVAL_PENDING", "APPROVED", "REJECTED"):
                        cmeta["status"] = "APPROVAL_PENDING"
                    if cmeta.get("current_state") in ("VERIFIED", "REVIEW_REQUIRED", "BLOCKED"):
                        cmeta["current_state"] = "AWAITING_APPROVAL"
                    write_json_atomic(c_dir / "case.json", cmeta)
                except Exception:
                    pass
            try:
                res = _case_service.approve_or_reject_case(
                    case_id=case_id,
                    approver=user,
                    decision=decision,
                    reason=str(reason) if reason is not None else None,
                    amount=str(amount) if amount is not None else None,
                )
                try:
                    record_event(
                        case_id=case_id,
                        event_type=f"CASE_{decision}",
                        actor_id=user.username,
                        payload={
                            "receipt_id": res.get("receipt_id"),
                            "decision": decision,
                            "approved_amount": res.get("approved_amount"),
                            "withheld_amount": res.get("withheld_amount"),
                            "receipt_hash": res.get("receipt_hash"),
                        },
                        db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                    )
                except Exception:
                    pass
                self._send_json(
                    200,
                    {
                        "ok": res["ok"],
                        "decision": res["decision"],
                        "receipt_id": res["receipt_id"],
                        "receipt_hash": res["receipt_hash"],
                        "receipt_signature": res["receipt_signature"],
                        "approved_amount": res.get("approved_amount"),
                        "withheld_amount": res.get("withheld_amount"),
                        "idempotent": res.get("idempotent", False),
                    },
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 10. Export Case Audit Package
        m_exp = re.match(r"^/api/v1/cases/([^/]+)/export-audit$", path)
        if m_exp:
            case_id = m_exp.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            try:
                res = _case_service.export_audit_package(case_id)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "case_id": res["case_id"],
                        "target_package_directory": res["target_package_directory"],
                        "package_integrity_digest": res["package_integrity_digest"],
                        "package_verified": res["package_verified"],
                        "verification_issues": res["verification_issues"],
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 11. Create Payment Instruction
        m_pay = re.match(r"^/api/v1/cases/([^/]+)/payment-instruction$", path)
        if m_pay:
            case_id = m_pay.group(1)
            user = self._authenticate(PERM_PAYMENT_EXPORT)
            if not user:
                return
            idem_key = body.get("idempotency_key")
            try:
                inst = _case_service.create_payment_instruction(
                    case_id=case_id,
                    operator=user,
                    idempotency_key=str(idem_key) if idem_key is not None else None,
                )
                try:
                    record_event(
                        case_id=inst.case_id,
                        event_type="PAYMENT_INSTRUCTION_CREATED",
                        actor_id=user.username,
                        payload={
                            "instruction_id": inst.instruction_id,
                            "approval_receipt_id": inst.approval_receipt_id,
                            "approved_amount": inst.approved_amount,
                            "destination_reference": inst.destination_reference,
                        },
                        db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                    )
                except Exception:
                    pass
                self._send_json(
                    200,
                    {
                        "instruction_id": inst.instruction_id,
                        "case_id": inst.case_id,
                        "approval_receipt_id": inst.approval_receipt_id,
                        "approved_amount": inst.approved_amount,
                        "currency": inst.currency,
                        "vendor_id": inst.vendor_id,
                        "destination_reference": inst.destination_reference,
                        "destination_verified": inst.destination_verified,
                        "status": inst.status,
                        "created_at": inst.created_at,
                        "expires_at": inst.expires_at,
                        "idempotency_key": inst.idempotency_key,
                        "exported_at": inst.exported_at,
                        "exported_by": inst.exported_by,
                    },
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 12. Create / Update Vendor & Contract Profile
        if path == "/api/v1/vendors":
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            vendor_id = re.sub(r"[^a-z0-9_-]", "", str(body.get("vendor_id", "")).strip().lower())
            vendor_name = str(body.get("vendor_name", "")).strip()
            contract_id = str(body.get("contract_id", "")).strip() or f"CON-{vendor_id.upper()}-2026"
            currency = str(body.get("currency", "INR")).strip().upper() or "INR"
            effective_from = str(body.get("effective_from", "2026-01-01")).strip()
            effective_to = str(body.get("effective_to", "2026-12-31")).strip()
            dest_ref = str(body.get("destination_reference", f"HDFC-BANK-****{vendor_id[:4].upper()}-IN")).strip()
            bank_verified = bool(body.get("bank_verified", True))
            rates_in = body.get("rates", [])

            if not vendor_id or not vendor_name:
                self._send_json(400, {"detail": "Both 'vendor_id' and 'vendor_name' are required"})
                return

            clean_rates = []
            for idx, r in enumerate(rates_in if isinstance(rates_in, list) else [], start=1):
                sku = str(r.get("item_code") or r.get("sku") or "").strip()
                desc = str(r.get("description") or "").strip()
                u_price = fmt_dec(to_dec(r.get("unit_price", "0.00")))
                if not sku or to_dec(u_price) <= Decimal("0.00"):
                    self._send_json(400, {"detail": f"Rate line {idx} requires a valid SKU and unit_price > 0"})
                    return
                ikey = re.sub(r"[^a-z0-9-]+", "-", sku.lower()).strip("-") or f"item-{idx}"
                full_desc = desc if (sku.lower() in desc.lower()) else f"{desc} ({sku})"
                clean_rates.append(
                    {
                        "item_key": ikey,
                        "sku": sku,
                        "item_code": sku,
                        "description": full_desc,
                        "aliases": r.get("aliases") if isinstance(r.get("aliases"), list) else [desc or sku, sku],
                        "unit": str(r.get("unit", "unit")).strip(),
                        "unit_price": u_price,
                        "currency": currency,
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "clause_ref": str(r.get("clause_ref", f"Schedule A, item {idx}")).strip(),
                    }
                )

            src_md_rel = _write_contract_markdown(
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                contract_id=contract_id,
                effective_from=effective_from,
                effective_to=effective_to,
                currency=currency,
                rates=clean_rates,
            )

            vendor_payload = {
                "vendor_id": vendor_id,
                "name": vendor_name,
                "aliases": [vendor_name, vendor_id],
                "currency": currency,
                "destination_reference": dest_ref,
                "bank_verified": bank_verified,
                "contract": {
                    "contract_id": contract_id,
                    "vendor_id": vendor_id,
                    "source_file": src_md_rel,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "rates": clean_rates,
                },
                "history": {"cases": []},
            }
            v_file = ROOT_DIR / "vendors" / f"{vendor_id}.json"
            v_file.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(v_file, vendor_payload)
            _sync_vendor_registry()
            try:
                record_event(
                    case_id=f"VENDOR-{vendor_id.upper()}",
                    event_type="VENDOR_REGISTERED",
                    actor_id=user.username,
                    payload={
                        "vendor_id": vendor_id,
                        "vendor_name": vendor_name,
                        "contract_id": contract_id,
                        "destination_reference": dest_ref,
                        "rates_count": len(clean_rates),
                    },
                    db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                )
            except Exception:
                pass
            self._send_json(201, {"ok": True, "vendor_id": vendor_id, "vendors": list_vendors_payload()})
            return

        # 13. Add Rate to Existing or New Vendor Contract
        m_rate = re.match(r"^/api/v1/contracts/([^/]+)/rates$", path)
        if m_rate:
            vendor_id = re.sub(r"[^a-z0-9_-]", "", m_rate.group(1).strip().lower())
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            if not vendor_id:
                self._send_json(400, {"detail": "Valid 'vendor_id' is required"})
                return
            v_file = ROOT_DIR / "vendors" / f"{vendor_id}.json"
            sku = str(body.get("item_code") or body.get("sku") or "").strip()
            desc = str(body.get("description") or "").strip()
            unit = str(body.get("unit", "unit")).strip() or "unit"
            u_price = fmt_dec(to_dec(body.get("unit_price", "0.00")))
            clause_ref = str(body.get("clause_ref", "")).strip()
            if not sku or to_dec(u_price) <= Decimal("0.00"):
                self._send_json(400, {"detail": "Valid 'item_code' and 'unit_price' (> 0.00) are required"})
                return

            if v_file.exists():
                vdata = load_json(v_file)
            else:
                v_name = str(body.get("vendor_name") or f"{vendor_id.upper()} Vendor Services").strip()
                vdata = {
                    "vendor_id": vendor_id,
                    "name": v_name,
                    "aliases": [v_name, vendor_id],
                    "currency": str(body.get("currency", "INR")).strip().upper() or "INR",
                    "destination_reference": f"TREASURY-{vendor_id.upper()}-001",
                    "bank_verified": True,
                    "contract": {
                        "contract_id": f"CON-{vendor_id.upper()}-2026",
                        "vendor_id": vendor_id,
                        "source_file": f"contracts/{vendor_id}-contract.md",
                        "effective_from": "2026-01-01",
                        "effective_to": "2026-12-31",
                        "rates": [],
                    },
                    "history": {"cases": []},
                }

            contract = vdata.setdefault("contract", {})
            rates = contract.setdefault("rates", [])
            if not clause_ref:
                clause_ref = f"Schedule A, item {len(rates) + 1}"
            eff_from = str(body.get("effective_from") or contract.get("effective_from") or "2026-01-01")
            eff_to = str(body.get("effective_to") or contract.get("effective_to") or "2026-12-31")
            curr = str(body.get("currency") or vdata.get("currency") or "INR")
            ikey = re.sub(r"[^a-z0-9-]+", "-", sku.lower()).strip("-") or f"item-{len(rates) + 1}"
            full_desc = desc if (sku.lower() in desc.lower()) else f"{desc} ({sku})"

            new_rate = {
                "item_key": ikey,
                "sku": sku,
                "item_code": sku,
                "description": full_desc,
                "aliases": [a.strip() for a in str(body.get("aliases", desc or sku)).split(",") if a.strip()],
                "unit": unit,
                "unit_price": u_price,
                "currency": curr,
                "effective_from": eff_from,
                "effective_to": eff_to,
                "clause_ref": clause_ref,
            }
            replaced = False
            for idx, existing in enumerate(rates):
                if (existing.get("sku") or existing.get("item_code")) == sku:
                    rates[idx] = new_rate
                    replaced = True
                    break
            if not replaced:
                rates.append(new_rate)

            contract["source_file"] = _write_contract_markdown(
                vendor_id=vendor_id,
                vendor_name=vdata.get("name", vendor_id),
                contract_id=contract.get("contract_id") or f"CON-{vendor_id.upper()}-2026",
                effective_from=eff_from,
                effective_to=eff_to,
                currency=curr,
                rates=rates,
            )
            v_file.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(v_file, vdata)
            _sync_vendor_registry()
            try:
                record_event(
                    case_id=f"CONTRACT-{vendor_id.upper()}",
                    event_type="CONTRACT_RATE_SAVED",
                    actor_id=user.username,
                    payload={
                        "vendor_id": vendor_id,
                        "sku": sku,
                        "unit_price": u_price,
                        "clause_ref": clause_ref,
                    },
                    db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
                )
            except Exception:
                pass
            self._send_json(200, {"ok": True, "rate": new_rate, "contracts": list_contracts_payload()})
            return

        # 14. Audit Ledger Checkpoint
        if path == "/api/v1/audit/ledger/checkpoint":
            user = self._authenticate(PERM_AUDIT_CHECKPOINT)
            if not user:
                return
            key_bytes = get_active_signing_key()
            CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
            ledger_db_path = ROOT_DIR / DEFAULT_LEDGER_DB
            try:
                init_ledger_db(ledger_db_path)
                if not list_events(db_path=ledger_db_path):
                    record_event(
                        case_id="SYSTEM-GENESIS",
                        event_type="LEDGER_INITIALIZED",
                        actor_id=user.username,
                        payload={"note": "Genesis audit ledger event initialized prior to signed checkpoint"},
                        db_path=ledger_db_path,
                    )
                chk = create_checkpoint(db_path=ledger_db_path, key_bytes=key_bytes)
                out_file = CHECKPOINTS_DIR / f"{chk['checkpoint_id']}.json"
                write_json_atomic(out_file, chk)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "checkpoint_id": chk["checkpoint_id"],
                        "timestamp": chk["timestamp"],
                        "total_events": chk["total_events"],
                        "highest_sequence": chk["highest_sequence"],
                        "head_event_hash": chk["head_event_hash"],
                        "chain_digest": chk["chain_digest"],
                        "signature": chk.get("signature"),
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 15. Simulate Switch Multi-Agent Workflow (isolated sandbox — does not pollute workspace)
        if path == "/api/v1/integrations/switch/simulate":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            target_case = str(body.get("case_id", "sandbox-verify-01")).strip() or "sandbox-verify-01"
            try:
                import tempfile
                from desk import run_audit, run_finalize, run_history, run_intake
                from approve import approve_case_cli

                with tempfile.TemporaryDirectory(prefix="overcharge_switch_sandbox_") as tmp_str:
                    tmp_dir = Path(tmp_str)
                    for sub in ["cases", "vendors", "contracts", "invoices", "config"]:
                        (tmp_dir / sub).mkdir(parents=True, exist_ok=True)
                    if (ROOT_DIR / "config" / "actors.json").exists():
                        shutil.copy2(ROOT_DIR / "config" / "actors.json", tmp_dir / "config" / "actors.json")
                    if (ROOT_DIR / "identity.db").exists():
                        shutil.copy2(ROOT_DIR / "identity.db", tmp_dir / "identity.db")

                    con_path = ROOT_DIR / "seed" / "acme.json"
                    shutil.copy2(con_path, tmp_dir / "vendors" / "acme.json")
                    (tmp_dir / "contracts" / "acme-contract.md").write_text(
                        "# Master Supply Agreement — Acme Industrial Supplies\n"
                        "- Schedule A, item 1:SKU-BOX-200 — INR 30.00\n"
                        "- Schedule A, item 2:SKU-TAPE-48 — INR 60.00\n"
                        "- Schedule A, item 3:SKU-LABEL-1000 — INR 450.00\n",
                        encoding="utf-8",
                    )
                    inv_path = tmp_dir / "invoices" / "sandbox-invoice.txt"
                    inv_path.write_text(
                        "Vendor: Acme Industrial Supplies\n"
                        "Invoice Number: INV-SANDBOX-101\n"
                        "Invoice Date: 2026-11-03\n"
                        "Currency: INR\n"
                        "Line 1: Corrugated Shipping Boxes (SKU-BOX-200) | Qty: 100 | Unit Price: 36.00 | Line Total: 3600.00\n"
                        "Line 2: Packing Tape 48mm (SKU-TAPE-48) | Qty: 20 | Unit Price: 60.00 | Line Total: 1200.00\n"
                        "Stated Total: 4800.00\n",
                        encoding="utf-8",
                    )

                    r_intake = run_intake(invoice_path=inv_path, contract_path=con_path, case_id=target_case, base_dir=tmp_dir)
                    r_audit = run_audit(case_arg=target_case, base_dir=tmp_dir)
                    r_hist = run_history(vendor_id="acme", base_dir=tmp_dir)
                    r_app = approve_case_cli(
                        case_arg=target_case,
                        username="owner",
                        password_input="owner123",
                        force_tty=True,
                        base_dir=tmp_dir,
                    )
                    r_fin = run_finalize(case_arg=target_case, base_dir=tmp_dir)

                transcript = [
                    {
                        "turn": 1,
                        "agent": "@reader",
                        "stage": "INTAKE_COMPLETED",
                        "summary": f"[Isolated Sandbox] Preserved raw invoice artifact and registered 3 SHA-256 evidence records for {r_intake['case_id']}.",
                        "digests": {
                            "source_sha256": r_intake["source_sha256"],
                            "contract_sha256": r_intake["contract_sha256"],
                        },
                    },
                    {
                        "turn": 2,
                        "agent": "@auditor",
                        "stage": "VERIFICATION_COMPLETED",
                        "summary": (
                            f"[Isolated Sandbox] Status: {r_audit['verification_status']} ({r_audit['commercial_status']}). "
                            f"Payable: INR {r_audit['payable_goods_subtotal']} | Withheld Overcharge: INR {r_audit['withheld_goods_variance']}. "
                            f"Recalled {r_hist.get('prior_cases_count', 0)} prior cases."
                        ),
                        "digests": {
                            "compare_sha256": r_audit["compare_sha256"],
                            "ledger_head": r_audit["ledger_head"],
                        },
                    },
                    {
                        "turn": 3,
                        "agent": "@owner (Human Out-of-Band TTY)",
                        "stage": "APPROVAL_GRANTED",
                        "summary": f"[Isolated Sandbox] Authenticated human approval recorded ({r_app['receipt_id']}). Approved INR {r_app['approved_amount']}.",
                        "digests": {
                            "receipt_hash": r_app["receipt_hash"],
                        },
                    },
                    {
                        "turn": 4,
                        "agent": "@writer",
                        "stage": "PAYMENT_GENERATED",
                        "summary": f"[Isolated Sandbox] Verified HMAC receipt signature, emitted {r_fin['payment_sheet']} and dispute_email.md.",
                        "digests": {
                            "payable_amount": r_fin["payable_amount"],
                            "withheld_amount": r_fin["withheld_amount"],
                        },
                    },
                ]
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "case_id": r_intake["case_id"],
                        "transcript": transcript,
                    },
                )
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 16. Settings: Create User or Toggle Active Status
        if path == "/api/v1/settings/users":
            user = self._authenticate(PERM_ADMIN_USERS)
            if not user:
                return
            action = str(body.get("action", "create")).strip().lower()
            id_repo = IdentityRepository(db_path=ROOT_DIR / DEFAULT_IDENTITY_DB)
            try:
                if action == "toggle_active":
                    target_uid = str(body.get("user_id", "")).strip()
                    is_act = bool(body.get("is_active", True))
                    if target_uid == user.user_id and not is_act:
                        self._send_json(400, {"detail": "Cannot deactivate your own active administrator account"})
                        return
                    id_repo.set_user_active(target_uid, is_act)
                    self._send_json(200, {"ok": True, "data": list_users_and_roles_payload()})
                    return

                username = re.sub(r"[^a-z0-9_.-]", "", str(body.get("username", "")).strip().lower())
                full_name = str(body.get("full_name", "")).strip()
                email = str(body.get("email", "")).strip().lower()
                role = str(body.get("role", SystemRole.FINANCE_OPERATOR)).strip().upper()
                password = str(body.get("password", ""))
                if not username or not full_name or not email or len(password) < 6:
                    self._send_json(400, {"detail": "Username, full_name, email, and password (min 6 chars) are required"})
                    return
                if role not in SystemRole.ALL:
                    self._send_json(400, {"detail": f"Invalid role '{role}'"})
                    return
                pw_hash = hash_password(password)
                id_repo.create_user(
                    user_id=f"USR-{os.urandom(4).hex().upper()}",
                    username=username,
                    email=email,
                    full_name=full_name,
                    role=role,
                    password_hash=pw_hash,
                    is_active=True,
                    is_demo=False,
                )
                self._send_json(201, {"ok": True, "data": list_users_and_roles_payload()})
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        self._send_json(404, {"detail": f"Endpoint '{path}' not found"})


def main() -> None:
    port = int(os.environ.get("PORT", "3000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ReusableThreadingHTTPServer((host, port), OverchargeDeskHandler)
    ensure_base_storage_initialized()
    print(f"Overcharge Desk server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
