#!/usr/bin/env python3
"""Independent Cryptographic Verifier for Overcharge Desk Audit Ledger.

Traverses the complete SQLite audit ledger from genesis to head, recalculating
and verifying each SHA-256 link in the cryptographic hash chain.

Exit codes:
    0 — Ledger is authentic, unbroken, and mathematically valid.
    2 — Broken hash chain, altered records, sequence gaps, or corrupt database.

Usage:
    python tools/verify_ledger.py [--db DB_PATH] [--strict]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, load_json, run_cli
from audit_ledger import DEFAULT_LEDGER_DB, list_events, verify_checkpoint, verify_ledger


def main() -> int:
    # Independent Auditor: Sequential traversal verifying continuous cryptographic hash chain
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_LEDGER_DB), help="Path to SQLite ledger database")
    ap.add_argument("--checkpoint", help="Optional path to trusted ledger checkpoint JSON")
    ap.add_argument("--key-file", help="Optional path to signing key file for checkpoint signature check")
    ap.add_argument("--strict", action="store_true", help="Exit code 2 on verification failure")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        emit({"ok": False, "error": f"Ledger database does not exist: {db_path}"})
        return 2

    valid, issues = verify_ledger(db_path)
    events = list_events(db_path=db_path)

    checkpoint_valid = None
    checkpoint_issues: list[str] = []
    if args.checkpoint:
        from auth import load_signing_key
        key_bytes = load_signing_key(args.key_file) if args.key_file else None
        chk_data = load_json(args.checkpoint)
        checkpoint_valid, checkpoint_issues = verify_checkpoint(chk_data, db_path=db_path, key_bytes=key_bytes)
        if not checkpoint_valid:
            valid = False
            issues.extend(checkpoint_issues)

    summary = {
        "ok": valid,
        "database": str(db_path),
        "total_events": len(events),
        "chain_integrity": "VALID" if valid else "COMPROMISED",
        "issues_count": len(issues),
        "issues": issues,
    }
    if args.checkpoint:
        summary["checkpoint_verified"] = checkpoint_valid
        summary["checkpoint_issues"] = checkpoint_issues

    if events:
        summary["first_event_id"] = events[0]["event_id"]
        summary["first_event_hash"] = events[0]["event_hash"]
        summary["latest_event_id"] = events[-1]["event_id"]
        summary["latest_event_hash"] = events[-1]["event_hash"]

    emit(summary)
    return 0 if valid else 2


if __name__ == "__main__":
    run_cli(main)

