"""Vendor registry and rate schedule endpoints."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status

from common import ToolError, load_json, write_json_atomic
from domain.authorization.policies import PERM_CASE_CREATE, PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import (
    ROOT_DIR,
    fmt_dec,
    list_vendors_payload,
    sync_vendor_registry,
    to_dec,
    write_contract_markdown,
)

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("")
def list_vendors(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> List[Dict[str, Any]]:
    """List all registered vendors with contracts, currencies, and active rate schedules."""
    return list_vendors_payload()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_or_update_vendor(
    body: Dict[str, Any],
    user: User = Depends(require_permission(PERM_CASE_CREATE)),
) -> Dict[str, Any]:
    """Create or update a vendor profile and associated master contract."""
    vendor_id = re.sub(r"[^a-z0-9_-]", "", str(body.get("vendor_id", "")).strip().lower())
    vendor_name = str(body.get("vendor_name", "")).strip()
    contract_id = str(body.get("contract_id", "")).strip() or f"CON-{vendor_id.upper()}-2026"
    currency = str(body.get("currency", "INR")).strip().upper() or "INR"
    effective_from = str(body.get("effective_from", "2026-01-01")).strip()
    effective_to = str(body.get("effective_to", "2026-12-31")).strip()
    dest_ref = str(body.get("destination_reference", f"HDFC-BANK-****{vendor_id[:4].upper()}-IN")).strip()
    bank_verified = bool(body.get("bank_verified", True))
    rates_in = body.get("rates", [])

    if not vendor_id or not vendor_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'vendor_id' and 'vendor_name' are required",
        )

    clean_rates = []
    for idx, r in enumerate(rates_in if isinstance(rates_in, list) else [], start=1):
        sku = str(r.get("item_code") or r.get("sku") or "").strip()
        desc = str(r.get("description") or "").strip()
        u_price = fmt_dec(to_dec(r.get("unit_price", "0.00")))
        if not sku or to_dec(u_price) <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rate line {idx} requires a valid SKU and unit_price > 0",
            )
        ikey = re.sub(r"[^a-z0-9-]+", "-", sku.lower()).strip("-") or f"item-{idx}"
        full_desc = desc if (sku.lower() in desc.lower()) else f"{desc} ({sku})"
        clean_rates.append(
            {
                "item_key": ikey,
                "sku": sku,
                "item_code": sku,
                "description": full_desc,
                "aliases": [a.strip() for a in str(r.get("aliases", desc or sku)).split(",") if a.strip()],
                "unit": str(r.get("unit", "unit")).strip() or "unit",
                "unit_price": u_price,
                "currency": currency,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "clause_ref": str(r.get("clause_ref") or f"Schedule A, item {idx}"),
            }
        )

    src_md_rel = write_contract_markdown(
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        contract_id=contract_id,
        effective_from=effective_from,
        effective_to=effective_to,
        currency=currency,
        rates=clean_rates,
    )

    vendor_f = ROOT_DIR / "vendors" / f"{vendor_id}.json"
    ex_v = load_json(vendor_f) if vendor_f.exists() else {}
    aliases_list = list(dict.fromkeys([vendor_name, vendor_id] + list(ex_v.get("aliases") or [])))
    vendor_payload = {
        "vendor_id": vendor_id,
        "name": vendor_name,
        "aliases": aliases_list,
        "currency": currency,
        "destination_reference": dest_ref,
        "bank_verified": bank_verified,
        "contract": {
            "contract_id": contract_id,
            "vendor_id": vendor_id,
            "source_file": src_md_rel,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "rates": clean_rates,
        },
        "history": ex_v.get("history") or {"cases": []},
    }
    vendor_f.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(vendor_f, vendor_payload)
    sync_vendor_registry()

    return {
        "ok": True,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "contract_id": contract_id,
        "rates_count": len(clean_rates),
        "source_file": src_md_rel,
    }
