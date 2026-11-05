"""Tests for persistent IdentityRepository SQLite constraints, sessions, and touch."""
from __future__ import annotations

import pytest
from common import ToolError
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
