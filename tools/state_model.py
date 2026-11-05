"""Central 4-dimensional state model for Overcharge Desk.

Standard library only (Python 3.9+).

Dimensions:
1. VerificationStatus: Independent technical & evidence verification state.
2. CommercialStatus: Economic relationship between invoice and contract terms.
3. ApprovalStatus: Human governance and cryptographic authorization state.
4. PaymentRecommendationStatus: Disbursement eligibility and release state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set

from common import ToolError, utc_now_iso


class VerificationStatus:
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"

    ALL: Set[str] = {
        NOT_VERIFIED,
        VERIFIED,
        REVIEW_REQUIRED,
        BLOCKED,
        INVALIDATED,
    }


class CommercialStatus:
    COMPLIANT = "COMPLIANT"
    OVERCHARGED = "OVERCHARGED"
    UNDERCHARGED = "UNDERCHARGED"
    UNSUPPORTED_CHARGES = "UNSUPPORTED_CHARGES"
    AMBIGUOUS = "AMBIGUOUS"
    DISCREPANCY = "DISCREPANCY"
    UNDETERMINED = "UNDETERMINED"

    ALL: Set[str] = {
        COMPLIANT,
        OVERCHARGED,
        UNDERCHARGED,
        UNSUPPORTED_CHARGES,
        AMBIGUOUS,
        DISCREPANCY,
        UNDETERMINED,
    }


class ApprovalStatus:
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"

    ALL: Set[str] = {
        NOT_REQUESTED,
        PENDING,
        APPROVED,
        REJECTED,
        REVOKED,
        EXPIRED,
        INVALIDATED,
    }


class PaymentRecommendationStatus:
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    GENERATED = "GENERATED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"

    ALL: Set[str] = {
        NOT_ELIGIBLE,
        ELIGIBLE,
        GENERATED,
        BLOCKED,
        INVALIDATED,
    }


# Legal state transitions per dimension
LEGAL_VERIFICATION_TRANSITIONS: Dict[str, Set[str]] = {
    VerificationStatus.NOT_VERIFIED: {
        VerificationStatus.VERIFIED,
        VerificationStatus.REVIEW_REQUIRED,
        VerificationStatus.BLOCKED,
    },
    VerificationStatus.VERIFIED: {
        VerificationStatus.REVIEW_REQUIRED,
        VerificationStatus.BLOCKED,
        VerificationStatus.INVALIDATED,
    },
    VerificationStatus.REVIEW_REQUIRED: {
        VerificationStatus.VERIFIED,
        VerificationStatus.BLOCKED,
        VerificationStatus.INVALIDATED,
    },
    VerificationStatus.BLOCKED: {
        VerificationStatus.INVALIDATED,
    },
    VerificationStatus.INVALIDATED: set(),
}

LEGAL_APPROVAL_TRANSITIONS: Dict[str, Set[str]] = {
    ApprovalStatus.NOT_REQUESTED: {
        ApprovalStatus.PENDING,
        ApprovalStatus.REJECTED,
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.PENDING: {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.APPROVED: {
        ApprovalStatus.REVOKED,
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.REJECTED: {
        ApprovalStatus.PENDING,  # Re-submitted with new evidence
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.REVOKED: {
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.EXPIRED: {
        ApprovalStatus.PENDING,
        ApprovalStatus.INVALIDATED,
    },
    ApprovalStatus.INVALIDATED: set(),
}

LEGAL_PAYMENT_TRANSITIONS: Dict[str, Set[str]] = {
    PaymentRecommendationStatus.NOT_ELIGIBLE: {
        PaymentRecommendationStatus.ELIGIBLE,
        PaymentRecommendationStatus.BLOCKED,
        PaymentRecommendationStatus.INVALIDATED,
    },
    PaymentRecommendationStatus.ELIGIBLE: {
        PaymentRecommendationStatus.GENERATED,
        PaymentRecommendationStatus.BLOCKED,
        PaymentRecommendationStatus.NOT_ELIGIBLE,
        PaymentRecommendationStatus.INVALIDATED,
    },
    PaymentRecommendationStatus.GENERATED: {
        PaymentRecommendationStatus.INVALIDATED,
    },
    PaymentRecommendationStatus.BLOCKED: {
        PaymentRecommendationStatus.INVALIDATED,
    },
    PaymentRecommendationStatus.INVALIDATED: set(),
}


def validate_state_consistency(
    verification_status: str,
    commercial_status: str,
    approval_status: str,
    payment_status: str,
) -> None:
    """Enforce cross-dimensional invariants. Fail-closed on contradiction."""
    if verification_status not in VerificationStatus.ALL:
        raise ToolError(f"Invalid verification_status: {verification_status!r}")
    if commercial_status not in CommercialStatus.ALL:
        raise ToolError(f"Invalid commercial_status: {commercial_status!r}")
    if approval_status not in ApprovalStatus.ALL:
        raise ToolError(f"Invalid approval_status: {approval_status!r}")
    if payment_status not in PaymentRecommendationStatus.ALL:
        raise ToolError(f"Invalid payment_status: {payment_status!r}")

    # Invariant: BLOCKED verification forces BLOCKED/NOT_ELIGIBLE payment and no approvals
    if verification_status == VerificationStatus.BLOCKED:
        if payment_status not in (PaymentRecommendationStatus.BLOCKED, PaymentRecommendationStatus.NOT_ELIGIBLE):
            raise ToolError(
                f"State contradiction: verification_status is BLOCKED but payment_status is {payment_status}"
            )
        if approval_status in (ApprovalStatus.APPROVED, ApprovalStatus.PENDING):
            raise ToolError(
                f"State contradiction: verification_status is BLOCKED but approval_status is {approval_status}"
            )

    # Invariant: REVIEW_REQUIRED can never be ELIGIBLE or GENERATED for payment
    if verification_status == VerificationStatus.REVIEW_REQUIRED:
        if payment_status in (PaymentRecommendationStatus.ELIGIBLE, PaymentRecommendationStatus.GENERATED):
            raise ToolError(
                f"State contradiction: verification_status is REVIEW_REQUIRED but payment_status is {payment_status}"
            )

    # Invariant: Payment GENERATED strictly requires APPROVED and VERIFIED
    if payment_status == PaymentRecommendationStatus.GENERATED:
        if approval_status != ApprovalStatus.APPROVED:
            raise ToolError(
                f"State contradiction: payment_status is GENERATED but approval_status is {approval_status} (must be APPROVED)"
            )
        if verification_status != VerificationStatus.VERIFIED:
            raise ToolError(
                f"State contradiction: payment_status is GENERATED but verification_status is {verification_status} (must be VERIFIED)"
            )

    # Invariant: Payment ELIGIBLE requires VERIFIED
    if payment_status == PaymentRecommendationStatus.ELIGIBLE:
        if verification_status != VerificationStatus.VERIFIED:
            raise ToolError(
                f"State contradiction: payment_status is ELIGIBLE but verification_status is {verification_status} (must be VERIFIED)"
            )

    # Invariant: Approval APPROVED requires VERIFIED
    if approval_status == ApprovalStatus.APPROVED:
        if verification_status != VerificationStatus.VERIFIED:
            raise ToolError(
                f"State contradiction: approval_status is APPROVED but verification_status is {verification_status} (must be VERIFIED)"
            )


@dataclass
class CaseStateRecord:
    verification_status: str = VerificationStatus.NOT_VERIFIED
    commercial_status: str = CommercialStatus.UNDETERMINED
    approval_status: str = ApprovalStatus.NOT_REQUESTED
    payment_status: str = PaymentRecommendationStatus.NOT_ELIGIBLE
    last_updated: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.last_updated:
            self.last_updated = utc_now_iso()
        validate_state_consistency(
            self.verification_status,
            self.commercial_status,
            self.approval_status,
            self.payment_status,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CaseStateRecord:
        return cls(
            verification_status=data.get("verification_status", VerificationStatus.NOT_VERIFIED),
            commercial_status=data.get("commercial_status", CommercialStatus.UNDETERMINED),
            approval_status=data.get("approval_status", ApprovalStatus.NOT_REQUESTED),
            payment_status=data.get("payment_status", PaymentRecommendationStatus.NOT_ELIGIBLE),
            last_updated=data.get("last_updated", utc_now_iso()),
            reason=data.get("reason", ""),
        )

