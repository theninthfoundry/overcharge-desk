"""Password hashing and verification using Argon2id."""
from __future__ import annotations

import hmac
import os
import secrets
from typing import Optional

try:
    import argon2
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    _HAS_ARGON2 = True
    _PH = argon2.PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MB
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )
except ImportError:  # pragma: no cover
    _HAS_ARGON2 = False
    _PH = None

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024


class PasswordSecurityError(ValueError):
    """Raised when password validation or hashing fails."""
    pass


def validate_password_strength(password: str) -> None:
    """Validate password input bounds."""
    if not isinstance(password, str):
        raise PasswordSecurityError("Password must be a string")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordSecurityError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordSecurityError(f"Password exceeds maximum length of {MAX_PASSWORD_LENGTH} characters")


def hash_password(password: str) -> str:
    """Hash password using Argon2id (or PBKDF2-HMAC-SHA256 fallback if argon2 unavailable)."""
    validate_password_strength(password)
    if _HAS_ARGON2 and _PH is not None:
        return _PH.hash(password)

    # Secure fallback to PBKDF2-HMAC-SHA256 (600,000 iterations)
    import hashlib
    salt = secrets.token_bytes(16)
    iterations = 600000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_hex = salt.hex()
    hash_hex = derived.hex()
    return f"$pbkdf2-sha256$i={iterations}${salt_hex}${hash_hex}"


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification of password against hash."""
    if not password or not password_hash or not isinstance(password_hash, str):
        return False

    if password_hash.startswith("$argon2"):
        if not _HAS_ARGON2 or _PH is None:
            return False
        try:
            return _PH.verify(password_hash, password)
        except (VerificationError, VerifyMismatchError, InvalidHashError):
            return False

    if password_hash.startswith("$pbkdf2-sha256$"):
        import hashlib
        try:
            parts = password_hash.split("$")
            # format: '', 'pbkdf2-sha256', 'i=600000', salt_hex, hash_hex
            if len(parts) != 5:
                return False
            iter_part = parts[2]
            iterations = int(iter_part.split("=")[1])
            salt = bytes.fromhex(parts[3])
            expected_hash = parts[4]
            derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()
            return hmac.compare_digest(derived, expected_hash)
        except Exception:
            return False

    # Refuse plain unsalted legacy hashes
    return False


def needs_rehash(password_hash: str) -> bool:
    """Check if hash parameters require an upgrade."""
    if not password_hash or not isinstance(password_hash, str):
        return True
    if password_hash.startswith("$argon2"):
        if _HAS_ARGON2 and _PH is not None:
            return _PH.check_needs_rehash(password_hash)
        return False
    # Any non-argon2 hash should be rehashed to Argon2id
    return True
