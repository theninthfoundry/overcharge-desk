"""Contract management and Schedule A rate endpoints."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from common import ToolError, load_json, write_json_atomic
from domain.authorization.policies import PERM_CASE_CREATE, PERM_CASE_READ
from domain.identity.models import User
from services.api.middleware import require_permission
from services.api.workspace_service import (
    ROOT_DIR,
    fmt_dec,
    list_contracts_payload,
    sync_vendor_registry,
    to_dec,
    write_contract_markdown,
)

router = APIRouter(prefix="/contracts", tags=["Contracts"])


class ContractRateRequest(BaseModel):
    item_code: str = Field(..., alias="item_code")
    description: str = ""
    unit: str = "unit"
    unit_price: str = "0.00"
    clause_ref: str = ""
    currency: str = "INR"
    effective_from: str = "2026-01-01"
    effective_to: str = "2026-12-31"
    aliases: str = ""


@router.get("")
def list_contracts(
    user: User = Depends(require_permission(PERM_CASE_READ)),
) -> List[Dict[str, Any]]:
    """List all registered supplier contracts and Schedule A terms."""
    return list_contracts_payload()


@router.post("/{vendor_id}/rates")
def add_or_update_contract_rate(
    vendor_id: str,
    req: Dict[str, Any],
    user: User = Depends(require_permission(PERM_CASE_CREATE)),
):
    """Add or update a contracted unit rate for a vendor."""
    clean_vid = re.sub(r"[^a-z0-9_-]", "", vendor_id.strip().lower())
    if not clean_vid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid 'vendor_id' is required")

    v_file = ROOT_DIR / "vendors" / f"{clean_vid}.json"
    sku = str(req.get("item_code") or req.get("sku") or "").strip()
    desc = str(req.get("description") or "").strip()
    unit = str(req.get("unit", "unit")).strip() or "unit"
    u_price = fmt_dec(to_dec(req.get("unit_price", "0.00")))
    clause_ref = str(req.get("clause_ref", "")).strip()

    if not sku or to_dec(u_price) <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid 'item_code' and 'unit_price' (> 0.00) are required",
        )

    if v_file.exists():
        vdata = load_json(v_file)
    else:
        v_name = str(req.get("vendor_name") or f"{clean_vid.upper()} Vendor Services").strip()
        vdata = {
            "vendor_id": clean_vid,
            "name": v_name,
            "aliases": [v_name, clean_vid],
            "currency": str(req.get("currency", "INR")).strip().upper() or "INR",
            "destination_reference": f"TREASURY-{clean_vid.upper()}-001",
            "bank_verified": True,
            "contract": {
                "contract_id": f"CON-{clean_vid.upper()}-2026",
                "vendor_id": clean_vid,
                "source_file": f"contracts/{clean_vid}-contract.md",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "rates": [],
            },
            "history": {"cases": []},
        }

    contract = vdata.setdefault("contract", {})
    rates = contract.setdefault("rates", [])
    if not clause_ref:
        clause_ref = f"Schedule A, item {len(rates) + 1}"
    eff_from = str(req.get("effective_from") or contract.get("effective_from") or "2026-01-01")
    eff_to = str(req.get("effective_to") or contract.get("effective_to") or "2026-12-31")
    curr = str(req.get("currency") or vdata.get("currency") or "INR")
    ikey = re.sub(r"[^a-z0-9-]+", "-", sku.lower()).strip("-") or f"item-{len(rates) + 1}"
    full_desc = desc if (sku.lower() in desc.lower()) else f"{desc} ({sku})"

    new_rate = {
        "item_key": ikey,
        "sku": sku,
        "item_code": sku,
        "description": full_desc,
        "aliases": [a.strip() for a in str(req.get("aliases", desc or sku)).split(",") if a.strip()],
        "unit": unit,
        "unit_price": u_price,
        "currency": curr,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "clause_ref": clause_ref,
    }
    replaced = False
    for idx, existing in enumerate(rates):
        if (existing.get("sku") or existing.get("item_code")) == sku:
            rates[idx] = new_rate
            replaced = True
            break
    if not replaced:
        rates.append(new_rate)

    contract["source_file"] = write_contract_markdown(
        vendor_id=clean_vid,
        vendor_name=vdata.get("name", clean_vid),
        contract_id=contract.get("contract_id") or f"CON-{clean_vid.upper()}-2026",
        effective_from=eff_from,
        effective_to=eff_to,
        currency=curr,
        rates=rates,
    )
    v_file.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(v_file, vdata)
    sync_vendor_registry()

    return {
        "ok": True,
        "action": "rate_updated" if replaced else "rate_created",
        "vendor_id": clean_vid,
        "item_code": sku,
        "unit_price": u_price,
        "total_rates": len(rates),
    }
