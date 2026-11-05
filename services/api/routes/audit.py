"""Audit ledger, verification, and checkpoint endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from common import ToolError, load_json
from domain.authorization.policies import PERM_AUDIT_CHECKPOINT, PERM_AUDIT_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.schemas import CheckpointResponse, LedgerVerifyResponse

# Directly use existing ledger engine
from audit_ledger import DEFAULT_LEDGER_DB, create_checkpoint, list_events, verify_checkpoint, verify_ledger
from auth import get_default_key_path, load_signing_key

router = APIRouter(prefix="/audit", tags=["Audit & Ledger"])


@router.get("/ledger/events")
def get_ledger_events(
    case_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(require_permission(PERM_AUDIT_READ)),
) -> List[Dict[str, Any]]:
    events = list_events(case_id=case_id)
    return events[-limit:]


@router.get("/ledger/verify", response_model=LedgerVerifyResponse)
def run_ledger_verification(
    user: User = Depends(require_permission(PERM_AUDIT_READ)),
) -> LedgerVerifyResponse:
    valid, issues = verify_ledger()
    events = list_events()
    return LedgerVerifyResponse(
        ok=valid,
        valid=valid,
        total_events=len(events),
        issues_count=len(issues),
        issues=issues,
    )


@router.post("/ledger/checkpoint", response_model=CheckpointResponse)
def trigger_checkpoint(
    user: User = Depends(require_permission(PERM_AUDIT_CHECKPOINT)),
) -> CheckpointResponse:
    key_path = get_default_key_path()
    key_bytes = load_signing_key(key_path) if key_path.exists() else b"0123456789abcdef0123456789abcdef"
    try:
        chk = create_checkpoint(key_bytes=key_bytes)
        return CheckpointResponse(
            ok=True,
            checkpoint_id=chk["checkpoint_id"],
            highest_sequence=chk["highest_sequence"],
            head_event_hash=chk["head_event_hash"],
            chain_digest=chk["chain_digest"],
            signature=chk.get("signature"),
        )
    except ToolError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

