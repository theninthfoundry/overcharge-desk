"""FastAPI authentication dependencies and security middleware."""
from __future__ import annotations

from typing import Callable, Optional
from fastapi import Depends, Header, HTTPException, status

from domain.authorization.policies import AuthorizationService, ROLE_PERMISSIONS
from domain.identity.models import IdentityService, User

# Shared singletons for backend service
_identity_service = IdentityService()
_auth_service = AuthorizationService(enforce_strict_separation_of_duties=True)


def get_identity_service() -> IdentityService:
    return _identity_service


def get_auth_service() -> AuthorizationService:
    return _auth_service


def get_current_user(
    authorization: Optional[str] = Header(None),
    identity_svc: IdentityService = Depends(get_identity_service),
) -> User:
    """Extract and verify user from Bearer session token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    user = identity_svc.verify_session_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked session token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(permission: str) -> Callable[[User], User]:
    """Dependency factory checking that current user has a specific permission."""

    def _check(
        user: User = Depends(get_current_user),
        auth_svc: AuthorizationService = Depends(get_auth_service),
    ) -> User:
        if not auth_svc.has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: Requires '{permission}'",
            )
        return user

    return _check
