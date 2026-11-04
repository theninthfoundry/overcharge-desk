"""Adversarial and Edge-Case Tests for the Overcharge Desk Financial Engine.

Covers all 35 required scenarios from Phase 2 Section 9:
1. Correct invoice.
2. Contract overcharge.
3. Contract undercharge.
4. Exact contract match.
5. Written line total differs from quantity x unit price.
6. Stated invoice total differs from written line totals.
7. Missing line total.
8. Missing quantity.
9. Zero quantity.
10. Negative quantity.
11. Negative unit price.
12. Non-finite numeric input.
13. Invalid numeric string.
14. Duplicate line identifiers.
15. Unknown SKU.
16. Ambiguous SKU.
17. Expired contract rate.
18. Future contract rate.
19. Overlapping contract rates.
20. Currency mismatch.
21. Missing currency.
22. Source file missing.
23. Source fingerprint mismatch.
24. Path traversal attempt.
25. Unmatched item mixed with matched items.
26. Multiple discrepancies in one invoice.
27. Rounding boundary cases.
28. Very large monetary values.
29. Very small monetary values.
30. Formula injection in descriptions.
31. Malformed comparison JSON.
32. Tampered comparison result.
33. Payment-sheet attempt on a blocked result.
34. Payment-sheet attempt on an incomplete result.
35. Goods subtotal incorrectly presented as complete settlement.
"""
from decimal import Decimal
import pytest

from common import (
    STATE_BLOCKED, STATE_REVIEW_REQUIRED, STATE_VERIFIED,
    STATUS_SOURCE_DISCREPANCY, STATUS_UNMATCHED,
    ToolError, is_safe_relative_path, q2, to_decimal
)
from check_invoice import find_issues
from compare import compare
from payment_sheet import build_rows, safe_text


# ---------------------------------------------------------------------------
# 1. Correct Invoice
# ---------------------------------------------------------------------------
def test_scenario_01_correct_invoice(vendor, mk):
    make_invoice, carton, wrap = mk
    # 500 cartons at contract 100.00 = 50000.00
    # 40 rolls at contract 250.00 = 10000.00
    # Stated total = 60000.00
    inv = make_invoice([
        carton(500, "100.00", total="50000.00"),
        wrap(40, "250.00", total="10000.00")
    ], stated_total="60000.00")
    
    r = compare(inv, vendor)
    assert r["ok"] is True
    assert r["verification_status"] == STATE_VERIFIED
    assert r["settlement_status"] == "GOODS_SUBTOTAL_RECONCILED: TAX_AND_FREIGHT_UNVERIFIED"
    assert r["totals"]["complete"] is True
    assert r["taxes_and_freight_unverified"] is True
    assert len(r["blocking_issues"]) == 0
    assert r["totals"]["variance_on_matched_lines"] == "0.00"


# ---------------------------------------------------------------------------
# 2. Contract Overcharge (Acme baseline)
# ---------------------------------------------------------------------------
def test_scenario_02_contract_overcharge(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, "112.00", total="56000.00")])
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_VERIFIED
    assert r["totals"]["verified_overcharge_total"] == "6000.00"
    line = r["lines"][0]
    assert line["direction"] == "over"
    assert line["line_variance"] == "6000.00"
    assert line["variance_pct"] == "12.00"
    assert line["contract_unit_price"] == "100.00"
    assert line["invoiced_unit_price"] == "112.00"


# ---------------------------------------------------------------------------
# 3. Contract Undercharge
# ---------------------------------------------------------------------------
def test_scenario_03_contract_undercharge(vendor, mk):
    make_invoice, carton, _ = mk
    # Billed 90.00 vs contract 100.00
    inv = make_invoice([carton(10, "90.00", total="900.00")])
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_VERIFIED
    line = r["lines"][0]
    assert line["direction"] == "under"
    assert line["line_variance"] == "-100.00"
    assert r["totals"]["verified_undercharge_total"] == "-100.00"
    
    rows, summary = build_rows(r)
    assert summary["payable_total"] == "900.00"
    assert summary["withheld_total"] == "0.00"


# ---------------------------------------------------------------------------
# 4. Exact Contract Match
# ---------------------------------------------------------------------------
def test_scenario_04_exact_contract_match(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(100, "100.00", total="10000.00")])
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_VERIFIED
    line = r["lines"][0]
    assert line["direction"] == "match"
    assert line["line_variance"] == "0.00"
    assert r["totals"]["variance_on_matched_lines"] == "0.00"


