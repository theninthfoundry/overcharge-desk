#!/usr/bin/env python3
"""Actor Model & Authentication Gateway for Overcharge Desk.

Implements role-based access control (RBAC), HMAC-SHA-256 actor token issuance
and verification, and permission validation per AGENTS.md invariant 3.

Security Notice:
    HMAC-SHA-256 tokens authenticate that the bearer possessed the provisioned
    shared secret at token issuance time within the permitted time window.
    They do NOT provide cryptographic non-repudiation (which requires asymmetric
    key pairs such as Ed25519). All authorization claims are strictly fail-closed.

Usage:
    python tools/auth.py issue-token ACTOR_ID [--key-file FILE] [--ttl SECONDS]
    python tools/auth.py verify-token TOKEN [--key-file FILE]
    python tools/auth.py check-perm  ACTOR_ID PERMISSION [--config FILE]
    python tools/auth.py list-actors [--config FILE]

Exit codes: 0 ok | 2 bad input / invalid token | 4 unauthorized.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import ToolError, emit, load_json, run_cli, utc_now_iso

DEFAULT_ACTORS_CONFIG = Path("config/actors.json")
DEFAULT_KEY_FILE = Path("config/signing.key")
DEFAULT_TOKEN_TTL = 300  # 5 minutes

ROLES = ("SYSTEM", "REVIEWER", "APPROVER", "ADMINISTRATOR")

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "SYSTEM": [
        "register_evidence",
        "validate_invoice",
        "run_comparison",
        "generate_artifacts",
        "record_ledger",
    ],
    "REVIEWER": [
        "view_cases",
        "add_review_notes",
        "request_approval",
    ],
    "APPROVER": [
        "view_cases",
        "approve_case",
        "reject_case",
        "view_approvals",
        "record_ledger",
    ],
    "ADMINISTRATOR": [
        "register_evidence",
        "validate_invoice",
        "run_comparison",
        "generate_artifacts",
        "view_cases",
        "add_review_notes",
        "request_approval",
        "approve_case",
        "reject_case",
        "view_approvals",
        "record_ledger",
        "administer_system",
    ],
}


def load_signing_key(key_file: Path | str | None = None) -> bytes:
    """Load HMAC signing key bytes from file, failing closed if missing or empty."""
    target = Path(key_file) if key_file else DEFAULT_KEY_FILE
    if not target.exists():
        # Look in config directory relative to script
        alt = Path(__file__).resolve().parent.parent / "config" / "signing.key"
        if alt.exists():
            target = alt
        else:
            raise ToolError(
                f"Signing key file not found: {target}. Generate one or specify via --key-file",
                4,
            )

    try:
        key_bytes = target.read_bytes().strip()
    except Exception as exc:
        raise ToolError(f"Failed to read signing key: {exc}", 4)

    if len(key_bytes) < 16:
        raise ToolError(
            f"Signing key in {target} is dangerously short (<16 bytes); refusing for security",
            4,
        )
    return key_bytes


def ensure_signing_key(key_file: Path | str | None = None) -> bytes:
    """Ensure a signing key exists, generating a strong 32-byte key if absent."""
    target = Path(key_file) if key_file else DEFAULT_KEY_FILE
    if target.exists():
        return load_signing_key(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    generated = hashlib.sha256(os.urandom(64)).hexdigest().encode("utf-8")
    target.write_bytes(generated)
    return generated


def load_actors_config(config_path: Path | str | None = None) -> dict:
    """Load actor registry configuration."""
    target = Path(config_path) if config_path else DEFAULT_ACTORS_CONFIG
    if not target.exists():
        alt = Path(__file__).resolve().parent.parent / "config" / "actors.json"
        if alt.exists():
            target = alt
        else:
            raise ToolError(f"Actors configuration file not found: {target}", 2)
    return load_json(target)


def get_actor(actor_id: str, config: Optional[dict] = None) -> dict:
    """Find actor definition by ID, failing closed if not found or inactive."""
    cfg = config or load_actors_config()
    actors = cfg.get("actors", [])
    for a in actors:
        if a.get("actor_id") == actor_id:
            if not a.get("active"):
                raise ToolError(f"Actor {actor_id!r} is disabled/inactive", 4)
            return a
    raise ToolError(f"Unknown actor: {actor_id!r}", 4)


def check_actor_permission(
    actor_id: str,
    permission: str,
    config: Optional[dict] = None,
) -> bool:
    """Check if an actor holds a specific permission."""
    try:
        actor = get_actor(actor_id, config)
    except ToolError:
        return False

    # Check explicit permissions or role permissions
    actor_perms = actor.get("permissions")
    if actor_perms is not None:
        return permission in actor_perms

    role = actor.get("role")
    role_perms = ROLE_PERMISSIONS.get(role, [])
    return permission in role_perms


def issue_actor_token(
    # Authentication Protocol: Issues HMAC-SHA-256 token binding identity and timestamp
    actor_id: str,
    key_bytes: bytes,
    timestamp: Optional[int] = None,
    config: Optional[dict] = None,
) -> str:
    """Issue a signed HMAC-SHA-256 token for an active actor.

    Token format: `<actor_id>.<timestamp>.<hmac_hex>`
    """
    # Verify actor exists and is active
    get_actor(actor_id, config)

    ts = timestamp if timestamp is not None else int(time.time())
    payload = f"{actor_id}:{ts}".encode("utf-8")
    sig = hmac.new(key_bytes, payload, hashlib.sha256).hexdigest()
    return f"{actor_id}.{ts}.{sig}"


def verify_actor_token(
    token: str,
    key_bytes: bytes,
    max_age_seconds: int = DEFAULT_TOKEN_TTL,
    config: Optional[dict] = None,
    current_time: Optional[int] = None,
) -> tuple[bool, str, Optional[dict]]:
    """Verify an actor token.

    Validates:
      1. Structural syntax (`actor_id.timestamp.signature`).
      2. Full 64-char HMAC-SHA-256 signature against shared key.
      3. Token expiration against max_age_seconds (fail-closed on replay/stale).
      4. Actor presence and active status in actor registry.

    Returns: `(is_valid, reason, actor_dict_or_None)`
    """
    if not token or not isinstance(token, str):
        return False, "Token is empty or not a string", None

    parts = token.strip().split(".")
    if len(parts) != 3:
        return False, "Malformed token structure (expected actor.timestamp.sig)", None

    actor_id, ts_str, claimed_sig = parts

    try:
        ts = int(ts_str)
    except ValueError:
        return False, "Token timestamp is not an integer", None

    if len(claimed_sig) != 64:
        return False, "Token signature must be 64-character hex", None

    # Check actor registry
    try:
        actor = get_actor(actor_id, config)
    except ToolError as exc:
        return False, str(exc), None

    # Verify signature
    payload = f"{actor_id}:{ts}".encode("utf-8")
    expected_sig = hmac.new(key_bytes, payload, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig.lower(), claimed_sig.lower()):
        return False, "Cryptographic signature mismatch", None

    # Verify freshness
    now = current_time if current_time is not None else int(time.time())
    age = now - ts
    if age < -10:  # Allow 10s clock skew into future
        return False, f"Token timestamp is in the future by {-age}s", None
    if age > max_age_seconds:
        return False, f"Token expired (age {age}s > allowed {max_age_seconds}s)", None

    return True, "Authenticated", actor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    issue_cmd = sub.add_parser("issue-token", help="Issue an authentication token for an actor")
    issue_cmd.add_argument("actor_id", help="Actor identifier (e.g. 'owner', 'reviewer')")
    issue_cmd.add_argument("--key-file", help="Path to signing key file")
    issue_cmd.add_argument("--config", help="Path to actors.json config")

    verify_cmd = sub.add_parser("verify-token", help="Verify an actor token")
    verify_cmd.add_argument("token", help="Token string to verify")
    verify_cmd.add_argument("--key-file", help="Path to signing key file")
    verify_cmd.add_argument("--ttl", type=int, default=DEFAULT_TOKEN_TTL, help="Max token TTL in seconds")
    verify_cmd.add_argument("--config", help="Path to actors.json config")

    perm_cmd = sub.add_parser("check-perm", help="Check if an actor has a permission")
    perm_cmd.add_argument("actor_id", help="Actor identifier")
    perm_cmd.add_argument("permission", help="Permission name")
    perm_cmd.add_argument("--config", help="Path to actors.json config")

    list_cmd = sub.add_parser("list-actors", help="List registered actors")
    list_cmd.add_argument("--config", help="Path to actors.json config")

    args = ap.parse_args()

    if args.cmd == "issue-token":
        key = load_signing_key(args.key_file)
        cfg = load_actors_config(args.config)
        token = issue_actor_token(args.actor_id, key, config=cfg)
        emit({"ok": True, "actor_id": args.actor_id, "token": token})
        return 0

    elif args.cmd == "verify-token":
        key = load_signing_key(args.key_file)
        cfg = load_actors_config(args.config)
        valid, reason, actor = verify_actor_token(args.token, key, max_age_seconds=args.ttl, config=cfg)
        emit({"ok": valid, "reason": reason, "actor": actor})
        return 0 if valid else 2

    elif args.cmd == "check-perm":
        cfg = load_actors_config(args.config)
        allowed = check_actor_permission(args.actor_id, args.permission, config=cfg)
        emit({"ok": True, "actor_id": args.actor_id, "permission": args.permission, "allowed": allowed})
        return 0 if allowed else 4

    elif args.cmd == "list-actors":
        cfg = load_actors_config(args.config)
        emit({"ok": True, "actors": cfg.get("actors", [])})
        return 0

    return 2


if __name__ == "__main__":
    run_cli(main)

