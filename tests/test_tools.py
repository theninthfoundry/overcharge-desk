from __future__ import annotations

import csv
import json
import subprocess
import sys
from argparse import Namespace

import pytest

import ledger
from check_invoice import find_issues
from common import ToolError
from compare import compare
from next_case_id import next_id
from payment_sheet import build_rows

SHA = "a" * 64


def good_record(**over):
    rec = {"case_id": "OC-20261105-01", "invoice_number": "INV-0914", "status": "approved_dispute",
           "variance_total": "2400.00", "finding_summary": "Carton billed 112 vs contract 100",
           "owner_decision": "APPROVE", "decided_by": "@owner", "audit_sha256": SHA,
           "identity_check": "instruction-only", "evidence_refs": ["vendors/acme.json#carton-cc5"]}
    rec.update(over)
    return rec


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------- ledger ----------

def test_add_case_appends_and_stamps_time(vendor_file, tmp_path):
    rec = write(tmp_path / "r.json", good_record(decided_at="1999-01-01T00:00:00Z"))
    ledger.cmd_add_case(Namespace(vendor_json=str(vendor_file), record=str(rec)))
    saved = json.loads(vendor_file.read_text())
    c = saved["cases"][0]
    assert c["case_id"] == "OC-20261105-01"
    assert c["decided_at"] != "1999-01-01T00:00:00Z"  # caller cannot fake the time
    assert c["vendor_outcome"] is None
    assert saved["contract"]["rates"]  # rest of the file untouched


def test_duplicate_case_refused(vendor_file, tmp_path):
    rec = write(tmp_path / "r.json", good_record())
    ns = Namespace(vendor_json=str(vendor_file), record=str(rec))
    ledger.cmd_add_case(ns)
    with pytest.raises(ToolError) as e:
        ledger.cmd_add_case(ns)
    assert e.value.code == 4
    assert len(json.loads(vendor_file.read_text())["cases"]) == 1


@pytest.mark.parametrize("over", [
    {"case_id": "case-1"}, {"status": "maybe"}, {"audit_sha256": "abc"},
    {"variance_total": None}, {"evidence_refs": "none"}, {"surprise": 1},
    {"vendor_outcome": {"text": "pre-filled"}}, {"decided_by": ""},
])
def test_bad_records_refused(vendor_file, tmp_path, over):
    rec = write(tmp_path / "r.json", good_record(**over))
    with pytest.raises(ToolError):
        ledger.cmd_add_case(Namespace(vendor_json=str(vendor_file), record=str(rec)))
    assert json.loads(vendor_file.read_text())["cases"] == []


def test_rejection_needs_reason(vendor_file, tmp_path):
    rec = write(tmp_path / "r.json", good_record(status="rejected_by_owner", variance_total=None))
    with pytest.raises(ToolError):
        ledger.cmd_add_case(Namespace(vendor_json=str(vendor_file), record=str(rec)))
    rec = write(tmp_path / "r2.json", good_record(status="rejected_by_owner", variance_total=None,
                                                 owner_reason="Vendor already sent a credit note"))
    ledger.cmd_add_case(Namespace(vendor_json=str(vendor_file), record=str(rec)))
    assert json.loads(vendor_file.read_text())["cases"][0]["owner_reason"].startswith("Vendor already")


def test_outcome_set_once_and_verbatim(vendor_file, tmp_path):
    rec = write(tmp_path / "r.json", good_record())
    ledger.cmd_add_case(Namespace(vendor_json=str(vendor_file), record=str(rec)))
    text = "Vendor acknowledged by phone, credit note CN-114 promised for 2,400"
    ledger.cmd_set_outcome(Namespace(vendor_json=str(vendor_file), case_id="OC-20261105-01",
                                     text=f"  {text}  ", recorded_by="@owner"))
    out = json.loads(vendor_file.read_text())["cases"][0]["vendor_outcome"]
    assert out["text"] == text and out["recorded_by"] == "@owner" and out["recorded_at"]
    with pytest.raises(ToolError) as e:
        ledger.cmd_set_outcome(Namespace(vendor_json=str(vendor_file), case_id="OC-20261105-01",
                                         text="changed my mind", recorded_by="@owner"))
    assert e.value.code == 4


def test_outcome_for_unknown_case_refused(vendor_file):
    with pytest.raises(ToolError) as e:
        ledger.cmd_set_outcome(Namespace(vendor_json=str(vendor_file), case_id="OC-20261105-09",
                                         text="x", recorded_by="@owner"))
    assert e.value.code == 4


def test_ledger_refuses_file_without_cases_list(tmp_path):
    p = write(tmp_path / "bad.json", {"vendor_id": "x"})
    rec = write(tmp_path / "r.json", good_record())
    with pytest.raises(ToolError):
        ledger.cmd_add_case(Namespace(vendor_json=str(p), record=str(rec)))


# ---------- payment sheet ----------

def test_payment_sheet_demo_numbers(vendor, mk, tmp_path):
    make_invoice, carton, wrap = mk
    result = compare(make_invoice([carton(500, 112), wrap()]), vendor)
    rows, summary = build_rows(result)
    assert summary["payable_total"] == "60000.00"
    assert summary["withheld_total"] == "6000.00"
    assert summary["invoiced_total"] == "66000.00"
    assert summary["complete"] is True
    assert rows[0][6] == "50000.00" and rows[0][7] == "6000.00"  # carton line
    assert rows[1][6] == "10000.00" and rows[1][7] == "0.00"      # wrap line matches


from partial_review import build_partial_review_rows


