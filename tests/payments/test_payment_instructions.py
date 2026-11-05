from __future__ import annotations

import pytest
from common import ToolError, write_json_atomic
from domain.authorization.policies import AuthorizationService
from domain.identity.models import SystemRole, User
from domain.payments.models import PaymentInstructionStatus
from domain.payments.repository import PaymentRepository
from domain.payments.service import PaymentService
from domain.vendors.models import VendorDestination, VendorRegistry


@pytest.fixture
def payment_service(tmp_path):
    repo = PaymentRepository(db_path=tmp_path / "payments.db")
    v_reg = VendorRegistry({
        "acme": VendorDestination(
            vendor_id="acme",
            destination_reference="HDFC-****4102",
            verification_status="VERIFIED",
            verification_method="BANK_CONFIRMATION",
            verified_by="treasury",
            verified_at="2026-10-01T00:00:00Z",
            evidence_digest="0" * 64,
        ),
        "unverified_vendor": VendorDestination(
            vendor_id="unverified_vendor",
            destination_reference="UNKNOWN",
            verification_status="UNVERIFIED",
            verification_method="NONE",
            verified_by="",
            verified_at="",
            evidence_digest="0" * 64,
        ),
    })
    auth = AuthorizationService()
    return PaymentService(repository=repo, vendor_registry=v_reg, auth_service=auth)


def test_payment_instruction_creation_from_approved_case(payment_service, tmp_path):
    case_dir = tmp_path / "case_approved"
    approvals_dir = case_dir / "approvals"
    approvals_dir.mkdir(parents=True)
    write_json_atomic(case_dir / "invoice.json", {"vendor_id": "acme"})
    write_json_atomic(
        approvals_dir / "approval_receipt.json",
        {
            "receipt_id": "AR-TEST-001",
            "case_id": "OC-TEST-01",
            "decision": "APPROVED",
            "approved_amount": "60000.00",
            "currency": "INR",
        },
    )

    user = User("U1", "pay_op", "Payment Op", "p@test.local", SystemRole.PAYMENT_OPERATOR)
    inst = payment_service.create_instruction_from_case(case_dir, user)
    assert inst.instruction_id.startswith("PI-OC-TEST-01-")
    assert inst.approved_amount == "60000.00"
    assert inst.destination_verified is True
    assert inst.status == PaymentInstructionStatus.AUTHORIZED


def test_payment_instruction_refused_for_rejected_case(payment_service, tmp_path):
    case_dir = tmp_path / "case_rejected"
    approvals_dir = case_dir / "approvals"
    approvals_dir.mkdir(parents=True)
    write_json_atomic(
        approvals_dir / "approval_receipt.json",
        {
            "receipt_id": "AR-TEST-002",
            "case_id": "OC-TEST-02",
            "decision": "REJECTED",
            "approved_amount": None,
        },
    )

    user = User("U1", "pay_op", "Payment Op", "p@test.local", SystemRole.PAYMENT_OPERATOR)
    with pytest.raises(ToolError, match="Receipt decision is 'REJECTED'"):
        payment_service.create_instruction_from_case(case_dir, user)


def test_payment_export_and_permission_enforcement(payment_service, tmp_path):
    case_dir = tmp_path / "case_approved"
    approvals_dir = case_dir / "approvals"
    approvals_dir.mkdir(parents=True)
    write_json_atomic(case_dir / "invoice.json", {"vendor_id": "acme"})
    write_json_atomic(
        approvals_dir / "approval_receipt.json",
        {
            "receipt_id": "AR-TEST-003",
            "case_id": "OC-TEST-03",
            "decision": "APPROVED",
            "approved_amount": "30000.00",
        },
    )

    pay_op = User("U1", "pay_op", "Payment Op", "p@test.local", SystemRole.PAYMENT_OPERATOR)
    inst = payment_service.create_instruction_from_case(case_dir, pay_op)

    # Reviewer cannot export payment instructions
    reviewer = User("U2", "rev", "Reviewer", "r@test.local", SystemRole.REVIEWER)
    with pytest.raises(ToolError, match="lacks permission 'payment:export'"):
        payment_service.export_instruction(inst.instruction_id, reviewer)

    # Payment operator can export
    m_type, csv_bytes = payment_service.export_instruction(inst.instruction_id, pay_op)
    assert m_type == "text/csv"
    assert b"AUTHORIZED PAYMENT INSTRUCTION" in csv_bytes
    assert b"30000.00" in csv_bytes


def test_export_blocked_if_vendor_destination_unverified(payment_service, tmp_path):
    case_dir = tmp_path / "case_unverified"
    approvals_dir = case_dir / "approvals"
    approvals_dir.mkdir(parents=True)
    write_json_atomic(case_dir / "invoice.json", {"vendor_id": "unverified_vendor"})
    write_json_atomic(
        approvals_dir / "approval_receipt.json",
        {
            "receipt_id": "AR-TEST-004",
            "case_id": "OC-TEST-04",
            "decision": "APPROVED",
            "approved_amount": "50000.00",
        },
    )

    pay_op = User("U1", "pay_op", "Payment Op", "p@test.local", SystemRole.PAYMENT_OPERATOR)
    inst = payment_service.create_instruction_from_case(case_dir, pay_op)
    assert inst.destination_verified is False

    with pytest.raises(ToolError, match="Vendor bank destination is unverified"):
        payment_service.export_instruction(inst.instruction_id, pay_op)


def test_csv_formula_injection_escaping():
    """Verify formula injection characters are properly sanitized in exports."""
    from domain.payments.exports import export_payment_instruction_csv
    from domain.payments.models import PaymentInstruction
    inst = PaymentInstruction(
        instruction_id="PI-TEST",
        case_id="=cmd|' /C calc'!A0",  # malicious case_id
        approval_receipt_id="+cmd|...",
        approved_amount="100.00",
        currency="INR",
        vendor_id="@vendor",
        destination_reference="-BANK",
        destination_verified=True,
        idempotency_key="IDEM",
        status="AUTHORIZED",
        created_at="2026-11-05T00:00:00Z",
        expires_at="2026-11-12T00:00:00Z",
    )
    csv_out = export_payment_instruction_csv(inst)
    # Each malicious prefix must be prepended with a single quote
    assert "'=cmd" in csv_out
    assert "'+cmd" in csv_out
    assert "'@vendor" in csv_out
    assert "'-BANK" in csv_out


