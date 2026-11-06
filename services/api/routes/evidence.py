"""Global evidence inventory endpoints."""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends

from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import list_all_evidence_payload

router = APIRouter(prefix="/evidence", tags=["Evidence"])


@router.get("")
def list_global_evidence(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """Return all registered evidentiary artifacts across cases."""
    return list_all_evidence_payload()
