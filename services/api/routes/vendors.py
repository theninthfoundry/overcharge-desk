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
        for f in sorted(vendors_dir.glob("*.json")):
            try:
                data = load_json(f)
                contract = data.get("contract", {})
                rates = contract.get("rates") or []
                items = contract.get("items") or {}
                first_rate = rates[0] if isinstance(rates, list) and rates else {}
                currency = data.get("currency") or contract.get("currency") or first_rate.get("currency") or "INR"
                effective_from = contract.get("effective_from") or first_rate.get("effective_from") or "2026-01-01"
                effective_to = contract.get("effective_to") or first_rate.get("effective_to") or "Active"
                items_count = len(rates) if rates else len(items)
                results.append(
                    {
                        "vendor_id": data.get("vendor_id"),
                        "vendor_name": data.get("name"),
                        "currency": currency,
                        "contract_id": contract.get("contract_id"),
                        "source_file": contract.get("source_file"),
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "items_count": items_count,
                        "rates": rates,
                    }
                )
            except Exception:
                pass
    return results


