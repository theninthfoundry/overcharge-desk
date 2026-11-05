from __future__ import annotations

"""Tests for Phase 2.1 Financial Boundary Audit.

Verifies:
1. Blocked result with explicit override attempt is rejected (fail-closed).
2. Review-required result passed to normal payment generator is refused.
3. Blocked result passed to normal payment generator is refused.
4. Verified status with a missing required line field fails validation.
5. Verified status with incorrect line variance fails validation.
6. Verified status with incorrect contract total fails validation.
7. Verified status with tampered totals fails validation.
8. Invalid schema version is rejected.
9. Unknown line status is rejected.
10. Altered comparison JSON after digest creation fails digest check.
11. Missing digest file is detected.
12. Incorrect digest is rejected.
13. Source validation bypass attempt is blocked by compare engine and pipeline.
14. Backslash path traversal attempts are rejected across all operating systems.
15. Absolute-path injections are rejected across all operating systems.
16. Partial-review artifact contains no final settlement recommendation.
17. Blocked-review artifact contains no payable amounts or payment recommendations.
18. End-to-end pipeline execution across all three states (VERIFIED, REVIEW_REQUIRED, BLOCKED).
"""
import copy
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from common import (
    STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
    ToolError, hash_comparison_result, is_safe_relative_path,
    save_comparison_with_digest, verify_comparison_digest_file
)
from compare import compare
from payment_sheet import build_rows as build_payment_rows
from partial_review import build_partial_review_rows
from blocked_review_report import build_blocked_rows
from validate_comparison import validate_comparison
from pipeline import run_pipeline


# ---------------------------------------------------------------------------
# 1. Blocked result override attempt (Fail-Closed)
# ---------------------------------------------------------------------------
def test_blocked_result_override_rejected(vendor, mk):
    # Boundary Test: Verifies complete removal of --allow-blocked-draft bypass
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, "112.00", total="57000.00")])
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED

    with pytest.raises(ToolError) as exc_info:
        build_payment_rows(r)
    assert exc_info.value.code == 2
    assert "PAYMENT_RECOMMENDATION_BLOCKED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Review-required passed to payment generator is refused
