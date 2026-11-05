"""Tests for API operational health checks, ready/live probes, and degradation detection."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from domain.identity.key_manager import KeyManager
from domain.identity.repository import IdentityRepository
from services.api.main import app

client = TestClient(app)


def test_health_check_ready():
    """Operational health check returns READY when all subsystems are operational."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["is_ready"] is True
    assert data["service"] == "overcharge-desk-api"
    assert data["checks"]["database"] == "OK"
    assert data["checks"]["storage"] == "OK"
    assert data["checks"]["key_manager"] == "OK"


def test_health_check_degraded_on_key_manager_failure(monkeypatch):
    """Health check signals DEGRADED when signing keys cannot be accessed."""
    from services.api import main

    class FailingKM:
        def get_active_key(self):
            raise RuntimeError("Signing key missing or corrupted")

    monkeypatch.setattr(main, "get_key_manager", lambda: FailingKM())

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DEGRADED"
    assert data["is_ready"] is False
    assert "Signing key missing" in data["checks"]["key_manager"]


def test_health_check_degraded_on_db_failure(monkeypatch):
    """Health check signals DEGRADED when identity database connection fails."""
    def fail_check_production_safety(self):
        raise RuntimeError("Database locked or unreachable")

    monkeypatch.setattr(IdentityRepository, "check_production_safety", fail_check_production_safety)

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DEGRADED"
    assert data["is_ready"] is False
    assert "Database locked" in data["checks"]["database"]


def test_health_check_degraded_on_storage_failure(monkeypatch):
    """Health check signals DEGRADED when case storage write fails."""
    from pathlib import Path

    def fail_write_text(self, data):
        raise OSError("Read-only filesystem")

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DEGRADED"
    assert data["is_ready"] is False
    assert "ERROR" in data["checks"]["storage"]

