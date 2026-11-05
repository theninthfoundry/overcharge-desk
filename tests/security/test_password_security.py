from __future__ import annotations

import pytest
from domain.identity.passwords import (
    PasswordSecurityError,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)


def test_password_hash_and_verify_success():
    pw = "SuperSecurePassword123!"
    h = hash_password(pw)
    assert h.startswith("$argon2") or h.startswith("$pbkdf2-sha256$")
    assert verify_password(pw, h) is True
    assert verify_password("WrongPassword!", h) is False


def test_password_salt_uniqueness():
    pw = "SamePasswordEveryTime123"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2
    assert verify_password(pw, h1) is True
    assert verify_password(pw, h2) is True


def test_password_strength_validation():
    with pytest.raises(PasswordSecurityError, match="at least 8 characters"):
        hash_password("short")

    with pytest.raises(PasswordSecurityError, match="at least 8 characters"):
        hash_password("")

    with pytest.raises(PasswordSecurityError, match="exceeds maximum length"):
        hash_password("a" * 1025)


def test_invalid_hash_format_fails_gracefully():
    assert verify_password("password123", "not_a_valid_hash") is False
    assert verify_password("password123", "") is False
    assert verify_password("password123", "$argon2id$invalid_formatting") is False


def test_needs_rehash():
    pw = "ValidPassword123"
    h = hash_password(pw)
    # A fresh argon2 hash does not need rehash immediately
    if h.startswith("$argon2"):
        assert needs_rehash(h) is False
    # A legacy or pbkdf2 hash needs rehash to argon2
    assert needs_rehash("$pbkdf2-sha256$i=1000$00$00") is True
