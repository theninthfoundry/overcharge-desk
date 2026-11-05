"""Tests for persistent IdentityRepository SQLite constraints, sessions, and touch."""
from __future__ import annotations

import pytest
from common import ToolError, utc_now_iso
from domain.identity.repository import IdentityRepository


def test_user_unique_constraints_enforced(tmp_path):
    repo = IdentityRepository(db_path=tmp_path / "test_identity.db")
    u1 = repo.create_user(
        user_id="U1",
        username="unique_user",
        email="unique@test.local",
        full_name="Unique User",
        role="OPERATOR",
        password_hash="some_hash",
    )
    assert u1.username == "unique_user"

    # Duplicate username must fail
    with pytest.raises(ToolError, match="already exists"):
        repo.create_user(
            user_id="U2",
            username="unique_user",
            email="other@test.local",
            full_name="Duplicate Username",
            role="OPERATOR",
            password_hash="some_hash",
        )

    # Duplicate email must fail
    with pytest.raises(ToolError, match="already exists"):
        repo.create_user(
            user_id="U3",
            username="other_username",
            email="unique@test.local",
            full_name="Duplicate Email",
            role="OPERATOR",
            password_hash="some_hash",
        )


def test_session_lifecycle_and_touch(tmp_path):
    repo = IdentityRepository(db_path=tmp_path / "test_identity.db")
    u = repo.create_user(
        user_id="U1",
        username="session_user",
        email="session@test.local",
        full_name="Session User",
        role="REVIEWER",
        password_hash="hash",
    )
    exp = utc_now_iso()
    # Create session with future expiry
    future_exp = "2099-01-01T00:00:00Z"
    sess = repo.create_session(
        session_id="SESS-01",
        user_id="U1",
        token_hash="hash_01",
        expires_at=future_exp,
    )
    assert sess.user_id == "U1"
    assert sess.is_valid is True

    # Touch session updates last_used_at
    repo.touch_session(sess.session_id)
    updated = repo.get_session_by_token_hash("hash_01")
    assert updated is not None
    assert updated.session_id == sess.session_id


def test_session_revocation(tmp_path):
    repo = IdentityRepository(db_path=tmp_path / "test_identity.db")
    u = repo.create_user(
        user_id="U2",
        username="revoke_user",
        email="revoke@test.local",
        full_name="Revoke User",
        role="OPERATOR",
        password_hash="hash",
    )
    sess = repo.create_session("SESS-02", "U2", "hash_02", "2099-01-01T00:00:00Z")
    assert sess.is_valid is True

    # Revoke session
    repo.revoke_session("SESS-02")
    revoked = repo.get_session_by_token_hash("hash_02")
    assert revoked is not None
    assert revoked.revoked_at is not None
    assert revoked.is_valid is False