# ---------------------------------------------------------------------------
# 5. Written Line Total Differs from Qty x Price (FAIL-CLOSED)
# ---------------------------------------------------------------------------
def test_scenario_05_written_line_total_differs_from_qty_times_price(vendor, mk):
    make_invoice, carton, _ = mk
    # 500 x 112 = 56,000, but written as 57,000
    inv = make_invoice([carton(500, "112.00", total="57000.00")])
    
    # In check_invoice
    issues = find_issues(inv)
    assert any("quantity x unit price = 56000.00 but line total is written as 57000.00" in i for i in issues)
    
    # In compare
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert r["lines"][0]["line_total_matches"] is False
    assert len(r["blocking_issues"]) > 0
    assert "PAYMENT_RECOMMENDATION_BLOCKED: SOURCE_DISCREPANCY" in r["settlement_status"]
    
    # Payment sheet generation must strictly fail closed
    with pytest.raises(ToolError) as exc_info:
        build_rows(r)
    assert exc_info.value.code == 2
    assert "PAYMENT_RECOMMENDATION_BLOCKED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. Stated Invoice Total Differs from Written Line Totals (FAIL-CLOSED)
# ---------------------------------------------------------------------------
def test_scenario_06_stated_invoice_total_differs_from_written_line_totals(vendor, mk):
    make_invoice, carton, _ = mk
    # Written line is 56,000, but stated total claims 99,999
    inv = make_invoice([carton(500, "112.00", total="56000.00")], stated_total="99999.00")
    
    issues = find_issues(inv)
    assert any("Stated total 99999.00 differs from the sum of line totals as written, 56000.00" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["totals"]["stated_total_matches"] is False
    assert any("Stated total 99999.00 differs" in b for b in r["blocking_issues"])
    
    # Payment sheet must fail closed
    with pytest.raises(ToolError) as exc_info:
        build_rows(r)
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 7. Missing Line Total
# ---------------------------------------------------------------------------
def test_scenario_07_missing_line_total(mk):
    make_invoice, carton, _ = mk
    bad = carton(500, "112.00")
    bad["line_total"] = None
    inv = make_invoice([bad])
    issues = find_issues(inv)
    assert any("Line 1: missing line_total" in i for i in issues)


# ---------------------------------------------------------------------------
# 8. Missing Quantity
# ---------------------------------------------------------------------------
def test_scenario_08_missing_quantity(vendor, mk):
    make_invoice, _, _ = mk
    bad_line = {
        "line_no": 1, "description": "Corrugated carton, 5-ply (CC-5)",
        "quantity": None, "unit": "unit", "unit_price": "112.00", "line_total": "56000.00"
    }
    inv = make_invoice([bad_line])
    
    issues = find_issues(inv)
    assert any("Line 1: missing quantity" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["lines"][0]["status"] == "unmatched"
    assert "missing" in r["lines"][0]["unmatched_reason"]


# ---------------------------------------------------------------------------
# 9. Zero Quantity
# ---------------------------------------------------------------------------
def test_scenario_09_zero_quantity(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(0, "112.00", total="0.00")])
    
    issues = find_issues(inv)
    assert any("Line 1: quantity must be positive (> 0), got 0" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert any("quantity must be positive" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 10. Negative Quantity
# ---------------------------------------------------------------------------
def test_scenario_10_negative_quantity(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(-5, "112.00", total="-560.00")])
    
    issues = find_issues(inv)
    assert any("Line 1: quantity must be positive (> 0), got -5" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert any("quantity must be positive" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 11. Negative Unit Price
# ---------------------------------------------------------------------------
def test_scenario_11_negative_unit_price(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(5, "-112.00", total="-560.00")])
    
    issues = find_issues(inv)
    assert any("Line 1: unit_price cannot be negative, got -112.00" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert any("unit_price cannot be negative" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 12. Non-Finite Numeric Input
# ---------------------------------------------------------------------------
def test_scenario_12_non_finite_numeric_input(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton("NaN", "112.00", total="56000.00")])
    
    issues = find_issues(inv)
    assert any("not a finite number" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert any("not a finite number" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 13. Invalid Numeric String
# ---------------------------------------------------------------------------
def test_scenario_13_invalid_numeric_string(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton("five hundred", "112.00", total="56000.00")])
    
    issues = find_issues(inv)
    assert any("not a valid decimal number" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert r["lines"][0]["status"] == STATUS_SOURCE_DISCREPANCY
    assert any("not a valid decimal number" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 14. Duplicate Line Identifiers
# ---------------------------------------------------------------------------
def test_scenario_14_duplicate_line_identifiers(vendor, mk):
    make_invoice, carton, wrap = mk
    c = carton()
    w = wrap()
    w["line_no"] = 1  # Duplicate line_no
    inv = make_invoice([c, w])
    
    issues = find_issues(inv)
    assert any("Duplicate line_no: 1" in i for i in issues)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert any("Duplicate line_no 1" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 15. Unknown SKU
# ---------------------------------------------------------------------------
def test_scenario_15_unknown_sku(vendor, mk):
    make_invoice, _, _ = mk
    mystery = {
        "line_no": 1, "description": "Custom Solvent X-99", "quantity": 10,
        "unit": "can", "unit_price": "50.00", "line_total": "500.00"
    }
    inv = make_invoice([mystery], stated_total="500.00")
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["lines"][0]["verification_status"] == STATUS_UNMATCHED
    assert r["lines"][0]["status"] in ("unmatched", STATUS_UNMATCHED)
    assert "no contract item matches" in r["lines"][0]["unmatched_reason"]


# ---------------------------------------------------------------------------
# 16. Ambiguous SKU
# ---------------------------------------------------------------------------
def test_scenario_16_ambiguous_sku(vendor, mk):
    make_invoice, carton, _ = mk
    # Description contains keywords for both CC-5 and PW-1
    ambiguous = carton(desc="CC-5 carton with PW-1 pallet wrap bundle")
    inv = make_invoice([ambiguous])
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["lines"][0]["verification_status"] == STATUS_UNMATCHED
    assert r["lines"][0]["status"] in ("unmatched", STATUS_UNMATCHED)
    assert "more than one contract item" in r["lines"][0]["unmatched_reason"]


# ---------------------------------------------------------------------------
# 17. Expired Contract Rate
# ---------------------------------------------------------------------------
def test_scenario_17_expired_contract_rate(vendor, mk):
    make_invoice, carton, _ = mk
    # Contract rate for CC-5 expired on 2026-06-30
    expired_vendor = dict(vendor)
    rates = [dict(r) for r in vendor["contract"]["rates"]]
    rates[0]["effective_to"] = "2026-06-30"
    expired_vendor["contract"] = {"rates": rates}
    
    # Invoice dated 2026-11-03 (after expiry)
    inv = make_invoice([carton()], invoice_date="2026-11-03")
    r = compare(inv, expired_vendor)
    
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["lines"][0]["verification_status"] == STATUS_UNMATCHED
    assert r["lines"][0]["status"] in ("unmatched", STATUS_UNMATCHED)
    assert "no rate in effect on 2026-11-03" in r["lines"][0]["unmatched_reason"]


# ---------------------------------------------------------------------------
# 18. Future Contract Rate
# ---------------------------------------------------------------------------
def test_scenario_18_future_contract_rate(vendor, mk):
    make_invoice, carton, _ = mk
    # Rate starts 2026-01-01, invoice dated 2025-12-31
    inv = make_invoice([carton()], invoice_date="2025-12-31")
    r = compare(inv, vendor)
    
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["lines"][0]["verification_status"] == STATUS_UNMATCHED
    assert r["lines"][0]["status"] in ("unmatched", STATUS_UNMATCHED)
    assert "no rate in effect on 2025-12-31" in r["lines"][0]["unmatched_reason"]


# ---------------------------------------------------------------------------
# 19. Overlapping Contract Rates (FAIL-CLOSED)
# ---------------------------------------------------------------------------
def test_scenario_19_overlapping_contract_rates(vendor, mk):
    make_invoice, carton, _ = mk
    # Introduce conflicting rates in vendor contract
    conflict_vendor = dict(vendor)
    conflict_rates = list(vendor["contract"]["rates"])
    conflict_rates.append({
        "item_key": "carton-cc5",
        "description_pattern": "Corrugated carton",
        "unit": "unit",
        "currency": "INR",
        "unit_price": 105.00,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "clause_ref": "Schedule-A-Item-1-Conflicting"
    })
    conflict_vendor["contract"] = {"rates": conflict_rates}
    
    inv = make_invoice([carton()])
    r = compare(inv, conflict_vendor)
    
    assert r["verification_status"] == STATE_BLOCKED
    assert any("overlapping rates for carton-cc5" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 20. Currency Mismatch
# ---------------------------------------------------------------------------
def test_scenario_20_currency_mismatch(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton()], currency="USD")
    with pytest.raises(ToolError) as exc_info:
        compare(inv, vendor)
    assert exc_info.value.code == 3
    assert "Currency differs" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 21. Missing Currency
# ---------------------------------------------------------------------------
def test_scenario_21_missing_currency(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton()], currency="")
    with pytest.raises(ToolError) as exc_info:
        compare(inv, vendor)
    assert exc_info.value.code == 3
    assert "currency is missing" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 22. Source File Missing
# ---------------------------------------------------------------------------
def test_scenario_22_source_file_missing(mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton()], source_file="invoices/missing_file.txt")
    issues = find_issues(inv)
    assert any("source_file not found on disk" in i for i in issues)


# ---------------------------------------------------------------------------
# 23. Source Fingerprint Mismatch
# ---------------------------------------------------------------------------
def test_scenario_23_source_fingerprint_mismatch(mk):
    make_invoice, carton, _ = mk
    fake_sha = "a" * 64
    inv = make_invoice([carton()], source_sha256=fake_sha)
    issues = find_issues(inv)
    assert any("source_sha256 mismatch" in i for i in issues)


# ---------------------------------------------------------------------------
# 24. Path Traversal Attempt
# ---------------------------------------------------------------------------
def test_scenario_24_path_traversal_attempt(mk):
    make_invoice, carton, _ = mk
    assert not is_safe_relative_path("../../etc/passwd")
    assert not is_safe_relative_path("C:\\Windows\\System32\\cmd.exe")
    assert is_safe_relative_path("invoices/acme-inv-1103.txt")
    
    inv = make_invoice([carton()], source_file="../../etc/passwd")
    issues = find_issues(inv)
    assert any("unsafe path" in i for i in issues)


# ---------------------------------------------------------------------------
# 25. Unmatched Item Mixed with Matched Items
# ---------------------------------------------------------------------------
def test_scenario_25_unmatched_item_mixed_with_matched_items(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Uncontracted mystery box", "quantity": 5, "unit_price": "20.00", "line_total": "100.00"}
    inv = make_invoice([carton(), odd], stated_total="56100.00")
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    assert r["totals"]["complete"] is False
    assert r["lines"][0]["status"] == "matched"
    assert r["lines"][1]["verification_status"] == STATUS_UNMATCHED
    assert r["lines"][1]["status"] in ("unmatched", STATUS_UNMATCHED)
    
    rows, summary = build_rows(r)
    assert summary["complete"] is False
    assert summary["unverified_lines"] == 1
    assert rows[1][6] == ""  # Payable is empty for unmatched line
    assert "UNVERIFIED" in rows[1][8]


# ---------------------------------------------------------------------------
# 26. Multiple Discrepancies in One Invoice
# ---------------------------------------------------------------------------
def test_scenario_26_multiple_discrepancies_in_one_invoice(vendor, mk):
    make_invoice, carton, wrap = mk
    # Line 1: Arithmetic error (500 x 112 = 56000 != 57000)
    # Line 2: Negative quantity (-10)
    # Stated total: Mismatch
    inv = make_invoice([
        carton(500, "112.00", total="57000.00"),
        wrap(-10, "250.00", total="-2500.00")
    ], stated_total="99999.00")
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    assert len(r["blocking_issues"]) >= 3
    assert any("source arithmetic discrepancy" in b for b in r["blocking_issues"])
    assert any("quantity must be positive" in b for b in r["blocking_issues"])
    assert any("Stated total" in b for b in r["blocking_issues"])


# ---------------------------------------------------------------------------
# 27. Rounding Boundary Cases (ROUND_HALF_UP)
# ---------------------------------------------------------------------------
def test_scenario_27_rounding_boundary_cases():
    assert q2(Decimal("0.0050")) == Decimal("0.01")
    assert q2(Decimal("0.0049")) == Decimal("0.00")
    assert q2(Decimal("0.0150")) == Decimal("0.02")
    assert q2(Decimal("0.0250")) == Decimal("0.03")  # Half-up, NOT banker's 0.02
    assert q2(Decimal("0.0350")) == Decimal("0.04")
    assert q2(Decimal("0.0450")) == Decimal("0.05")


# ---------------------------------------------------------------------------
# 28. Very Large Monetary Values (No Float Overflow)
# ---------------------------------------------------------------------------
def test_scenario_28_very_large_monetary_values(vendor, mk):
    make_invoice, carton, _ = mk
    qty = 10000000  # 10 million units
    price = "999999.99"
    expected_total = "9999999900000.00"
    inv = make_invoice([carton(qty, price, total=expected_total)], stated_total=expected_total)
    
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_VERIFIED
    assert r["lines"][0]["invoiced_line_total_computed"] == expected_total
    # Contract is 100.00 -> variance is (999999.99 - 100.00) * 10,000,000 = 9,998,999,900,000.00
    assert r["lines"][0]["line_variance"] == "9998999900000.00"


# ---------------------------------------------------------------------------
# 29. Very Small Monetary Values
# ---------------------------------------------------------------------------
def test_scenario_29_very_small_monetary_values(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(1, "0.01", total="0.01")], stated_total="0.01")
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_VERIFIED
    assert r["lines"][0]["invoiced_line_total_computed"] == "0.01"
    assert r["lines"][0]["line_variance"] == "-99.99"


# ---------------------------------------------------------------------------
# 30. Formula Injection in Descriptions
# ---------------------------------------------------------------------------
def test_scenario_30_formula_injection_in_descriptions():
    payloads = [
        "=HYPERLINK(\"http://evil.com\")",
        "+SUM(A1:A10)",
        "-cmd|'/C calc'!A0",
        "@SUM(B1:B10)",
        "\tTAB_PAYLOAD",
        "\rRET_PAYLOAD"
    ]
    for p in payloads:
        sanitized = safe_text(p)
        assert sanitized.startswith("'"), f"Failed to escape formula payload: {p!r}"


# ---------------------------------------------------------------------------
# 31. Malformed Comparison JSON
# ---------------------------------------------------------------------------
def test_scenario_31_malformed_comparison_json():
    with pytest.raises(ToolError):
        build_rows({"ok": False})
    with pytest.raises(ToolError):
        build_rows({})


# ---------------------------------------------------------------------------
# 32. Tampered Comparison Result (FAIL-CLOSED)
# ---------------------------------------------------------------------------
def test_scenario_32_tampered_comparison_result():
    # An attacker alters JSON so ok is True, but leaves a blocking issue or BLOCKED status
    tampered = {
        "ok": True,
        "verification_status": STATE_BLOCKED,
        "blocking_issues": ["Line 1: tampered data detected"],
        "lines": []
    }
    with pytest.raises(ToolError) as exc_info:
        build_rows(tampered)
    assert exc_info.value.code == 2
    assert "PAYMENT_RECOMMENDATION_BLOCKED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 33. Payment-Sheet Attempt on a Blocked Result (FAIL-CLOSED)
# ---------------------------------------------------------------------------
def test_scenario_33_payment_sheet_attempt_on_blocked_result(vendor, mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, "112.00", total="57000.00")])
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_BLOCKED
    
    with pytest.raises(ToolError) as exc_info:
        build_rows(r)
    assert exc_info.value.code == 2
    
    # Can only build if explicitly requesting a blocked draft
    rows, summary = build_rows(r, allow_blocked_draft=True)
    assert "BLOCKED" in rows[-1][1]
    assert summary["complete"] is False


# ---------------------------------------------------------------------------
# 34. Payment-Sheet Attempt on an Incomplete Result
# ---------------------------------------------------------------------------
def test_scenario_34_payment_sheet_attempt_on_incomplete_result(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Mystery item", "quantity": 1, "unit_price": "10.00", "line_total": "10.00"}
    inv = make_invoice([carton(), odd], stated_total="56010.00")
    r = compare(inv, vendor)
    assert r["verification_status"] == STATE_REVIEW_REQUIRED
    
    rows, summary = build_rows(r)
    assert summary["complete"] is False
    assert "INCOMPLETE" in rows[-1][1]
    assert summary["unverified_lines"] == 1


# ---------------------------------------------------------------------------
# 35. Goods Subtotal Incorrectly Presented as Complete Settlement
# ---------------------------------------------------------------------------
def test_scenario_35_goods_subtotal_never_presented_as_complete_settlement(vendor, mk):
    make_invoice, carton, wrap = mk
    inv = make_invoice([carton(), wrap()])
    r = compare(inv, vendor)
    
    # Engine must explicitly declare goods only and unverified tax/freight
    assert r["taxes_and_freight_unverified"] is True
    assert "TAX_AND_FREIGHT_UNVERIFIED" in r["settlement_status"]
    
    rows, summary = build_rows(r)
    assert summary["taxes_and_freight_unverified"] is True
    # The summary label must say GOODS ONLY
    assert "GOODS ONLY" in rows[-1][1]
    # The footer note must explicitly state taxes and freight are unverified
    assert "Taxes and freight are unverified" in rows[-1][8]
