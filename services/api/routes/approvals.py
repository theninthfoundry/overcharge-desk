"""Approval governance and cryptographic receipt queue endpoints."""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends

from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import build_approvals_payload

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("")
def list_approvals_queue(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """Return pending review cases, approved receipts, and rejected dispositions."""
    return build_approvals_payload(user)

