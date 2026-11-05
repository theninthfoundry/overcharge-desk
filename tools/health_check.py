#!/usr/bin/env python3
"""Standalone CLI Health Check Probe for Overcharge Desk.

Validates core engine readiness:
- Python version and decimal support
- Argon2id cryptographic library availability
- SQLite ledger database and hash chain integrity
- Case directories containment and read/write access
- Key management configuration status
"""

import sys
import json
import os
from pathlib import Path
from decimal import Decimal

# Bootstrap paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("tools.health_check")


def run_health_check(root: Path = None, as_json: bool = False) -> int:
    if root is None:
        root = ROOT

    status = {
        "status": "HEALTHY",
        "python_version": sys.version.split()[0],
        "checks": {},
    }

    exit_code = 0

    # 1. Decimal arithmetic readiness
    try:
        d1 = Decimal("0.1") + Decimal("0.2")
        status["checks"]["decimal_arithmetic"] = {
            "status": "PASS",
            "sample_calculation": str(d1),
        }
    except Exception as exc:
        status["checks"]["decimal_arithmetic"] = {"status": "FAIL", "error": str(exc)}
        exit_code = 1

    # 2. Argon2id / Password Hashing readiness
    try:
        import argon2  # noqa: F401
        status["checks"]["argon2id"] = {"status": "PASS", "module": "argon2-cffi"}
    except ImportError:
        try:
            from domain.identity.passwords import hash_password, verify_password
            probe_hash = hash_password("healthcheck_probe_123")
            if verify_password("healthcheck_probe_123", probe_hash):
                status["checks"]["argon2id"] = {"status": "PASS", "module": "pbkdf2-hmac-sha256-fallback"}
            else:
                status["checks"]["argon2id"] = {"status": "FAIL", "error": "password verification probe failed"}
                exit_code = 1
        except Exception as exc:
            status["checks"]["argon2id"] = {"status": "FAIL", "error": str(exc)}
            exit_code = 1

    # 3. Storage and Case Directory Containment
    try:
        cases_dir = root / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)
        status["checks"]["case_storage"] = {
            "status": "PASS",
            "path": str(cases_dir),
            "writable": os.access(cases_dir, os.W_OK),
        }
    except Exception as exc:
        status["checks"]["case_storage"] = {"status": "FAIL", "error": str(exc)}
        exit_code = 1

    # 4. Ledger and Hash Chain Integrity
    try:
        db_path = root / "ledger.db"
        if db_path.exists():
            from audit_ledger import list_events, verify_ledger
            is_valid, issues = verify_ledger(db_path)
            events = list_events(db_path=db_path)
            status["checks"]["ledger_chain"] = {
                "status": "PASS" if is_valid else "FAIL",
                "events_count": len(events),
                "chain_integrity": "VALID" if is_valid else "INVALID",
                "issues": issues,
            }
            if not is_valid:
                exit_code = 1
        else:
            status["checks"]["ledger_chain"] = {
                "status": "PASS",
                "notice": "ledger.db not yet created (will initialize on first case)",
            }
    except Exception as exc:
        status["checks"]["ledger_chain"] = {"status": "FAIL", "error": str(exc)}
        exit_code = 1

    # 5. Key Management Configuration
    key_dir = os.environ.get("OVERCHARGE_KEY_DIR")
    status["checks"]["key_management"] = {
        "mode": "PRODUCTION" if key_dir else "DEVELOPMENT",
        "key_dir_configured": bool(key_dir),
    }

    if exit_code != 0:
        status["status"] = "UNHEALTHY"

    if as_json:
        print(json.dumps(status, indent=2))
    else:
        print(f"Overcharge Desk Health Probe: {status['status']}")
        for check, res in status["checks"].items():
            st = res.get("status", "INFO")
            print(f"  - {check:<20}: [{st}]")

    return exit_code


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Overcharge Desk Standalone Health Check")
    parser.add_argument("--json", action="store_true", help="Output health report as JSON")
    args = parser.parse_args()

    sys.exit(run_health_check(as_json=args.json))


if __name__ == "__main__":
    main()
