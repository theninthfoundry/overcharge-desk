"""Case domain models and data transfer objects."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CaseSummary:
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
    available_artifacts: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CaseDetail(CaseSummary):
    directory_path: str = ""
    invoice_file: str = ""
    contract_id: Optional[str] = None
    verification_id: Optional[str] = None
    approval_receipt_id: Optional[str] = None
    reconciliation_issues: Optional[List[str]] = None
    lines_count: int = 0
    overcharge_detected: bool = False
    audit_package_exported: bool = False

