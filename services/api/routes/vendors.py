"""Vendor registry and rate schedule endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends

from common import load_json
from domain.authorization.policies import PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("")
def list_vendors(user: User = Depends(require_permission(PERM_CASE_READ))) -> List[Dict[str, Any]]:
    vendors_dir = Path("vendors")
    results = []
    if vendors_dir.exists():
        for f in vendors_dir.glob("*.json"):
            try:
                data = load_json(f)
                results.append(
                    {
                        "vendor_id": data.get("vendor_id"),
                        "vendor_name": data.get("name"),
                        "currency": data.get("currency"),
                        "contract_id": data.get("contract", {}).get("contract_id"),
                        "effective_from": data.get("contract", {}).get("effective_from"),
                        "effective_to": data.get("contract", {}).get("effective_to"),
                        "items_count": len(data.get("contract", {}).get("items", {})),
                    }
                )
            except Exception:
                pass
    return results

