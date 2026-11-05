"""Tests for Unified Agent CLI (tools/desk.py) and Key Isolation Invariants."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from common import ToolError, load_json
from tools.desk import run_audit, run_finalize, run_history, run_intake, run_status

ROOT = Path(__file__).resolve().parent.parent


def test_desk_approve_subcommand_does_not_exist():
    """Verify that agents cannot call 'approve' via desk.py."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "desk.py"), "approve", "demo-overcharge"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "invalid choice: 'approve'" in (res.stdout + res.stderr)


def test_desk_status_4d_model():
    """Verify 4-dimensional state tracking via tools/desk.py status."""
    res = run_status("demo-overcharge", cases_dir=ROOT / "cases", base_dir=ROOT)
    assert res["ok"] is True
    assert res["verification_status"] == "VERIFIED"
    assert res["commercial_status"] == "OVERCHARGED"
    assert res["approval_status"] == "APPROVED"
    assert res["payment_status"] == "AUTHORIZED"
    assert res["payable_amount"] == "60000.00"
    assert res["withheld_amount"] == "6000.00"
    assert res["invoiced_total"] == "66000.00"


def test_desk_audit_64_char_hashes():
    """Verify desk.py audit outputs full 64-character SHA-256 digests and exact amounts."""
    res = run_audit("demo-overcharge", cases_dir=ROOT / "cases", base_dir=ROOT)
    assert res["ok"] is True
    assert res["case_id"] == "OC-20261106-01"
    assert res["verification_status"] == "VERIFIED"
    assert res["commercial_status"] == "OVERCHARGED"
    assert len(res["invoice_sha256"]) == 64
    assert len(res["compare_sha256"]) == 64
    assert len(res["ledger_head"]) == 64
    assert res["payable_goods_subtotal"] == "60000.00"
    assert res["withheld_goods_variance"] == "6000.00"


