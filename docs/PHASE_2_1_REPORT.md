# PHASE 2.1 REPORT — FINANCIAL BOUNDARY AUDIT & CONTROLLED PIPELINE

> **Project**: Overcharge Desk — Evidence-First Vendor Reconciliation  
> **Phase**: Phase 2.1 — Financial Boundary Hardening, Independent Validation & Artifact Separation  
> **Date**: 2026-11-04  
> **Status**: Completed & Fully Verified  

---

## 1. Executive Summary

Phase 2.1 conducted a comprehensive boundary audit of the Overcharge Desk financial verification engine. While Phase 2 established mathematical correctness and fail-closed handling for internal discrepancies, Phase 2.1 closed the remaining operational boundaries:
1. **Removed the Blocked-Draft Override**: Eliminated `--allow-blocked-draft` from `payment_sheet.py`. A blocked audit can never produce a payment recommendation under any circumstances.
2. **Three-Tier Output Artifact Separation**:
   - `VERIFIED` $\to$ `corrected_payment.csv` (only fully verified audits with 100% matched items).
   - `REVIEW_REQUIRED` $\to$ `partial_review.csv` (unresolved items highlighted; strictly disclaims final payment recommendation).
   - `BLOCKED` $\to$ `blocked_review_report.csv` (discrepancy evidence only; contains NO payable columns, values, or recommendations).
