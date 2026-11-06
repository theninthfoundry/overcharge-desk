"""Overview metrics and financial status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import build_overview_metrics

router = APIRouter(prefix="/overview", tags=["Overview"])


@router.get("/metrics")
def get_overview_metrics(
    user: User = Depends(require_permission(PERM_CASE_READ)),
):
    """Retrieve operational financial control overview metrics."""
    return build_overview_metrics(user)

