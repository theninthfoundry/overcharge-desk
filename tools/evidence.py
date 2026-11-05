#!/usr/bin/env python3
"""Evidence Registry for Overcharge Desk.

Tracks, hashes, and cryptographically fingerprints all artifacts associated with
a verification case. Enforces universal source referencing and immutable source
locators per AGENTS.md invariant 2.

Usage:
    python tools/evidence.py register CASE_DIR FILE_PATH EVIDENCE_TYPE [--case-id CASE_ID]
    python tools/evidence.py verify   CASE_DIR [--evidence-id EVIDENCE_ID]
    python tools/evidence.py list     CASE_DIR
    python tools/evidence.py get      CASE_DIR EVIDENCE_ID

Exit codes: 0 ok | 2 bad input / verification failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (CASE_ID_RE, ToolError, canonical_json_bytes, emit,
                    is_safe_relative_path, load_json, run_cli, sha256_file,
                    utc_now_iso, write_json_atomic)

REGISTRY_VERSION = "1.0.0"
REGISTRY_FILENAME = "evidence_registry.json"

EVIDENCE_TYPES = (
    "source_invoice",
    "extracted_invoice",
    "vendor_contract",
    "comparison_result",
    "payment_artifact",
    "review_artifact",
    "blocked_report",
    "approval_receipt",
    "ledger_snapshot",
    "audit_export",
)


def _get_registry_path(case_dir: Path | str) -> Path:
    return Path(case_dir) / REGISTRY_FILENAME


def load_registry(case_dir: Path | str) -> dict:
    """Load case evidence registry, initializing a blank one if missing."""
    reg_path = _get_registry_path(case_dir)
    if not reg_path.exists():
        return {
            "registry_version": REGISTRY_VERSION,
            "case_id": None,
            "created_at": utc_now_iso(),
            "evidence": [],
        }
    data = load_json(reg_path)
    if not isinstance(data, dict) or "evidence" not in data:
        raise ToolError(f"Malformed evidence registry at {reg_path}")
    return data


def save_registry(case_dir: Path | str, registry: dict) -> None:
    """Save case evidence registry atomically."""
    reg_path = _get_registry_path(case_dir)
    registry["updated_at"] = utc_now_iso()
    write_json_atomic(reg_path, registry)


def register_evidence(
    # Invariant Rule 2.1: Universal source referencing with immutable SHA-256 fingerprinting
    case_dir: Path | str,
    file_path: Path | str,
    evidence_type: str,
    case_id: Optional[str] = None,
    base_dir: Optional[Path | str] = None,
    description: Optional[str] = None,
) -> dict:
    """Register an artifact in the case evidence registry.

    Computes full 64-char SHA-256 content hash, records byte size,
    timestamps, and saves registry atomically.
    """
    if evidence_type not in EVIDENCE_TYPES:
        raise ToolError(
            f"Invalid evidence_type: {evidence_type!r}. Must be one of: {', '.join(EVIDENCE_TYPES)}"
        )

    base = Path(base_dir) if base_dir else Path.cwd()
    target = Path(file_path)
    resolved_path = target if target.is_absolute() else (base / target).resolve()

    if not resolved_path.exists() or not resolved_path.is_file():
        raise ToolError(f"Evidence file not found: {file_path}")

    # Compute content hash
    content_hash = sha256_file(str(resolved_path))
    byte_size = resolved_path.stat().st_size

    # Load registry
    c_dir = Path(case_dir)
    c_dir.mkdir(parents=True, exist_ok=True)
    registry = load_registry(c_dir)

    # Validate or associate case_id
    if case_id:
        if not CASE_ID_RE.match(case_id):
            raise ToolError(f"Invalid case_id format: {case_id!r}")
        if registry.get("case_id") and registry["case_id"] != case_id:
            raise ToolError(
                f"Registry case_id mismatch: existing {registry['case_id']!r} vs given {case_id!r}"
            )
        registry["case_id"] = case_id
    else:
        case_id = registry.get("case_id") or "OC-UNKNOWN"

    # Compute sequential evidence_id: EV-{case_id}-{seq:03d}
    existing_evidence = registry.get("evidence", [])
    seq = len(existing_evidence) + 1
    evidence_id = f"EV-{case_id}-{seq:03d}"

    # Try storing relative path if inside case_dir or base_dir
    stored_path: str
    try:
        stored_path = str(resolved_path.relative_to(base)).replace("\\", "/")
    except ValueError:
        try:
            stored_path = str(resolved_path.relative_to(c_dir.resolve())).replace("\\", "/")
        except ValueError:
            stored_path = str(resolved_path).replace("\\", "/")

    record = {
        "evidence_id": evidence_id,
        "case_id": case_id,
        "evidence_type": evidence_type,
        "original_filename": resolved_path.name,
        "stored_path": stored_path,
        "content_hash": content_hash,
        "hash_algorithm": "SHA-256",
        "byte_size": byte_size,
        "received_at": utc_now_iso(),
        "validation_status": "VERIFIED",
        "description": description or f"Registered {evidence_type} artifact",
    }

    registry["evidence"].append(record)
    save_registry(c_dir, registry)
    return record


def verify_evidence(
    # Integrity Verification: Re-hashes on-disk evidence files to detect unauthorized modification
    case_dir: Path | str,
    evidence_id: Optional[str] = None,
    base_dir: Optional[Path | str] = None,
) -> dict:
    """Re-verify content hashes of registered evidence files against current disk contents.

    Returns summary of verified and failed items.
    """
    c_dir = Path(case_dir)
    registry = load_registry(c_dir)
    evidence_list = registry.get("evidence", [])
    if not evidence_list:
        raise ToolError(f"No evidence registered in {case_dir}")

    base = Path(base_dir) if base_dir else Path.cwd()
    targets = (
        [e for e in evidence_list if e.get("evidence_id") == evidence_id]
        if evidence_id
        else evidence_list
    )

    if evidence_id and not targets:
        raise ToolError(f"Evidence ID {evidence_id!r} not found in registry")

    results = []
    failures = []

    for item in targets:
        eid = item.get("evidence_id")
        declared_hash = item.get("content_hash")
        stored_path = item.get("stored_path")
        orig_name = item.get("original_filename")

        # Resolve path
        path_candidate = Path(stored_path)
        if not path_candidate.is_absolute():
            # Try relative to base, then relative to case_dir
            if (base / path_candidate).exists():
                actual_path = base / path_candidate
            elif (c_dir / path_candidate).exists():
                actual_path = c_dir / path_candidate
            elif (c_dir / orig_name).exists():
                actual_path = c_dir / orig_name
            else:
                actual_path = base / path_candidate
        else:
            actual_path = path_candidate

        if not actual_path.exists() or not actual_path.is_file():
            item["validation_status"] = "FAILED"
            failures.append({
                "evidence_id": eid,
                "error": f"File not found on disk: {stored_path}",
            })
            results.append({"evidence_id": eid, "valid": False, "reason": "FILE_MISSING"})
            continue

        current_hash = sha256_file(str(actual_path))
        if current_hash.lower() != str(declared_hash).lower():
            item["validation_status"] = "FAILED"
            failures.append({
                "evidence_id": eid,
                "error": f"Hash mismatch: calculated {current_hash} != declared {declared_hash}",
            })
            results.append({
                "evidence_id": eid,
                "valid": False,
                "reason": "HASH_MISMATCH",
                "calculated": current_hash,
                "expected": declared_hash,
            })
        else:
            item["validation_status"] = "VERIFIED"
            results.append({
                "evidence_id": eid,
                "valid": True,
                "hash": current_hash,
            })

    save_registry(c_dir, registry)

    return {
        "ok": len(failures) == 0,
        "case_id": registry.get("case_id"),
        "total_checked": len(targets),
        "verified_count": len([r for r in results if r["valid"]]),
        "failed_count": len(failures),
        "failures": failures,
        "results": results,
    }


def list_evidence(case_dir: Path | str) -> list[dict]:
    """Return all evidence records in a case registry."""
    registry = load_registry(case_dir)
    return registry.get("evidence", [])


def get_evidence(case_dir: Path | str, evidence_id: str) -> dict:
    """Retrieve a single evidence record by ID."""
    items = list_evidence(case_dir)
    for it in items:
        if it.get("evidence_id") == evidence_id:
            return it
    raise ToolError(f"Evidence ID {evidence_id!r} not found", 2)


def get_evidence_digest_map(case_dir: Path | str) -> dict[str, str]:
    # Cryptographic Digest Mapping: Extracts full 64-char SHA-256 mapping for approval bindings
    """Return mapping of evidence_id -> content_hash for all registered items."""
    items = list_evidence(case_dir)
    return {
        item["evidence_id"]: item["content_hash"]
        for item in items
        if "evidence_id" in item and "content_hash" in item
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    reg_cmd = sub.add_parser("register", help="Register an artifact in the evidence registry")
    reg_cmd.add_argument("case_dir", help="Path to case directory")
    reg_cmd.add_argument("file_path", help="Path to file to register")
    reg_cmd.add_argument("evidence_type", help=f"Evidence type: {', '.join(EVIDENCE_TYPES)}")
    reg_cmd.add_argument("--case-id", help="Case ID (e.g. OC-YYYYMMDD-NN)")
    reg_cmd.add_argument("--desc", help="Optional description")

    ver_cmd = sub.add_parser("verify", help="Verify registered evidence content hashes")
    ver_cmd.add_argument("case_dir", help="Path to case directory")
    ver_cmd.add_argument("--evidence-id", help="Optional specific evidence ID to verify")

    list_cmd = sub.add_parser("list", help="List all registered evidence")
    list_cmd.add_argument("case_dir", help="Path to case directory")

    get_cmd = sub.add_parser("get", help="Get a single evidence record")
    get_cmd.add_argument("case_dir", help="Path to case directory")
    get_cmd.add_argument("evidence_id", help="Evidence ID")

    args = ap.parse_args()

    if args.cmd == "register":
        rec = register_evidence(
            args.case_dir,
            args.file_path,
            args.evidence_type,
            case_id=args.case_id,
            description=args.desc,
        )
        emit({"ok": True, "action": "evidence_registered", "evidence": rec})
        return 0

    elif args.cmd == "verify":
        res = verify_evidence(args.case_dir, evidence_id=args.evidence_id)
        emit(res)
        return 0 if res["ok"] else 2

    elif args.cmd == "list":
        items = list_evidence(args.case_dir)
        emit({"ok": True, "count": len(items), "evidence": items})
        return 0

    elif args.cmd == "get":
        item = get_evidence(args.case_dir, args.evidence_id)
        emit({"ok": True, "evidence": item})
        return 0

    return 2


if __name__ == "__main__":
    run_cli(main)