3. **Independent Comparison Validation**: Built [`tools/validate_comparison.py`](file:///d:/overcharge%20files/tools/validate_comparison.py) to independently verify comparison JSON schema 2.0.0, line-level arithmetic parity, variance calculations, and totals reconciliation before downstream consumption.
4. **Audit Cryptographic Integrity**: Implemented deterministic canonical serialization (`canonical_json_bytes`) and companion `.sha256` digest files.
5. **In-Engine Source File Verification**: Enforced SHA-256 recalculation and cross-platform path safety directly within [`tools/compare.py`](file:///d:/overcharge%20files/tools/compare.py), making source verification bypasses impossible.
6. **Controlled 9-Stage Pipeline**: Created [`tools/pipeline.py`](file:///d:/overcharge%20files/tools/pipeline.py) orchestrating the end-to-end verification and artifact routing workflow.
7. **Expanded Test Suite**: Added [`tests/test_boundary_audit.py`](file:///d:/overcharge%20files/tests/test_boundary_audit.py) (20 tests). The complete test suite now stands at **101 passing tests in 1.62s** (100% pass rate).

---

## 2. Summary of Changes

### 2.1 Files Created & Modified

| File | Change Type | Purpose |
|---|---|---|
| [`tools/common.py`](file:///d:/overcharge%20files/tools/common.py) | Modified | Hardened `is_safe_relative_path()` for cross-platform backslash/slash traversal prevention; added `canonical_json_bytes()`, `hash_comparison_result()`, `save_comparison_with_digest()`, and `verify_comparison_digest_file()`. |
| [`tools/compare.py`](file:///d:/overcharge%20files/tools/compare.py) | Modified | Integrated direct source file existence and SHA-256 fingerprint validation inside comparison engine; added `source_file`, `source_sha256`, and `source_sha256_verified` to output; added `--save-digest` CLI option. |
| [`tools/payment_sheet.py`](file:///d:/overcharge%20files/tools/payment_sheet.py) | Modified | Removed `--allow-blocked-draft`; strictly restricted execution to fully `VERIFIED` audits with 0 unmatched and 0 discrepancy lines; added upstream `validate_comparison()` check and companion digest verification. |
| [`tools/validate_comparison.py`](file:///d:/overcharge%20files/tools/validate_comparison.py) | Created | Strict independent validator for comparison-result JSON: validates schema 2.0.0, line arithmetic parity, contract math, totals reconciliation, state consistency, and companion digests. |
| [`tools/partial_review.py`](file:///d:/overcharge%20files/tools/partial_review.py) | Created | Generates `partial_review.csv` for `REVIEW_REQUIRED` audits; highlights unresolved items; strictly disclaims final payment approval; refuses `BLOCKED` audits. |
| [`tools/blocked_review_report.py`](file:///d:/overcharge%20files/tools/blocked_review_report.py) | Created | Generates `blocked_review_report.csv` for `BLOCKED` audits; contains discrepancy evidence only; contains NO payable columns, values, or recommendations. |
| [`tools/pipeline.py`](file:///d:/overcharge%20files/tools/pipeline.py) | Created | Canonical 9-stage controlled reconciliation pipeline orchestrating source validation, comparison, digest creation, validation, and authorized artifact routing. |
| [`tests/test_tools.py`](file:///d:/overcharge%20files/tests/test_tools.py) | Modified | Updated test assertions to expect `payment_sheet.py` refusal on `REVIEW_REQUIRED` and test `build_partial_review_rows()`. |
| [`tests/test_financial_adversarial.py`](file:///d:/overcharge%20files/tests/test_financial_adversarial.py) | Modified | Updated Scenarios 25, 33, and 34 to test strict artifact routing and refusal on unverified inputs. |
| [`tests/test_boundary_audit.py`](file:///d:/overcharge%20files/tests/test_boundary_audit.py) | Created | 20 adversarial tests covering all Phase 2.1 boundary scenarios. |
| [`docs/FINANCIAL_BOUNDARY_MODEL.md`](file:///d:/overcharge%20files/docs/FINANCIAL_BOUNDARY_MODEL.md) | Created | Comprehensive specification of the three-tier artifact model, validation rules, digest architecture, and pipeline stages. |

---

## 3. Defects Fixed

1. **Blocked-Draft Override Weakening Fail-Closed Controls (Critical)**:
   - *Previous behavior*: Calling `payment_sheet.py --allow-blocked-draft` generated a payment sheet on a blocked audit, calculating payable amounts for non-discrepancy lines.
   - *New behavior*: `--allow-blocked-draft` is completely removed. `payment_sheet.py` strictly refuses any non-`VERIFIED` audit (exit code 2). Discrepancy reporting is handled exclusively by `blocked_review_report.py`, which has no payable calculations.
2. **Unvalidated Downstream Comparison Results (Critical)**:
   - *Previous behavior*: `payment_sheet.py` checked `ok: true` but did not verify line-level math, totals reconciliation, or state coherence.
   - *New behavior*: [`tools/validate_comparison.py`](file:///d:/overcharge%20files/tools/validate_comparison.py) rigorously validates line arithmetic, contract calculations, variance calculations, and totals consistency before any artifact is created.
3. **Source Validation Bypass in Comparison Engine (High)**:
   - *Previous behavior*: If an agent called `compare.py` directly without running `check_invoice.py`, source fingerprint mismatches or missing files were not detected.
   - *New behavior*: `compare.py` directly recalculates and validates source file SHA-256 against on-disk files. Any missing file or hash mismatch locks status to `BLOCKED`.
4. **Ambiguous Incomplete Payment Sheets (High)**:
   - *Previous behavior*: Unmatched lines generated a payment sheet with an `INCOMPLETE` note in the total row, leaving risk of confusion with approved payment sheets.
   - *New behavior*: `payment_sheet.py` strictly refuses `REVIEW_REQUIRED`. Incomplete invoices must use `tools/partial_review.py` to generate `partial_review.csv`, which explicitly warns that unresolved items are excluded from any settlement.
5. **Cross-Platform Path Traversal (Security)**:
   - *Previous behavior*: `Path(path).parts` on POSIX systems did not split Windows backslashes (`..\..\etc\passwd`).
   - *New behavior*: `is_safe_relative_path()` normalizes backslashes to forward slashes before segment splitting, rejecting traversal, drive letters, and UNC paths across all platforms.

---

## 4. Test Suite Execution & Results

### 4.1 Pytest Execution Output

```powershell
python -m pytest -v
```

```
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.0, pluggy-1.6.0 -- C:\Users\namir\AppData\Local\Programs\Python\Python313\python.exe
cachedir: .pytest_cache
rootdir: D:\overcharge files
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.12.1, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 101 items

tests/test_boundary_audit.py::test_blocked_result_override_rejected PASSED [  0%]
tests/test_boundary_audit.py::test_review_required_passed_to_payment_generator_refused PASSED [  1%]
tests/test_boundary_audit.py::test_blocked_result_passed_to_payment_generator_refused PASSED [  2%]
tests/test_boundary_audit.py::test_validator_detects_missing_line_field PASSED [  3%]
tests/test_boundary_audit.py::test_validator_detects_incorrect_line_variance PASSED [  4%]
tests/test_boundary_audit.py::test_validator_detects_incorrect_contract_total PASSED [  5%]
tests/test_boundary_audit.py::test_validator_detects_tampered_totals PASSED [  6%]
tests/test_boundary_audit.py::test_validator_rejects_invalid_schema_version PASSED [  7%]
tests/test_boundary_audit.py::test_validator_rejects_unknown_line_status PASSED [  8%]
tests/test_boundary_audit.py::test_digest_fails_on_altered_comparison_json PASSED [  9%]
tests/test_boundary_audit.py::test_missing_digest_file_detected PASSED   [ 10%]
tests/test_boundary_audit.py::test_incorrect_digest_is_rejected PASSED   [ 11%]
tests/test_boundary_audit.py::test_source_validation_bypass_attempt_blocked_by_compare PASSED [ 12%]
tests/test_boundary_audit.py::test_backslash_traversal_rejected_cross_platform PASSED [ 13%]
tests/test_boundary_audit.py::test_absolute_path_injection_rejected_cross_platform PASSED [ 14%]
tests/test_boundary_audit.py::test_partial_review_artifact_contains_no_payment_recommendation PASSED [ 15%]
tests/test_boundary_audit.py::test_blocked_review_artifact_contains_no_payable_values PASSED [ 16%]
tests/test_boundary_audit.py::test_pipeline_execution_verified PASSED    [ 17%]
tests/test_boundary_audit.py::test_pipeline_execution_review_required PASSED [ 18%]
tests/test_boundary_audit.py::test_pipeline_execution_blocked PASSED     [ 19%]
tests/test_compare.py::test_demo_case_six_thousand_over PASSED           [ 20%]
tests/test_compare.py::test_exact_demo_invoice_fifty_vs_fifty_six_thousand PASSED [ 21%]
tests/test_compare.py::test_under_billing_is_reported_as_under PASSED    [ 22%]
tests/test_compare.py::test_matching_sku_only_description PASSED         [ 23%]
tests/test_compare.py::test_sku_boundary_does_not_match_longer_sku PASSED [ 24%]
tests/test_compare.py::test_unknown_item_is_unmatched_and_total_incomplete PASSED [ 25%]
tests/test_compare.py::test_rate_not_yet_in_force_is_unmatched PASSED    [ 26%]
tests/test_compare.py::test_rate_history_picks_the_period_in_force PASSED [ 27%]
tests/test_compare.py::test_overlapping_rates_are_refused_not_guessed PASSED [ 28%]
tests/test_compare.py::test_description_matching_two_items_is_ambiguous PASSED [ 29%]
tests/test_compare.py::test_currency_mismatch_stops PASSED               [ 30%]
tests/test_compare.py::test_missing_currency_stops PASSED                [ 31%]
tests/test_compare.py::test_wrong_vendor_stops PASSED                    [ 32%]
tests/test_compare.py::test_vendor_alias_and_case_insensitive PASSED     [ 33%]
tests/test_compare.py::test_missing_quantity_is_unmatched PASSED         [ 34%]
tests/test_compare.py::test_line_total_mismatch_warns PASSED             [ 35%]
tests/test_compare.py::test_stated_total_mismatch_warns PASSED           [ 36%]
tests/test_compare.py::test_no_float_error_on_awkward_decimals PASSED    [ 37%]
tests/test_compare.py::test_half_up_rounding PASSED                      [ 38%]
tests/test_compare.py::test_empty_invoice_is_an_error PASSED             [ 39%]
tests/test_compare.py::test_bad_date_is_an_error PASSED                  [ 40%]
tests/test_financial_adversarial.py::test_scenario_01_correct_invoice PASSED [ 41%]
tests/test_financial_adversarial.py::test_scenario_02_contract_overcharge PASSED [ 42%]
tests/test_financial_adversarial.py::test_scenario_03_contract_undercharge PASSED [ 43%]
tests/test_financial_adversarial.py::test_scenario_04_exact_contract_match PASSED [ 44%]
tests/test_financial_adversarial.py::test_scenario_05_written_line_total_differs_from_qty_times_price PASSED [ 45%]
tests/test_financial_adversarial.py::test_scenario_06_stated_invoice_total_differs_from_written_line_totals PASSED [ 46%]
tests/test_financial_adversarial.py::test_scenario_07_missing_line_total PASSED [ 47%]
tests/test_financial_adversarial.py::test_scenario_08_missing_quantity PASSED [ 48%]
tests/test_financial_adversarial.py::test_scenario_09_zero_quantity PASSED [ 49%]
tests/test_financial_adversarial.py::test_scenario_10_negative_quantity PASSED [ 50%]
tests/test_financial_adversarial.py::test_scenario_11_negative_unit_price PASSED [ 51%]
tests/test_financial_adversarial.py::test_scenario_12_non_finite_numeric_input PASSED [ 52%]
tests/test_financial_adversarial.py::test_scenario_13_invalid_numeric_string PASSED [ 53%]
tests/test_financial_adversarial.py::test_scenario_14_duplicate_line_identifiers PASSED [ 54%]
tests/test_financial_adversarial.py::test_scenario_15_unknown_sku PASSED [ 55%]
tests/test_financial_adversarial.py::test_scenario_16_ambiguous_sku PASSED [ 56%]
tests/test_financial_adversarial.py::test_scenario_17_expired_contract_rate PASSED [ 57%]
tests/test_financial_adversarial.py::test_scenario_18_future_contract_rate PASSED [ 58%]
tests/test_financial_adversarial.py::test_scenario_19_overlapping_contract_rates PASSED [ 59%]
tests/test_financial_adversarial.py::test_scenario_20_currency_mismatch PASSED [ 60%]
tests/test_financial_adversarial.py::test_scenario_21_missing_currency PASSED [ 61%]
tests/test_financial_adversarial.py::test_scenario_22_source_file_missing PASSED [ 62%]
tests/test_financial_adversarial.py::test_scenario_23_source_fingerprint_mismatch PASSED [ 63%]
tests/test_financial_adversarial.py::test_scenario_24_path_traversal_attempt PASSED [ 64%]
tests/test_financial_adversarial.py::test_scenario_25_unmatched_item_mixed_with_matched_items PASSED [ 65%]
tests/test_financial_adversarial.py::test_scenario_26_multiple_discrepancies_in_one_invoice PASSED [ 66%]
tests/test_financial_adversarial.py::test_scenario_27_rounding_boundary_cases PASSED [ 67%]
tests/test_financial_adversarial.py::test_scenario_28_very_large_monetary_values PASSED [ 68%]
tests/test_financial_adversarial.py::test_scenario_29_very_small_monetary_values PASSED [ 69%]
tests/test_financial_adversarial.py::test_scenario_30_formula_injection_in_descriptions PASSED [ 70%]
tests/test_financial_adversarial.py::test_scenario_31_malformed_comparison_json PASSED [ 71%]
tests/test_financial_adversarial.py::test_scenario_32_tampered_comparison_result PASSED [ 72%]
tests/test_financial_adversarial.py::test_scenario_33_payment_sheet_attempt_on_blocked_result PASSED [ 73%]
tests/test_financial_adversarial.py::test_scenario_34_payment_sheet_attempt_on_incomplete_result PASSED [ 74%]
tests/test_financial_adversarial.py::test_scenario_35_goods_subtotal_never_presented_as_complete_settlement PASSED [ 75%]
tests/test_tools.py::test_add_case_appends_and_stamps_time PASSED        [ 76%]
tests/test_tools.py::test_duplicate_case_refused PASSED                  [ 77%]
tests/test_tools.py::test_bad_records_refused[over0] PASSED              [ 78%]
tests/test_tools.py::test_bad_records_refused[over1] PASSED              [ 79%]
tests/test_tools.py::test_bad_records_refused[over2] PASSED              [ 80%]
tests/test_tools.py::test_bad_records_refused[over3] PASSED              [ 81%]
tests/test_tools.py::test_bad_records_refused[over4] PASSED              [ 82%]
tests/test_tools.py::test_bad_records_refused[over5] PASSED              [ 83%]
tests/test_tools.py::test_bad_records_refused[over6] PASSED              [ 84%]
tests/test_tools.py::test_bad_records_refused[over7] PASSED              [ 85%]
tests/test_tools.py::test_rejection_needs_reason PASSED                  [ 86%]
tests/test_tools.py::test_outcome_set_once_and_verbatim PASSED           [ 87%]
tests/test_tools.py::test_outcome_for_unknown_case_refused PASSED        [ 88%]
tests/test_tools.py::test_ledger_refuses_file_without_cases_list PASSED  [ 89%]
tests/test_tools.py::test_payment_sheet_demo_numbers PASSED              [ 90%]
tests/test_tools.py::test_payment_sheet_unmatched_is_marked_incomplete PASSED [ 91%]
tests/test_tools.py::test_payment_sheet_under_billing_pays_as_invoiced PASSED [ 92%]
tests/test_tools.py::test_payment_sheet_blocks_formula_injection PASSED  [ 93%]
tests/test_tools.py::test_payment_sheet_refuses_error_result PASSED      [ 94%]
tests/test_tools.py::test_check_invoice_clean PASSED                     [ 95%]
tests/test_tools.py::test_check_invoice_reports_arithmetic_and_missing PASSED [ 96%]
tests/test_tools.py::test_next_case_id PASSED                            [ 97%]
tests/test_tools.py::test_cli_end_to_end_with_demo_files PASSED          [ 98%]
tests/test_tools.py::test_cli_exit_codes PASSED                          [ 99%]
tests/test_demo_vendor_file_matches_seed PASSED           [100%]

============================= 101 passed in 1.62s =============================
```

---

## 5. Demonstrations of the Three Output States

### 5.1 VERIFIED $\to$ `corrected_payment.csv`

```powershell
python tools/pipeline.py tests/fixtures/example_invoice.json vendors/acme.json demo_out_verified
```

```
Exit: 0
Artifact Generated: demo_out_verified\corrected_payment.csv
Status: VERIFIED
Invoiced: ₹66,000.00 | Payable: ₹60,000.00 | Withheld: ₹6,000.00
```

`corrected_payment.csv`:
```csv
line_no,description,quantity,invoiced_unit_price,contract_unit_price,invoiced_line_total,payable_line_total,withheld_amount,note
1,"Corrugated carton, 5-ply (CC-5)",500,112.00,100.00,56000.00,50000.00,6000.00,"Billed above contract rate: paying contract amount, difference withheld"
2,Pallet wrap roll (PW-1),40,250.00,250.00,10000.00,10000.00,0.00,Matches contract rate
,TOTAL (GOODS ONLY - VERIFIED),,,,66000.00,60000.00,6000.00,Draft for owner review. No payment made. Taxes and freight are unverified per contract terms.
```

---

### 5.2 REVIEW_REQUIRED $\to$ `partial_review.csv`

```powershell
python tools/pipeline.py review_inv.json vendors/acme.json demo_out_review
```

```
Exit: 0
Artifact Generated: demo_out_review\partial_review.csv
Status: REVIEW_REQUIRED
Settlement Status: PAYMENT_RECOMMENDATION_PARTIAL: UNRESOLVED_LINES
```

`partial_review.csv`:
```csv
line_no,description,quantity,invoiced_unit_price,contract_unit_price,invoiced_line_total,contract_coverage_status,unresolved_reason,notes
1,"Corrugated carton, 5-ply (CC-5)",500,112.00,100.00,56000.00,COVERED_BY_CONTRACT,,Contract rate matched (over billing). Not approved for final disbursement.
2,Pallet wrap roll (PW-1),40,250.00,250.00,10000.00,COVERED_BY_CONTRACT,,Contract rate matched (match billing). Not approved for final disbursement.
3,Uncontracted mystery box,,,,100.00,UNMATCHED,no contract item matches this description,UNRESOLVED - requires owner decision
,"TOTAL (REVIEW REQUIRED: 1 unverified line(s), 2 contract-covered line(s))",,,,66100.00,REVIEW_REQUIRED,,INVESTIGATION ARTIFACT ONLY. NOT A FINAL PAYMENT RECOMMENDATION. Unresolved items require owner review and are excluded from any settlement.
```

---

### 5.3 BLOCKED $\to$ `blocked_review_report.csv`

```powershell
python tools/pipeline.py disc_inv.json vendors/acme.json demo_out_blocked
```

```
Exit: 0
Artifact Generated: demo_out_blocked\blocked_review_report.csv
Status: BLOCKED
Settlement Status: PAYMENT_RECOMMENDATION_BLOCKED: SOURCE_DISCREPANCY
```

`blocked_review_report.csv`:
```csv
line_no,description,quantity,invoiced_unit_price,contract_unit_price,invoiced_line_total_as_written,invoiced_line_total_computed,discrepancy_reason,source_ref,verification_status
1,"Corrugated carton, 5-ply (CC-5)",500,112.00,100.00,57000.00,56000.00,quantity x price = 56000.00 != written 57000.00,"invoices/acme-inv-1103.txt, line 1",SOURCE_DISCREPANCY
2,Pallet wrap roll (PW-1),40,250.00,250.00,10000.00,10000.00,"Line arithmetic sound, but audit blocked by invoice-level integrity issues","invoices/acme-inv-1103.txt, line 2",VERIFIED_MATCH
,"TOTAL (BLOCKED AUDIT: 1 discrepancy lines, 2 blocking issues)",,,,,,"INVESTIGATION EVIDENCE ONLY - NO PAYMENT AUTHORIZATION. Issues: Line 1: source arithmetic discrepancy: quantity (500) x unit price (112.00) = 56000.00 but line total is written as 57000.00; Stated total 66000.00 differs from the sum of line totals as written, 67000.00",,AUDIT_BLOCKED
```

*(Notice: zero payable columns, zero payable values).*

---

## 6. Known Limitations & Remaining Risks

1. **Companion Digest vs Cryptographic Signatures**: The `.sha256` digest file guarantees artifact tamper-evidence against accidental edits or filesystem corruption. Proving who created or approved an audit requires authenticated cryptographic signatures or protected database bindings (deferred to Phase 3/4).
2. **Statutory Tax Rates**: The synthetic demo contract covers goods only; statutory GST and freight tariff verification remain unmodeled.
3. **Database Ledger Migration**: The vendor ledger remains append-only JSON pending Phase 3 SQLite migration with hash chains.

---

## 7. Conclusion

Phase 2.1 is **100% complete and fully verified**. The financial verification engine, comparison validator, and artifact generation boundaries are frozen, trustworthy, and mathematically sound.

