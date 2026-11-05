"""Pydantic schemas for FastAPI backend service."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str
    full_name: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: str
    role: str
    is_active: bool
    permissions: List[str]


class CaseSummaryResponse(BaseModel):
    case_id: str
    vendor_id: str
    invoice_number: str
    created_by: str
    created_at: str
    verification_status: str
    commercial_status: str
    approval_status: str
    payment_status: str
    invoiced_total: Optional[str] = None
    payable_total: Optional[str] = None
    withheld_total: Optional[str] = None
    available_artifacts: List[str] = []


class CaseDetailResponse(CaseSummaryResponse):
    directory_path: str
    invoice_file: str
    contract_id: Optional[str] = None
    verification_id: Optional[str] = None
    approval_receipt_id: Optional[str] = None
    reconciliation_issues: List[str] = []
    lines_count: int = 0
    overcharge_detected: bool = False
    audit_package_exported: bool = False


class CreateCaseRequest(BaseModel):
    case_id: str = Field(..., description="Unique case identifier, e.g. OC-20261106-99")
    vendor_id: str = Field("acme", description="Vendor identifier")
    invoice_json: Dict[str, Any] = Field(..., description="Extracted invoice data conforming to schema")


class ReconcileRequest(BaseModel):
    require_approval: bool = False


class ReconcileResponse(BaseModel):
    ok: bool
    pipeline_status: str
    execution_id: str
    case_id: str
    verification_status: str
    commercial_status: str
    settlement_status: str
    source_digest_verified: bool
    comparison_digest: str
    artifact_type: str
    artifact_file: str
    approval_verified: Optional[bool] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., description="'APPROVED' or 'REJECTED'")
    amount: Optional[str] = Field(None, description="Payable amount (must match calculated payable amount)")
    reason: Optional[str] = Field(None, description="Mandatory reason for rejection")


class ApprovalDecisionResponse(BaseModel):
    ok: bool
    decision: str
    receipt_id: str
    receipt_hash: str
    receipt_signature: str
    approved_amount: Optional[str] = None
    withheld_amount: Optional[str] = None
    idempotent: bool = False


class AuditPackageResponse(BaseModel):
    ok: bool
    case_id: str
    target_package_directory: str
    package_integrity_digest: str
    package_verified: bool
    verification_issues: List[str] = []


class CheckpointRequest(BaseModel):
    pass


class CheckpointResponse(BaseModel):
    ok: bool
    checkpoint_id: str
    highest_sequence: int
    head_event_hash: str
    chain_digest: str
    signature: Optional[str] = None


class LedgerVerifyResponse(BaseModel):
    ok: bool
    valid: bool
    total_events: int
    issues_count: int
    issues: List[str] = []


class CreatePaymentInstructionRequest(BaseModel):
    idempotency_key: Optional[str] = Field(None, description="Optional client idempotency key")


class PaymentInstructionResponse(BaseModel):
    instruction_id: str
    case_id: str
    approval_receipt_id: str
    approved_amount: str
    currency: str
    vendor_id: str
    destination_reference: str
    destination_verified: bool
    status: str
    created_at: str
    expires_at: str
    idempotency_key: Optional[str] = None
    exported_at: Optional[str] = None
    exported_by: Optional[str] = None


