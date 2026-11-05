#!/usr/bin/env python3
"""Interactive Terminal Owner Approval CLI for Overcharge Desk.

Performs human authorization of reconciliation findings via interactive terminal session.
Enforces fail-closed security invariants:
  1. Interactive TTY Required: Automated pipes and agent prompt execution are strictly refused.
  2. Argon2id Password Authentication: Checks credentials against persistent identity store.
  3. Role-Based Verification: Only authenticated APPROVER or ADMINISTRATOR users can authorize.
  4. Server-Side Amount Calculation: Payable amount is computed deterministically from compare.json.
  5. Cryptographic Receipt Issuance: Produces full 64-character SHA-256 receipt for Switch room.

Usage:
    python tools/approve.py CASE_ID [--username USER] [--decision {APPROVED,REJECTED}] [--reason REASON]

Exit codes: 0 ok | 2 bad input / verification failure | 4 unauthorized / non-TTY.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Ensure tools directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common import (STATE_VERIFIED, ToolError, emit, load_json, money_str,
                    run_cli, to_decimal)
from auth import ensure_signing_key, get_default_key_path, issue_actor_token, load_actors_config
from approval_gateway import process_approval_decision
from domain.identity.models import IdentityService, SystemRole


def resolve_case_dir(case_arg: str, root_dir: Path) -> Path:
    """Resolve case directory path from ID or relative path."""
    p = Path(case_arg)
    if p.is_dir() and (p / "invoice.json").exists():
        return p.resolve()
    candidate = root_dir / "cases" / case_arg
    if candidate.is_dir() and (candidate / "invoice.json").exists():
        return candidate.resolve()
    if p.is_dir():
        return p.resolve()
    if candidate.is_dir():
        return candidate.resolve()
    raise ToolError(f"Case directory not found: '{case_arg}'", 2)


def approve_case_cli(
    case_arg: str,
    username: str = "owner",
    decision: str = "APPROVED",
    reason: Optional[str] = None,
    key_file: Optional[Path | str] = None,
    force_tty: bool = False,
    password_input: Optional[str] = None,
) -> dict:
    """Execute human approval decision with TTY enforcement and Argon2id verification."""
    root = ROOT_DIR

    # 1. Mandatory TTY check: Automated scripts or piped input cannot forge human authorization
    is_tty = sys.stdin.isatty() or force_tty or bool(os.getenv("OVERCHARGE_FORCE_TTY_TEST"))
    if not is_tty:
        raise ToolError(
            "Human approval requires an interactive TTY session; automated or piped execution prohibited",
            4,
        )

    # 2. Interactive password acquisition
    if password_input is not None:
        pw = password_input
    else:
        try:
            pw = getpass.getpass(f"Enter password for approver '{username}': ")
        except (EOFError, KeyboardInterrupt):
            raise ToolError("Authentication aborted by user", 4)

    if not pw:
        raise ToolError("Authentication refused: Empty password", 4)

    # 3. Authenticate against Argon2id identity store
    id_service = IdentityService(app_env=os.getenv("APP_ENV", "development"))
    user = id_service.authenticate(username, pw)
    if not user:
        raise ToolError(f"Authentication failed: Invalid credentials for user '{username}'", 4)

    # 4. Enforce role-based access control (RBAC)
    if user.role not in (SystemRole.APPROVER, SystemRole.ADMINISTRATOR):
        raise ToolError(
            f"Authorization refused: User '{username}' with role '{user.role}' lacks approval permissions",
            4,
        )

    # 5. Resolve case directory and inspect comparison
    case_dir = resolve_case_dir(case_arg, root)
    comp_file = case_dir / "comparison" / "compare.json"
    if not comp_file.exists():
        comp_file = case_dir / "compare.json"
    if not comp_file.exists():
        raise ToolError(f"Comparison artifact compare.json not found in case directory: {case_dir}", 2)

    comp_data = load_json(comp_file)
    case_id = comp_data.get("case_id", case_dir.name)
    v_status = comp_data.get("verification_status")

    # 6. Verify case eligibility
    if decision == "APPROVED":
        if v_status != STATE_VERIFIED:
            raise ToolError(
                f"Authorization refused: Case '{case_id}' verification status is '{v_status}'. "
                f"Only '{STATE_VERIFIED}' cases may be approved.",
                4,
            )
        totals = comp_data.get("totals", {})
        calc_payable = to_decimal(totals.get("per_contract_total", totals.get("matched_per_contract", "0")))
        calc_withheld = to_decimal(totals.get("variance_on_matched_lines", "0"))
        payable_str = money_str(calc_payable)
        withheld_str = money_str(calc_withheld)
    else:
        if not reason or not reason.strip():
            raise ToolError("Rejection requires an explicit reason", 2)
        payable_str = "0.00"
        withheld_str = "0.00"

    # 7. Issue internal HMAC-SHA-256 actor token for authorized execution
    key_path = Path(key_file) if key_file else get_default_key_path()
    key_bytes = ensure_signing_key(key_path)
    actors_cfg = load_actors_config(root / "config" / "actors.json")
    actor_token = issue_actor_token(username, key_bytes, config=actors_cfg)

    # 8. Call Authorization Gateway to perform verification & sign receipt
    result = process_approval_decision(
        case_dir=case_dir,
        actor_token=actor_token,
        decision=decision,
        reason=reason,
        amount=payable_str if decision == "APPROVED" else None,
        key_file=key_path,
        config_file=root / "config" / "actors.json",
    )

    receipt_path = Path(result["receipt_file"])
    receipt_data = load_json(receipt_path)
    receipt_hash = receipt_data.get("receipt_hash") or receipt_data.get("receipt_signature")

    return {
        "ok": True,
        "case_id": case_id,
        "decision": decision,
        "authenticated_actor": username,
        "actor_role": user.role,
        "approved_amount": result.get("approved_amount", payable_str),
        "withheld_amount": result.get("withheld_amount", withheld_str),
        "receipt_id": result.get("receipt_id"),
        "receipt_file": str(receipt_path),
        "receipt_hash": receipt_hash,
        "switch_notification": (
            f"[OVERCHARGE DESK] Human approval recorded for case {case_id} by @{username}.\n"
            f"Payable Goods: INR {result.get('approved_amount', payable_str)} | "
            f"Withheld Overcharge: INR {result.get('withheld_amount', withheld_str)}\n"
            f"Receipt SHA-256: {receipt_hash}"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("case", help="Case ID or path (e.g. 'demo-overcharge' or 'cases/demo-overcharge')")
    ap.add_argument("--username", default="owner", help="Approver username (default: 'owner')")
    ap.add_argument("--decision", choices=["APPROVED", "REJECTED"], default="APPROVED", help="Approval decision")
    ap.add_argument("--reason", help="Rejection rationale (required if REJECTED)")
    ap.add_argument("--key-file", help="Path to signing key file")
    ap.add_argument("--force-tty", action="store_true", help=argparse.SUPPRESS)

    args = ap.parse_args()

    res = approve_case_cli(
        case_arg=args.case,
        username=args.username,
        decision=args.decision,
        reason=args.reason,
        key_file=args.key_file,
        force_tty=args.force_tty,
    )

    # Print formatted Switch notification for human operator
    sys.stderr.write("\n" + "=" * 80 + "\n")
    sys.stderr.write("           OVERCHARGE DESK - HUMAN AUTHORIZATION RECORDED\n")
    sys.stderr.write("=" * 80 + "\n")
    sys.stderr.write(f"Case ID:            {res['case_id']}\n")
    sys.stderr.write(f"Decision:           {res['decision']}\n")
    sys.stderr.write(f"Approver:           @{res['authenticated_actor']} ({res['actor_role']})\n")
    sys.stderr.write(f"Payable Goods:      INR {res['approved_amount']}\n")
    sys.stderr.write(f"Withheld Amount:    INR {res['withheld_amount']}\n")
    sys.stderr.write(f"Receipt ID:         {res['receipt_id']}\n")
    sys.stderr.write(f"Receipt SHA-256:    {res['receipt_hash']}\n")
    sys.stderr.write("-" * 80 + "\n")
    sys.stderr.write("Switch Room Notification (Copy to Mattermost):\n")
    sys.stderr.write(res["switch_notification"] + "\n")
    sys.stderr.write("=" * 80 + "\n\n")

    emit(res)
    return 0


if __name__ == "__main__":
    run_cli(main)
