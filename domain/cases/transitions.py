"""Transactional Case Lifecycle, Validated State Transitions, and Optimistic Concurrency."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from common import ToolError, load_json, utc_now_iso, write_json_atomic


class CaseState:
    """Explicit lifecycle states for vendor overcharge cases."""
    CREATED = "CREATED"
    RECONCILIATION_RUNNING = "RECONCILIATION_RUNNING"
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAYMENT_INSTRUCTION_READY = "PAYMENT_INSTRUCTION_READY"
    EXPORTED = "EXPORTED"
    CLOSED = "CLOSED"


# Closed state transition graph enforcing strictly legal forward progression
LEGAL_STATE_TRANSITIONS: Dict[str, Set[str]] = {
    CaseState.CREATED: {
        CaseState.RECONCILIATION_RUNNING,
        CaseState.BLOCKED,
        CaseState.CLOSED,
    },
    CaseState.RECONCILIATION_RUNNING: {
        CaseState.VERIFIED,
        CaseState.REVIEW_REQUIRED,
        CaseState.BLOCKED,
    },
    CaseState.VERIFIED: {
        CaseState.AWAITING_APPROVAL,
        CaseState.RECONCILIATION_RUNNING,
        CaseState.BLOCKED,
        CaseState.CLOSED,
    },
    CaseState.REVIEW_REQUIRED: {
        CaseState.RECONCILIATION_RUNNING,
        CaseState.CLOSED,
    },
    CaseState.BLOCKED: {
        CaseState.RECONCILIATION_RUNNING,
        CaseState.CLOSED,
    },
    CaseState.AWAITING_APPROVAL: {
        CaseState.APPROVED,
        CaseState.REJECTED,
        CaseState.RECONCILIATION_RUNNING,
        CaseState.BLOCKED,
    },
    CaseState.APPROVED: {
        CaseState.PAYMENT_INSTRUCTION_READY,
        CaseState.CLOSED,
    },
    CaseState.REJECTED: {
        CaseState.CLOSED,
    },
    CaseState.PAYMENT_INSTRUCTION_READY: {
        CaseState.EXPORTED,
        CaseState.CLOSED,
    },
    CaseState.EXPORTED: {
        CaseState.CLOSED,
    },
    CaseState.CLOSED: set(),  # Terminal state
}


class ConcurrencyConflictError(ToolError):
    """Raised when an optimistic concurrency version check fails (HTTP 409)."""
    def __init__(self, message: str):
        super().__init__(f"Concurrency conflict: {message}", 409)


class InvalidStateTransitionError(ToolError):
    """Raised when an illegal lifecycle transition is attempted."""
    def __init__(self, from_state: str, to_state: str):
        super().__init__(
            f"Invalid state transition from '{from_state}' to '{to_state}'. Permitted: {sorted(LEGAL_STATE_TRANSITIONS.get(from_state, set()))}",
            4,
        )


class CaseLifecycleManager:
    """Manages transactional case transitions with versioning and audit history."""

    @staticmethod
    def transition(
        case_file: Path | str,
        to_state: str,
        actor_id: str,
        reason: str,
        expected_version: Optional[int] = None,
        event_id: Optional[str] = None,
        evidence_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        p = Path(case_file)
        if not p.exists():
            raise ToolError(f"Case metadata file '{p}' not found", 2)

        data = load_json(p)
        current_state = data.get("current_state", CaseState.CREATED)
        current_version = data.get("version", 1)

        # 1. Optimistic Concurrency check
        if expected_version is not None and expected_version != current_version:
            raise ConcurrencyConflictError(
                f"Version mismatch for case '{data.get('case_id')}': expected version {expected_version}, but found {current_version}"
            )

        # 2. Transition legality check
        permitted = LEGAL_STATE_TRANSITIONS.get(current_state, set())
        if to_state not in permitted:
            raise InvalidStateTransitionError(current_state, to_state)

        # 3. Apply state mutation
        now = utc_now_iso()
        new_version = current_version + 1
        transition_record = {
            "from_state": current_state,
            "to_state": to_state,
            "version": new_version,
            "actor_id": actor_id,
            "reason": reason,
            "timestamp": now,
            "event_id": event_id,
            "evidence_version": evidence_version,
        }

        data["current_state"] = to_state
        data["version"] = new_version
        data["updated_at"] = now
        data.setdefault("state_history", []).append(transition_record)

        write_json_atomic(p, data)
        return data

