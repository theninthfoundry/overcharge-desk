"""Vendor domain exports."""
from __future__ import annotations

from domain.vendors.models import DEFAULT_VENDOR_DESTINATIONS, VendorDestination, VendorRegistry

__all__ = ["VendorDestination", "VendorRegistry", "DEFAULT_VENDOR_DESTINATIONS"]
