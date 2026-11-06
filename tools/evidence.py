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

import hmac

REGISTRY_VERSION = "2.0.0"
REGISTRY_FILENAME = "evidence_registry.json"
GENESIS_REGISTRY_DIGEST = "0" * 64

EVIDENCE_TYPES = (
    "source_invoice",
    "extracted_invoice",
    "vendor_contract",
    "comparison_result",
    "verification_record",
    "payment_artifact",
    "review_artifact",
    "blocked_report",
    "approval_receipt",
    "ledger_snapshot",
    "audit_export",
)

IMMUTABLE_EVIDENCE_TYPES = (
    "source_invoice",
    "vendor_contract",
    "extracted_invoice",
    "approval_receipt",
)

POST_APPROVAL_EVIDENCE_TYPES = (
    "approval_receipt",
    "payment_artifact",
    "ledger_snapshot",
    "audit_export",
)


def _get_registry_path(case_dir: Path | str) -> Path:
    return Path(case_dir) / REGISTRY_FILENAME


def _canonical_evidence_entry(item: dict) -> dict:
    """Extract immutable fields of an evidence record for deterministic registry hashing."""
    return {
        "evidence_id": item.get("evidence_id"),
        "case_id": item.get("case_id"),
        "evidence_type": item.get("evidence_type"),
        "original_filename": item.get("original_filename"),
        "stored_path": item.get("stored_path"),
        "content_hash": item.get("content_hash"),
        "hash_algorithm": item.get("hash_algorithm", "SHA-256"),
        "byte_size": item.get("byte_size"),
        "version": item.get("version", 1),
        "supersedes_evidence_id": item.get("supersedes_evidence_id"),
        "previous_content_hash": item.get("previous_content_hash"),
    }


