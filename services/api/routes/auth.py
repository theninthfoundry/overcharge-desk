"""Authentication and identity endpoints with lockout protection."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from domain.authorization.policies import ROLE_PERMISSIONS
from domain.identity.models import IdentityService, User
from services.api.middleware import (
    get_current_user,
    get_identity_service,
    is_user_locked_out,
    record_failed_login,
    reset_failed_logins,
)
from services.api.schemas import LoginRequest, LoginResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    req: LoginRequest,
    identity_svc: IdentityService = Depends(get_identity_service),
) -> LoginResponse:
    # 1. Lockout check
    if is_user_locked_out(req.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to multiple failed login attempts. Please try again later.",
        )

    # 2. Authenticate
    user = identity_svc.authenticate(req.username, req.password)
    if not user:
        is_locked = record_failed_login(req.username)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked due to multiple failed login attempts. Please try again later.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # 3. Successful authentication: reset failed attempts & issue session token
    reset_failed_logins(req.username)
    token = identity_svc.issue_session_token(user)

    return LoginResponse(
        ok=True,
        access_token=token,
        token_type="bearer",
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
    )


@router.post("/logout")
def logout(
    authorization: str = Header(...),
    identity_svc: IdentityService = Depends(get_identity_service),
):
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        identity_svc.revoke_token(parts[1])
    return {"ok": True, "action": "logged_out"}


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    perms = list(ROLE_PERMISSIONS.get(user.role, set()))
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        permissions=perms,
    )