def test_desk_audit_blocked_fails_closed():
    """Verify desk.py audit fails closed on arithmetic discrepancy / BLOCKED case."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "desk.py"), "audit", "demo-blocked"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    out = json.loads(proc.stdout)
    assert out["ok"] is False
    assert "error" in out or out.get("verification_status") == "BLOCKED"


def test_desk_history_vendor_memory():
    """Verify desk.py history --vendor acme returns all prior cases for the vendor."""
    res = run_history(vendor_id="acme", cases_dir=ROOT / "cases", base_dir=ROOT)
    assert res["ok"] is True
    assert res["vendor_id"] == "acme"
    assert res["prior_cases_count"] >= 2
    assert res["total_overcharges_withheld"] == "6000.00"
    case_ids = [c["case_id"] for c in res["prior_cases"]]
    assert "OC-20261106-01" in case_ids


def test_desk_finalize_without_receipt_fails_closed():
    """Verify desk.py finalize fails closed when no valid approval receipt exists."""
    with pytest.raises(ToolError, match="Finalization refused: No signed human approval receipt found"):
        run_finalize("demo-review", cases_dir=ROOT / "cases", base_dir=ROOT)


def test_desk_finalize_with_valid_receipt():
    """Verify desk.py finalize releases payment sheet with ₹60,000 payable and ₹6,000 withheld."""
    res = run_finalize("demo-overcharge", cases_dir=ROOT / "cases", base_dir=ROOT)
    assert res["ok"] is True
    assert res["payment_status"] == "AUTHORIZED"
    assert res["payable_amount"] == "60000.00"
    assert res["withheld_amount"] == "6000.00"
    assert Path(res["payment_sheet"]).name == "corrected_payment.csv"
    assert len(res["receipt_hash"]) == 64


def test_desk_intake_workflow(tmp_path):
    """Verify desk.py intake copies evidence and registers source SHA-256."""
    inv_file = tmp_path / "sample_invoice.json"
    con_file = tmp_path / "sample_contract.json"
    shutil_inv = ROOT / "cases" / "demo-overcharge" / "invoice.json"
    shutil_con = ROOT / "seed" / "acme.json"
    inv_file.write_text(shutil_inv.read_text(encoding="utf-8"), encoding="utf-8")
    con_file.write_text(shutil_con.read_text(encoding="utf-8"), encoding="utf-8")

    c_dir = tmp_path / "cases"
    res = run_intake(
        invoice_path=inv_file,
        contract_path=con_file,
        case_id="OC-20261105-01",
        cases_dir=c_dir,
        base_dir=tmp_path,
    )
    assert res["ok"] is True
    assert res["case_id"] == "OC-20261105-01"
    assert len(res["source_sha256"]) == 64
    assert (Path(res["case_dir"]) / "evidence_registry.json").exists()


def test_no_key_files_under_repository_tree():
    """Invariant: No signing key files or manifests may exist inside the git repository tree."""
    repo_keys = list(ROOT.rglob("*.key"))
    manifests = list(ROOT.rglob("keys_manifest.json"))
    # Filter out any in git, pytest, or virtual environments
    illegal_keys = [
        str(k.relative_to(ROOT))
        for k in repo_keys
        if ".git" not in str(k) and ".venv" not in str(k) and ".pytest_cache" not in str(k)
    ]
    illegal_manifests = [
        str(m.relative_to(ROOT))
        for m in manifests
        if ".git" not in str(m) and ".venv" not in str(m) and ".pytest_cache" not in str(m)
    ]
    assert illegal_keys == [], f"Found key files inside repository tree: {illegal_keys}"
    assert illegal_manifests == [], f"Found key manifests inside repository tree: {illegal_manifests}"


def test_desk_intake_txt_invoice(tmp_path):
    """Verify desk.py intake deterministically parses raw .txt tabular invoices into structured invoice.json."""
    inv_txt = ROOT / "invoices" / "acme-inv-1103.txt"
    con_json = ROOT / "seed" / "acme.json"
    c_dir = tmp_path / "cases"

    res = run_intake(
        invoice_path=inv_txt,
        contract_path=con_json,
        case_id="OC-20261105-02",
        cases_dir=c_dir,
        base_dir=tmp_path,
    )
    assert res["ok"] is True
    assert res["case_id"] == "OC-20261105-02"
    generated_inv = Path(res["case_dir"]) / "invoice.json"
    assert generated_inv.exists()

    inv_data = load_json(generated_inv)
    assert inv_data["invoice_number"] == "INV-1103"
    assert inv_data["vendor_name_as_written"] == "Acme Supplies Pvt Ltd"
    assert len(inv_data["lines"]) == 2
    assert inv_data["lines"][0]["line_no"] == 1
    assert inv_data["lines"][0]["quantity"] == "500"
    assert inv_data["lines"][0]["unit_price"] == "112.00"
    assert inv_data["lines"][0]["line_total"] == "56000.00"
    assert "acme-inv-1103.txt, line 1" in inv_data["lines"][0]["source_ref"]
    assert inv_data["stated_total"] == "66000.00"


def test_simulate_switch_fast_execution():
    """Verify tools/simulate_switch.py runs all 4 turns cleanly in fast mode."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "simulate_switch.py"), "--fast"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    output = res.stdout
    assert "[READER]" in output
    assert "[AUDITOR]" in output
    assert "[OWNER]" in output
    assert "[WRITER]" in output
    assert "VENDOR MEMORY MOMENT:" in output
    assert "MULTI-AGENT WORKFLOW COMPLETED SUCCESSFULLY" in output


def test_quickstart_cli_runner():
    """Verify tools/quickstart.py executes benchmark and ledger verification."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "quickstart.py"), "--no-clean"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    output = res.stdout
    assert "Running 6 Canonical Benchmark Demo Cases..." in output
    assert "Verifying SQLite Ledger Cryptographic Hash Chain..." in output
    assert "Chain Integrity:" in output
    assert "VALID" in output
