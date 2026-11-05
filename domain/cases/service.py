"""Case domain service: Bridges API routes to existing deterministic Python modules."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import ToolError, load_json, utc_now_iso, write_json_atomic
from domain.authorization.policies import (
    AuthorizationService,
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_READ,
    PERM_CASE_RECONCILE,
    PERM_PAYMENT_EXPORT,
)
from domain.cases.models import CaseDetail, CaseSummary
from domain.cases.storage import CaseStorage, StorageSecurityError
from domain.cases.transitions import CaseLifecycleManager, CaseState
from domain.identity.key_manager import KeyManager
from domain.identity.models import User
from domain.payments.models import PaymentInstruction
from domain.payments.service import PaymentService
from state_model import ApprovalStatus, CommercialStatus, PaymentRecommendationStatus, VerificationStatus

# Import directly from existing Python engine in tools/
from approval_gateway import process_approval_decision
from auth import issue_actor_token, load_actors_config
from export_audit_package import export_case_audit, verify_package_integrity
from pipeline import run_pipeline


class CaseService:
    """Orchestrates case management, reconciliation, authorization, and payment release."""

    def __init__(
        self,
        base_dir: Path | str = ".",
        cases_dir: Optional[Path | str] = None,
        auth_service: Optional[AuthorizationService] = None,
        key_file: Optional[Path | str] = None,
    ):
        self.base_dir = Path(base_dir)
        self.cases_dir = Path(cases_dir) if cases_dir else self.base_dir / "cases"
        self.storage = CaseStorage(self.cases_dir)
        self.auth_service = auth_service or AuthorizationService(enforce_strict_separation_of_duties=True)
        self.key_manager = KeyManager(config_dir=self.base_dir / "config")
        self.key_file = Path(key_file) if key_file else self.base_dir / "config" / "signing.key"
        self.actors_cfg_file = self.base_dir / "config" / "actors.json"
        self.payment_service = PaymentService(auth_service=self.auth_service)

    def _get_signing_key(self) -> bytes:
        active_id, key_bytes = self.key_manager.get_active_key()
        return key_bytes

    def list_cases(self, filter_status: Optional[str] = None) -> List[CaseSummary]:
        """Scan case directories and return summaries."""
        summaries: List[CaseSummary] = []
        if not self.cases_dir.exists():
            return summaries

        for entry in sorted(self.cases_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            summary = self._summarize_case_dir(entry)
            if summary:
                if filter_status:
                    fs = filter_status.upper()
                    if fs == "VERIFIED" and summary.verification_status != VerificationStatus.VERIFIED:
                        continue
                    if fs == "REVIEW_REQUIRED" and summary.verification_status != VerificationStatus.REVIEW_REQUIRED:
                        continue
                    if fs == "BLOCKED" and summary.verification_status != VerificationStatus.BLOCKED:
                        continue
                    if fs == "AWAITING_APPROVAL" and (
                        summary.verification_status != VerificationStatus.VERIFIED
                        or summary.approval_status != ApprovalStatus.NOT_REQUESTED
                    ):
                        continue
                summaries.append(summary)
        return summaries

    def get_case(self, case_id: str) -> Optional[CaseDetail]:
        """Get rich case detail by case_id or folder name."""
        c_dir = self._resolve_case_dir(case_id)
        if not c_dir or not c_dir.exists():
            return None
        return self._detail_case_dir(c_dir)

    def create_case(
        self,
        case_id: str,
        vendor_id: str,
        invoice_json_content: Dict[str, Any],
        creator_user: User,
    ) -> CaseDetail:
        """Create a new case directory and initialize invoice."""
        self.auth_service.require_permission(creator_user, PERM_CASE_CREATE)
        clean_id = self.storage.validate_case_id(case_id)
        c_dir = self.storage.get_case_directory(clean_id, create=False)
        if c_dir.exists():
            raise ToolError(f"Case '{clean_id}' already exists", 2)
        c_dir = self.storage.get_case_directory(clean_id, create=True)

        # Write invoice.json
        invoice_json_content["case_id"] = clean_id
        invoice_json_content["vendor_id"] = vendor_id
        inv_path = c_dir / "invoice.json"
        write_json_atomic(inv_path, invoice_json_content)

        # Write initial case.json metadata with version tracking
        now = utc_now_iso()
        case_meta = {
            "case_id": clean_id,
            "vendor_id": vendor_id,
            "created_by": creator_user.username,
            "created_at": now,
            "current_state": CaseState.CREATED,
            "version": 1,
            "state_history": [
                {
                    "from_state": None,
                    "to_state": CaseState.CREATED,
                    "reason": f"Case created by {creator_user.username}",
                    "actor_id": creator_user.username,
                    "timestamp": now,
                }
            ],
        }
        write_json_atomic(c_dir / "case.json", case_meta)
        return self._detail_case_dir(c_dir)

    def reconcile_case(self, case_id: str, operator: User, require_approval: bool = False) -> Dict[str, Any]:
        """Trigger the 13-stage deterministic reconciliation pipeline."""
        self.auth_service.require_permission(operator, PERM_CASE_RECONCILE)
        c_dir = self._resolve_case_dir(case_id)
        if not c_dir or not c_dir.exists():
            raise ToolError(f"Case '{case_id}' not found", 2)

        inv_file = c_dir / "invoice.json"
        if not inv_file.exists():
            raise ToolError(f"Missing invoice.json in case directory {c_dir}", 2)

        inv_data = load_json(inv_file)
        vendor_id = inv_data.get("vendor_id", "acme")
        vendor_file = self.base_dir / "vendors" / f"{vendor_id}.json"
        if not vendor_file.exists():
            vendor_file = self.base_dir / "vendors" / "acme.json"

        # Record running state transition if case.json exists
        case_meta_p = c_dir / "case.json"
        if case_meta_p.exists():
            try:
                CaseLifecycleManager.transition(
                    case_file=case_meta_p,
                    to_state=CaseState.RECONCILIATION_RUNNING,
                    actor_id=operator.username,
                    reason="Reconciliation pipeline started",
                )
            except Exception:
                pass

        # Execute existing deterministic pipeline
        res = run_pipeline(
            invoice_path=inv_file,
            vendor_path=vendor_file,
            out_dir=c_dir,
            base_dir=self.base_dir,
            require_approval=require_approval,
            record_ledger_events=True,
        )

        # Transition lifecycle state based on pipeline verification outcome
        if case_meta_p.exists():
            v_status = res.get("verification_status")
            if v_status == VerificationStatus.VERIFIED:
                next_state = CaseState.AWAITING_APPROVAL if require_approval else CaseState.VERIFIED
            elif v_status == VerificationStatus.BLOCKED:
                next_state = CaseState.BLOCKED
            else:
                next_state = CaseState.REVIEW_REQUIRED

            try:
                CaseLifecycleManager.transition(
                    case_file=case_meta_p,
                    to_state=next_state,
                    actor_id=operator.username,
                    reason=f"Reconciliation completed: {v_status}",
                    evidence_version=res.get("comparison_digest"),
                )
            except Exception:
                pass

        return res

    def approve_or_reject_case(
        self,
        case_id: str,
        approver: User,
        decision: str,
        reason: Optional[str] = None,
        amount: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process human approval or rejection via gateway with policy checks.
        
        Security Invariants:
        - Server Calculation Authority: The payable amount is independently computed from compare.json.
        - Separation of Duties: Approver username cannot match case creator username.
        - Positive Allowlist: Only cases in status VERIFIED may be approved.
        """
        c_dir = self._resolve_case_dir(case_id)
        if not c_dir or not c_dir.exists():
            raise ToolError(f"Case '{case_id}' not found", 2)

        # 1. Fetch case creator
        case_creator = "system"
        case_meta_p = c_dir / "case.json"
        if case_meta_p.exists():
            case_creator = load_json(case_meta_p).get("created_by") or case_creator

        # 2. Fetch verification status and calculate payable amount independently
        comp_file = c_dir / "compare.json"
        v_status = None
        calculated_payable: Optional[str] = None
        if comp_file.exists():
            comp_data = load_json(comp_file)
            v_status = comp_data.get("verification_status")
            totals = comp_data.get("totals", {})
            calculated_payable = totals.get("matched_per_contract")

        # 3. Server-side policy evaluation (Separation of duties & Allowlist)
        if decision == "APPROVED":
            eligible, err_msg = self.auth_service.evaluate_approval_policy(
                approver=approver,
                case_creator_username=case_creator,
                verification_status=v_status,
            )
            if not eligible:
                raise ToolError(f"Authorization denied: {err_msg}", 4)

            if not calculated_payable:
                raise ToolError("Cannot approve case without calculated payable amount in comparison", 4)

            # Invariant: Caller cannot dictate amount. If supplied, must exactly match server calculated amount.
            if amount is not None:
                if Decimal(str(amount)) != Decimal(str(calculated_payable)):
                    raise ToolError(
                        f"Supplied amount '{amount}' does not match server-calculated payable amount '{calculated_payable}'",
                        4,
                    )
            # Authoritative amount comes strictly from server calculation
            amount = calculated_payable

        # 4. Issue temporary actor token for gateway execution
        key_bytes = self._get_signing_key()
        actors_cfg = load_actors_config(self.actors_cfg_file) if self.actors_cfg_file.exists() else None
        token = issue_actor_token(approver.username, key_bytes, config=actors_cfg)

        # 5. Call existing authorization gateway
        res = process_approval_decision(
            case_dir=c_dir,
            actor_token=token,
            decision=decision,
            amount=amount,
            reason=reason,
            key_file=self.key_file,
            config_file=self.actors_cfg_file if self.actors_cfg_file.exists() else None,
        )

        # 6. Record state transition in lifecycle manager
        if case_meta_p.exists():
            target_state = CaseState.APPROVED if decision == "APPROVED" else CaseState.REJECTED
            try:
                CaseLifecycleManager.transition(
                    case_file=case_meta_p,
                    to_state=target_state,
                    actor_id=approver.username,
                    reason=reason or f"Case human decision: {decision}",
                    event_id=res.get("receipt_id"),
                )
            except Exception:
                pass

        return res

    def create_payment_instruction(
        self,
        case_id: str,
        operator: User,
        idempotency_key: Optional[str] = None,
    ) -> PaymentInstruction:
        """Generate an authorized payment instruction for an approved case."""
        c_dir = self._resolve_case_dir(case_id)
        if not c_dir or not c_dir.exists():
            raise ToolError(f"Case '{case_id}' not found", 2)

        inst = self.payment_service.create_instruction_from_case(
            case_dir=c_dir,
            user=operator,
            idempotency_key=idempotency_key,
        )

        case_meta_p = c_dir / "case.json"
        if case_meta_p.exists():
            try:
                CaseLifecycleManager.transition(
                    case_file=case_meta_p,
                    to_state=CaseState.PAYMENT_INSTRUCTION_READY,
                    actor_id=operator.username,
                    reason=f"Payment instruction created: {inst.instruction_id}",
                    event_id=inst.instruction_id,
                )
            except Exception:
                pass

        return inst

    def export_payment_instruction(
        self,
        case_id: str,
        instruction_id: str,
        operator: User,
        format_type: str = "csv",
    ) -> Tuple[str, bytes]:
        """Export payment instruction safely in CSV or JSON format."""
        c_dir = self._resolve_case_dir(case_id)
        media_type, content = self.payment_service.export_instruction(
            instruction_id=instruction_id,
            user=operator,
            format_type=format_type,
        )

        if c_dir and c_dir.exists():
            case_meta_p = c_dir / "case.json"
            if case_meta_p.exists():
                try:
                    CaseLifecycleManager.transition(
                        case_file=case_meta_p,
                        to_state=CaseState.EXPORTED,
                        actor_id=operator.username,
                        reason=f"Payment instruction exported as {format_type.upper()}",
                        event_id=instruction_id,
                    )
                except Exception:
                    pass

        return media_type, content

    def export_audit_package(self, case_id: str) -> Dict[str, Any]:
        """Export and verify standalone case audit package."""
        c_dir = self._resolve_case_dir(case_id)
        if not c_dir or not c_dir.exists():
            raise ToolError(f"Case '{case_id}' not found", 2)

        export_res = export_case_audit(case_dir=c_dir, key_file=self.key_file)
        target_dir = export_res["target_package_directory"]
        valid, issues = verify_package_integrity(package_dir=target_dir, key_file=self.key_file)
        export_res["package_verified"] = valid
        export_res["verification_issues"] = issues
        return export_res

    def get_artifact_path(self, case_id: str, artifact_name: str) -> Optional[Path]:
        """Safely resolve an artifact path within a case directory using storage boundaries."""
        try:
            return self.storage.resolve_artifact_path(case_id, artifact_name)
        except (StorageSecurityError, ToolError):
            return None

    def _resolve_case_dir(self, case_id: str) -> Optional[Path]:
        """Resolve case folder by exact name or matching case.json case_id."""
        try:
            clean_id = self.storage.validate_case_id(case_id)
            exact = self.cases_dir / clean_id
            if exact.exists() and exact.is_dir():
                return exact
        except Exception:
            pass

        # Search inside subdirectories
        if self.cases_dir.exists():
            for entry in self.cases_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    meta_p = entry / "case.json"
                    if meta_p.exists():
                        try:
                            if load_json(meta_p).get("case_id") == case_id:
                                return entry
                        except Exception:
                            pass
                    inv_p = entry / "invoice.json"
                    if inv_p.exists():
                        try:
                            if load_json(inv_p).get("case_id") == case_id:
                                return entry
                        except Exception:
                            pass
        return None

    def _summarize_case_dir(self, c_dir: Path) -> Optional[CaseSummary]:
        """Extract lightweight summary from case directory."""
        inv_file = c_dir / "invoice.json"
        if not inv_file.exists():
            return None

        inv_data = load_json(inv_file)
        case_id = inv_data.get("case_id") or c_dir.name
        vendor_id = inv_data.get("vendor_id", "acme")
        invoice_number = inv_data.get("invoice_number", "UNKNOWN")

        # Defaults
        created_by = "system"
        created_at = inv_data.get("extracted_at") or utc_now_iso()
        case_meta_p = c_dir / "case.json"
        if case_meta_p.exists():
            meta = load_json(case_meta_p)
            created_by = meta.get("created_by") or created_by
            created_at = meta.get("created_at") or created_at

        # Verification & Commercial state
        v_status = VerificationStatus.NOT_VERIFIED
        comm_status = CommercialStatus.UNDETERMINED
        invoiced_total = str(inv_data.get("stated_total")) if inv_data.get("stated_total") is not None else None
        payable_total = None
        withheld_total = None

        comp_p = c_dir / "compare.json"
        if comp_p.exists():
            comp_data = load_json(comp_p)
            v_status = comp_data.get("verification_status", v_status)
            comm_status = comp_data.get("commercial_status", comm_status)
            totals = comp_data.get("totals", {})
            invoiced_total = totals.get("goods_subtotal_invoiced", invoiced_total)
            payable_total = totals.get("matched_per_contract")
            withheld_total = totals.get("variance_on_matched_lines")

        # Approval state
        app_status = ApprovalStatus.NOT_REQUESTED
        receipt_p = c_dir / "approvals" / "approval_receipt.json"
        if receipt_p.exists():
            try:
                receipt = load_json(receipt_p)
                app_status = receipt.get("decision", ApprovalStatus.APPROVED)
            except Exception:
                app_status = ApprovalStatus.PENDING

        # Payment recommendation state
        if (c_dir / "corrected_payment.csv").exists():
            pay_status = PaymentRecommendationStatus.GENERATED
        elif (c_dir / "payment_preview.csv").exists():
            pay_status = PaymentRecommendationStatus.ELIGIBLE
        elif (c_dir / "blocked_review_report.csv").exists():
            pay_status = PaymentRecommendationStatus.BLOCKED
        else:
            pay_status = PaymentRecommendationStatus.NOT_ELIGIBLE

        # Available artifacts
        artifacts = []
        for name in [
            "payment_preview.csv",
            "corrected_payment.csv",
            "partial_review.csv",
            "blocked_review_report.csv",
            "compare.json",
            "manifest.json",
            "approval_receipt.json",
        ]:
            if (c_dir / name).exists() or (c_dir / "approvals" / name).exists():
                artifacts.append(name)

        return CaseSummary(
            case_id=case_id,
            vendor_id=vendor_id,
            invoice_number=invoice_number,
            created_by=created_by,
            created_at=created_at,
            verification_status=v_status,
            commercial_status=comm_status,
            approval_status=app_status,
            payment_status=pay_status,
            invoiced_total=invoiced_total,
            payable_total=payable_total,
            withheld_total=withheld_total,
            available_artifacts=artifacts,
        )

    def _detail_case_dir(self, c_dir: Path) -> CaseDetail:
        """Extract detailed information for a case."""
        summary = self._summarize_case_dir(c_dir)
        inv_file = c_dir / "invoice.json"
        inv_data = load_json(inv_file) if inv_file.exists() else {}

        contract_id = None
        verification_id = None
        receipt_id = None
        issues = []
        lines_count = len(inv_data.get("lines", []))
        overcharge_detected = False

        comp_p = c_dir / "compare.json"
        if comp_p.exists():
            comp_data = load_json(comp_p)
            contract_id = comp_data.get("contract_id")
            issues = comp_data.get("blocking_issues", [])
            lines_count = len(comp_data.get("lines", []))
            totals = comp_data.get("totals", {})
            try:
                from decimal import Decimal
                overcharge_detected = Decimal(totals.get("variance_on_matched_lines", "0")) > Decimal("0.00")
            except Exception:
                pass

        ver_p = c_dir / "audit" / "verification.json"
        if ver_p.exists():
            verification_id = load_json(ver_p).get("verification_id")

        receipt_p = c_dir / "approvals" / "approval_receipt.json"
        if receipt_p.exists():
            receipt_id = load_json(receipt_p).get("receipt_id")

        case_id = summary.case_id if summary else c_dir.name
        pkg_p = Path("case_audit") / case_id / "audit_integrity_report.json"
        audit_pkg_exported = pkg_p.exists()

        return CaseDetail(
            case_id=case_id,
            vendor_id=summary.vendor_id if summary else "acme",
            invoice_number=summary.invoice_number if summary else "UNKNOWN",
            created_by=summary.created_by if summary else "system",
            created_at=summary.created_at if summary else utc_now_iso(),
            verification_status=summary.verification_status if summary else VerificationStatus.NOT_VERIFIED,
            commercial_status=summary.commercial_status if summary else CommercialStatus.UNDETERMINED,
            approval_status=summary.approval_status if summary else ApprovalStatus.NOT_REQUESTED,
            payment_status=summary.payment_status if summary else PaymentRecommendationStatus.NOT_ELIGIBLE,
            invoiced_total=summary.invoiced_total if summary else None,
            payable_total=summary.payable_total if summary else None,
            withheld_total=summary.withheld_total if summary else None,
            available_artifacts=summary.available_artifacts if summary else [],
            directory_path=str(c_dir),
            invoice_file=str(inv_file),
            contract_id=contract_id,
            verification_id=verification_id,
            approval_receipt_id=receipt_id,
            reconciliation_issues=issues,
            lines_count=lines_count,
            overcharge_detected=overcharge_detected,
            audit_package_exported=audit_pkg_exported,
        )
