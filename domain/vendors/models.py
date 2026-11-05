"""Vendor payment destination verification records and repository."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class VendorDestination:
    vendor_id: str
    destination_reference: str  # Masked bank account / remittance routing
    verification_status: str    # "VERIFIED", "UNVERIFIED", "DISPUTED"
    verification_method: str    # "BANK_CONFIRMATION", "VOIDED_CHECK", "DIRECT_PORTAL"
    verified_by: str
    verified_at: str
    evidence_digest: str
    change_request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Authoritative verified vendor destinations
DEFAULT_VENDOR_DESTINATIONS: Dict[str, VendorDestination] = {
    "acme": VendorDestination(
        vendor_id="acme",
        destination_reference="HDFC-BANK-****4102-IN",
        verification_status="VERIFIED",
        verification_method="BANK_CONFIRMATION",
        verified_by="treasury_admin",
        verified_at="2026-10-01T00:00:00Z",
        evidence_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
}


class VendorRegistry:
    """Manages verified vendor payment destinations."""

    def __init__(self, destinations: Optional[Dict[str, VendorDestination]] = None):
        self._destinations = dict(destinations or DEFAULT_VENDOR_DESTINATIONS)

    def get_destination(self, vendor_id: str) -> Optional[VendorDestination]:
        return self._destinations.get(vendor_id.lower())

    def is_destination_verified(self, vendor_id: str) -> bool:
        dest = self.get_destination(vendor_id)
        return dest is not None and dest.verification_status == "VERIFIED"
