"""Case management, reconciliation, approval, and artifact endpoints."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from common import ToolError, load_json
from domain.authorization.policies import (
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_READ,
    PERM_CASE_RECONCILE,
    PERM_PAYMENT_EXPORT,
)
from domain.cases.service import CaseService
from domain.identity.models import User
from evidence import register_evidence, verify_evidence
from audit_ledger import DEFAULT_LEDGER_DB, record_event
from services.api.middleware import get_current_user, require_permission
from services.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    AuditPackageResponse,
    CaseDetailResponse,
    CaseSummaryResponse,
    CreateCaseRequest,
    CreatePaymentInstructionRequest,
    PaymentInstructionResponse,
    ReconcileRequest,
    ReconcileResponse,
)
from services.api.workspace_service import ROOT_DIR, build_case_workspace

router = APIRouter(prefix="/cases", tags=["Cases"])

# Shared singleton case service
_case_service = CaseService()


def get_case_service() -> CaseService:
    return _case_service


@router.get("", response_model=List[CaseSummaryResponse])
def list_cases(
    status_filter: Optional[str] = Query(None, alias="status"),
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
) -> List[CaseSummaryResponse]:
    summaries = case_svc.list_cases(filter_status=status_filter)
    return [CaseSummaryResponse(**s.to_dict()) for s in summaries]


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(
    case_id: str,
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
) -> CaseDetailResponse:
    detail = case_svc.get_case(case_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found",
        )
    return CaseDetailResponse(**detail.to_dict())


@router.post("", response_model=CaseDetailResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    req: CreateCaseRequest,
    user: User = Depends(require_permission(PERM_CASE_CREATE)),
    case_svc: CaseService = Depends(get_case_service),
) -> CaseDetailResponse:
    try:
        detail = case_svc.create_case(
            case_id=req.case_id,
            vendor_id=req.vendor_id,
            invoice_json_content=req.invoice_json,
            creator_user=user,
        )
        return CaseDetailResponse(**detail.to_dict())
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{case_id}/reconcile", response_model=ReconcileResponse)
def reconcile_case(
    case_id: str,
    req: ReconcileRequest,
    user: User = Depends(require_permission(PERM_CASE_RECONCILE)),
    case_svc: CaseService = Depends(get_case_service),
) -> ReconcileResponse:
    try:
        res = case_svc.reconcile_case(
            case_id=case_id,
            operator=user,
            require_approval=req.require_approval,
        )
        return ReconcileResponse(
            ok=res["ok"],
            pipeline_status=res["pipeline_status"],
            execution_id=res["execution_id"],
            case_id=res["case_id"],
            verification_status=res["verification_status"],
            commercial_status=res["commercial_status"],
            settlement_status=res["settlement_status"],
            source_digest_verified=res["source_digest_verified"],
            comparison_digest=res["comparison_digest"],
            artifact_type=res["artifact_type"],
            artifact_file=res["artifact_file"],
            approval_verified=res.get("approval_verified"),
        )
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{case_id}/approve", response_model=ApprovalDecisionResponse)
def approve_or_reject_case(
    case_id: str,
    req: ApprovalDecisionRequest,
    user: User = Depends(require_permission(PERM_CASE_APPROVE)),
    case_svc: CaseService = Depends(get_case_service),
) -> ApprovalDecisionResponse:
    try:
        res = case_svc.approve_or_reject_case(
            case_id=case_id,
            approver=user,
            decision=req.decision,
            reason=req.reason,
            amount=req.amount,
        )
        return ApprovalDecisionResponse(
            ok=res["ok"],
            decision=res["decision"],
            receipt_id=res["receipt_id"],
            receipt_hash=res["receipt_hash"],
            receipt_signature=res["receipt_signature"],
            approved_amount=res.get("approved_amount"),
            withheld_amount=res.get("withheld_amount"),
            idempotent=res.get("idempotent", False),
        )
    except ToolError as exc:
        code = status.HTTP_403_FORBIDDEN if exc.code == 4 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/{case_id}/export-audit", response_model=AuditPackageResponse)
def export_audit_package(
    case_id: str,
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
) -> AuditPackageResponse:
    try:
        res = case_svc.export_audit_package(case_id)
        return AuditPackageResponse(
            ok=True,
            case_id=res["case_id"],
            target_package_directory=res["target_package_directory"],
            package_integrity_digest=res["package_integrity_digest"],
            package_verified=res["package_verified"],
            verification_issues=res["verification_issues"],
        )
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{case_id}/artifacts/{artifact_name}")
def download_artifact(
    case_id: str,
    artifact_name: str,
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
):
    # Only Payment Operators or Admins can download finalized corrected_payment.csv
    if artifact_name == "corrected_payment.csv":
        from domain.authorization.policies import PERM_PAYMENT_EXPORT
        if not _case_service.auth_service.has_permission(user, PERM_PAYMENT_EXPORT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Downloading authorized payment sheets requires 'payment:export' permission",
            )

    art_p = case_svc.get_artifact_path(case_id, artifact_name)
    if not art_p or not art_p.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_name}' not available for case '{case_id}'",
        )

    media_type = "text/csv" if artifact_name.endswith(".csv") else "application/json"
    return FileResponse(path=str(art_p), filename=artifact_name, media_type=media_type)


@router.post("/{case_id}/payment-instruction", response_model=PaymentInstructionResponse)
def create_payment_instruction(
    case_id: str,
    req: CreatePaymentInstructionRequest,
    user: User = Depends(require_permission(PERM_PAYMENT_EXPORT)),
    case_svc: CaseService = Depends(get_case_service),
) -> PaymentInstructionResponse:
    try:
        inst = case_svc.create_payment_instruction(
            case_id=case_id,
            operator=user,
            idempotency_key=req.idempotency_key,
        )
        return PaymentInstructionResponse(
            instruction_id=inst.instruction_id,
            case_id=inst.case_id,
            approval_receipt_id=inst.approval_receipt_id,
            approved_amount=inst.approved_amount,
            currency=inst.currency,
            vendor_id=inst.vendor_id,
            destination_reference=inst.destination_reference,
            destination_verified=inst.destination_verified,
            status=inst.status,
            created_at=inst.created_at,
            expires_at=inst.expires_at,
            idempotency_key=inst.idempotency_key,
            exported_at=inst.exported_at,
            exported_by=inst.exported_by,
        )
    except ToolError as exc:
        code = status.HTTP_403_FORBIDDEN if exc.code == 4 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc))


@router.get("/{case_id}/payment-instruction/{instruction_id}/export")
def export_payment_instruction(
    case_id: str,
    instruction_id: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    user: User = Depends(require_permission(PERM_PAYMENT_EXPORT)),
    case_svc: CaseService = Depends(get_case_service),
):
    try:
        media_type, content = case_svc.export_payment_instruction(
            case_id=case_id,
            instruction_id=instruction_id,
            operator=user,
            format_type=format,
        )
        ext = "json" if format == "json" else "csv"
        filename = f"{instruction_id}.{ext}"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ToolError as exc:
        code = status.HTTP_403_FORBIDDEN if exc.code == 4 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc))


@router.get("/{case_id}/workspace")
def get_case_workspace(
    case_id: str,
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
) -> Dict[str, Any]:
    """Retrieve full unified workspace context for financial investigation."""
    ws = build_case_workspace(case_id, user)
    if not ws:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case '{case_id}' not found")
    return ws


@router.post("/{case_id}/evidence/verify")
def verify_case_evidence(
    case_id: str,
    user: User = Depends(require_permission(PERM_CASE_READ)),
    case_svc: CaseService = Depends(get_case_service),
) -> Dict[str, Any]:
    """Verify cryptographic hashes and signatures of all registered case evidence on disk."""
    c_dir = case_svc._resolve_case_dir(case_id)
    if not c_dir or not c_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case '{case_id}' not found")
    try:
        res = verify_evidence(c_dir, base_dir=ROOT_DIR)
        res["verified"] = bool(res.get("valid", res.get("ok", False)))
        return res
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{case_id}/evidence", status_code=status.HTTP_201_CREATED)
def add_case_evidence(
    case_id: str,
    body: Dict[str, Any],
    user: User = Depends(require_permission(PERM_CASE_CREATE)),
    case_svc: CaseService = Depends(get_case_service),
) -> Dict[str, Any]:
    """Register supporting evidence artifact into immutable case registry."""
    c_dir = case_svc._resolve_case_dir(case_id)
    if not c_dir or not c_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case '{case_id}' not found")
    filename = str(body.get("filename", "")).strip()
    artifact_type = str(body.get("artifact_type", "SUPPORTING_DOCUMENT")).strip().upper()
    content_text = str(body.get("content", ""))
    if not filename or not content_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'filename' and 'content' are required to register evidence",
        )
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    att_dir = c_dir / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    target_file = att_dir / safe_name
    target_file.write_text(content_text, encoding="utf-8")

    canonical_case_id = case_id
    if (c_dir / "invoice.json").exists():
        try:
            canonical_case_id = load_json(c_dir / "invoice.json").get("case_id") or case_id
        except Exception:
            pass

    try:
        rec = register_evidence(
            case_dir=c_dir,
            file_path=target_file,
            evidence_type="review_artifact",
            case_id=canonical_case_id,
            base_dir=ROOT_DIR,
            description=artifact_type,
        )
        norm_rec = {
            **rec,
            "artifact_type": artifact_type,
            "source_locator": rec["stored_path"],
            "sha256": rec["content_hash"],
            "recorded_sha256": rec["content_hash"],
            "size_bytes": rec["byte_size"],
            "registered_at": rec["received_at"],
        }
        try:
            record_event(
                case_id=canonical_case_id,
                event_type="EVIDENCE_REGISTERED",
                actor_id=user.username,
                payload={
                    "evidence_id": rec["evidence_id"],
                    "artifact_type": artifact_type,
                    "source_locator": rec["stored_path"],
                    "sha256": rec["content_hash"],
                },
                evidence_refs=[rec["evidence_id"]],
                db_path=ROOT_DIR / DEFAULT_LEDGER_DB,
            )
        except Exception:
            pass
        return {"ok": True, "evidence": norm_rec}
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


