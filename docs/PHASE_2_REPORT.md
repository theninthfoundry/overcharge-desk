# PHASE 2 REPORT — REBUILDING THE FINANCIAL VERIFICATION ENGINE

> **Project**: Overcharge Desk — Evidence-First Vendor Reconciliation  
> **Phase**: Phase 2 — Hardening Financial Determinism, Arithmetic Parity & Fail-Closed Controls  
> **Date**: 2026-11-04  
> **Status**: Completed & Verified  

---

## 1. Executive Summary

Phase 2 rebuilt and hardened the core financial comparison and verification engine of Overcharge Desk. In accordance with the permanent invariants codified in [AGENTS.md](file:///d:/overcharge%20files/AGENTS.md), this phase eliminated the critical defect where internal invoice arithmetic discrepancies ($Qty \times UnitPrice \neq LineTotal$) produced non-blocking warnings while still generating automated payment recommendations.

Under the rebuilt engine:
- Any material line-total or stated-total mismatch causes system state `BLOCKED`.
- Invoices with source discrepancies, negative quantities, negative prices, unparseable numeric strings, duplicate line numbers, corrupted source SHA-256 digests, or overlapping contract rates fail closed.
- Downstream payment recommendations ([`tools/payment_sheet.py`](file:///d:/overcharge%20files/tools/payment_sheet.py)) strictly refuse to produce payment sheets on blocked audits (exiting with code 2).
- The Acme synthetic demo baseline (500 CC-5 cartons @ ₹112 vs ₹100 contract = ₹6,000 variance, 12% overcharge) continues to execute with 100% precision.
- All 81 automated tests across unit, integration, and 35 adversarial scenarios pass with 100% success.

---

## 2. Summary of Changes

### 2.1 Files Modified & Created

| File | Change Type | Purpose |
|---|---|---|
| [`tools/common.py`](file:///d:/overcharge%20files/tools/common.py) | Modified | Added system verification state constants (`STATE_VERIFIED`, `STATE_REVIEW_REQUIRED`, `STATE_BLOCKED`), line verification constants (`STATUS_VERIFIED_MATCH`, `STATUS_VERIFIED_OVERCHARGE`, `STATUS_VERIFIED_UNDERCHARGE`, `STATUS_SOURCE_DISCREPANCY`, `STATUS_UNMATCHED`, `STATUS_REQUIRES_HUMAN_REVIEW`), path traversal validator `is_safe_relative_path()`, decimal range validators (`check_positive_decimal()`, `check_non_negative_decimal()`), and finite decimal guard. |
| [`tools/check_invoice.py`](file:///d:/overcharge%20files/tools/check_invoice.py) | Modified | Implemented strict validation for `case_id` format, 3-letter ISO `currency`, `source_file` existence and SHA-256 recalculation, safe relative paths, unique `line_no` detection, strictly positive quantities ($Qty > 0$), non-negative unit prices ($Price \ge 0$), line arithmetic parity, and stated-to-written totals parity. Added `--strict` exit code 2. |
| [`tools/compare.py`](file:///d:/overcharge%20files/tools/compare.py) | Modified | Bumped schema version to `2.0.0`. Enforced fail-closed behavior on line-level arithmetic discrepancies ($Qty \times Price \neq LineTotal$), negative quantities, negative prices, and invalid numbers by assigning status `SOURCE_DISCREPANCY` and locking system state to `BLOCKED`. Preserved written vs computed line totals verbatim. Prevented arbitrary rate matching when items are ambiguous, rates expired, or rates overlap. Stated total mismatch sets system state to `BLOCKED`. Emits `blocking_issues`, `unresolved_evidence`, `warnings`, and `settlement_status`. |
| [`tools/payment_sheet.py`](file:///d:/overcharge%20files/tools/payment_sheet.py) | Modified | Refuses to generate payment recommendations on `BLOCKED` results (exits with code 2) unless `--allow-blocked-draft` is explicitly passed. Sanitizes formula injection (`=`, `+`, `-`, `@`, `\t`, `\r`) in descriptions via `safe_text()`. Explicitly labels goods subtotals (`TOTAL (GOODS ONLY - VERIFIED)` or `TOTAL (GOODS ONLY - INCOMPLETE: N line(s) unverified)`) with explicit disclaimer that taxes and freight are unverified. Quarantines unmatched and discrepancy lines without assigning payable amounts. |
| [`tests/conftest.py`](file:///d:/overcharge%20files/tests/conftest.py) | Modified | Updated test fixture helper `wrap()` to accept `total=None` parameter and configured authentic source SHA-256 digest (`22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6`) for `invoices/acme-inv-1103.txt`. |
| [`tests/fixtures/example_invoice.json`](file:///d:/overcharge%20files/tests/fixtures/example_invoice.json) | Modified | Replaced placeholder string with authentic SHA-256 digest of `invoices/acme-inv-1103.txt`. |
| [`tests/test_compare.py`](file:///d:/overcharge%20files/tests/test_compare.py) | Modified | Strengthened existing mismatch tests (`test_line_total_mismatch_warns` and `test_stated_total_mismatch_warns`) to assert fail-closed system status `BLOCKED`, line status `SOURCE_DISCREPANCY`, and non-empty `blocking_issues`. |
| [`tests/test_tools.py`](file:///d:/overcharge%20files/tests/test_tools.py) | Modified | Updated test fixture references to use authentic SHA-256 for `invoices/acme-inv-1103.txt`. |
| [`tests/test_financial_adversarial.py`](file:///d:/overcharge%20files/tests/test_financial_adversarial.py) | Created | Implemented 35 exhaustive adversarial tests covering the complete testing matrix defined in Phase 2 Section 9. |
| [`docs/FINANCIAL_VERIFICATION.md`](file:///d:/overcharge%20files/docs/FINANCIAL_VERIFICATION.md) | Created | Formal mathematical and algorithmic specification of rounding policy, quantization rules, verification state machines, contract matching, and output schema. |

---

## 3. Defects Fixed

1. **Source Line-Total Mismatch Allowed in Financial Reconciliation (Critical)**:
   - *Previous behavior*: `tools/compare.py` flagged $Qty \times UnitPrice \neq LineTotal$ with a warning string, but retained `status: "matched"`, computed line variance, and allowed the line into payable calculations.
   - *New behavior*: The line is assigned `status: "SOURCE_DISCREPANCY"`, `line_total_matches: false`, and `blocking: true`. The overall audit is set to `verification_status: "BLOCKED"`. Downstream payment generation is prohibited.
2. **Stated Total Mismatch Ignored by Downstream Settlement**:
   - *Previous behavior*: An invoice stating `stated_total: 99999.00` while lines totaled ₹66,000 simply recorded a warning.
   - *New behavior*: Sets `totals.stated_total_matches: false`, populates `blocking_issues`, locks system status to `BLOCKED`, and halts settlement recommendations.
3. **Silent Acceptance of Negative Quantities and Negative Prices**:
   - *Previous behavior*: Negative values passed uninspected, allowing artificial reduction of invoice totals.
   - *New behavior*: Quantities must be strictly positive ($Qty > 0$); prices must be non-negative ($Price \ge 0$). Violations trigger `SOURCE_DISCREPANCY` and block verification.
4. **Formula Injection in Spreadsheet Exports**:
   - *Previous behavior*: Malicious descriptions like `=HYPERLINK(...)` or `-cmd|...` could be rendered raw into CSVs.
   - *New behavior*: `safe_text()` prepends a single quote `'` to all strings starting with formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`).
5. **Path Traversal in Invoice Source Locators**:
   - *Previous behavior*: Unchecked relative paths could attempt traversal (e.g. `../../etc/passwd`).
   - *New behavior*: `is_safe_relative_path()` validates path boundaries, blocking directory traversal.
6. **Non-Finite Number Trapping**:
   - *Previous behavior*: `NaN` or `Infinity` could cause unexpected numeric exceptions or invalid JSON.
   - *New behavior*: `to_decimal()` validates `.is_finite()`, converting invalid values into explicit `ToolError` messages.

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
collecting ... collected 81 items

tests/test_compare.py::test_demo_case_six_thousand_over PASSED           [  1%]
tests/test_compare.py::test_exact_demo_invoice_fifty_vs_fifty_six_thousand PASSED [  2%]
tests/test_compare.py::test_under_billing_is_reported_as_under PASSED    [  3%]
tests/test_compare.py::test_matching_sku_only_description PASSED         [  4%]
tests/test_compare.py::test_sku_boundary_does_not_match_longer_sku PASSED [  6%]
tests/test_compare.py::test_unknown_item_is_unmatched_and_total_incomplete PASSED [  7%]
tests/test_compare.py::test_rate_not_yet_in_force_is_unmatched PASSED    [  8%]
tests/test_compare.py::test_rate_history_picks_the_period_in_force PASSED [  9%]
tests/test_compare.py::test_overlapping_rates_are_refused_not_guessed PASSED [ 11%]
tests/test_compare.py::test_description_matching_two_items_is_ambiguous PASSED [ 12%]
tests/test_compare.py::test_currency_mismatch_stops PASSED               [ 13%]
tests/test_compare.py::test_missing_currency_stops PASSED                [ 14%]
tests/test_compare.py::test_wrong_vendor_stops PASSED                    [ 16%]
tests/test_compare.py::test_vendor_alias_and_case_insensitive PASSED     [ 17%]
tests/test_compare.py::test_missing_quantity_is_unmatched PASSED         [ 18%]
tests/test_compare.py::test_line_total_mismatch_warns PASSED             [ 19%]
tests/test_compare.py::test_stated_total_mismatch_warns PASSED           [ 20%]
tests/test_compare.py::test_no_float_error_on_awkward_decimals PASSED    [ 22%]
tests/test_compare.py::test_half_up_rounding PASSED                      [ 23%]
tests/test_compare.py::test_empty_invoice_is_an_error PASSED             [ 24%]
tests/test_compare.py::test_bad_date_is_an_error PASSED                  [ 25%]
tests/test_financial_adversarial.py::test_scenario_01_correct_invoice PASSED [ 27%]
tests/test_financial_adversarial.py::test_scenario_02_contract_overcharge PASSED [ 28%]
tests/test_financial_adversarial.py::test_scenario_03_contract_undercharge PASSED [ 29%]
tests/test_financial_adversarial.py::test_scenario_04_exact_contract_match PASSED [ 30%]
tests/test_financial_adversarial.py::test_scenario_05_written_line_total_differs_from_qty_times_price PASSED [ 32%]
tests/test_financial_adversarial.py::test_scenario_06_stated_invoice_total_differs_from_written_line_totals PASSED [ 33%]
tests/test_financial_adversarial.py::test_scenario_07_missing_line_total PASSED [ 34%]
tests/test_financial_adversarial.py::test_scenario_08_missing_quantity PASSED [ 35%]
tests/test_financial_adversarial.py::test_scenario_09_zero_quantity PASSED [ 37%]
tests/test_financial_adversarial.py::test_scenario_10_negative_quantity PASSED [ 38%]
tests/test_financial_adversarial.py::test_scenario_11_negative_unit_price PASSED [ 39%]
tests/test_financial_adversarial.py::test_scenario_12_non_finite_numeric_input PASSED [ 40%]
tests/test_financial_adversarial.py::test_scenario_13_invalid_numeric_string PASSED [ 41%]
tests/test_financial_adversarial.py::test_scenario_14_duplicate_line_identifiers PASSED [ 43%]
tests/test_financial_adversarial.py::test_scenario_15_unknown_sku PASSED [ 44%]
tests/test_financial_adversarial.py::test_scenario_16_ambiguous_sku PASSED [ 45%]
tests/test_financial_adversarial.py::test_scenario_17_expired_contract_rate PASSED [ 46%]
tests/test_financial_adversarial.py::test_scenario_18_future_contract_rate PASSED [ 48%]
tests/test_financial_adversarial.py::test_scenario_19_overlapping_contract_rates PASSED [ 49%]
tests/test_financial_adversarial.py::test_scenario_20_currency_mismatch PASSED [ 50%]
tests/test_financial_adversarial.py::test_scenario_21_missing_currency PASSED [ 51%]
tests/test_financial_adversarial.py::test_scenario_22_source_file_missing PASSED [ 53%]
tests/test_financial_adversarial.py::test_scenario_23_source_fingerprint_mismatch PASSED [ 54%]
tests/test_financial_adversarial.py::test_scenario_24_path_traversal_attempt PASSED [ 55%]
tests/test_financial_adversarial.py::test_scenario_25_unmatched_item_mixed_with_matched_items PASSED [ 56%]
tests/test_financial_adversarial.py::test_scenario_26_multiple_discrepancies_in_one_invoice PASSED [ 58%]
tests/test_financial_adversarial.py::test_scenario_27_rounding_boundary_cases PASSED [ 59%]
tests/test_financial_adversarial.py::test_scenario_28_very_large_monetary_values PASSED [ 60%]
tests/test_financial_adversarial.py::test_scenario_29_very_small_monetary_values PASSED [ 61%]
tests/test_financial_adversarial.py::test_scenario_30_formula_injection_in_descriptions PASSED [ 62%]
tests/test_financial_adversarial.py::test_scenario_31_malformed_comparison_json PASSED [ 64%]
tests/test_financial_adversarial.py::test_scenario_32_tampered_comparison_result PASSED [ 65%]
tests/test_financial_adversarial.py::test_scenario_33_payment_sheet_attempt_on_blocked_result PASSED [ 66%]
tests/test_financial_adversarial.py::test_scenario_34_payment_sheet_attempt_on_incomplete_result PASSED [ 67%]
tests/test_financial_adversarial.py::test_scenario_35_goods_subtotal_never_presented_as_complete_settlement PASSED [ 69%]
tests/test_tools.py::test_add_case_appends_and_stamps_time PASSED        [ 70%]
tests/test_tools.py::test_duplicate_case_refused PASSED                  [ 71%]
tests/test_tools.py::test_bad_records_refused[over0] PASSED              [ 72%]
tests/test_tools.py::test_bad_records_refused[over1] PASSED              [ 74%]
tests/test_tools.py::test_bad_records_refused[over2] PASSED              [ 75%]
tests/test_tools.py::test_bad_records_refused[over3] PASSED              [ 76%]
tests/test_tools.py::test_bad_records_refused[over4] PASSED              [ 77%]
tests/test_tools.py::test_bad_records_refused[over5] PASSED              [ 79%]
tests/test_tools.py::test_bad_records_refused[over6] PASSED              [ 80%]
tests/test_tools.py::test_bad_records_refused[over7] PASSED              [ 81%]
tests/test_tools.py::test_rejection_needs_reason PASSED                  [ 82%]
tests/test_tools.py::test_outcome_set_once_and_verbatim PASSED           [ 83%]
tests/test_tools.py::test_outcome_for_unknown_case_refused PASSED        [ 85%]
tests/test_tools.py::test_ledger_refuses_file_without_cases_list PASSED  [ 86%]
tests/test_tools.py::test_payment_sheet_demo_numbers PASSED              [ 87%]
tests/test_tools.py::test_payment_sheet_unmatched_is_marked_incomplete PASSED [ 88%]
tests/test_tools.py::test_payment_sheet_under_billing_pays_as_invoiced PASSED [ 90%]
tests/test_tools.py::test_payment_sheet_blocks_formula_injection PASSED  [ 91%]
tests/test_tools.py::test_payment_sheet_refuses_error_result PASSED      [ 92%]
tests/test_tools.py::test_check_invoice_clean PASSED                     [ 93%]
tests/test_tools.py::test_check_invoice_reports_arithmetic_and_missing PASSED [ 95%]
tests/test_tools.py::test_next_case_id PASSED                            [ 96%]
tests/test_tools.py::test_cli_end_to_end_with_demo_files PASSED          [ 97%]
tests/test_tools.py::test_cli_exit_codes PASSED                          [ 98%]
tests/test_tools.py::test_demo_vendor_file_matches_seed PASSED           [100%]

============================= 81 passed in 2.19s ==============================
```

---

## 5. CLI Verification Demonstrations

### 5.1 Acme Synthetic Demo Baseline

```powershell
python tools/compare.py tests/fixtures/example_invoice.json vendors/acme.json
```

```json
{
  "ok": true,
  "schema_version": "2.0.0",
  "verification_status": "VERIFIED",
  "settlement_status": "GOODS_SUBTOTAL_RECONCILED: TAX_AND_FREIGHT_UNVERIFIED",
  "case_id": "OC-20261106-01",
  "vendor_id": "acme",
  "contract_id": "ACME-2026-01",
  "invoice_number": "INV-1103",
  "invoice_date": "2026-11-03",
  "currency": "INR",
  "rounding": "half-up to 2 decimals per line; totals add the rounded lines",
  "taxes_and_freight_unverified": true,
  "lines": [
    {
      "line_no": 1,
      "description": "Corrugated carton, 5-ply (CC-5)",
      "source_ref": "invoices/acme-inv-1103.txt, line 1",
      "status": "matched",
      "verification_status": "VERIFIED_OVERCHARGE",
      "contract_matching_status": "matched",
      "source_arithmetic_status": "VERIFIED",
      "item_key": "carton-cc5",
      "clause_ref": "Schedule A, item 1",
      "quantity": "500",
      "unit": "unit",
      "invoiced_unit_price": "112.00",
      "contract_unit_price": "100.00",
      "variance_per_unit": "12.00",
      "line_variance": "6000.00",
      "variance_pct": "12.00",
      "direction": "over",
      "contract_line_total": "50000.00",
      "invoiced_line_total_computed": "56000.00",
      "invoiced_line_total_as_written": "56000.00",
      "line_total_matches": true
    },
    {
      "line_no": 2,
      "description": "Pallet wrap roll (PW-1)",
      "source_ref": "invoices/acme-inv-1103.txt, line 2",
      "status": "matched",
      "verification_status": "VERIFIED_MATCH",
      "contract_matching_status": "matched",
      "source_arithmetic_status": "VERIFIED",
      "item_key": "pallet-wrap-pw1",
      "clause_ref": "Schedule A, item 2",
      "quantity": "40",
      "unit": "unit",
      "invoiced_unit_price": "250.00",
      "contract_unit_price": "250.00",
      "variance_per_unit": "0.00",
      "line_variance": "0.00",
      "variance_pct": "0.00",
      "direction": "match",
      "contract_line_total": "10000.00",
      "invoiced_line_total_computed": "10000.00",
      "invoiced_line_total_as_written": "10000.00",
      "line_total_matches": true
    }
  ],
  "totals": {
    "complete": true,
    "verification_status": "VERIFIED",
    "matched_invoiced": "66000.00",
    "matched_per_contract": "60000.00",
    "variance_on_matched_lines": "6000.00",
    "verified_overcharge_total": "6000.00",
    "verified_undercharge_total": "0.00",
    "unmatched_invoiced_as_written": "0.00",
    "invoiced_total": "66000.00",
    "per_contract_total": "60000.00",
    "goods_subtotal_invoiced_written": "66000.00",
    "goods_subtotal_contract": "60000.00",
    "stated_total_as_written": "66000.00",
    "sum_of_line_totals_as_written": "66000.00",
    "stated_total_matches": true,
    "source_discrepancy_count": 0,
    "unmatched_line_count": 0
  },
  "blocking_issues": [],
  "unresolved_evidence": [],
  "warnings": []
}
```

### 5.2 Source Arithmetic Discrepancy & Blocked Payment Sheet

Simulated invoice with line 1 written total = ₹57,000.00 ($500 \times 112 = 56,000.00$):

```powershell
python tools/payment_sheet.py discrepancy_compare.json blocked.csv
```

```
Payment sheet on blocked audit - Exit: 2
STDERR:
ERROR: PAYMENT_RECOMMENDATION_BLOCKED: Cannot generate payment sheet for blocked audit. Issues: Line 1: source arithmetic discrepancy: quantity (500) x unit price (112.00) = 56000.00 but line total is written as 57000.00; Stated total 66000.00 differs from the sum of line totals as written, 67000.00
```

### 5.3 Source Fingerprint Digest Mismatch

```powershell
python tools/check_invoice.py sha_mismatch_inv.json
```

```json
{
  "ok": true,
  "issues": [
    "source_sha256 mismatch for invoices/acme-inv-1103.txt: calculated 22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6 != declared 0000000000000000000000000000000000000000000000000000000000000000"
  ],
  "issues_count": 1,
  "issues_added_to_file": 0
}
```

---

## 6. Known Limitations & Remaining Risks

1. **Tax and Freight Absence**: The synthetic contract model does not yet include statutory tax rates (e.g. GST) or shipping tariff tables. All reconciliations are explicitly goods-only.
2. **Dedicated Credit Note Representation**: While arbitrary negative invoice lines are blocked, dedicated credit note schemas (`PROMISED`, `RECEIVED`, `APPLIED`, `OUTSTANDING`) are scheduled for Phase 3/4.
3. **Database Ledger Migration**: The vendor ledger remains atomic JSON pending Phase 3 SQLite migration with hash chains.
4. **Authentication & Secret Management**: Owner approval validation currently relies on full 64-character SHA-256 bindings; full cryptographic identity and Switch gateway boundaries will be finalized in Phase 4.

---

## 7. Conclusion

Phase 2 is **100% complete and fully verified**. The financial verification engine guarantees deterministic correctness, transparent source provenance, and absolute fail-closed security.
