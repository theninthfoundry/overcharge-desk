#!/usr/bin/env python3
"""Cryptographic Receipt Inspection CLI for Overcharge Desk.

Inspects, decodes, and cryptographically verifies human approval receipts
(`receipt.json` or `approvals/approval_receipt.json`):
  1. Validates structural schema and required fields.
  2. Verifies full 64-character SHA-256 digests.
  3. Recomputes canonical receipt hash.
  4. Verifies HMAC-SHA-256 signature against the active signing key.

Usage:
  python tools/inspect_receipt.py <path_or_case_id> [--key-file PATH] [--json]

Exit codes: 0 verified valid | 1 signature/digest invalid or file missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Bootstrap paths
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from approval_receipt import (
    load_json,
    load_signing_key,
    verify_approval_receipt,
)


def locate_receipt(target: str, base_dir: Path) -> Path:
    target_path = Path(target)
    if target_path.is_file():
        return target_path.resolve()

    aliases = [target]
    ALIAS_MAP = {
        "OC-20261001-01": "demo-clean",
        "OC-20261106-01": "demo-overcharge",
        "demo-clean": "OC-20261001-01",
        "demo-overcharge": "OC-20261106-01",
        "demo-tampering": "OC-20261001-tampering",
    }
    if target in ALIAS_MAP:
        aliases.append(ALIAS_MAP[target])

    # If case ID given, search under cases/
    candidates = []
    for a in aliases:
        candidates.extend([
            base_dir / "cases" / a / "approvals" / "approval_receipt.json",
            base_dir / "cases" / a / "approval_receipt.json",
            base_dir / "cases" / a / "receipt.json",
            base_dir / a / "approvals" / "approval_receipt.json",
            base_dir / a / "receipt.json",
        ])

    for cand in candidates:
        if cand.is_file():
            return cand.resolve()

    raise FileNotFoundError(f"Could not locate receipt for target: '{target}'")


def inspect_receipt(
    target: str,
    base_dir: Path = None,
    key_path: Path = None,
    as_json: bool = False,
) -> int:
    if base_dir is None:
        base_dir = ROOT_DIR

    try:
        receipt_file = locate_receipt(target, base_dir)
        receipt_data = load_json(receipt_file)
    except Exception as exc:
        if as_json:
            print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2))
        else:
            print(f"Error loading receipt: {exc}", file=sys.stderr)
        return 1

    # Load signing key
    key_bytes = None
    key_source = None
    try:
        key_bytes = load_signing_key(key_path)
        key_source = str(key_path or "default_key_path")
    except Exception as exc:
        key_source = f"FAILED: {exc}"

    is_valid = False
    issues = []
    if key_bytes:
        is_valid, issues = verify_approval_receipt(receipt_data, key_bytes=key_bytes)
    else:
        issues.append(f"Signing key unavailable: {key_source}")

    result = {
        "status": "VALID" if is_valid else "INVALID",
        "receipt_file": str(receipt_file),
        "case_id": receipt_data.get("case_id"),
        "invoice_number": receipt_data.get("invoice_number"),
        "contract_id": receipt_data.get("contract_id"),
        "actor_id": receipt_data.get("actor_id"),
        "actor_role": receipt_data.get("actor_role"),
        "decision": receipt_data.get("decision"),
        "approved_amount": receipt_data.get("approved_amount"),
        "currency": receipt_data.get("currency"),
        "created_at": receipt_data.get("created_at"),
        "hashes": {
            "invoice_sha256": receipt_data.get("invoice_sha256"),
            "compare_sha256": receipt_data.get("compare_sha256"),
            "receipt_hash": receipt_data.get("receipt_hash"),
            "signature": receipt_data.get("receipt_signature"),
        },
        "issues": issues,
        "key_source": str(key_source) if key_source else None,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        status_color = "\033[32mVALID\033[0m" if is_valid else "\033[31mINVALID\033[0m"
        print(f"\nCryptographic Receipt Inspection: [{status_color}]")
        print(f"  File:           {receipt_file}")
        print(f"  Case ID:        {result['case_id']}")
        print(f"  Invoice:        {result['invoice_number']}")
        print(f"  Contract:       {result['contract_id']}")
        print(f"  Actor:          {result['actor_id']} ({result['actor_role']})")
        print(f"  Decision:       {result['decision']}")
        print(f"  Approved Sum:   {result['approved_amount']} {result['currency']}")
        print(f"  Receipt Hash:   {result['hashes']['receipt_hash']}")
        print(f"  HMAC Signature: {result['hashes']['signature']}")
        print(f"  Key Source:     {result['key_source']}")
        if issues:
            print("\n  Verification Issues:")
            for issue in issues:
                print(f"    - {issue}")
        print()

    return 0 if is_valid else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Cryptographic Receipt Inspector")
    parser.add_argument("target", help="Receipt JSON file path or Case ID")
    parser.add_argument("--key-file", help="Path to HMAC signing key file", default=None)
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    key_p = Path(args.key_file) if args.key_file else None
    sys.exit(inspect_receipt(args.target, key_path=key_p, as_json=args.json))


if __name__ == "__main__":
    main()
