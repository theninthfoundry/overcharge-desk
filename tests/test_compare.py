import copy

import pytest

from common import ToolError
from compare import compare


def test_demo_case_six_thousand_over(vendor, mk):
    make_invoice, carton, wrap = mk
    inv = make_invoice([carton(500, 112), wrap()], stated_total=66000)
    r = compare(inv, vendor)
    l1, l2 = r["lines"]
    assert l1["status"] == "matched" and l1["direction"] == "over"
    assert l1["line_variance"] == "6000.00"
    assert l1["variance_pct"] == "12.00"
    assert l1["contract_unit_price"] == "100.00" and l1["invoiced_unit_price"] == "112.00"
    assert l2["direction"] == "match" and l2["line_variance"] == "0.00"
    t = r["totals"]
    assert t["complete"] is True
    assert t["invoiced_total"] == "66000.00"
    assert t["per_contract_total"] == "60000.00"
    assert t["variance_on_matched_lines"] == "6000.00"
    assert t["stated_total_matches"] is True
    assert r["warnings"] == []


def test_exact_demo_invoice_fifty_vs_fifty_six_thousand(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(500, 112)], stated_total=56000), vendor)
    t = r["totals"]
    assert t["per_contract_total"] == "50000.00"
    assert t["invoiced_total"] == "56000.00"
    assert t["variance_on_matched_lines"] == "6000.00"


def test_under_billing_is_reported_as_under(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(10, 90)]), vendor)
    line = r["lines"][0]
    assert line["direction"] == "under"
    assert line["line_variance"] == "-100.00"
    assert line["variance_pct"] == "-10.00"


def test_matching_sku_only_description(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(5, 100, desc="5 ply box cc-5 large")]), vendor)
    assert r["lines"][0]["status"] == "matched"


def test_sku_boundary_does_not_match_longer_sku(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(5, 100, desc="Mega box CC-50")]), vendor)
    assert r["lines"][0]["status"] == "unmatched"


def test_unknown_item_is_unmatched_and_total_incomplete(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Mystery item", "quantity": 3, "unit_price": 10, "line_total": 30}
    r = compare(make_invoice([carton(500, 112), odd]), vendor)
    assert r["lines"][1]["status"] == "unmatched"
    t = r["totals"]
    assert t["complete"] is False
    assert t["per_contract_total"] is None
    assert t["unmatched_invoiced_as_written"] == "30.00"
    assert t["invoiced_total"] == "56030.00"


def test_rate_not_yet_in_force_is_unmatched(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()], invoice_date="2025-12-31"), vendor)
    assert r["lines"][0]["status"] == "unmatched"
    assert "no rate in effect" in r["lines"][0]["unmatched_reason"]


def test_rate_history_picks_the_period_in_force(vendor, mk):
    make_invoice, carton, _ = mk
    v = copy.deepcopy(vendor)
    old = v["contract"]["rates"][0]
    old["effective_to"] = "2026-06-30"
    new = copy.deepcopy(old)
    new.update({"unit_price": 105, "effective_from": "2026-07-01", "effective_to": None})
    v["contract"]["rates"].append(new)
    r = compare(make_invoice([carton(10, 112)], invoice_date="2026-09-01"), v)
    assert r["lines"][0]["contract_unit_price"] == "105.00"
    r = compare(make_invoice([carton(10, 112)], invoice_date="2026-06-30"), v)
    assert r["lines"][0]["contract_unit_price"] == "100.00"


def test_overlapping_rates_are_refused_not_guessed(vendor, mk):
    make_invoice, carton, _ = mk
    v = copy.deepcopy(vendor)
    dup = copy.deepcopy(v["contract"]["rates"][0])
    dup["unit_price"] = 99
    v["contract"]["rates"].append(dup)
    r = compare(make_invoice([carton()]), v)
    assert r["lines"][0]["status"] == "unmatched"
    assert "overlapping" in r["lines"][0]["unmatched_reason"]


def test_description_matching_two_items_is_ambiguous(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(1, 1, desc="CC-5 carton with PW-1 wrap")]), vendor)
    assert r["lines"][0]["status"] == "unmatched"
    assert "more than one" in r["lines"][0]["unmatched_reason"]


def test_currency_mismatch_stops(vendor, mk):
    make_invoice, carton, _ = mk
    with pytest.raises(ToolError) as e:
        compare(make_invoice([carton()], currency="USD"), vendor)
    assert e.value.code == 3


def test_missing_currency_stops(vendor, mk):
    make_invoice, carton, _ = mk
    with pytest.raises(ToolError) as e:
        compare(make_invoice([carton()], currency=None), vendor)
    assert e.value.code == 3


def test_wrong_vendor_stops(vendor, mk):
    make_invoice, carton, _ = mk
    with pytest.raises(ToolError) as e:
        compare(make_invoice([carton()], vendor_name_as_written="Globex Ltd"), vendor)
    assert e.value.code == 3


def test_vendor_alias_and_case_insensitive(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()], vendor_name_as_written="  acme   supplies "), vendor)
    assert r["ok"]


def test_missing_quantity_is_unmatched(vendor, mk):
    make_invoice, _, _ = mk
    bad = {"line_no": 1, "description": "Corrugated carton, 5-ply (CC-5)", "quantity": None,
           "unit_price": 112, "line_total": 56000}
    r = compare(make_invoice([bad]), vendor)
    assert r["lines"][0]["status"] == "unmatched"


def test_line_total_mismatch_warns(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton(500, 112, total=57000)]), vendor)
    assert r["lines"][0]["line_total_matches"] is False
    assert any("line total is written as 57000.00" in w for w in r["warnings"])


def test_stated_total_mismatch_warns(vendor, mk):
    make_invoice, carton, _ = mk
    r = compare(make_invoice([carton()], stated_total=99999), vendor)
    assert r["totals"]["stated_total_matches"] is False
    assert any("Stated total" in w for w in r["warnings"])


def test_no_float_error_on_awkward_decimals(vendor, mk):
    make_invoice, carton, _ = mk
    # 0.1 + 0.2 style traps: 3 units at 100.10 vs contract 100.00
    r = compare(make_invoice([carton(3, "100.10", total="300.30")]), vendor)
    assert r["lines"][0]["line_variance"] == "0.30"
    assert r["lines"][0]["variance_pct"] == "0.10"


def test_half_up_rounding(vendor, mk):
    make_invoice, carton, _ = mk
    # variance per unit 0.005 x 1 unit = 0.005 -> 0.01 (half up), not 0.00 (banker's)
    r = compare(make_invoice([carton(1, "100.005", total="100.01")]), vendor)
    assert r["lines"][0]["line_variance"] == "0.01"


def test_empty_invoice_is_an_error(vendor, mk):
    make_invoice, _, _ = mk
    with pytest.raises(ToolError):
        compare(make_invoice([]), vendor)


def test_bad_date_is_an_error(vendor, mk):
    make_invoice, carton, _ = mk
    with pytest.raises(ToolError):
        compare(make_invoice([carton()], invoice_date="03/11/2026"), vendor)

# Tests Decimal calculation accuracy

# Validates underbilling variance calculation

# Validates expired rate handling
