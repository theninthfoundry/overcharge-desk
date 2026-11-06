"""Payment authorization and export instruction endpoints."""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends

from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import build_payments_payload

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("")
def list_payments(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """Return verified payment authorizations and export instructions."""
    return build_payments_payload()

