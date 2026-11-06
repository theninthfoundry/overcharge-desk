"""User administration and role assignment endpoints."""
from __future__ import annotations

import re
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from common import ToolError
from domain.authorization.policies import PERM_ADMIN_USERS, PERM_CASE_READ, SystemRole
from domain.identity.models import User
from domain.identity.repository import IdentityRepository
from services.api.middleware import require_permission
from services.api.workspace_service import ROOT_DIR, list_users_and_roles_payload

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/users")
def list_users(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """List system users, roles, and administrative permissions."""
    return list_users_and_roles_payload()


@router.post("/users")
def manage_user(
    body: Dict[str, Any],
    user: User = Depends(require_permission(PERM_ADMIN_USERS)),
):
    """Create, update, or toggle activation status for system operators."""
    action = str(body.get("action", "create")).strip().lower()
    id_repo = IdentityRepository()
    try:
        if action == "toggle_active":
            target_uid = str(body.get("user_id", "")).strip()
            is_act = bool(body.get("is_active", True))
            if target_uid == user.user_id and not is_act:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate your own active administrator account",
                )
            id_repo.set_user_active(target_uid, is_act)
            return {"ok": True, "data": list_users_and_roles_payload()}

        username = re.sub(r"[^a-z0-9_.-]", "", str(body.get("username", "")).strip().lower())
        full_name = str(body.get("full_name", "")).strip()
        email = str(body.get("email", "")).strip().lower()
        role = str(body.get("role", SystemRole.FINANCE_OPERATOR)).strip().upper()
        password = str(body.get("password", "")).strip()

        if not username or not full_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both 'username' and 'full_name' are required",
            )
        if len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )

        new_u = id_repo.create_user(
            username=username,
            full_name=full_name,
            email=email or f"{username}@overcharge.internal",
            role=role,
            password=password,
            is_demo=False,
        )
        return {
            "ok": True,
            "user": {
                "user_id": new_u.user_id,
                "username": new_u.username,
                "full_name": new_u.full_name,
                "email": new_u.email,
                "role": new_u.role,
                "is_active": new_u.is_active,
                "is_demo": new_u.is_demo,
            },
            "data": list_users_and_roles_payload(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

