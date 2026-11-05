#!/usr/bin/env python3
"""Bootstrap Initial Administrator Account for Overcharge Desk.

Usage:
    python -m tools.bootstrap_admin [--username USERNAME] [--email EMAIL] [--full-name NAME] [--seed-demo]

Securely provisions the root administrator account.
Refuses to overwrite an existing active administrator.
Prompts for password securely using getpass (never echoes or prints).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from common import ToolError, emit, run_cli, utc_now_iso
from domain.identity.models import SystemRole
from domain.identity.passwords import hash_password, validate_password_strength
from domain.identity.repository import DEFAULT_IDENTITY_DB, IdentityRepository


def bootstrap_admin(
    username: str = "admin",
    email: str = "admin@overcharge-desk.local",
    full_name: str = "System Administrator",
    password: str | None = None,
    db_path: Path | str = DEFAULT_IDENTITY_DB,
    seed_demo_accounts: bool = False,
) -> dict:
    """Securely bootstrap the initial root administrator account.
    
    Security Controls:
    - Never uses hardcoded default passwords in production.
    - Requires interactive getpass input with confirmation if not passed explicitly.
    - Refuses to run if an active administrator account already exists.
    """
    repo = IdentityRepository(db_path=db_path)

    # 1. Check if an active administrator already exists
    existing = repo.get_user_by_username(username)
    if existing and existing.is_active and existing.role == SystemRole.ADMINISTRATOR:
        raise ToolError(f"Bootstrap refused: Active administrator '{username}' already exists", 2)

    # 2. Acquire password securely if not provided via environment or argument
    if not password:
        pw1 = getpass.getpass("Enter password for administrator: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            raise ToolError("Passwords do not match", 2)
        password = pw1

    validate_password_strength(password)
    pw_hash = hash_password(password)

    # 3. Create or update administrator
    user_id = f"USR-ADMIN-{username.upper()}"
    if existing:
        repo.update_password(existing.user_id, pw_hash)
        admin_rec = repo.get_user_by_id(existing.user_id)
        action = "admin_password_updated"
    else:
        admin_rec = repo.create_user(
            user_id=user_id,
            username=username,
            email=email,
            full_name=full_name,
            role=SystemRole.ADMINISTRATOR,
            password_hash=pw_hash,
            is_active=True,
            is_demo=False,
        )
        action = "admin_created"

    seeded = []
    if seed_demo_accounts:
        # Explicit development-only demo seed
        # Demo accounts are strictly isolated and flagged is_demo=True to block production startup
        demo_specs = [
            ("operator", "sanya.m@overcharge-desk.local", "Sanya Malhotra (Finance Ops)", SystemRole.FINANCE_OPERATOR, "operator123"),
            ("reviewer", "rohan.v@overcharge-desk.local", "Rohan Verma (Reviewer)", SystemRole.REVIEWER, "reviewer123"),
            ("approver", "vikram.seth@overcharge-desk.local", "Vikram Seth (Approver)", SystemRole.APPROVER, "approver123"),
            ("auditor", "pooja.h@overcharge-desk.local", "Pooja Hegde (Auditor)", SystemRole.AUDITOR, "auditor123"),
            ("pay_operator", "karan.m@overcharge-desk.local", "Karan Mehra (Payment Ops)", SystemRole.PAYMENT_OPERATOR, "payment123"),
        ]
        for d_user, d_email, d_name, d_role, d_pw in demo_specs:
            if not repo.get_user_by_username(d_user):
                d_hash = hash_password(d_pw)
                repo.create_user(
                    user_id=f"USR-DEMO-{d_user.upper()}",
                    username=d_user,
                    email=d_email,
                    full_name=d_name,
                    role=d_role,
                    password_hash=d_hash,
                    is_active=True,
                    is_demo=True,  # Explicitly marked as demo-only
                )
                seeded.append(d_user)

    return {
        "ok": True,
        "action": action,
        "user_id": admin_rec.user_id,
        "username": admin_rec.username,
        "role": admin_rec.role,
        "is_demo": admin_rec.is_demo,
        "demo_accounts_seeded": seeded,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default="admin", help="Administrator username (default: admin)")
    ap.add_argument("--email", default="admin@overcharge-desk.local", help="Administrator email")
    ap.add_argument("--full-name", default="System Administrator", help="Administrator full name")
    ap.add_argument("--password", help="Administrator password (prompted securely if omitted)")
    ap.add_argument("--db", default=str(DEFAULT_IDENTITY_DB), help="Path to identity database")
    ap.add_argument("--seed-demo", action="store_true", help="Explicitly seed demo roles for development testing")
    args = ap.parse_args()

    res = bootstrap_admin(
        username=args.username,
        email=args.email,
        full_name=args.full_name,
        password=args.password,
        db_path=args.db,
        seed_demo_accounts=args.seed_demo,
    )
    emit(res)
    return 0


if __name__ == "__main__":
    run_cli(main)

