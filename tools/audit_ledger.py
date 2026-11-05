#!/usr/bin/env python3
"""Tamper-Evident SQLite Audit Ledger for Overcharge Desk.

Implements a cryptographically verifiable, append-only audit trail using SQLite
ACID transactions and cryptographic SHA-256 hash chains per AGENTS.md invariant 4.

Hash Chain Definition:
    event_hash = SHA-256(canonical_json_bytes({
        "event_id": event_id,
        "event_sequence": seq,
        "case_id": case_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "timestamp": timestamp,
        "payload": payload,
        "evidence_refs": evidence_refs,
        "previous_event_hash": prev_hash
    }))

Genesis Event:
    The first event in the ledger has previous_event_hash = "0" * 64.

Security & Integrity Notice:
    The ledger enforces relational constraints, sequence integrity, and a continuous
    cryptographic hash chain. Any modification, reordering, deletion, or injection of
    records will immediately invalidate subsequent hash links. However, a user with
    direct write access to the SQLite file could recalculate the entire chain from the
    point of tampering forward; external checkpoints, digital signatures, or remote
    witnessing are required to defeat a full database rewrite.

Usage:
    python tools/audit_ledger.py init       [--db DB_PATH]
    python tools/audit_ledger.py record     CASE_ID EVENT_TYPE ACTOR_ID PAYLOAD_JSON [--db DB_PATH]
    python tools/audit_ledger.py list       [--case-id CASE_ID] [--db DB_PATH]
    python tools/audit_ledger.py verify     [--db DB_PATH]

Exit codes: 0 ok | 2 bad input / verification failure | 4 constraint violation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (CASE_ID_RE, ToolError, canonical_json_bytes, emit, load_json,
                    run_cli, utc_now_iso)

DEFAULT_LEDGER_DB = Path("ledger.db")
GENESIS_PREV_HASH = "0" * 64

EVENT_TYPES = (
    "CASE_CREATED",
    "EVIDENCE_REGISTERED",
    "INVOICE_VALIDATED",
    "CONTRACT_VALIDATED",
    "COMPARISON_COMPLETED",
    "VERIFICATION_COMPLETED",
    "REVIEW_REQUESTED",
    "REVIEW_COMPLETED",
    "APPROVAL_REQUESTED",
    "APPROVAL_GRANTED",
    "APPROVAL_REJECTED",
    "PAYMENT_RECOMMENDATION_CREATED",
    "PAYMENT_RECOMMENDATION_BLOCKED",
    "CASE_CLOSED",
)


def get_connection(db_path: Path | str = DEFAULT_LEDGER_DB) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and strict foreign keys."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Path | str = DEFAULT_LEDGER_DB) -> None:
    """Initialize audit ledger schema."""
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                event_sequence INTEGER NOT NULL UNIQUE,
                case_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                previous_event_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_case ON audit_events (case_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_seq ON audit_events (event_sequence);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON audit_events (event_type);")
    conn.close()


def compute_event_hash(
    event_id: str,
    event_sequence: int,
    case_id: str,
    event_type: str,
    actor_id: str,
    timestamp: str,
    payload: dict,
    evidence_refs: list,
    previous_event_hash: str,
) -> str:
    """Compute deterministic SHA-256 digest of canonical event contents."""
    canonical_dict = {
        "actor_id": actor_id,
        "case_id": case_id,
        "event_id": event_id,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "evidence_refs": evidence_refs,
        "payload": payload,
        "previous_event_hash": previous_event_hash.lower(),
        "timestamp": timestamp,
    }
    return hashlib.sha256(canonical_json_bytes(canonical_dict)).hexdigest()


def record_event(
    case_id: str,
    event_type: str,
    actor_id: str,
    payload: dict,
    evidence_refs: Optional[list] = None,
    db_path: Path | str = DEFAULT_LEDGER_DB,
    timestamp: Optional[str] = None,
) -> dict:
    """Atomically append a tamper-evident audit event to the ledger."""
    if event_type not in EVENT_TYPES:
        raise ToolError(
            f"Invalid event_type: {event_type!r}. Permitted: {', '.join(EVENT_TYPES)}", 2
        )

    if not actor_id or not isinstance(actor_id, str):
        raise ToolError("actor_id is required", 2)

    if not isinstance(payload, dict):
        raise ToolError("payload must be a JSON object (dict)", 2)

    refs = evidence_refs if isinstance(evidence_refs, list) else []
    ts = timestamp or utc_now_iso()

    init_db(db_path)
    conn = get_connection(db_path)

    try:
        with conn:
            # Lock the table for writing
            cursor = conn.execute(
                "SELECT event_sequence, event_hash FROM audit_events ORDER BY event_sequence DESC LIMIT 1"
            )
            latest = cursor.fetchone()

            if latest is None:
                new_seq = 1
                prev_hash = GENESIS_PREV_HASH
            else:
                new_seq = latest["event_sequence"] + 1
                prev_hash = latest["event_hash"]

            event_id = f"EVT-{new_seq:08d}"
            ev_hash = compute_event_hash(
                event_id=event_id,
                event_sequence=new_seq,
                case_id=case_id,
                event_type=event_type,
                actor_id=actor_id,
                timestamp=ts,
                payload=payload,
                evidence_refs=refs,
                previous_event_hash=prev_hash,
            )

            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, event_sequence, case_id, event_type, actor_id,
                    timestamp, payload_json, evidence_refs_json, previous_event_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    new_seq,
                    case_id,
                    event_type,
                    actor_id,
                    ts,
                    json.dumps(payload, sort_keys=True, ensure_ascii=False),
                    json.dumps(refs, sort_keys=True, ensure_ascii=False),
                    prev_hash,
                    ev_hash,
                ),
            )

        return {
            "event_id": event_id,
            "event_sequence": new_seq,
            "case_id": case_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "timestamp": ts,
            "previous_event_hash": prev_hash,
            "event_hash": ev_hash,
            "payload": payload,
            "evidence_refs": refs,
        }

    finally:
        conn.close()


def list_events(
    case_id: Optional[str] = None,
    db_path: Path | str = DEFAULT_LEDGER_DB,
) -> list[dict]:
    """Retrieve audit events from ledger."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        if case_id:
            cursor = conn.execute(
                "SELECT * FROM audit_events WHERE case_id = ? ORDER BY event_sequence ASC",
                (case_id,),
            )
        else:
            cursor = conn.execute("SELECT * FROM audit_events ORDER BY event_sequence ASC")

        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append({
                "event_id": r["event_id"],
                "event_sequence": r["event_sequence"],
                "case_id": r["case_id"],
                "event_type": r["event_type"],
                "actor_id": r["actor_id"],
                "timestamp": r["timestamp"],
                "payload": json.loads(r["payload_json"]),
                "evidence_refs": json.loads(r["evidence_refs_json"]),
                "previous_event_hash": r["previous_event_hash"],
                "event_hash": r["event_hash"],
            })
        return result
    finally:
        conn.close()


