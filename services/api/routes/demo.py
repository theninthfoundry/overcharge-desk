"""Demo benchmark orchestration and workspace reset endpoints."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from domain.authorization.policies import PERM_CASE_CREATE, PERM_CASE_READ
from domain.identity.models import User
from domain.payments.repository import PaymentRepository
from run_demo_suite import run_full_demo
from services.api.middleware import require_permission
from services.api.workspace_service import (
    DEFAULT_LEDGER_DB,
    DEFAULT_PAYMENT_DB,
    ROOT_DIR,
    ensure_base_storage_initialized,
)

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.post("/run")
@router.post("/reset")
def run_or_reset_demo(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> Dict[str, Any]:
    """Execute the end-to-end multi-scenario demo benchmark suite."""
    try:
        marker = ROOT_DIR / "cases" / ".demo_cleared"
        if marker.exists():
            marker.unlink()
        cases_p = ROOT_DIR / "cases"
        if cases_p.exists():
            for d in sorted(cases_p.iterdir()):
                if d.is_dir() and not d.name.startswith(".") and not d.name.startswith("demo-"):
                    shutil.rmtree(d, ignore_errors=True)
        inv_p = ROOT_DIR / "invoices"
        if inv_p.exists():
            for f in sorted(inv_p.glob("intake-*")):
                try:
                    f.unlink()
                except Exception:
                    pass
        for suffix in ["", "-wal", "-shm"]:
            p = Path(str(ROOT_DIR / DEFAULT_PAYMENT_DB) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        pay_repo = PaymentRepository()
        pay_repo.init_db()
        res = run_full_demo(base_dir=ROOT_DIR, clean_run=True)
        return res
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/clear")
def clear_demo_workspace(
    user: User = Depends(require_permission(PERM_CASE_CREATE)),
) -> Dict[str, Any]:
    """Reset workspace cases to base empty state for evaluation testing."""
    try:
        cases_p = ROOT_DIR / "cases"
        removed = []
        if cases_p.exists():
            for d in sorted(cases_p.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    shutil.rmtree(d, ignore_errors=True)
                    removed.append(d.name)
        cases_p.mkdir(parents=True, exist_ok=True)
        for folder_name, pattern in [
            ("checkpoints", "*.json"),
        ]:
            folder_p = ROOT_DIR / folder_name
            if folder_p.exists():
                for fp in sorted(folder_p.glob(pattern)):
                    try:
                        fp.unlink()
                    except Exception:
                        pass
        # Reset payments.db and ledger.db cleanly
        for db_f in [ROOT_DIR / DEFAULT_LEDGER_DB, ROOT_DIR / DEFAULT_PAYMENT_DB]:
            for suffix in ["", "-wal", "-shm"]:
                p = Path(str(db_f) + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        ensure_base_storage_initialized()
        return {
            "ok": True,
            "action": "workspace_reset_to_base",
            "removed_cases": removed,
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

