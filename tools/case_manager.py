#!/usr/bin/env python3
"""Case Directory & Lifecycle Manager for Overcharge Desk.

Creates and manages standardized case directory structures with deterministic
file layouts and lifecycle state tracking per AGENTS.md.

Standard case structure:
    cases/<case_id>/
        case.json               # Case metadata & current state
        evidence_registry.json  # Fingerprinted artifact registry
        source/                 # Preserved raw intake documents
        normalized/             # Extracted JSON representations
        comparison/             # Deterministic comparison outputs & digests
        artifacts/              # Payment sheets, review files, blocked reports
        approvals/              # Cryptographic approval receipts
        audit/                  # Verification audit logs & manifests

Usage:
    python tools/case_manager.py init   CASE_ID [--cases-dir DIR] [--vendor-id VENDOR]
    python tools/case_manager.py status CASE_ID [--cases-dir DIR]
    python tools/case_manager.py set-state CASE_ID NEW_STATE [--reason REASON]

Exit codes: 0 ok | 2 bad input | 4 invalid state transition.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from common import (CASE_ID_RE, ToolError, emit, load_json, run_cli,
                    utc_now_iso, write_json_atomic)

# Case lifecycle states
CASE_STATE_CREATED = "CREATED"
CASE_STATE_INTAKE_VERIFIED = "INTAKE_VERIFIED"
CASE_STATE_COMPARED = "COMPARED"
CASE_STATE_VERIFIED = "VERIFIED"
CASE_STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
CASE_STATE_BLOCKED = "BLOCKED"
CASE_STATE_APPROVAL_PENDING = "APPROVAL_PENDING"
CASE_STATE_APPROVED = "APPROVED"
CASE_STATE_REJECTED = "REJECTED"
CASE_STATE_PAYMENT_GENERATED = "PAYMENT_GENERATED"
CASE_STATE_CLOSED = "CLOSED"

ALL_CASE_STATES = {
    CASE_STATE_CREATED,
    CASE_STATE_INTAKE_VERIFIED,
    CASE_STATE_COMPARED,
    CASE_STATE_VERIFIED,
    CASE_STATE_REVIEW_REQUIRED,
    CASE_STATE_BLOCKED,
    CASE_STATE_APPROVAL_PENDING,
    CASE_STATE_APPROVED,
    CASE_STATE_REJECTED,
    CASE_STATE_PAYMENT_GENERATED,
    CASE_STATE_CLOSED,
}

# Permitted state transitions
LEGAL_TRANSITIONS: Dict[str, Set[str]] = {
    CASE_STATE_CREATED: {CASE_STATE_INTAKE_VERIFIED, CASE_STATE_BLOCKED},
    CASE_STATE_INTAKE_VERIFIED: {
        CASE_STATE_COMPARED,
        CASE_STATE_VERIFIED,
        CASE_STATE_REVIEW_REQUIRED,
        CASE_STATE_BLOCKED,
    },
    CASE_STATE_COMPARED: {
        CASE_STATE_VERIFIED,
        CASE_STATE_REVIEW_REQUIRED,
        CASE_STATE_BLOCKED,
    },
    CASE_STATE_VERIFIED: {CASE_STATE_APPROVAL_PENDING, CASE_STATE_BLOCKED},
    CASE_STATE_REVIEW_REQUIRED: {
        CASE_STATE_APPROVAL_PENDING,
        CASE_STATE_REJECTED,
        CASE_STATE_BLOCKED,
        CASE_STATE_CLOSED,
    },
    CASE_STATE_BLOCKED: {CASE_STATE_REJECTED, CASE_STATE_CLOSED},
    CASE_STATE_APPROVAL_PENDING: {
        CASE_STATE_APPROVED,
        CASE_STATE_REJECTED,
        CASE_STATE_BLOCKED,
    },
    CASE_STATE_APPROVED: {CASE_STATE_PAYMENT_GENERATED, CASE_STATE_CLOSED},
    CASE_STATE_PAYMENT_GENERATED: {CASE_STATE_CLOSED},
    CASE_STATE_REJECTED: {CASE_STATE_CLOSED},
    CASE_STATE_CLOSED: set(),  # Terminal state
}

SUBDIRECTORIES = [
    "source",
    "normalized",
    "comparison",
    "artifacts",
    "approvals",
    "audit",
]


def get_case_dir(cases_dir: Path | str, case_id: str) -> Path:
    """Return Path to case directory after validating case_id format."""
    if not CASE_ID_RE.match(case_id):
        raise ToolError(f"Invalid case_id format: {case_id!r} (expected OC-YYYYMMDD-NN)")
    return Path(cases_dir) / case_id


def init_case(
    case_id: str,
    cases_dir: Path | str = "cases",
    vendor_id: Optional[str] = None,
    invoice_number: Optional[str] = None,
) -> dict:
    """Initialize a standardized case directory structure and metadata."""
    c_dir = get_case_dir(cases_dir, case_id)
    case_meta_path = c_dir / "case.json"

    if case_meta_path.exists():
        raise ToolError(f"Case {case_id} already exists at {c_dir}", 4)

    # Create subdirectories
    c_dir.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRECTORIES:
        (c_dir / sub).mkdir(parents=True, exist_ok=True)

    now = utc_now_iso()
    meta = {
        "case_id": case_id,
        "vendor_id": vendor_id,
        "invoice_number": invoice_number,
        "status": CASE_STATE_CREATED,
        "created_at": now,
        "updated_at": now,
        "history": [
            {
                "status": CASE_STATE_CREATED,
                "timestamp": now,
                "reason": "Case initialized",
            }
        ],
    }
    write_json_atomic(case_meta_path, meta)
    return meta


def load_case(case_id: str, cases_dir: Path | str = "cases") -> dict:
    """Load case metadata dictionary."""
    c_dir = get_case_dir(cases_dir, case_id)
    meta_path = c_dir / "case.json"
    if not meta_path.exists():
        raise ToolError(f"Case {case_id} does not exist at {c_dir}", 2)
    return load_json(meta_path)


def transition_case_state(
    case_id: str,
    new_state: str,
    cases_dir: Path | str = "cases",
    reason: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> dict:
    """Safely transition case state enforcing state-machine invariants."""
    if new_state not in ALL_CASE_STATES:
        raise ToolError(
            f"Invalid target state {new_state!r}. Permitted states: {sorted(ALL_CASE_STATES)}"
        )

    meta = load_case(case_id, cases_dir=cases_dir)
    current_state = meta.get("status")

    if new_state == current_state:
        return meta  # Idempotent no-op

    permitted = LEGAL_TRANSITIONS.get(current_state, set())
    if new_state not in permitted:
        raise ToolError(
            f"Illegal state transition for case {case_id}: cannot transition from {current_state!r} to {new_state!r}. "
            f"Permitted next states: {sorted(permitted) if permitted else 'None (terminal state)'}",
            4,
        )

    now = utc_now_iso()
    meta["status"] = new_state
    meta["updated_at"] = now
    meta.setdefault("history", []).append({
        "from_status": current_state,
        "to_status": new_state,
        "timestamp": now,
        "reason": reason or f"Transitioned to {new_state}",
        "actor_id": actor_id or "SYSTEM",
    })

    c_dir = get_case_dir(cases_dir, case_id)
    write_json_atomic(c_dir / "case.json", meta)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    init_cmd = sub.add_parser("init", help="Initialize a case directory structure")
    init_cmd.add_argument("case_id", help="Case ID (OC-YYYYMMDD-NN)")
    init_cmd.add_argument("--cases-dir", default="cases", help="Cases base directory")
    init_cmd.add_argument("--vendor-id", help="Associated vendor ID")
    init_cmd.add_argument("--invoice-number", help="Associated invoice number")

    status_cmd = sub.add_parser("status", help="Get case status and metadata")
    status_cmd.add_argument("case_id", help="Case ID")
    status_cmd.add_argument("--cases-dir", default="cases")

    trans_cmd = sub.add_parser("set-state", help="Transition case lifecycle state")
    trans_cmd.add_argument("case_id", help="Case ID")
    trans_cmd.add_argument("new_state", help=f"Target state ({', '.join(sorted(ALL_CASE_STATES))})")
    trans_cmd.add_argument("--cases-dir", default="cases")
    trans_cmd.add_argument("--reason", help="Transition rationale")
    trans_cmd.add_argument("--actor-id", help="Acting identity")

    args = ap.parse_args()

    if args.cmd == "init":
        meta = init_case(
            args.case_id,
            cases_dir=args.cases_dir,
            vendor_id=args.vendor_id,
            invoice_number=args.invoice_number,
        )
        emit({"ok": True, "action": "case_initialized", "case": meta})
        return 0

    elif args.cmd == "status":
        meta = load_case(args.case_id, cases_dir=args.cases_dir)
        emit({"ok": True, "case": meta})
        return 0

    elif args.cmd == "set-state":
        meta = transition_case_state(
            args.case_id,
            args.new_state,
            cases_dir=args.cases_dir,
            reason=args.reason,
            actor_id=args.actor_id,
        )
        emit({"ok": True, "action": "state_transitioned", "case": meta})
        return 0

    return 2


if __name__ == "__main__":
    run_cli(main)
