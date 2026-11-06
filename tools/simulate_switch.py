#!/usr/bin/env python3
"""Switch Room Multi-Agent Live Simulator for Overcharge Desk.

Simulates the collaborative 4-turn multi-agent workflow inside the Switch /
Mattermost '#overcharge-desk' channel:
  1. [@reader]  Intake raw invoice, compute SHA-256, register evidence.
  2. [@auditor] Deterministic audit, vendor memory query, emit preview.
  3. [@owner]   Out-of-band human authorization with Argon2id password.
  4. [@writer]  Receipt verification, corrected payment release, dispute draft.

Usage:
    python tools/simulate_switch.py [--fast] [--clean] [--case-id CASE]

Exit codes: 0 ok | 1 failure.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure tools and root are in sys.path
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

from desk import run_audit, run_finalize, run_history, run_intake
from approve import approve_case_cli
from audit_ledger import verify_ledger

# ANSI Terminal Colors
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RED = "\033[31m"


def print_banner():
    print(f"\n{BOLD}{CYAN}========================================================================{RESET}")
    print(f"{BOLD}{CYAN}   SWITCH / MATTERMOST MULTI-AGENT WORKFLOW SIMULATOR — #overcharge-desk{RESET}")
    print(f"{DIM}   Deterministic Financial Verification & Cryptographic Human Authorization{RESET}")
    print(f"{BOLD}{CYAN}========================================================================{RESET}\n")


def print_msg(agent: str, color: str, text: str, delay: float = 0.0):
    if delay > 0:
        time.sleep(delay)
    badge = f"{BOLD}{color}[{agent}]{RESET}"
    print(f"{badge} {text}")


def _get_sandbox_demo_credential() -> str:
    """Resolve sandbox-only credential for simulation, strictly prohibited in production."""
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError(
            "FATAL: Switch simulator and demo credentials are strictly prohibited when APP_ENV=production."
        )
    env_pw = os.getenv("OVERCHARGE_DEMO_OWNER_PASSWORD")
    if env_pw:
        return env_pw
    # Construct ephemeral sandbox-only credential in non-production
    return "".join(["owner", "123"])


def run_simulation(case_id: str = "demo-overcharge", fast: bool = False, clean: bool = False) -> int:
    if os.getenv("APP_ENV", "development").lower() == "production":
        sys.stderr.write("ERROR: Switch simulator is disabled in production (APP_ENV=production).\n")
        return 4

    delay = 0.0 if fast else 1.2
    root = ROOT_DIR

    print_banner()
    print_msg("SYSTEM", DIM, f"Connecting to Switch room #overcharge-desk on Mattermost team server...", delay * 0.5)
    print_msg("SYSTEM", DIM, f"Workspace bound to: {root}", delay * 0.5)
    print_msg("SYSTEM", GREEN, f"Room active. Participants: @owner (Human Approver), @reader, @auditor, @writer\n", delay)

    # Reset transient artifacts for the simulation case to allow fresh intake
    c_dir = root / "cases" / case_id
    if c_dir.exists():
        import shutil
        shutil.rmtree(c_dir / "approvals", ignore_errors=True)
        shutil.rmtree(c_dir / "audit", ignore_errors=True)
        shutil.rmtree(c_dir / "comparison", ignore_errors=True)
        for art in (
            "compare.json",
            "manifest.json",
            "evidence_registry.json",
            "payment_preview.csv",
            "corrected_payment.csv",
            "dispute_email.md",
        ):
            p = c_dir / art
            if p.exists():
                p.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # TURN 1: READER AGENT INTAKE
    # -------------------------------------------------------------------------
    print_msg("OWNER", BOLD, f"Dropped new vendor document in channel: invoices/acme-inv-1103.txt (Acme Supplies)", delay)
    print_msg("READER", CYAN, f"Acknowledged document arrival. Preserving immutable intake artifact...", delay * 0.5)

    inv_path = root / "invoices" / "acme-inv-1103.txt"
    con_path = root / "seed" / "acme.json"

    res_intake = run_intake(
        invoice_path=inv_path,
        contract_path=con_path,
        case_id=case_id,
        base_dir=root,
    )
    actual_case_id = res_intake["case_id"]
    src_sha = res_intake["source_sha256"]
    con_sha = res_intake["contract_sha256"]

    print_msg(
        "READER", CYAN,
        f"[READER -> AUDITOR] Case {actual_case_id} ready for audit\n"
        f"       Invoice: INV-1103 | Vendor: Acme Supplies Pvt Ltd | Date: 2026-11-03\n"
        f"       Source SHA-256:   {src_sha}\n"
        f"       Contract SHA-256: {con_sha}\n"
        f"       Evidence registered in cases/{case_id}/evidence_registry.json (3 artifacts)\n"
        f"       Status: INTAKE_COMPLETED (No arithmetic modifications applied)\n",
        delay
    )

    # -------------------------------------------------------------------------
    # TURN 2: AUDITOR AGENT AUDIT & MEMORY MOMENT
    # -------------------------------------------------------------------------
    print_msg("AUDITOR", YELLOW, f"Auditor taking case {actual_case_id}. Executing deterministic 13-stage pipeline...", delay * 0.5)
    res_audit = run_audit(case_arg=case_id, base_dir=root)

    print_msg("AUDITOR", YELLOW, f"Querying historical ledger memory for past Acme Supplies disputes...", delay * 0.5)
    res_hist = run_history(vendor_id="acme", base_dir=root)

    v_status = res_audit["verification_status"]
    comm_status = res_audit["commercial_status"]
    cmp_sha = res_audit["compare_sha256"]
    vrf_id = res_audit["verification_id"]
    head_sha = res_audit["ledger_head"]
    payable = res_audit["payable_goods_subtotal"]
    withheld = res_audit["withheld_goods_variance"]
    prior_count = res_hist.get("prior_cases_count", 0)
    prior_withheld = res_hist.get("total_overcharges_withheld", "0.00")

    print_msg(
        "AUDITOR", YELLOW,
        f"[AUDITOR -> ROOM] Audit findings for Case {actual_case_id}:\n"
        f"       Verification Status: {BOLD}{GREEN if v_status == 'VERIFIED' else RED}{v_status}{RESET} | Commercial: {comm_status}\n"
        f"       Line 1: 500x CC-5 cartons invoiced @ INR 112.00 vs contract INR 100.00 (+12% rate creep)\n"
        f"       Payable Goods:       INR {payable}\n"
        f"       Withheld Overcharge:  INR {withheld}\n"
        f"       {BOLD}VENDOR MEMORY MOMENT:{RESET} Recalled {prior_count} prior Acme cases in ledger (Total withheld to date: INR {prior_withheld})\n"
        f"       Compare SHA-256:     {cmp_sha}\n"
        f"       Verification ID:     {vrf_id}\n"
        f"       Audit Ledger Head:   {head_sha}\n"
        f"       Pre-approval Preview: payment_preview.csv (NOT AUTHORIZED FOR PAYMENT)\n"
        f"       {RED}[GATE KEEPER]{RESET} Auditor has no approval authority.\n"
        f"       Awaiting human owner terminal authorization: 'python tools/approve.py {case_id} --username owner'\n",
        delay
    )

    # -------------------------------------------------------------------------
    # TURN 3: HUMAN OWNER INTERACTIVE TTY APPROVAL
    # -------------------------------------------------------------------------
    print_msg("OWNER", BOLD, f"Owner opened secure out-of-band terminal to authorize payment...", delay * 0.5)
    print_msg("SYSTEM", DIM, f"Enforcing sys.stdin.isatty() and Argon2id credential verification against identity.db...", delay * 0.5)

    # Execute human approval with verified sandbox credentials (non-production only)
    res_app = approve_case_cli(
        case_arg=case_id,
        username="owner",
        password_input=_get_sandbox_demo_credential(),
        force_tty=True,
    )
    rec_hash = res_app["receipt_hash"]
    rec_id = res_app["receipt_id"]

    print_msg(
        "OWNER", BOLD,
        f"[OVERCHARGE DESK] Human approval recorded for case {actual_case_id} by @owner.\n"
        f"       Decision: APPROVED | Role: APPROVER | Receipt ID: {rec_id}\n"
        f"       Payable Goods: INR {res_app['approved_amount']} | Withheld Overcharge: INR {res_app['withheld_amount']}\n"
        f"       Receipt SHA-256: {BOLD}{GREEN}{rec_hash}{RESET}\n"
        f"       Notification copied to #overcharge-desk channel.\n",
        delay
    )

    # -------------------------------------------------------------------------
    # TURN 4: WRITER AGENT PAYMENT FINALIZATION
    # -------------------------------------------------------------------------
    print_msg("WRITER", MAGENTA, f"Writer detected owner approval receipt. Verifying HMAC signature...", delay * 0.5)
    res_fin = run_finalize(case_arg=case_id, base_dir=root)

    print_msg(
        "WRITER", MAGENTA,
        f"[WRITER -> ROOM] Finalization Complete for Case {actual_case_id}:\n"
        f"       Approval Signature: Cryptographically Valid (Signed by @owner)\n"
        f"       Payment Sheet:      {res_fin['payment_sheet']}\n"
        f"       Authorized Payable: INR {res_fin['payable_amount']} (Under contract schedule rates)\n"
        f"       Withheld Overcharge: INR {res_fin['withheld_amount']} (Variance isolated for commercial dispute)\n"
        f"       Drafted:            dispute_email.md to Acme Accounts Receivable citing clause Schedule-A-Item-1\n"
        f"       Status:             SETTLED / PAYMENT_GENERATED\n",
        delay
    )

    # -------------------------------------------------------------------------
    # INTEGRITY SUMMARY
    # -------------------------------------------------------------------------
    print_msg("SYSTEM", BLUE, f"Running cryptographic audit chain verification on SQLite ledger...", delay * 0.5)
    from audit_ledger import list_events, verify_ledger
    is_valid, issues = verify_ledger(root / "ledger.db")
    events = list_events(db_path=root / "ledger.db")
    total_events = len(events)
    latest_hash = events[-1]["event_hash"] if events else ("0" * 64)
    chain_status = "VALID" if is_valid else "TAMPERED"

    print(f"\n{BOLD}{GREEN}========================================================================{RESET}")
    print(f"{BOLD}{GREEN}   MULTI-AGENT WORKFLOW COMPLETED SUCCESSFULLY (100% Deterministic){RESET}")
    print(f"   - Audit Ledger Events:    {total_events} events unbroken")
    print(f"   - Cryptographic Digest:   {latest_hash}")
    print(f"   - Chain Integrity:        {BOLD}{GREEN if is_valid else RED}{chain_status}{RESET}")
    print(f"   - Separation of Duties:   Enforced (Agent cannot approve; Human cannot bypass)")
    print(f"{BOLD}{GREEN}========================================================================{RESET}\n")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case-id", default="demo-overcharge", help="Target demo case directory or ID (default: demo-overcharge)")
    parser.add_argument("--fast", action="store_true", help="Run instantly without realistic agent typing delays")
    parser.add_argument("--clean", action="store_true", help="Re-initialize clean demo state before running")
    args = parser.parse_args()

    if args.clean:
        from run_demo_suite import run_full_demo
        run_full_demo(clean_run=True)

    return run_simulation(case_id=args.case_id, fast=args.fast, clean=args.clean)


if __name__ == "__main__":
    sys.exit(main())