def compute_registry_digest(registry: dict) -> str:
    """Compute canonical 64-character SHA-256 digest of the evidence registry state."""
    payload = {
        "registry_version": registry.get("registry_version", REGISTRY_VERSION),
        "case_id": registry.get("case_id"),
        "registry_sequence": int(registry.get("registry_sequence", 1)),
        "previous_registry_digest": registry.get("previous_registry_digest", GENESIS_REGISTRY_DIGEST),
        "evidence": [_canonical_evidence_entry(e) for e in registry.get("evidence", [])],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _try_get_signing_key() -> Optional[bytes]:
    """Attempt to load the active HMAC signing key without failing if unconfigured in unit tests."""
    try:
        from auth import load_signing_key
        return load_signing_key()
    except Exception:
        return None


def compute_registry_signature(registry_digest: str, key_bytes: bytes) -> str:
    """Compute HMAC-SHA256 signature over the registry digest."""
    return hmac.new(key_bytes, registry_digest.encode("utf-8"), hashlib.sha256).hexdigest()


def load_registry(case_dir: Path | str) -> dict:
    """Load case evidence registry, initializing a blank one if missing."""
    reg_path = _get_registry_path(case_dir)
    if not reg_path.exists():
        return {
            "registry_version": REGISTRY_VERSION,
            "case_id": None,
            "registry_sequence": 0,
            "previous_registry_digest": GENESIS_REGISTRY_DIGEST,
            "registry_digest": None,
            "registry_signature": None,
            "created_at": utc_now_iso(),
            "evidence": [],
        }
    data = load_json(reg_path)
    if not isinstance(data, dict) or "evidence" not in data:
        raise ToolError(f"Malformed evidence registry at {reg_path}")
    return data


def save_registry(
    case_dir: Path | str,
    registry: dict,
    bump_sequence: bool = True,
    key_bytes: Optional[bytes] = None,
    key_file: Optional[Path | str] = None,
) -> None:
    """Save case evidence registry atomically with cryptographic hash-chain and HMAC authentication."""
    reg_path = _get_registry_path(case_dir)
    if bump_sequence:
        prev_digest = registry.get("registry_digest") or GENESIS_REGISTRY_DIGEST
        seq = int(registry.get("registry_sequence") or 0) + 1
        registry["registry_version"] = REGISTRY_VERSION
        registry["registry_sequence"] = seq
        registry["previous_registry_digest"] = prev_digest
    elif not registry.get("registry_sequence"):
        registry["registry_version"] = REGISTRY_VERSION
        registry["registry_sequence"] = 1
        registry["previous_registry_digest"] = GENESIS_REGISTRY_DIGEST

    digest = compute_registry_digest(registry)
    registry["registry_digest"] = digest
    if not key_bytes and key_file:
        try:
            from auth import load_signing_key
            key_bytes = load_signing_key(key_file)
        except Exception:
            key_bytes = None
    if not key_bytes:
        key_bytes = _try_get_signing_key()
    if key_bytes:
        registry["registry_signature"] = compute_registry_signature(digest, key_bytes)
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
    allow_amendment: bool = False,
) -> dict:
    """Register an artifact in the case evidence registry (append-only).

    - Never overwrites an existing evidence record's content_hash in place.
    - If the exact same artifact with the same content_hash is already registered,
      returns the existing record idempotently.
    - If an immutable source/input artifact (source_invoice, vendor_contract,
      extracted_invoice, approval_receipt) is re-registered with a different
      content_hash without allow_amendment=True, fails closed (exit code 4).
    - When a derived artifact is recomputed or allow_amendment=True, appends a new
      versioned evidence entry linking to the superseded record.
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
                f"Registry case_id mismatch: existing {registry['case_id']!r} vs given {case_id!r}",
                4,
            )
        registry["case_id"] = case_id
    else:
        case_id = registry.get("case_id") or "OC-UNKNOWN"

    # Try storing relative path: relative to c_dir first (for self-contained portability), then relative to base
    stored_path: str
    try:
        stored_path = str(resolved_path.relative_to(c_dir.resolve())).replace("\\", "/")
    except ValueError:
        try:
            stored_path = str(resolved_path.relative_to(base)).replace("\\", "/")
        except ValueError:
            stored_path = str(resolved_path).replace("\\", "/")

    # Locate active (non-superseded) matching evidence record
    existing_record = None
    for item in reversed(registry.get("evidence", [])):
        if item.get("superseded_by"):
            continue
        if item.get("stored_path") == stored_path or (
            item.get("evidence_type") == evidence_type and item.get("original_filename") == resolved_path.name
        ):
            existing_record = item
            break

    if existing_record:
        # Idempotent re-registration when content_hash is identical
        if str(existing_record.get("content_hash", "")).lower() == content_hash.lower():
            return existing_record

        # Different content hash on an already-registered artifact!
        if evidence_type in IMMUTABLE_EVIDENCE_TYPES and not allow_amendment:
            raise ToolError(
                f"Evidence mutation refused (EVIDENCE_MUTATION_REFUSED): {evidence_type} "
                f"({resolved_path.name}) is already registered as {existing_record.get('evidence_id')} "
                f"with SHA-256 {existing_record.get('content_hash')}, which differs from new "
                f"SHA-256 {content_hash}. Create a new case or invoke explicit amendment workflow.",
                4,
            )

    # Compute sequential evidence_id: EV-{case_id}-{seq:03d}
    existing_evidence = registry.get("evidence", [])
    seq = len(existing_evidence) + 1
    evidence_id = f"EV-{case_id}-{seq:03d}"

    version = 1
    supersedes_id = None
    prev_content_hash = None
    if existing_record:
        version = int(existing_record.get("version", 1)) + 1
        supersedes_id = existing_record.get("evidence_id")
        prev_content_hash = existing_record.get("content_hash")
        existing_record["superseded_by"] = evidence_id
        existing_record["superseded_at"] = utc_now_iso()

    record = {
        "evidence_id": evidence_id,
        "case_id": case_id,
        "evidence_type": evidence_type,
        "original_filename": resolved_path.name,
        "stored_path": stored_path,
        "content_hash": content_hash,
        "hash_algorithm": "SHA-256",
        "byte_size": byte_size,
        "version": version,
        "supersedes_evidence_id": supersedes_id,
        "previous_content_hash": prev_content_hash,
        "received_at": utc_now_iso(),
        "validation_status": "VERIFIED",
        "description": description or f"Registered {evidence_type} artifact (v{version})",
    }

    registry["evidence"].append(record)
    save_registry(c_dir, registry, bump_sequence=True)
    return record


def verify_evidence(
    # Integrity Verification: Re-hashes on-disk evidence files AND verifies registry cryptographic authenticity
    case_dir: Path | str,
    evidence_id: Optional[str] = None,
    base_dir: Optional[Path | str] = None,
    key_bytes: Optional[bytes] = None,
    key_file: Optional[Path | str] = None,
) -> dict:
    """Re-verify content hashes of registered evidence files and registry cryptographic digest/HMAC."""
    c_dir = Path(case_dir)
    registry = load_registry(c_dir)
    evidence_list = registry.get("evidence", [])
    if not evidence_list:
        raise ToolError(f"No evidence registered in {case_dir}")

    results = []
    failures = []

    # 1. Verify registry cryptographic digest & optional HMAC signature
    declared_reg_digest = registry.get("registry_digest")
    if declared_reg_digest:
        calc_reg_digest = compute_registry_digest(registry)
        if calc_reg_digest.lower() != str(declared_reg_digest).lower():
            failures.append({
                "evidence_id": "REGISTRY",
                "error": f"Registry digest mismatch: calculated {calc_reg_digest} != declared {declared_reg_digest}",
            })
        else:
            declared_sig = registry.get("registry_signature")
            candidate_keys: list[bytes] = []
            if key_bytes:
                candidate_keys.append(key_bytes)
            if key_file:
                try:
                    from auth import load_signing_key
                    kf_bytes = load_signing_key(key_file)
                    if kf_bytes and kf_bytes not in candidate_keys:
                        candidate_keys.append(kf_bytes)
                except Exception:
                    pass
            ambient_key = _try_get_signing_key()
            if ambient_key and ambient_key not in candidate_keys:
                candidate_keys.append(ambient_key)

            if declared_sig and candidate_keys:
                sig_matched = any(
                    hmac.compare_digest(
                        compute_registry_signature(calc_reg_digest, k).lower(),
                        str(declared_sig).lower(),
                    )
                    for k in candidate_keys
                )
                if not sig_matched:
                    failures.append({
                        "evidence_id": "REGISTRY_HMAC",
                        "error": "Registry HMAC signature verification failed (tampered registry metadata)",
                    })

    base = Path(base_dir) if base_dir else Path.cwd()
    active_evidence = [e for e in evidence_list if not e.get("superseded_by")]
    targets = (
        [e for e in evidence_list if e.get("evidence_id") == evidence_id]
        if evidence_id
        else active_evidence
    )

    if evidence_id and not targets:
        raise ToolError(f"Evidence ID {evidence_id!r} not found in registry")

    for item in targets:
        eid = item.get("evidence_id")
        declared_hash = item.get("content_hash")
        stored_path = item.get("stored_path")
        orig_name = item.get("original_filename")

        # Resolve path: try relative to case_dir first, then relative to base
        path_candidate = Path(stored_path)
        if not path_candidate.is_absolute():
            stripped_parts = list(path_candidate.parts)
            if len(stripped_parts) >= 2 and stripped_parts[0] == "cases":
                stripped_path = Path(*stripped_parts[2:])
            else:
                stripped_path = path_candidate

            if (c_dir / path_candidate).exists():
                actual_path = c_dir / path_candidate
            elif (c_dir / stripped_path).exists():
                actual_path = c_dir / stripped_path
            elif (c_dir / orig_name).exists():
                actual_path = c_dir / orig_name
            elif (base / path_candidate).exists():
                actual_path = base / path_candidate
            else:
                actual_path = c_dir / path_candidate
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

    # Only save validation_status updates without bumping the sequence if the registry itself wasn't tampered
    if not any(f["evidence_id"] in ("REGISTRY", "REGISTRY_HMAC") for f in failures):
        save_registry(c_dir, registry, bump_sequence=False)

    return {
        "ok": len(failures) == 0,
        "case_id": registry.get("case_id"),
        "registry_digest": registry.get("registry_digest"),
        "registry_sequence": registry.get("registry_sequence", 1),
        "total_checked": len(targets),
        "verified_count": len([r for r in results if r["valid"]]),
        "failed_count": len(failures),
        "failures": failures,
        "results": results,
    }


def list_evidence(case_dir: Path | str, include_superseded: bool = True) -> list[dict]:
    """Return evidence records in a case registry."""
    registry = load_registry(case_dir)
    items = registry.get("evidence", [])
    if not include_superseded:
        return [it for it in items if not it.get("superseded_by")]
    return items


def get_evidence(case_dir: Path | str, evidence_id: str) -> dict:
    """Retrieve a single evidence record by ID."""
    items = list_evidence(case_dir, include_superseded=True)
    for it in items:
        if it.get("evidence_id") == evidence_id:
            return it
    raise ToolError(f"Evidence ID {evidence_id!r} not found", 2)


def get_evidence_digest_map(
    case_dir: Path | str,
    active_only: bool = True,
    pre_approval_only: bool = False,
) -> dict[str, str]:
    # Cryptographic Digest Mapping: Extracts full 64-char SHA-256 mapping for approval bindings
    """Return mapping of evidence_id -> content_hash for registered items."""
    items = list_evidence(case_dir, include_superseded=not active_only)
    out: dict[str, str] = {}
    for item in items:
        if active_only and item.get("superseded_by"):
            continue
        if pre_approval_only and item.get("evidence_type") in POST_APPROVAL_EVIDENCE_TYPES:
            continue
        if "evidence_id" in item and "content_hash" in item:
            out[item["evidence_id"]] = item["content_hash"]
    return out


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

