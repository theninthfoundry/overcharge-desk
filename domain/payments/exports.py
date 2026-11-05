"""Export formatting for Payment Instructions with CSV injection defenses."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict

from domain.payments.models import PaymentInstruction
from payment_sheet import safe_text


def export_payment_instruction_csv(instruction: PaymentInstruction) -> str:
    """Format an authorized payment instruction as an immutable CSV record."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "# NOTICE: AUTHORIZED PAYMENT INSTRUCTION - REQUIRES CORPORATE TREASURY EXECUTION",
    ])
    writer.writerow([
        "instruction_id",
        "case_id",
        "approval_receipt_id",
        "vendor_id",
        "destination_reference",
        "destination_verified",
        "payable_amount",
        "currency",
        "status",
        "created_at",
        "exported_at",
        "exported_by",
    ])
    writer.writerow([
        safe_text(instruction.instruction_id),
        safe_text(instruction.case_id),
        safe_text(instruction.approval_receipt_id),
        safe_text(instruction.vendor_id),
        safe_text(instruction.destination_reference),
        "TRUE" if instruction.destination_verified else "FALSE",
        safe_text(instruction.approved_amount),
        safe_text(instruction.currency),
        safe_text(instruction.status),
        safe_text(instruction.created_at),
        safe_text(instruction.exported_at or ""),
        safe_text(instruction.exported_by or ""),
    ])
    return buf.getvalue()


def export_payment_instruction_json(instruction: PaymentInstruction) -> str:
    return json.dumps(instruction.to_dict(), indent=2, sort_keys=True)