def test_payment_sheet_unmatched_is_marked_incomplete(vendor, mk):
    make_invoice, carton, _ = mk
    odd = {"line_no": 2, "description": "Mystery item", "quantity": 3, "unit_price": 10, "line_total": 30}
    comp = compare(make_invoice([carton(), odd]), vendor)
    # Payment sheet must strictly refuse REVIEW_REQUIRED results
    with pytest.raises(ToolError) as exc_info:
        build_rows(comp)
    assert exc_info.value.code == 2

    # Partial review handles it cleanly
    rows, summary = build_partial_review_rows(comp)
    assert summary["unmatched_lines"] == 1
    assert "REVIEW REQUIRED" in rows[-1][1]


def test_payment_sheet_under_billing_pays_as_invoiced(vendor, mk):
    make_invoice, carton, _ = mk
    rows, summary = build_rows(compare(make_invoice([carton(10, 90)]), vendor))
    assert summary["payable_total"] == "900.00" and summary["withheld_total"] == "0.00"


def test_payment_sheet_blocks_formula_injection(vendor, mk):
    make_invoice, carton, _ = mk
    evil = carton(1, 100, desc="=HYPERLINK(\"http://x\") CC-5", n=2)
    rows, _ = build_rows(compare(make_invoice([carton(), evil]), vendor))
    assert rows[1][1].startswith("'=")


def test_payment_sheet_refuses_error_result():
    with pytest.raises(ToolError):
        build_rows({"ok": False})


# ---------- check_invoice ----------

def test_check_invoice_clean(mk):
    make_invoice, carton, wrap = mk
    assert find_issues(make_invoice([carton(), wrap()], stated_total=66000)) == []


def test_check_invoice_reports_arithmetic_and_missing(mk):
    make_invoice, carton, _ = mk
    inv = make_invoice([carton(500, 112, total=57000)], stated_total=1, source_sha256=None)
    issues = find_issues(inv)
    assert any("Missing field: source_sha256" in i for i in issues)
    assert any("Line 1: quantity x unit price = 56000.00" in i for i in issues)
    assert any("Stated total 1.00 differs" in i for i in issues)


# ---------- next_case_id ----------

def test_next_case_id(tmp_path):
    assert next_id(tmp_path, "20261106") == "OC-20261106-01"
    (tmp_path / "OC-20261106-01").mkdir()
    (tmp_path / "OC-20261106-02").mkdir()
    (tmp_path / "OC-20261105-07").mkdir()
    (tmp_path / "notes").mkdir()
    assert next_id(tmp_path, "20261106") == "OC-20261106-03"
    assert next_id(tmp_path, "20261107") == "OC-20261107-01"


# ---------- end to end through the real CLIs and the demo files ----------

def run(root, *args):
    return subprocess.run([sys.executable, *map(str, args)], cwd=root, capture_output=True, text=True)


def test_cli_end_to_end_with_demo_files(root, tmp_path, vendor_file):
    inv = {
        "case_id": "OC-20261106-01", "vendor_name_as_written": "Acme Supplies Pvt Ltd",
        "invoice_number": "INV-1103", "invoice_date": "2026-11-03", "currency": "INR",
        "lines": [
            {"line_no": 1, "description": "Corrugated carton, 5-ply (CC-5)", "quantity": 500, "unit": "unit",
             "unit_price": 112.00, "line_total": 56000.00},
            {"line_no": 2, "description": "Pallet wrap roll (PW-1)", "quantity": 40, "unit": "unit",
             "unit_price": 250.00, "line_total": 10000.00}],
        "stated_total": 66000.00, "source_file": "invoices/acme-inv-1103.txt",
        "source_sha256": "2c7d4c457e0b1d3f59092f997676589139738a89843c30da25824f1fbfe54543", "extraction_issues": []}
    inv_path = write(tmp_path / "invoice.json", inv)

    chk = run(root, "tools/check_invoice.py", inv_path, "--update")
    assert chk.returncode == 0 and json.loads(chk.stdout)["issues"] == []

    cmp_out = tmp_path / "compare.json"
    r = run(root, "tools/compare.py", inv_path, vendor_file, "--out", cmp_out)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["totals"]["variance_on_matched_lines"] == "6000.00"

    sheet = tmp_path / "corrected_payment.csv"
    s = run(root, "tools/payment_sheet.py", cmp_out, sheet)
    assert s.returncode == 0, s.stderr
    with open(sheet, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "line_no" and rows[-1][6] == "60000.00" and rows[-1][7] == "6000.00"

    sha = run(root, "tools/sha.py", cmp_out)
    assert len(json.loads(sha.stdout)["short"]) == 12


def test_cli_exit_codes(root, tmp_path, vendor_file):
    missing = run(root, "tools/compare.py", tmp_path / "nope.json", vendor_file)
    assert missing.returncode == 2 and json.loads(missing.stdout)["ok"] is False
    bad = write(tmp_path / "inv.json", {"vendor_name_as_written": "Globex", "currency": "INR",
                                       "invoice_date": "2026-11-03", "lines": [{"x": 1}]})
    wrong_vendor = run(root, "tools/compare.py", bad, vendor_file)
    assert wrong_vendor.returncode == 3


def test_demo_vendor_file_matches_seed(root):
    assert json.loads((root / "vendors" / "acme.json").read_text()) == \
        json.loads((root / "seed" / "acme.json").read_text()), \
        "vendors/acme.json must equal seed/acme.json before a demo run (use `make reset-demo`)"

# Verifies ISO format and valid UTC offset

# Verifies full SHA-256 and 12-char slice

# Tests sequential increment behavior

# Tests invoice validator error handling

# Tests rejection of duplicate case records

# Validates atomic write safety

# Validates partial match CSV generation

# Tests exit code 2 on missing inputs
