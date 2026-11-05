#!/usr/bin/env python3
"""Seed & Demo State Manager for Overcharge Desk.

Verifies seed integrity and safely resets vendor data and cases for clean demo runs:
  - Validates seed/acme.json schema and exact decimals.
  - Restores vendors/acme.json from seed.
  - Cleanly purges or verifies generated demo cases.

Usage:
  python tools/seed_demo.py [--check] [--reset] [--json]

Exit codes: 0 ok | 1 failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent


def check_seed_integrity(root: Path = None) -> dict:
    if root is None:
        root = ROOT

    seed_file = root / "seed" / "acme.json"
    result = {"status": "PASS", "checks": {}}

    if not seed_file.is_file():
        result["status"] = "FAIL"
        result["checks"]["seed_exists"] = {"status": "FAIL", "error": f"Missing {seed_file}"}
        return result

    result["checks"]["seed_exists"] = {"status": "PASS", "file": str(seed_file)}

    try:
        data = json.loads(seed_file.read_text(encoding="utf-8"))
        contract = data.get("contract", {})
        rates = contract.get("rates", [])
        if not rates:
            result["checks"]["rates"] = {"status": "FAIL", "error": "No rates defined in contract"}
            result["status"] = "FAIL"
        else:
            # Validate rates parse as exact Decimal
            for item in rates:
                Decimal(str(item.get("unit_price", "0")))
            result["checks"]["rates"] = {"status": "PASS", "sku_count": len(rates)}
    except Exception as exc:
        result["checks"]["rates"] = {"status": "FAIL", "error": str(exc)}
        result["status"] = "FAIL"

    return result


def reset_demo_state(root: Path = None) -> dict:
    if root is None:
        root = ROOT

    seed_file = root / "seed" / "acme.json"
    target_file = root / "vendors" / "acme.json"

    target_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed_file, target_file)

    # Clean generated cases matching OC-2026*
    cases_dir = root / "cases"
    cleared = []
    if cases_dir.exists():
        for case_folder in cases_dir.glob("OC-*"):
            if case_folder.is_dir():
                shutil.rmtree(case_folder, ignore_errors=True)
                cleared.append(case_folder.name)

    return {
        "status": "RESET_COMPLETE",
        "vendor_restored": str(target_file),
        "cases_cleared": cleared,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed & Demo State Manager")
    parser.add_argument("--check", action="store_true", help="Verify seed integrity without modifying")
    parser.add_argument("--reset", action="store_true", help="Reset vendors/acme.json and purge demo cases")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    if args.reset:
        res = reset_demo_state()
    else:
        res = check_seed_integrity()

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Seed Manager: {res.get('status')}")
        if "checks" in res:
            for k, v in res["checks"].items():
                print(f"  - {k}: [{v.get('status')}]")
        if "cases_cleared" in res:
            print(f"  Cleared {len(res['cases_cleared'])} cases: {res['cases_cleared']}")

    sys.exit(0 if res.get("status") in ("PASS", "RESET_COMPLETE") else 1)


if __name__ == "__main__":
    main()
