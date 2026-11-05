from __future__ import annotations

import pytest
from common import ToolError
from domain.identity.models import SystemRole
from domain.identity.passwords import verify_password
from domain.identity.repository import IdentityRepository
from tools.bootstrap_admin import bootstrap_admin


def test_bootstrap_admin_creates_administrator(tmp_path):
    db_file = tmp_path / "test_identity.db"
    res = bootstrap_admin(
        username="secops_admin",
        email="secops@company.local",
        full_name="Security Officer",
        password="ValidPassword123!",
        db_path=db_file,
    )
    assert res["ok"] is True
    assert res["action"] == "admin_created"
    assert res["username"] == "secops_admin"
    assert res["role"] == SystemRole.ADMINISTRATOR
    assert res["is_demo"] is False

    repo = IdentityRepository(db_path=db_file)
    u = repo.get_user_by_username("secops_admin")
    assert u is not None
    assert verify_password("ValidPassword123!", u.password_hash) is True


def test_bootstrap_refuses_to_overwrite_existing_active_admin(tmp_path):
    db_file = tmp_path / "test_identity.db"
    bootstrap_admin(
        username="admin",
        password="FirstPassword123!",
        db_path=db_file,
    )

    with pytest.raises(ToolError, match="Active administrator 'admin' already exists"):
        bootstrap_admin(
            username="admin",
            password="SecondPassword123!",
            db_path=db_file,
        )


def test_bootstrap_seed_demo_accounts_explicit(tmp_path):
    db_file = tmp_path / "test_identity.db"
    res = bootstrap_admin(
        username="admin",
        password="AdminPassword123!",
        db_path=db_file,
        seed_demo_accounts=True,
    )
    assert len(res["demo_accounts_seeded"]) == 5
    repo = IdentityRepository(db_path=db_file)
    op = repo.get_user_by_username("operator")
    assert op is not None
    assert op.is_demo is True
    assert op.role == SystemRole.FINANCE_OPERATOR

    # Production safety check must catch demo accounts in production
    with pytest.raises(ToolError, match="Production startup refused"):
        repo.check_production_safety(app_env="production")