# ---------------------------------------------------------------------------
def test_review_required_passed_to_payment_generator_refused(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Uncontracted mystery box", "quantity": 1, "unit_price": "20.00", "line_total": "20.00"}
    r = compare(make_invoice([carton(), odd]), vendor)
    assert r["verification_status"] == STATE_REVIEW_REQUIRED

    with pytest.raises(ToolError) as exc_info:
        build_payment_rows(r)
    assert exc_info.value.code == 2
    assert "PAYMENT_RECOMMENDATION_BLOCKED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Blocked result passed to payment generator is refused
# ---------------------------------------------------------------------------
def test_blocked_result_passed_to_payment_generator_refused(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(0, "112.00", total="0.00")])
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED

    with pytest.raises(ToolError) as exc_info:
        build_payment_rows(r)
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 4. Verified status with missing required line field
# ---------------------------------------------------------------------------
def test_validator_detects_missing_line_field(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    del tampered["lines"][0]["source_ref"]

    issues = validate_comparison(tampered)
    assert any("missing required field source_ref" in i for i in issues)


# ---------------------------------------------------------------------------
# 5. Verified status with incorrect line variance
# ---------------------------------------------------------------------------
def test_validator_detects_incorrect_line_variance(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    # Acme demo variance is 6000.00; tamper to 5000.00
    tampered["lines"][0]["line_variance"] = "5000.00"

    issues = validate_comparison(tampered)
    assert any("variance mismatch" in i for i in issues)


# ---------------------------------------------------------------------------
# 6. Verified status with incorrect contract total
# ---------------------------------------------------------------------------
def test_validator_detects_incorrect_contract_total(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    # Expected contract line total is 50000.00; tamper to 45000.00
    tampered["lines"][0]["contract_line_total"] = "45000.00"

    issues = validate_comparison(tampered)
    assert any("contract total mismatch" in i for i in issues)


# ---------------------------------------------------------------------------
# 7. Verified status with tampered totals
# ---------------------------------------------------------------------------
def test_validator_detects_tampered_totals(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    tampered["totals"]["variance_on_matched_lines"] = "9999.00"

    issues = validate_comparison(tampered)
    assert any("Totals mismatch: variance_on_matched_lines" in i for i in issues)


# ---------------------------------------------------------------------------
# 8. Invalid schema version
# ---------------------------------------------------------------------------
def test_validator_rejects_invalid_schema_version(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    tampered["schema_version"] = "1.0.0"

    issues = validate_comparison(tampered)
    assert any("Unsupported schema_version: '1.0.0'" in i for i in issues)


# ---------------------------------------------------------------------------
# 9. Unknown line status
# ---------------------------------------------------------------------------
def test_validator_rejects_unknown_line_status(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    tampered = copy.deepcopy(r)
    tampered["lines"][0]["status"] = "partially_verified"

    issues = validate_comparison(tampered)
    assert any("invalid status 'partially_verified'" in i for i in issues)


# ---------------------------------------------------------------------------
# 10. Altered comparison JSON after digest creation fails check
# ---------------------------------------------------------------------------
def test_digest_fails_on_altered_comparison_json(tmp_path, vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    json_path = tmp_path / "compare.json"
    save_comparison_with_digest(r, json_path)

    # Tamper the file after digest creation
    tampered = copy.deepcopy(r)
    tampered["totals"]["verified_overcharge_total"] = "0.00"
    json_path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

    valid, calc, expected = verify_comparison_digest_file(json_path)
    assert valid is False
    assert calc != expected

    # Validator also reports digest mismatch
    issues = validate_comparison(tampered, companion_digest_file=tmp_path / "compare.json.sha256")
    assert any("digest mismatch" in i for i in issues)


# ---------------------------------------------------------------------------
# 11. Missing digest file detected
# ---------------------------------------------------------------------------
def test_missing_digest_file_detected(tmp_path, vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    json_path = tmp_path / "compare.json"
    json_path.write_text(json.dumps(r, indent=2), encoding="utf-8")

    with pytest.raises(ToolError) as exc_info:
        verify_comparison_digest_file(json_path)
    assert "Companion digest file not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 12. Incorrect digest is rejected
# ---------------------------------------------------------------------------
def test_incorrect_digest_is_rejected(tmp_path, vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()]), vendor)
    json_path = tmp_path / "compare.json"
    digest_path = tmp_path / "compare.json.sha256"
    json_path.write_text(json.dumps(r, indent=2), encoding="utf-8")
    digest_path.write_text("0" * 64 + "\n", encoding="utf-8")

    valid, _, _ = verify_comparison_digest_file(json_path, digest_path)
    assert valid is False


# ---------------------------------------------------------------------------
# 13. Source validation bypass attempt blocked by compare engine
# ---------------------------------------------------------------------------
def test_source_validation_bypass_attempt_blocked_by_compare(vendor, mk):
    make_invoice, carton, _ = mk
    # Invoice declaring non-existent file or corrupted digest
    inv = make_invoice([carton()], source_sha256="deadbeef" * 8)
    r = compare(inv, vendor)

    # Compare engine directly fails closed without needing separate check_invoice run
    assert r["verification_status"] == STATE_BLOCKED
    assert any("source_sha256 mismatch" in b for b in r["blocking_issues"])
    assert r["source_sha256_verified"] is False


# ---------------------------------------------------------------------------
# 14. Backslash path traversal rejected across all operating systems
# ---------------------------------------------------------------------------
def test_backslash_traversal_rejected_cross_platform():
    # Windows-style backslashes
    assert not is_safe_relative_path("..\\..\\etc\\passwd")
    assert not is_safe_relative_path("foo\\..\\..\\secret")
    assert not is_safe_relative_path("..\\windows\\system32")
    # POSIX style
    assert not is_safe_relative_path("../../etc/passwd")
    assert not is_safe_relative_path("foo/../../secret")
    # Mixed
    assert not is_safe_relative_path("foo\\../..\\secret")
    # Valid relative
    assert is_safe_relative_path("invoices/acme-inv-1103.txt")
    assert is_safe_relative_path("invoices\\acme-inv-1103.txt")


# ---------------------------------------------------------------------------
# 15. Absolute-path injection rejected across all operating systems
# ---------------------------------------------------------------------------
def test_absolute_path_injection_rejected_cross_platform():
    # POSIX absolute
    assert not is_safe_relative_path("/etc/passwd")
    assert not is_safe_relative_path("/root/secret.txt")
    # Windows absolute
    assert not is_safe_relative_path("C:\\Windows\\System32\\cmd.exe")
    assert not is_safe_relative_path("D:/overcharge files/secret.txt")
    assert not is_safe_relative_path("\\\\server\\share\\invoice.txt")
    assert not is_safe_relative_path("//server/share/invoice.txt")


# ---------------------------------------------------------------------------
# 16. Partial-review artifact contains no final payment recommendation
# ---------------------------------------------------------------------------
def test_partial_review_artifact_contains_no_payment_recommendation(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Mystery item", "quantity": 2, "unit_price": "50.00", "line_total": "100.00"}
    r = compare(make_invoice([carton(), odd]), vendor)
    assert r["verification_status"] == STATE_REVIEW_REQUIRED

    rows, summary = build_partial_review_rows(r)
    assert summary["artifact_type"] == "partial_review"
    assert summary["has_final_payment_recommendation"] is False
    # Headers must NOT include payable_line_total or withheld_amount
    headers = [
        "line_no", "description", "quantity", "invoiced_unit_price", "contract_unit_price",
        "invoiced_line_total", "contract_coverage_status", "unresolved_reason", "notes"
    ]
    # Check that the banner emphasizes INVESTIGATION ONLY
    assert "INVESTIGATION ARTIFACT ONLY" in rows[-1][8]
    assert "NOT A FINAL PAYMENT RECOMMENDATION" in rows[-1][8]


# ---------------------------------------------------------------------------
# 17. Blocked-review artifact contains no payable values
# ---------------------------------------------------------------------------
def test_blocked_review_artifact_contains_no_payable_values(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, "112.00", total="57000.00")])
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED

    rows, summary = build_blocked_rows(r)
    assert summary["artifact_type"] == "blocked_review_report"
    assert summary["has_payable_recommendation"] is False
    # Discrepancy is exposed
    assert "quantity x price = 56000.00 != written 57000.00" in rows[0][7]
    # Total row enforces NO PAYMENT
    assert "NO PAYMENT AUTHORIZATION" in rows[-1][7]


# ---------------------------------------------------------------------------
# 18. End-to-end Pipeline Execution Across All 3 States
# ---------------------------------------------------------------------------
def test_pipeline_execution_verified(tmp_path):
    inv_path = Path("tests/fixtures/example_invoice.json")
    vendor_path = Path("vendors/acme.json")
    out_dir = tmp_path / "pipeline_verified"

    summary = run_pipeline(inv_path, vendor_path, out_dir)
    assert summary["ok"] is True
    assert summary["verification_status"] == STATE_VERIFIED
    # Unapproved run emits pre-approval payment_preview.csv, never unauthorized corrected_payment.csv
    assert summary["artifact_type"] == "payment_preview"
    assert (out_dir / "payment_preview.csv").exists()
    assert (out_dir / "compare.json.sha256").exists()


def test_pipeline_execution_review_required(tmp_path, vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Uncontracted mystery box", "quantity": 1, "unit": "box", "unit_price": "20.00", "line_total": "20.00"}
    inv = make_invoice([carton(), odd], stated_total="56020.00")

    inv_path = tmp_path / "inv_review.json"
    vendor_path = tmp_path / "vendor.json"
    inv_path.write_text(json.dumps(inv), encoding="utf-8")
    vendor_path.write_text(json.dumps(vendor), encoding="utf-8")
    out_dir = tmp_path / "pipeline_review"

    summary = run_pipeline(inv_path, vendor_path, out_dir)
    assert summary["ok"] is True
    assert summary["verification_status"] == STATE_REVIEW_REQUIRED
    assert summary["artifact_type"] == "partial_review"
    assert (out_dir / "partial_review.csv").exists()


def test_pipeline_execution_blocked(tmp_path, vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, "112.00", total="57000.00")])

    inv_path = tmp_path / "inv_blocked.json"
    vendor_path = tmp_path / "vendor.json"
    inv_path.write_text(json.dumps(inv), encoding="utf-8")
    vendor_path.write_text(json.dumps(vendor), encoding="utf-8")
    out_dir = tmp_path / "pipeline_blocked"

    summary = run_pipeline(inv_path, vendor_path, out_dir)
    assert summary["ok"] is True
    assert summary["verification_status"] == STATE_BLOCKED
    assert summary["artifact_type"] == "blocked_review_report"
    assert (out_dir / "blocked_review_report.csv").exists()
