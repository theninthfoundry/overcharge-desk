"""Authentication and identity endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from domain.authorization.policies import ROLE_PERMISSIONS
from domain.identity.models import IdentityService, User
from services.api.middleware import get_current_user, get_identity_service
from services.api.schemas import LoginRequest, LoginResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    req: LoginRequest,
    identity_svc: IdentityService = Depends(get_identity_service),
) -> LoginResponse:
    user = identity_svc.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
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
