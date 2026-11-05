"""Audit Ledger Tests for Overcharge Desk.

Tests SQLite audit ledger ACID transactions, cryptographic SHA-256 hash chains,
tamper detection, sequence integrity, and genesis anchoring per AGENTS.md invariant 4.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from common import ToolError
from audit_ledger import (DEFAULT_LEDGER_DB, GENESIS_PREV_HASH, compute_event_hash,
                          init_db, list_events, record_event, verify_ledger)


@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test_ledger.db"
    init_db(db_path)
    return db_path


def test_genesis_event_has_zero_previous_hash(test_db):
    ev = record_event(
        case_id="OC-20261106-01",
        event_type="CASE_CREATED",
        actor_id="test_system",
        payload={"action": "created"},
        db_path=test_db,
    )

    assert ev["event_sequence"] == 1
    assert ev["event_id"] == "EVT-00000001"
    assert ev["previous_event_hash"] == GENESIS_PREV_HASH
    assert len(ev["event_hash"]) == 64

    valid, issues = verify_ledger(test_db)
    assert valid is True
    assert len(issues) == 0


def test_monotonic_hash_chain_verification(test_db):
    # Record 5 sequential events across lifecycle
    ev1 = record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {"step": 1}, db_path=test_db)
    ev2 = record_event("OC-20261106-01", "INVOICE_VALIDATED", "SYSTEM", {"step": 2}, db_path=test_db)
    ev3 = record_event("OC-20261106-01", "COMPARISON_COMPLETED", "SYSTEM", {"step": 3}, db_path=test_db)
    ev4 = record_event("OC-20261106-01", "APPROVAL_GRANTED", "owner", {"step": 4}, db_path=test_db)
    ev5 = record_event("OC-20261106-01", "PAYMENT_RECOMMENDATION_CREATED", "SYSTEM", {"step": 5}, db_path=test_db)

    # Verify link hashes
    assert ev2["previous_event_hash"] == ev1["event_hash"]
    assert ev3["previous_event_hash"] == ev2["event_hash"]
    assert ev4["previous_event_hash"] == ev3["event_hash"]
    assert ev5["previous_event_hash"] == ev4["event_hash"]

    valid, issues = verify_ledger(test_db)
    assert valid is True
    assert len(issues) == 0

    events = list_events(db_path=test_db)
    assert len(events) == 5


def test_tampered_payload_in_historical_event_detected(test_db):
    # Integrity Test: Verifies that database modification of historical payloads breaks hash chain
    record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {"amount": "100.00"}, db_path=test_db)
    record_event("OC-20261106-01", "APPROVAL_GRANTED", "owner", {"amount": "100.00"}, db_path=test_db)
    record_event("OC-20261106-01", "CASE_CLOSED", "SYSTEM", {"closed": True}, db_path=test_db)

    # Direct malicious SQLite manipulation of historical payload
    conn = sqlite3.connect(str(test_db))
    with conn:
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE event_sequence = 1",
            (json.dumps({"amount": "99999.00"}, sort_keys=True),)
        )
    conn.close()

    valid, issues = verify_ledger(test_db)
    assert valid is False
    assert any("Data tampering detected" in i for i in issues)


def test_deleted_event_detected_via_sequence_gap(test_db):
    record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {"v": 1}, db_path=test_db)
    record_event("OC-20261106-01", "INVOICE_VALIDATED", "SYSTEM", {"v": 2}, db_path=test_db)
    record_event("OC-20261106-01", "COMPARISON_COMPLETED", "SYSTEM", {"v": 3}, db_path=test_db)

    # Maliciously delete middle event
    conn = sqlite3.connect(str(test_db))
    with conn:
        conn.execute("DELETE FROM audit_events WHERE event_sequence = 2")
    conn.close()

    valid, issues = verify_ledger(test_db)
    assert valid is False
    assert any("Sequence discontinuity" in i for i in issues)
    assert any("Broken hash chain" in i for i in issues)


def test_reordered_events_detected(test_db):
    record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {"v": 1}, db_path=test_db)
    record_event("OC-20261106-01", "INVOICE_VALIDATED", "SYSTEM", {"v": 2}, db_path=test_db)

    # Swap timestamps or event IDs
    conn = sqlite3.connect(str(test_db))
    with conn:
        conn.execute("UPDATE audit_events SET event_id = 'EVT-00000099' WHERE event_sequence = 1")
    conn.close()

    valid, issues = verify_ledger(test_db)
    assert valid is False
    assert any("Event ID mismatch" in i for i in issues)


def test_broken_previous_hash_detected(test_db):
    record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {"v": 1}, db_path=test_db)
    record_event("OC-20261106-01", "INVOICE_VALIDATED", "SYSTEM", {"v": 2}, db_path=test_db)

    # Break hash link on event 2
    conn = sqlite3.connect(str(test_db))
    with conn:
        conn.execute(
            "UPDATE audit_events SET previous_event_hash = ? WHERE event_sequence = 2",
            ("f" * 64,)
        )
    conn.close()

    valid, issues = verify_ledger(test_db)
    assert valid is False
    assert any("Broken hash chain" in i for i in issues)


def test_filtering_events_by_case_id(test_db):
    record_event("OC-20261106-01", "CASE_CREATED", "SYSTEM", {}, db_path=test_db)
    record_event("OC-20261106-02", "CASE_CREATED", "SYSTEM", {}, db_path=test_db)
    record_event("OC-20261106-01", "INVOICE_VALIDATED", "SYSTEM", {}, db_path=test_db)

    c1_events = list_events(case_id="OC-20261106-01", db_path=test_db)
    c2_events = list_events(case_id="OC-20261106-02", db_path=test_db)

    assert len(c1_events) == 2
    assert len(c2_events) == 1
    assert c1_events[0]["case_id"] == "OC-20261106-01"
    assert c2_events[0]["case_id"] == "OC-20261106-02"


def test_empty_ledger_is_valid(test_db):
    valid, issues = verify_ledger(test_db)
    assert valid is True
    assert len(issues) == 0

