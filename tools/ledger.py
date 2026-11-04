#!/usr/bin/env python3
"""Safe, append-only writes to a vendor ledger (vendors/<id>.json).

Usage:
    python tools/ledger.py add-case    VENDOR_JSON --record RECORD_JSON
    python tools/ledger.py set-outcome VENDOR_JSON CASE_ID --text "..." --recorded-by @owner

Why a script: the Writer cannot hand-edit the ledger, cannot set its own
timestamps, cannot overwrite an earlier record, and a crash cannot leave a
half-written file. Exit codes: 0 ok | 2 bad input | 4 refused (duplicate, unknown case,
outcome already recorded).
"""
from __future__ import annotations

import argparse
import re

from common import (CASE_ID_RE, ToolError, emit, load_json, run_cli, utc_now_iso,
                    write_json_atomic)

REQUIRED = ["case_id", "invoice_number", "status", "owner_decision", "decided_by",
            "audit_sha256", "identity_check", "finding_summary", "evidence_refs"]
OPTIONAL = ["variance_total", "owner_reason"]
STATUSES = ("approved_dispute", "rejected_by_owner")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_record(rec: dict) -> dict:
    if not isinstance(rec, dict):
        raise ToolError("Record must be a JSON object")
    unknown = set(rec) - set(REQUIRED) - set(OPTIONAL) - {"vendor_outcome", "decided_at"}
    if unknown:
        raise ToolError(f"Unknown field(s) in record: {sorted(unknown)}")
    missing = [k for k in REQUIRED if rec.get(k) in (None, "", [])]
    if missing:
        raise ToolError(f"Record is missing required field(s): {missing}")
    if not CASE_ID_RE.match(rec["case_id"]):
        raise ToolError(f"case_id must look like OC-YYYYMMDD-NN, got {rec['case_id']!r}")
    if rec["status"] not in STATUSES:
        raise ToolError(f"status must be one of {STATUSES}")
    if not SHA_RE.match(str(rec["audit_sha256"])):
        raise ToolError("audit_sha256 must be the full 64-character hex digest")
    if not isinstance(rec["evidence_refs"], list):
        raise ToolError("evidence_refs must be a list")
    if rec["status"] == "approved_dispute" and not rec.get("variance_total"):
        raise ToolError("An approved dispute needs variance_total")
    if rec["status"] == "rejected_by_owner" and not rec.get("owner_reason"):
        raise ToolError("A rejection needs owner_reason (the owner's words)")
    if rec.get("vendor_outcome") is not None:
        raise ToolError("vendor_outcome cannot be set when a case is created; use set-outcome")
    clean = {k: rec[k] for k in REQUIRED + OPTIONAL if k in rec}
    clean["decided_at"] = utc_now_iso()  # always stamped here, never taken from the caller
    clean["vendor_outcome"] = None
    return clean


def check_vendor(vendor: dict, path: str) -> list:
    if not isinstance(vendor.get("cases"), list):
        raise ToolError(f"{path} has no 'cases' list; refusing to touch it")
    return vendor["cases"]


def cmd_add_case(args) -> int:
    vendor = load_json(args.vendor_json)
    cases = check_vendor(vendor, args.vendor_json)
    record = validate_record(load_json(args.record))
    if any(c.get("case_id") == record["case_id"] for c in cases):
        raise ToolError(f"Case {record['case_id']} is already in the ledger; records are never overwritten", 4)
    cases.append(record)
    write_json_atomic(args.vendor_json, vendor)
    emit({"ok": True, "action": "case_added", "record": record})
    return 0


def cmd_set_outcome(args) -> int:
    text = (args.text or "").strip()
    if not text:
        raise ToolError("Outcome text is empty")
    vendor = load_json(args.vendor_json)
    cases = check_vendor(vendor, args.vendor_json)
    target = next((c for c in cases if c.get("case_id") == args.case_id), None)
    if target is None:
        raise ToolError(f"Case {args.case_id} is not in the ledger", 4)
    if target.get("vendor_outcome") is not None:
        raise ToolError(f"Case {args.case_id} already has a recorded outcome; not overwriting", 4)
    target["vendor_outcome"] = {"text": text, "recorded_by": args.recorded_by, "recorded_at": utc_now_iso()}
    write_json_atomic(args.vendor_json, vendor)
    emit({"ok": True, "action": "outcome_recorded", "case_id": args.case_id, "vendor_outcome": target["vendor_outcome"]})
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-case")
    a.add_argument("vendor_json")
    a.add_argument("--record", required=True, help="JSON file holding the record to append")
    a.set_defaults(fn=cmd_add_case)
    o = sub.add_parser("set-outcome")
    o.add_argument("vendor_json")
    o.add_argument("case_id")
    o.add_argument("--text", required=True)
    o.add_argument("--recorded-by", required=True)
    o.set_defaults(fn=cmd_set_outcome)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    run_cli(main)

# Enforces append-only immutable case sequence

# Blocks duplicate registrations with exit code 4
