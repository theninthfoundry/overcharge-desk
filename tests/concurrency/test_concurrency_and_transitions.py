from __future__ import annotations

import pytest
from common import write_json_atomic
from domain.cases.transitions import (
    CaseLifecycleManager,
    CaseState,
    ConcurrencyConflictError,
    InvalidStateTransitionError,
)


@pytest.fixture
def case_file(tmp_path):
    f = tmp_path / "case.json"
    write_json_atomic(
        f,
        {
            "case_id": "OC-TEST-CONCURRENCY",
            "current_state": CaseState.CREATED,
            "version": 1,
            "created_by": "operator",
            "state_history": [],
        },
    )
    return f


def test_legal_state_transitions(case_file):
    # CREATED -> RECONCILIATION_RUNNING
    d1 = CaseLifecycleManager.transition(
        case_file,
        to_state=CaseState.RECONCILIATION_RUNNING,
        actor_id="operator",
        reason="Pipeline started",
        expected_version=1,
    )
    assert d1["current_state"] == CaseState.RECONCILIATION_RUNNING
    assert d1["version"] == 2

    # RECONCILIATION_RUNNING -> VERIFIED
    d2 = CaseLifecycleManager.transition(
        case_file,
        to_state=CaseState.VERIFIED,
        actor_id="system",
        reason="Comparison passed",
        expected_version=2,
    )
    assert d2["current_state"] == CaseState.VERIFIED
    assert d2["version"] == 3


def test_illegal_state_transition_fails_closed(case_file):
    # Cannot jump directly from CREATED to APPROVED
    with pytest.raises(InvalidStateTransitionError):
        CaseLifecycleManager.transition(
            case_file,
            to_state=CaseState.APPROVED,
            actor_id="approver",
            reason="Illegal bypass attempt",
        )


def test_optimistic_concurrency_conflict_detection(case_file):
    # Transition to RECONCILIATION_RUNNING increments version to 2
    CaseLifecycleManager.transition(
        case_file,
        to_state=CaseState.RECONCILIATION_RUNNING,
        actor_id="operator",
        reason="First update",
    )

    # Stale request expecting version 1 must raise ConcurrencyConflictError
    with pytest.raises(ConcurrencyConflictError, match="expected version 1, but found 2"):
        CaseLifecycleManager.transition(
            case_file,
            to_state=CaseState.VERIFIED,
            actor_id="operator",
            reason="Stale update attempt",
            expected_version=1,
        )


def test_terminal_state_closed_rejects_transitions(case_file):
    """Verify CLOSED state permits zero further transitions."""
    # CREATED -> CLOSED is legal
    CaseLifecycleManager.transition(
        case_file,
        to_state=CaseState.CLOSED,
        actor_id="admin",
        reason="Case cancelled",
    )

    # Any transition from CLOSED must fail
    with pytest.raises(InvalidStateTransitionError):
        CaseLifecycleManager.transition(
            case_file,
            to_state=CaseState.RECONCILIATION_RUNNING,
            actor_id="operator",
            reason="Illegal reopen",
        )


def test_invalid_transition_from_blocked(case_file):
    """BLOCKED cases cannot transition to APPROVED or PAYMENT_INSTRUCTION_READY."""
    CaseLifecycleManager.transition(
        case_file,
        to_state=CaseState.BLOCKED,
        actor_id="system",
        reason="Arithmetic error",
    )
    with pytest.raises(InvalidStateTransitionError):
        CaseLifecycleManager.transition(
            case_file,
            to_state=CaseState.APPROVED,
            actor_id="approver",
            reason="Bypass block",
        )


def test_version_increments_monotonically(case_file):
    """Verify version numbers strictly increment on every transition."""
    v1 = CaseLifecycleManager.transition(case_file, CaseState.RECONCILIATION_RUNNING, "op", "start")
    assert v1["version"] == 2
    v2 = CaseLifecycleManager.transition(case_file, CaseState.VERIFIED, "sys", "ok")
    assert v2["version"] == 3
    v3 = CaseLifecycleManager.transition(case_file, CaseState.AWAITING_APPROVAL, "sys", "ready")
    assert v3["version"] == 4




