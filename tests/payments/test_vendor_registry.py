"""Tests for VendorRegistry destination lookup, verification status, and routing validation."""
from __future__ import annotations

import pytest
from domain.vendors.models import VendorDestination, VendorRegistry


def test_vendor_registry_case_insensitive_lookup():
    reg = VendorRegistry()
    d1 = reg.get_destination("acme")
    d2 = reg.get_destination("ACME")
    d3 = reg.get_destination("Acme")
    assert d1 is not None
    assert d1 == d2 == d3
    assert reg.is_destination_verified("acme") is True
    assert reg.is_destination_verified("ACME") is True
