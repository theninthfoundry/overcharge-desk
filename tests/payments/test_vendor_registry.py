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


def test_unverified_vendor_destination_rejection():
    reg = VendorRegistry({
        "unverified_vendor": VendorDestination(
            vendor_id="unverified_vendor",
            destination_reference="UNKNOWN",
            verification_status="UNVERIFIED",
            verification_method="NONE",
            verified_by="",
            verified_at="",
            evidence_digest="0" * 64,
        )
    })
    assert reg.is_destination_verified("unverified_vendor") is False
    assert reg.is_destination_verified("non_existent_vendor") is False

