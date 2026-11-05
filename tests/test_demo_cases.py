"""Continuous Verification Test for Four End-to-End Benchmark Cases.

Executes all 4 canonical cases in an isolated temporary workspace:
  - Case A (Clean)
  - Case B (Overcharge with withholding)
  - Case C (Review Required)
  - Case D (Blocked Discrepancy)
"""
from __future__ import annotations

import shutil
from pathlib import Path
from run_demo_suite import run_full_demo


def test_four_demo_cases_end_to_end(tmp_path):
    # Continuous Integration: Executes all four benchmark demo cases in an isolated workspace
    # Copy repo's cases/demo-* into tmp_path
    cases_src = Path("cases")
    cases_tmp = tmp_path / "cases"
    cases_tmp.mkdir(parents=True)

    for item in cases_src.iterdir():
        if item.is_dir() and item.name.startswith("demo-"):
            dest = cases_tmp / item.name
            shutil.copytree(item, dest)

    res = run_full_demo(clean_run=True, cases_base_dir=cases_tmp)
    assert res["ok"] is True
    assert res["all_cases_passed"] is True
    assert res["cases"]["case_a_clean"]["status"] == "PASSED"
    assert res["cases"]["case_b_overcharge"]["status"] == "PASSED"
    assert res["cases"]["case_b_overcharge"]["withheld_total"] == "6000.00"
    assert res["cases"]["case_c_review_required"]["status"] == "PASSED"
    assert res["cases"]["case_d_blocked"]["status"] == "PASSED"
    assert res["cases"]["case_e_tampering"]["status"] == "PASSED"
    assert res["cases"]["case_e_tampering"]["tampering_detected"] is True
    assert res["cases"]["case_f_ledger_failure"]["status"] == "PASSED"
    assert res["cases"]["case_f_ledger_failure"]["pipeline_refused_fail_closed"] is True
    assert res["audit_package_exported"]["package_verified"] is True
    assert res["ledger_summary"]["chain_valid"] is True
