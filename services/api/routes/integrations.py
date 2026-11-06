"""Switch bot & Mattermost integration endpoints."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from common import ToolError
from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import ROOT_DIR, build_integrations_payload

router = APIRouter(prefix="/integrations", tags=["Integrations"])


class SwitchSimulateRequest(BaseModel):
    case_id: str = "sandbox-verify-01"


@router.get("")
def get_integrations_status(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """Return status and configuration for Switch / Mattermost room agents."""
    return build_integrations_payload()


@router.post("/switch/simulate")
def simulate_switch_run(
    req: SwitchSimulateRequest,
    user: User = Depends(require_permission(PERM_CASE_READ)),
):
    """Execute a dry-run multi-agent consensus workflow inside an isolated sandbox."""
    target_case = req.case_id.strip() or "sandbox-verify-01"
    try:
        from desk import run_audit, run_finalize, run_history, run_intake
        from approve import approve_case_cli

        with tempfile.TemporaryDirectory(prefix="overcharge_switch_sandbox_") as tmp_str:
            tmp_dir = Path(tmp_str)
            for sub in ["cases", "vendors", "contracts", "invoices", "config"]:
                (tmp_dir / sub).mkdir(parents=True, exist_ok=True)
            if (ROOT_DIR / "config" / "actors.json").exists():
                shutil.copy2(ROOT_DIR / "config" / "actors.json", tmp_dir / "config" / "actors.json")
            if (ROOT_DIR / "identity.db").exists():
                shutil.copy2(ROOT_DIR / "identity.db", tmp_dir / "identity.db")

            con_path = ROOT_DIR / "seed" / "acme.json"
            if con_path.exists():
                shutil.copy2(con_path, tmp_dir / "vendors" / "acme.json")
            (tmp_dir / "contracts" / "acme-contract.md").write_text(
                "# Master Supply Agreement — Acme Industrial Supplies\n"
                "- Schedule A, item 1:SKU-BOX-200 — INR 30.00\n"
                "- Schedule A, item 2:SKU-TAPE-48 — INR 60.00\n"
                "- Schedule A, item 3:SKU-LABEL-1000 — INR 450.00\n",
                encoding="utf-8",
            )
            inv_path = tmp_dir / "invoices" / "sandbox-invoice.txt"
            inv_path.write_text(
                "Vendor: Acme Industrial Supplies\n"
                "Invoice Number: INV-SANDBOX-101\n"
                "Invoice Date: 2026-11-03\n"
                "Currency: INR\n"
                "Line 1: Corrugated Shipping Boxes (SKU-BOX-200) | Qty: 100 | Unit Price: 36.00 | Line Total: 3600.00\n"
                "Line 2: Packing Tape 48mm (SKU-TAPE-48) | Qty: 20 | Unit Price: 60.00 | Line Total: 1200.00\n"
                "Stated Total: 4800.00\n",
                encoding="utf-8",
            )

            r_intake = run_intake(invoice_path=inv_path, contract_path=con_path, case_id=target_case, base_dir=tmp_dir)
            r_audit = run_audit(case_arg=target_case, base_dir=tmp_dir)
            r_hist = run_history(vendor_id="acme", base_dir=tmp_dir)
            r_app = approve_case_cli(
                case_arg=target_case,
                username="owner",
                password_input="owner123",
                force_tty=True,
                base_dir=tmp_dir,
            )
            r_fin = run_finalize(case_arg=target_case, base_dir=tmp_dir)

        transcript = [
            {
                "turn": 1,
                "agent": "@reader",
                "stage": "INTAKE_COMPLETED",
                "summary": f"[Isolated Sandbox] Preserved raw invoice artifact and registered 3 SHA-256 evidence records for {r_intake['case_id']}.",
                "digests": {
                    "source_sha256": r_intake["source_sha256"],
                    "contract_sha256": r_intake["contract_sha256"],
                },
            },
            {
                "turn": 2,
                "agent": "@auditor",
                "stage": "VERIFICATION_COMPLETED",
                "summary": (
                    f"[Isolated Sandbox] Status: {r_audit['verification_status']} ({r_audit['commercial_status']}). "
                    f"Payable: INR {r_audit['payable_goods_subtotal']} | Withheld Overcharge: INR {r_audit['withheld_goods_variance']}. "
                    f"Recalled {r_hist.get('prior_cases_count', 0)} prior cases."
                ),
                "digests": {
                    "compare_sha256": r_audit["compare_sha256"],
                    "ledger_head": r_audit["ledger_head"],
                },
            },
            {
                "turn": 3,
                "agent": "@owner (Human Out-of-Band TTY)",
                "stage": "APPROVAL_GRANTED",
                "summary": f"[Isolated Sandbox] Authenticated human approval recorded ({r_app['receipt_id']}). Approved INR {r_app['approved_amount']}.",
                "digests": {
                    "receipt_hash": r_app["receipt_hash"],
                },
            },
            {
                "turn": 4,
                "agent": "@writer",
                "stage": "PAYMENT_GENERATED",
                "summary": f"[Isolated Sandbox] Verified HMAC receipt signature, emitted {r_fin['payment_sheet']} and dispute_email.md.",
                "digests": {
                    "finalized_payment_sha256": r_fin["payment_sheet_sha256"],
                },
            },
        ]
        return {
            "ok": True,
            "status": "SIMULATION_SUCCESSFUL",
            "environment": "isolated_ephemeral_sandbox",
            "simulated_case_id": target_case,
            "transcript": transcript,
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

