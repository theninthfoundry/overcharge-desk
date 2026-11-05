"""Payment Instruction domain models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


class PaymentInstructionStatus:
    AUTHORIZED = "AUTHORIZED"
    EXPORTED = "EXPORTED"
    CANCELLED = "CANCELLED"


@dataclass
class PaymentInstruction:
    instruction_id: str
    case_id: str
    approval_receipt_id: str
    approved_amount: str
    currency: str
    vendor_id: str
    destination_reference: str
    destination_verified: bool
    idempotency_key: str
    status: str
    created_at: str
    expires_at: str
    exported_at: Optional[str] = None
    exported_by: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancellation_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
