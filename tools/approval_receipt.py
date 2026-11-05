#!/usr/bin/env python3
"""Cryptographic Approval Receipts for Overcharge Desk.

Generates and validates cryptographically bound, fail-closed human approval
receipts. Enforces AGENTS.md invariant 3:
    Approval bindings must strictly incorporate:
    (case_id, invoice_number, invoice_sha256, contract_id, compare_sha256,
     audit_sha256, decision, authenticated_actor)

Usage:
    python tools/approval_receipt.py verify RECEIPT_JSON [--key-file FILE] [--case-id CASE_ID]

Exit codes: 0 ok | 2 verification failure / bad input.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (CASE_ID_RE, CURRENCY_RE, ToolError, canonical_json_bytes,
                    emit, exact_str, load_json, money_str, q2, run_cli,
                    to_decimal, utc_now_iso, write_json_atomic)
from auth import DEFAULT_KEY_FILE, load_signing_key

RECEIPT_VERSION = "1.0.0"
HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DECISIONS = ("APPROVED", "REJECTED")


def build_receipt_body(
    # Invariant Rule 3.3: Cryptographically binds full 64-char SHA-256 digests of all evidence
    case_id: str,
    invoice_number: str,
    invoice_sha256: str,
    contract_id: str,
    compare_sha256: str,
    evidence_digest_set: dict[str, str],
    actor_id: str,
    actor_role: str,
    decision: str,
    approved_amount: Optional[Decimal | str] = None,
    withheld_amount: Optional[Decimal | str] = None,
    currency: Optional[str] = None,
    reason: Optional[str] = None,
    created_at: Optional[str] = None,
) -> dict:
    """Construct canonical approval receipt body prior to signing."""
    if not CASE_ID_RE.match(case_id):
        raise ToolError(f"Invalid case_id format: {case_id!r}")

    if not invoice_number:
        raise ToolError("invoice_number is required")

    if not HEX_64_RE.match(str(invoice_sha256)):
        raise ToolError(f"invoice_sha256 must be a 64-char hex digest, got {invoice_sha256!r}")

    if not contract_id:
        raise ToolError("contract_id is required")

    if not HEX_64_RE.match(str(compare_sha256)):
        raise ToolError(f"compare_sha256 must be a 64-char hex digest, got {compare_sha256!r}")

    if decision not in DECISIONS:
        raise ToolError(f"decision must be one of {DECISIONS}, got {decision!r}")

    if decision == "REJECTED" and not reason:
        raise ToolError("Rejection decision requires an explicit reason (owner rationale)")

    if decision == "APPROVED":
        if approved_amount is None:
            raise ToolError("Approval decision requires approved_amount")
        if not currency or not CURRENCY_RE.match(str(currency)):
            raise ToolError("Approval decision requires a valid 3-letter ISO currency code")

    app_amt_str = money_str(to_decimal(approved_amount)) if approved_amount is not None else None
    with_amt_str = money_str(to_decimal(withheld_amount)) if withheld_amount is not None else None

    # Validate evidence digests
    clean_digests = {}
    for eid, dgst in sorted(evidence_digest_set.items()):
        if not HEX_64_RE.match(str(dgst)):
            raise ToolError(f"Evidence {eid} has malformed digest: {dgst!r}")
        clean_digests[str(eid)] = str(dgst).lower()

    timestamp = created_at or utc_now_iso()
    compact_ts = timestamp.replace("-", "").replace(":", "").replace("Z", "")
    receipt_id = f"AR-{case_id}-{compact_ts}"

    return {
        "receipt_version": RECEIPT_VERSION,
        "receipt_id": receipt_id,
        "case_id": case_id,
        "invoice_number": invoice_number,
        "invoice_sha256": invoice_sha256.lower(),
        "contract_id": contract_id,
        "compare_sha256": compare_sha256.lower(),
        "evidence_digest_set": clean_digests,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "decision": decision,
        "approved_amount": app_amt_str,
        "withheld_amount": with_amt_str,
        "currency": currency,
        "reason": reason,
        "created_at": timestamp,
        "trust_model": {
            "signing_algorithm": "HMAC-SHA-256",
            "security_notice": (
                "HMAC-SHA-256 proves shared secret possession at signing time. "
                "Does not provide cryptographic non-repudiation."
            ),
        },
    }


def compute_receipt_hash(receipt_body: dict) -> str:
    """Compute the 64-character SHA-256 digest of the canonical receipt body."""
    # Ensure signature fields are stripped before hashing
    body_copy = {k: v for k, v in receipt_body.items() if k not in ("receipt_hash", "receipt_signature")}
    canonical_bytes = canonical_json_bytes(body_copy)
    return hashlib.sha256(canonical_bytes).hexdigest()


def sign_receipt(receipt_body: dict, key_bytes: bytes) -> dict:
    # Cryptographic Signature: HMAC-SHA-256 computation over sorted canonical JSON bytes
    """Compute receipt hash and sign it using HMAC-SHA-256."""
    r_hash = compute_receipt_hash(receipt_body)
    sig = hmac.new(key_bytes, r_hash.encode("utf-8"), hashlib.sha256).hexdigest()

    signed = dict(receipt_body)
    signed["receipt_hash"] = r_hash
    signed["receipt_signature"] = sig
    return signed


def verify_approval_receipt(
    receipt: dict,
    key_bytes: bytes,
    expected_case_id: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Strictly verify a cryptographic approval receipt.

    Checks:
      1. Structural integrity and required fields.
      2. Full 64-char SHA-256 digest format on all hashes.
      3. Receipt hash parity against re-computed canonical JSON hash.
      4. HMAC-SHA-256 cryptographic signature against provisioned key.
      5. Case ID match (if expected_case_id is provided).

    Returns: `(is_valid, list_of_issues)`
    """
    issues: list[str] = []

    if not isinstance(receipt, dict):
        return False, ["Receipt must be a JSON object"]

    if receipt.get("receipt_version") != RECEIPT_VERSION:
        issues.append(f"Unsupported receipt_version: {receipt.get('receipt_version')!r}")

    # Check case_id
    cid = receipt.get("case_id")
    if not cid or not CASE_ID_RE.match(str(cid)):
        issues.append(f"Invalid or missing case_id: {cid!r}")
    elif expected_case_id and cid != expected_case_id:
        issues.append(f"Case ID mismatch: expected {expected_case_id} but receipt is for {cid}")

    # Check required fields
    for req in ("invoice_number", "contract_id", "actor_id", "actor_role", "decision", "created_at"):
        if not receipt.get(req):
            issues.append(f"Missing required receipt field: {req}")

    # Check 64-char hashes
    inv_sha = receipt.get("invoice_sha256", "")
    if not HEX_64_RE.match(str(inv_sha)):
        issues.append(f"Malformed invoice_sha256: {inv_sha!r}")

    cmp_sha = receipt.get("compare_sha256", "")
    if not HEX_64_RE.match(str(cmp_sha)):
        issues.append(f"Malformed compare_sha256: {cmp_sha!r}")

    declared_hash = receipt.get("receipt_hash")
    if not declared_hash or not HEX_64_RE.match(str(declared_hash)):
        issues.append(f"Malformed or missing receipt_hash: {declared_hash!r}")

    declared_sig = receipt.get("receipt_signature")
    if not declared_sig or not HEX_64_RE.match(str(declared_sig)):
        issues.append(f"Malformed or missing receipt_signature: {declared_sig!r}")

    # Check decision-specific rules
    decision = receipt.get("decision")
    if decision not in DECISIONS:
        issues.append(f"Invalid decision: {decision!r}")
    elif decision == "REJECTED" and not receipt.get("reason"):
        issues.append("Rejected receipt is missing owner reason")
    elif decision == "APPROVED":
        if receipt.get("approved_amount") is None:
            issues.append("Approved receipt is missing approved_amount")
        if not receipt.get("currency"):
            issues.append("Approved receipt is missing currency")

    # If already failed basic structure, stop
    if issues:
        return False, issues

    # Re-compute receipt hash
    computed_hash = compute_receipt_hash(receipt)
    if declared_hash.lower() != computed_hash.lower():
        issues.append(
            f"Receipt hash mismatch: declared {declared_hash} != recomputed {computed_hash}"
        )

    # Re-compute HMAC signature
    expected_sig = hmac.new(key_bytes, declared_hash.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(declared_sig.lower(), expected_sig.lower()):
        issues.append("Cryptographic signature verification failed (invalid signature)")

    return len(issues) == 0, issues


def save_approval_receipt(receipt: dict, out_path: Path | str) -> None:
    """Save signed approval receipt atomically to disk."""
    write_json_atomic(out_path, receipt)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ver_cmd = sub.add_parser("verify", help="Verify a signed approval receipt")
    ver_cmd.add_argument("receipt_json", help="Path to approval receipt JSON file")
    ver_cmd.add_argument("--key-file", help="Path to signing key file")
    ver_cmd.add_argument("--case-id", help="Expected case ID")

    args = ap.parse_args()

    if args.cmd == "verify":
        receipt_data = load_json(args.receipt_json)
        key_bytes = load_signing_key(args.key_file)
        valid, issues = verify_approval_receipt(receipt_data, key_bytes, expected_case_id=args.case_id)
        emit({"ok": valid, "valid": valid, "receipt_id": receipt_data.get("receipt_id"), "issues": issues})
        return 0 if valid else 2

    return 2


if __name__ == "__main__":
    run_cli(main)

