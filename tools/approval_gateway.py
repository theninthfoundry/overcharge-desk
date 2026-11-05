#!/usr/bin/env python3
"""Authorization Gateway for Overcharge Desk.

Validates human authorization decisions, performs deep evidence and arithmetic
re-verification, enforces role permissions, and creates signed approval receipts.

Per AGENTS.md:
    1. Hash verification does not equal identity.
    2. LLM prompts are not security boundaries.
    3. Full cryptographic digest requirement (64-char SHA-256).
    4. Fail-closed authorization: missing, ambiguous, stale, or unverified identity
       causes immediate refusal.

Usage:
    python tools/approval_gateway.py approve CASE_DIR --token ACTOR_TOKEN [--amount AMOUNT] [--key-file KEY]
    python tools/approval_gateway.py reject  CASE_DIR --token ACTOR_TOKEN --reason REASON   [--key-file KEY]
    python tools/approval_gateway.py verify  CASE_DIR [--key-file KEY]

Exit codes: 0 ok | 2 validation failure | 4 unauthorized / refused.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import (CENT, STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
                    ToolError, emit, load_json, money_str, q2, run_cli,
                    to_decimal, utc_now_iso)
from auth import (check_actor_permission, load_actors_config, load_signing_key,
                  verify_actor_token)
from evidence import (get_evidence_digest_map, load_registry, register_evidence,
                      verify_evidence)
from validate_comparison import validate_comparison
from approval_receipt import (build_receipt_body, save_approval_receipt,
                              sign_receipt, verify_approval_receipt)
from case_manager import (CASE_STATE_APPROVAL_PENDING, CASE_STATE_APPROVED,
                          CASE_STATE_REJECTED, load_case, transition_case_state)


def process_approval_decision(
    # Authorization Gateway: Orchestrates actor authentication, evidence checks, and receipt signing
    case_dir: Path | str,
    actor_token: str,
    decision: str,
    reason: Optional[str] = None,
    approved_amount: Optional[Decimal | str] = None,
    amount: Optional[Decimal | str] = None,
    key_file: Optional[Path | str] = None,
    config_file: Optional[Path | str] = None,
) -> dict:
    """Execute the full authorization gateway pipeline for an approval decision."""
    if approved_amount is None and amount is not None:
        approved_amount = amount
    c_dir = Path(case_dir)
    if not c_dir.exists():
        raise ToolError(f"Case directory does not exist: {c_dir}", 2)

    # 1. Authenticate Actor
    key_bytes = load_signing_key(key_file)
    actors_cfg = load_actors_config(config_file)

    auth_ok, auth_reason, actor = verify_actor_token(actor_token, key_bytes, config=actors_cfg)
    if not auth_ok or not actor:
        raise ToolError(f"Authorization refused: Authentication failure ({auth_reason})", 4)

    actor_id = actor["actor_id"]
    actor_role = actor.get("role", "UNKNOWN")

    # 2. Check Permissions
    required_perm = "approve_case" if decision == "APPROVED" else "reject_case"
    if not check_actor_permission(actor_id, required_perm, config=actors_cfg):
        raise ToolError(
            f"Authorization refused: Actor {actor_id!r} lacks required permission {required_perm!r}",
            4,
        )

    # 3. Load and inspect comparison result
    comp_json_path = c_dir / "comparison" / "compare.json"
    if not comp_json_path.exists():
        # Fallback to root of case_dir
        comp_json_path = c_dir / "compare.json"
        if not comp_json_path.exists():
            raise ToolError(f"Comparison result compare.json not found in {c_dir}", 2)

    comp_digest_path = Path(f"{comp_json_path}.sha256")
    comp_data = load_json(comp_json_path)

    # Validate comparison math & schema
    comp_issues = validate_comparison(
        comp_data,
        companion_digest_file=comp_digest_path if comp_digest_path.exists() else None,
    )
    if comp_issues:
        raise ToolError(
            f"Authorization refused: Comparison result failed independent verification: {'; '.join(comp_issues)}",
            2,
        )

    # 4. Verify registered evidence files on disk
    reg_path = c_dir / "evidence_registry.json"
    if reg_path.exists():
        ev_verify = verify_evidence(c_dir)
        if not ev_verify["ok"]:
            raise ToolError(
                f"Authorization refused: Evidence integrity check failed on disk: {ev_verify['failures']}",
                2,
            )
        evidence_digests = get_evidence_digest_map(c_dir)
    else:
        evidence_digests = {}

    v_status = comp_data.get("verification_status")
    case_id = comp_data.get("case_id") or c_dir.name
    inv_num = comp_data.get("invoice_number", "UNKNOWN")
    inv_sha = comp_data.get("source_sha256") or "0" * 64
    con_id = comp_data.get("contract_id", "UNKNOWN")
    currency = comp_data.get("currency", "INR")

    # Read comparison SHA from digest file or compute
    if comp_digest_path.exists():
        compare_sha = comp_digest_path.read_text(encoding="utf-8").strip()
    else:
        from common import hash_comparison_result
        compare_sha = hash_comparison_result(comp_data)

    # 5. Decision-specific verification
    calc_payable_str: Optional[str] = None
    calc_withheld_str: Optional[str] = None

    if decision == "APPROVED":
        # Fail-closed: Never approve a BLOCKED audit
        # Invariant Rule 1.4: Refuses approval on arithmetic discrepancies or hash mismatches
        if v_status == STATE_BLOCKED:
            blocking = comp_data.get("blocking_issues", [])
            raise ToolError(
                f"Authorization refused: Cannot approve BLOCKED audit. Blocking issues: {'; '.join(blocking)}",
                4,
            )

        # For VERIFIED audits: compute exact payable goods total
        if v_status == STATE_VERIFIED:
            totals = comp_data.get("totals", {})
            calc_payable = to_decimal(totals.get("matched_per_contract", "0"))
            calc_withheld = to_decimal(totals.get("variance_on_matched_lines", "0"))
            calc_payable_str = money_str(calc_payable)
            calc_withheld_str = money_str(calc_withheld)

            # If caller supplied amount, it must match exact payable amount
            if approved_amount is not None:
                given_d = q2(to_decimal(approved_amount))
                if given_d != calc_payable:
                    raise ToolError(
                        f"Authorization refused: Approved amount mismatch: given {money_str(given_d)} != "
                        f"calculated payable amount {calc_payable_str}",
                        4,
                    )
            else:
                approved_amount = calc_payable_str

    elif decision == "REJECTED":
        if not reason or not reason.strip():
            raise ToolError("Authorization refused: Rejection requires an explicit reason", 2)

    # 6. Construct and Sign Approval Receipt
    receipt_body = build_receipt_body(
        case_id=case_id,
        invoice_number=inv_num,
        invoice_sha256=inv_sha,
        contract_id=con_id,
        compare_sha256=compare_sha,
        evidence_digest_set=evidence_digests,
        actor_id=actor_id,
        actor_role=actor_role,
        decision=decision,
        approved_amount=approved_amount,
        withheld_amount=calc_withheld_str,
        currency=currency,
        reason=reason,
    )

    signed_receipt = sign_receipt(receipt_body, key_bytes)

    # 7. Save Receipt to Case directory
    approvals_dir = c_dir / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = approvals_dir / "approval_receipt.json"
    save_approval_receipt(signed_receipt, receipt_path)

    # 8. Register Receipt in Evidence Registry
    if reg_path.exists():
        register_evidence(
            c_dir,
            receipt_path,
            evidence_type="approval_receipt",
            case_id=case_id,
            description=f"{decision} decision receipt signed by {actor_id}",
        )

    # 9. Update case lifecycle state if case.json exists
    case_meta_path = c_dir / "case.json"
    if case_meta_path.exists():
        try:
            target_state = CASE_STATE_APPROVED if decision == "APPROVED" else CASE_STATE_REJECTED
            transition_case_state(
                case_id=case_id,
                new_state=target_state,
                cases_dir=c_dir.parent,
                reason=reason or f"Case {decision} by {actor_id}",
                actor_id=actor_id,
            )
        except Exception:
            # Case state transition is best-effort for existing flat case dirs
            pass

    return {
        "ok": True,
        "action": f"case_{decision.lower()}",
        "decision": decision,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "receipt_id": signed_receipt["receipt_id"],
        "receipt_file": str(receipt_path),
        "receipt_hash": signed_receipt["receipt_hash"],
        "receipt_signature": signed_receipt["receipt_signature"],
        "approved_amount": signed_receipt.get("approved_amount"),
        "withheld_amount": signed_receipt.get("withheld_amount"),
        "currency": signed_receipt.get("currency"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    app_cmd = sub.add_parser("approve", help="Approve an audit case")
    app_cmd.add_argument("case_dir", help="Path to case directory")
    app_cmd.add_argument("--token", required=True, help="HMAC actor token for authentication")
    app_cmd.add_argument("--amount", help="Optional exact approved amount check")
    app_cmd.add_argument("--key-file", help="Path to signing key file")
    app_cmd.add_argument("--config", help="Path to actors.json config")

    rej_cmd = sub.add_parser("reject", help="Reject an audit case")
    rej_cmd.add_argument("case_dir", help="Path to case directory")
    rej_cmd.add_argument("--token", required=True, help="HMAC actor token for authentication")
    rej_cmd.add_argument("--reason", required=True, help="Mandatory rejection rationale")
    rej_cmd.add_argument("--key-file", help="Path to signing key file")
    rej_cmd.add_argument("--config", help="Path to actors.json config")

    ver_cmd = sub.add_parser("verify", help="Verify existing approval receipt in case directory")
    ver_cmd.add_argument("case_dir", help="Path to case directory")
    ver_cmd.add_argument("--key-file", help="Path to signing key file")

    args = ap.parse_args()

    if args.cmd == "approve":
        res = process_approval_decision(
            case_dir=args.case_dir,
            actor_token=args.token,
            decision="APPROVED",
            approved_amount=args.amount,
            key_file=args.key_file,
            config_file=args.config,
        )
        emit(res)
        return 0

    elif args.cmd == "reject":
        res = process_approval_decision(
            case_dir=args.case_dir,
            actor_token=args.token,
            decision="REJECTED",
            reason=args.reason,
            key_file=args.key_file,
            config_file=args.config,
        )
        emit(res)
        return 0

    elif args.cmd == "verify":
        receipt_path = Path(args.case_dir) / "approvals" / "approval_receipt.json"
        if not receipt_path.exists():
            receipt_path = Path(args.case_dir) / "approval_receipt.json"
            if not receipt_path.exists():
                raise ToolError(f"No approval receipt found in {args.case_dir}", 2)

        data = load_json(receipt_path)
        key_bytes = load_signing_key(args.key_file)
        valid, issues = verify_approval_receipt(data, key_bytes)
        emit({"ok": valid, "valid": valid, "receipt_id": data.get("receipt_id"), "issues": issues})
        return 0 if valid else 2

    return 2


if __name__ == "__main__":
    run_cli(main)
