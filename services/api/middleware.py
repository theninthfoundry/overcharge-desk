"""FastAPI authentication dependencies, rate-limiting, and security middleware."""
from __future__ import annotations

import os
import time
from typing import Callable, Dict, Optional, Tuple
from fastapi import Depends, Header, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from domain.authorization.policies import AuthorizationService, ROLE_PERMISSIONS
from domain.identity.models import IdentityService, User
from domain.identity.key_manager import KeyManager

# Singletons
_identity_service = IdentityService()
_auth_service = AuthorizationService(enforce_strict_separation_of_duties=True)
_key_manager = KeyManager(app_env=os.getenv("APP_ENV", "development"))

# Rate limiting and failed login tracking (in-memory tracking for brute-force protection)
_FAILED_LOGINS: Dict[str, Tuple[int, float]] = {}  # username -> (failed_count, lockout_until)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300  # 5 minutes


def record_failed_login(username: str) -> bool:
    """Record a failed login attempt; returns True if user is locked out."""
    now = time.time()
    count, until = _FAILED_LOGINS.get(username.lower(), (0, 0.0))
    if now < until:
        return True
    count += 1
    if count >= MAX_FAILED_ATTEMPTS:
        until = now + LOCKOUT_DURATION_SECONDS
        _FAILED_LOGINS[username.lower()] = (count, until)
        return True
    _FAILED_LOGINS[username.lower()] = (count, 0.0)
    return False


def is_user_locked_out(username: str) -> bool:
    now = time.time()
    count, until = _FAILED_LOGINS.get(username.lower(), (0, 0.0))
    return now < until


def reset_failed_logins(username: str) -> None:
    _FAILED_LOGINS.pop(username.lower(), None)


def get_identity_service() -> IdentityService:
    return _identity_service


def get_auth_service() -> AuthorizationService:
    return _auth_service


def get_key_manager() -> KeyManager:
    return _key_manager


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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard security headers on all HTTP responses.
    
    Headers Set:
    - X-Content-Type-Options: nosniff (MIME-sniffing prevention)
    - X-Frame-Options: DENY (anti-clickjacking)
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy: default-src 'self' (XSS mitigation)
    - X-Request-ID: End-to-end request correlation tracking
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Request correlation ID
        req_id = request.headers.get("X-Request-ID") or os.urandom(8).hex()
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        return response
