"""Payment Instruction service enforcing release boundaries and export controls."""
from __future__ import annotations

import datetime
import secrets
from pathlib import Path
from typing import Optional, Tuple

from common import ToolError, load_json, utc_now_iso
from domain.authorization.policies import AuthorizationService, PERM_PAYMENT_EXPORT
from domain.identity.models import User
from domain.payments.exports import export_payment_instruction_csv, export_payment_instruction_json
from domain.payments.models import PaymentInstruction, PaymentInstructionStatus
from domain.payments.repository import PaymentRepository
from domain.vendors.models import VendorRegistry


class PaymentService:
    def __init__(
        self,
        repository: Optional[PaymentRepository] = None,
        vendor_registry: Optional[VendorRegistry] = None,
        auth_service: Optional[AuthorizationService] = None,
    ):
        self.repo = repository or PaymentRepository()
        self.vendor_registry = vendor_registry or VendorRegistry()
        self.auth_service = auth_service or AuthorizationService()

    def create_instruction_from_case(
        self,
        case_dir: Path | str,
        user: User,
        idempotency_key: Optional[str] = None,
    ) -> PaymentInstruction:
        c_p = Path(case_dir)
        receipt_p = c_p / "approvals" / "approval_receipt.json"
        if not receipt_p.exists():
            raise ToolError("Cannot create payment instruction: Case lacks a verified approval receipt", 4)

        receipt = load_json(receipt_p)
        if receipt.get("decision") != "APPROVED":
            raise ToolError(f"Cannot create payment instruction: Receipt decision is '{receipt.get('decision')}' (must be APPROVED)", 4)

        receipt_id = receipt["receipt_id"]
        case_id = receipt["case_id"]
        approved_amount = receipt["approved_amount"]
        currency = receipt.get("currency", "INR")

        inv_p = c_p / "invoice.json"
        vendor_id = load_json(inv_p).get("vendor_id", "acme") if inv_p.exists() else "acme"

        # Invariant: Single active instruction per approved receipt (double-payment prevention)
        existing = self.repo.get_by_approval_receipt_id(receipt_id)
        if existing:
            return existing

        # Idempotency check: Client-specified or receipt-derived idempotency key
        idem_key = idempotency_key or f"IDEM-{receipt_id}"
        existing_idem = self.repo.get_by_idempotency_key(idem_key)
        if existing_idem:
            return existing_idem

        # Verify vendor destination
        dest = self.vendor_registry.get_destination(vendor_id)
        dest_ref = dest.destination_reference if dest else "UNKNOWN-UNVERIFIED"
        dest_verified = dest.verification_status == "VERIFIED" if dest else False

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        exp_dt = now_dt + datetime.timedelta(days=7)  # 7 day expiry
        now_str = now_dt.isoformat().replace("+00:00", "Z")
        exp_str = exp_dt.isoformat().replace("+00:00", "Z")

        instruction_id = f"PI-{case_id}-{secrets.token_hex(4).upper()}"
        inst = PaymentInstruction(
            instruction_id=instruction_id,
            case_id=case_id,
            approval_receipt_id=receipt_id,
            approved_amount=approved_amount,
            currency=currency,
            vendor_id=vendor_id,
            destination_reference=dest_ref,
            destination_verified=dest_verified,
            idempotency_key=idem_key,
            status=PaymentInstructionStatus.AUTHORIZED,
            created_at=now_str,
            expires_at=exp_str,
        )
        return self.repo.create_instruction(inst)

    def export_instruction(
        self,
        instruction_id: str,
        user: User,
        format_type: str = "csv",
    ) -> Tuple[str, bytes]:
        """Export payment instruction safely. Prohibits duplicate export."""
        self.auth_service.require_permission(user, PERM_PAYMENT_EXPORT)
        inst = self.repo.get_by_id(instruction_id)
        if not inst:
            raise ToolError(f"Payment instruction '{instruction_id}' not found", 2)

        if inst.status == PaymentInstructionStatus.CANCELLED:
            raise ToolError(f"Cannot export CANCELLED payment instruction: {inst.cancellation_reason}", 4)

        if inst.status == PaymentInstructionStatus.EXPORTED:
            raise ToolError(f"Payment instruction '{instruction_id}' has already been exported", 4)

        if not inst.destination_verified:
            raise ToolError("Cannot export payment instruction: Vendor bank destination is unverified", 4)

        # Mark exported
        updated_inst = self.repo.mark_exported(instruction_id, exported_by=user.username)

        if format_type.lower() == "json":
            content = export_payment_instruction_json(updated_inst).encode("utf-8")
            media_type = "application/json"
        else:
            content = export_payment_instruction_csv(updated_inst).encode("utf-8-sig")
            media_type = "text/csv"

        return media_type, content
