"""Authorization domain: RBAC policies, permissions, and separation of duties."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from common import ToolError
from domain.identity.models import SystemRole, User

# Permission Constants
PERM_CASE_CREATE = "cases:create"
PERM_CASE_READ = "cases:read"
PERM_CASE_RECONCILE = "cases:reconcile"
PERM_CASE_REVIEW = "cases:review"
PERM_CASE_APPROVE = "cases:approve"
PERM_CASE_REJECT = "cases:reject"
PERM_PAYMENT_EXPORT = "payment:export"
PERM_AUDIT_READ = "audit:read"
PERM_AUDIT_CHECKPOINT = "audit:checkpoint"
PERM_ADMIN_USERS = "admin:users"
PERM_ADMIN_CONFIG = "admin:config"

# Role -> Permissions Mapping
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    SystemRole.ADMINISTRATOR: {
        PERM_CASE_CREATE,
        PERM_CASE_READ,
        PERM_CASE_RECONCILE,
        PERM_CASE_REVIEW,
        PERM_CASE_APPROVE,
        PERM_CASE_REJECT,
        PERM_PAYMENT_EXPORT,
        PERM_AUDIT_READ,
        PERM_AUDIT_CHECKPOINT,
        PERM_ADMIN_USERS,
        PERM_ADMIN_CONFIG,
    },
    SystemRole.FINANCE_OPERATOR: {
        PERM_CASE_CREATE,
        PERM_CASE_READ,
        PERM_CASE_RECONCILE,
    },
    SystemRole.REVIEWER: {
        PERM_CASE_READ,
        PERM_CASE_REVIEW,
    },
    SystemRole.APPROVER: {
        PERM_CASE_READ,
        PERM_CASE_REVIEW,
        PERM_CASE_APPROVE,
        PERM_CASE_REJECT,
    },
    SystemRole.AUDITOR: {
        PERM_CASE_READ,
        PERM_AUDIT_READ,
    },
    SystemRole.PAYMENT_OPERATOR: {
        PERM_CASE_READ,
        PERM_PAYMENT_EXPORT,
    },
}


class AuthorizationService:
    """Enforces server-side permissions and separation-of-duties rules."""

    def __init__(self, enforce_strict_separation_of_duties: bool = True):
        self.enforce_strict_separation_of_duties = enforce_strict_separation_of_duties

    def has_permission(self, user: User, permission: str) -> bool:
        if not user or not user.is_active:
            return False
        perms = ROLE_PERMISSIONS.get(user.role, set())
        return permission in perms

    def require_permission(self, user: User, permission: str) -> None:
        if not self.has_permission(user, permission):
            raise ToolError(
                f"Authorization denied: User '{user.username}' with role '{user.role}' lacks permission '{permission}'",
                4,
            )

    def evaluate_approval_policy(
        self,
        approver: User,
        case_creator_username: Optional[str] = None,
        verification_status: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Strict server-side policy evaluation for approval actions.

        Rules:
        1. Approver must have PERM_CASE_APPROVE.
        2. Strict separation of duties: Approver cannot be case creator.
        3. Strict positive allowlist: VerificationStatus must be VERIFIED.
        """
        # Rule 1: Role authority
        if not self.has_permission(approver, PERM_CASE_APPROVE):
            return False, f"Role '{approver.role}' is not authorized to grant financial approvals"

        # Rule 2: Separation of duties
        if self.enforce_strict_separation_of_duties:
            if case_creator_username and approver.username.lower() == case_creator_username.lower():
                return (
                    False,
                    f"Separation of duties violation: Operator '{approver.username}' cannot approve their own case",
                )

        # Rule 3: Verification State
        if verification_status and verification_status != "VERIFIED":
            return (
                False,
                f"Strict allowlist violation: Cannot approve case in '{verification_status}' status (must be VERIFIED)",
            )

        return True, "Approval authorized under current governance policy"

