#!/usr/bin/env python3
"""Audit Package Exporter and Verifier for Overcharge Desk.

Packages all evidence artifacts, deterministic comparison records, verification
manifests, approval receipts, and ledger event histories into a self-contained
reconciliation audit package (`case_audit/<case_id>/`).

Includes a cryptographic `audit_integrity_report.json` and standalone verification.

Usage:
    python tools/export_audit_package.py export CASE_DIR [--out DIR] [--ledger-db DB] [--key-file KEY]
    python tools/export_audit_package.py verify PACKAGE_DIR [--key-file KEY]

Exit codes: 0 ok | 2 verification failure or missing critical artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (ToolError, canonical_json_bytes, emit, load_json, run_cli,
                    sha256_file, utc_now_iso, write_json_atomic)
from auth import load_signing_key
from approval_receipt import verify_approval_receipt
from audit_ledger import DEFAULT_LEDGER_DB, list_events

EXPORT_VERSION = "1.0.0"


def export_case_audit(
    case_dir: Path | str,
    out_dir: Optional[Path | str] = None,
    ledger_db: Path | str = DEFAULT_LEDGER_DB,
    key_file: Optional[Path | str] = None,
) -> dict:
    """Export complete evidence package for an audit case."""
    c_p = Path(case_dir)
    if not c_p.exists():
        raise ToolError(f"Case directory does not exist: {c_p}", 2)

    case_id = c_p.name
    # Try reading case_id from case.json or manifest.json or invoice.json
    manifest_p = c_p / "manifest.json"
    if manifest_p.exists():
        case_id = load_json(manifest_p).get("case_id") or case_id
    elif (c_p / "invoice.json").exists():
        case_id = load_json(c_p / "invoice.json").get("case_id") or case_id

    target_dir = Path(out_dir) if out_dir else Path("case_audit") / case_id
    target_dir.mkdir(parents=True, exist_ok=True)

    copied_artifacts: Dict[str, str] = {}
    artifact_hashes: Dict[str, str] = {}

    # Copy all case files and subdirectories
    for item in c_p.rglob("*"):
        if item.is_file():
            rel = item.relative_to(c_p)
            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            h = sha256_file(dest)
            rel_str = str(rel).replace("\\", "/")
            copied_artifacts[rel_str] = str(dest)
            artifact_hashes[rel_str] = h

    # Export relevant ledger events
    ledger_events = []
    db_p = Path(ledger_db)
    if db_p.exists():
        ledger_events = list_events(case_id=case_id, db_path=db_p)
        ledger_exp_p = target_dir / "audit" / "ledger_events.json"
        ledger_exp_p.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(ledger_exp_p, {"case_id": case_id, "events": ledger_events})
        rel_str = "audit/ledger_events.json"
        artifact_hashes[rel_str] = sha256_file(ledger_exp_p)

    # Verification inspection
    vrf_p = target_dir / "audit" / "verification.json"
    if not vrf_p.exists():
        vrf_p = target_dir / "verification.json"
    vrf_data = load_json(vrf_p) if vrf_p.exists() else {}

    # Approval receipt inspection
    app_p = target_dir / "approvals" / "approval_receipt.json"
    if not app_p.exists():
        app_p = target_dir / "approval_receipt.json"
    app_data = load_json(app_p) if app_p.exists() else None
    app_valid = None
    app_issues = []

    if app_data and key_file:
        key_bytes = load_signing_key(key_file)
        app_valid, app_issues = verify_approval_receipt(app_data, key_bytes, expected_case_id=case_id)

    report = {
        "export_version": EXPORT_VERSION,
        "exported_at": utc_now_iso(),
        "case_id": case_id,
        "source_case_directory": str(c_p),
        "target_package_directory": str(target_dir),
        "verification_status": vrf_data.get("verification_status", "UNKNOWN"),
        "commercial_status": vrf_data.get("commercial_status", "UNKNOWN"),
        "has_approval_receipt": app_data is not None,
        "approval_decision": app_data.get("decision") if app_data else None,
        "approval_signature_verified": app_valid,
        "approval_verification_issues": app_issues,
        "ledger_events_count": len(ledger_events),
        "total_packaged_files": len(artifact_hashes),
        "artifact_hashes": artifact_hashes,
    }

    # Compute Package Integrity Digest
    report_copy = {k: v for k, v in report.items() if k != "package_integrity_digest"}
    pkg_digest = hashlib.sha256(canonical_json_bytes(report_copy)).hexdigest()
    report["package_integrity_digest"] = pkg_digest

    report_path = target_dir / "audit_integrity_report.json"
    write_json_atomic(report_path, report)
    sha_path = target_dir / "audit_integrity_report.json.sha256"
    sha_path.write_text(pkg_digest + "\n", encoding="utf-8")

    return report


def verify_package_integrity(package_dir: Path | str, key_file: Optional[Path | str] = None) -> tuple[bool, list[str]]:
    """Strictly verify all hashes and cryptographic bindings of an audit package."""
    p_dir = Path(package_dir)
    report_path = p_dir / "audit_integrity_report.json"
    if not report_path.exists():
        return False, [f"audit_integrity_report.json missing in {p_dir}"]

    report = load_json(report_path)
    issues = []

    # 1. Verify Package Integrity Digest
    declared_digest = report.get("package_integrity_digest")
    report_copy = {k: v for k, v in report.items() if k != "package_integrity_digest"}
    calc_digest = hashlib.sha256(canonical_json_bytes(report_copy)).hexdigest()
    if not declared_digest or declared_digest.lower() != calc_digest.lower():
        issues.append(f"Package integrity digest mismatch: declared {declared_digest} != calculated {calc_digest}")

    # 2. Re-hash every packaged file
    artifact_hashes = report.get("artifact_hashes", {})
    for rel_path, expected_hash in artifact_hashes.items():
        file_path = p_dir / rel_path
        if not file_path.exists():
            issues.append(f"Missing packaged file: {rel_path}")
            continue
        actual_hash = sha256_file(file_path)
        if actual_hash.lower() != expected_hash.lower():
            issues.append(f"Tampered file {rel_path}: actual SHA {actual_hash} != expected {expected_hash}")

    # 3. Verify approval receipt HMAC if key provided
    app_p = p_dir / "approvals" / "approval_receipt.json"
    if not app_p.exists():
        app_p = p_dir / "approval_receipt.json"
    if app_p.exists() and key_file:
        key_bytes = load_signing_key(key_file)
        app_data = load_json(app_p)
        ok, r_issues = verify_approval_receipt(app_data, key_bytes, expected_case_id=report.get("case_id"))
        if not ok:
            issues.extend([f"Approval receipt invalid: {i}" for i in r_issues])

    return len(issues) == 0, issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    exp_cmd = sub.add_parser("export", help="Export audit package")
    exp_cmd.add_argument("case_dir", help="Path to case directory")
    exp_cmd.add_argument("--out", help="Optional output package directory")
    exp_cmd.add_argument("--ledger-db", default=str(DEFAULT_LEDGER_DB))
    exp_cmd.add_argument("--key-file", help="Path to signing key file")

    ver_cmd = sub.add_parser("verify", help="Verify audit package integrity")
    ver_cmd.add_argument("package_dir", help="Path to package directory")
    ver_cmd.add_argument("--key-file", help="Path to signing key file")

    args = ap.parse_args()

    if args.cmd == "export":
        rep = export_case_audit(
            case_dir=args.case_dir,
            out_dir=args.out,
            ledger_db=args.ledger_db,
            key_file=args.key_file,
        )
        emit({"ok": True, "action": "audit_package_exported", "report": rep})
        return 0

    elif args.cmd == "verify":
        ok, issues = verify_package_integrity(args.package_dir, key_file=args.key_file)
        emit({"ok": ok, "action": "audit_package_verified", "valid": ok, "issues": issues})
        return 0 if ok else 2

    return 2


if __name__ == "__main__":
    run_cli(main)