def verify_ledger(db_path: Path | str = DEFAULT_LEDGER_DB) -> tuple[bool, list[str]]:
    """Strictly verify the complete hash chain of the audit ledger.

    Detects:
      - Broken hash chains (previous_event_hash != preceding event_hash)
      - Modified payloads or metadata (event_hash != recomputed hash)
      - Sequence gaps, duplicates, or non-monotonic ordering
      - Invalid genesis hash
    """
    init_db(db_path)
    conn = get_connection(db_path)
    issues: list[str] = []

    try:
        cursor = conn.execute("SELECT * FROM audit_events ORDER BY event_sequence ASC")
        rows = cursor.fetchall()

        if not rows:
            return True, []  # Empty ledger is valid

        expected_seq = 1
        expected_prev_hash = GENESIS_PREV_HASH

        for row in rows:
            seq = row["event_sequence"]
            eid = row["event_id"]
            prev_hash = row["previous_event_hash"]
            ev_hash = row["event_hash"]

            # 1. Sequence check
            if seq != expected_seq:
                issues.append(
                    f"Sequence discontinuity: expected sequence {expected_seq}, found {seq} on event {eid}"
                )

            # 2. Event ID formatting
            if eid != f"EVT-{seq:08d}":
                issues.append(f"Event ID mismatch: sequence {seq} has event_id {eid!r}")

            # 3. Previous hash link check
            if prev_hash.lower() != expected_prev_hash.lower():
                issues.append(
                    f"Broken hash chain at sequence {seq} ({eid}): previous_event_hash {prev_hash} "
                    f"!= expected {expected_prev_hash}"
                )

            # 4. Recompute event hash
            try:
                payload = json.loads(row["payload_json"])
                refs = json.loads(row["evidence_refs_json"])
            except Exception as exc:
                issues.append(f"Corrupt JSON in event {eid}: {exc}")
                continue

            recomputed_hash = compute_event_hash(
                event_id=eid,
                event_sequence=seq,
                case_id=row["case_id"],
                event_type=row["event_type"],
                actor_id=row["actor_id"],
                timestamp=row["timestamp"],
                payload=payload,
                evidence_refs=refs,
                previous_event_hash=prev_hash,
            )

            if ev_hash.lower() != recomputed_hash.lower():
                issues.append(
                    f"Data tampering detected at sequence {seq} ({eid}): recorded event_hash {ev_hash} "
                    f"!= recomputed hash {recomputed_hash}"
                )

            expected_seq = seq + 1
            expected_prev_hash = ev_hash

        return len(issues) == 0, issues

    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    init_cmd = sub.add_parser("init", help="Initialize ledger database")
    init_cmd.add_argument("--db", default=str(DEFAULT_LEDGER_DB))

    rec_cmd = sub.add_parser("record", help="Record an audit event")
    rec_cmd.add_argument("case_id", help="Case ID")
    rec_cmd.add_argument("event_type", help=f"Event type ({', '.join(EVENT_TYPES)})")
    rec_cmd.add_argument("actor_id", help="Acting identity")
    rec_cmd.add_argument("payload", help="JSON payload string or path to JSON file")
    rec_cmd.add_argument("--refs", help="Comma-separated evidence IDs")
    rec_cmd.add_argument("--db", default=str(DEFAULT_LEDGER_DB))

    list_cmd = sub.add_parser("list", help="List audit events")
    list_cmd.add_argument("--case-id", help="Filter by case ID")
    list_cmd.add_argument("--db", default=str(DEFAULT_LEDGER_DB))

    ver_cmd = sub.add_parser("verify", help="Verify ledger cryptographic hash chain")
    ver_cmd.add_argument("--db", default=str(DEFAULT_LEDGER_DB))

    args = ap.parse_args()

    if args.cmd == "init":
        init_db(args.db)
        emit({"ok": True, "action": "ledger_initialized", "db": args.db})
        return 0

    elif args.cmd == "record":
        # Check if payload is a file path or JSON literal
        payload_data = None
        if Path(args.payload).exists():
            payload_data = load_json(args.payload)
        else:
            try:
                payload_data = json.loads(args.payload)
            except json.JSONDecodeError as exc:
                raise ToolError(f"Invalid JSON payload: {exc}")

        refs = [r.strip() for r in args.refs.split(",") if r.strip()] if args.refs else []
        ev = record_event(
            case_id=args.case_id,
            event_type=args.event_type,
            actor_id=args.actor_id,
            payload=payload_data,
            evidence_refs=refs,
            db_path=args.db,
        )
        emit({"ok": True, "action": "event_recorded", "event": ev})
        return 0

    elif args.cmd == "list":
        events = list_events(case_id=args.case_id, db_path=args.db)
        emit({"ok": True, "count": len(events), "events": events})
        return 0

    elif args.cmd == "verify":
        valid, issues = verify_ledger(args.db)
        emit({"ok": valid, "valid": valid, "issues": issues})
        return 0 if valid else 2

    return 2


if __name__ == "__main__":
    run_cli(main)
