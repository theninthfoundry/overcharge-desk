from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="session", autouse=True)
def fresh_clone_test_environment(tmp_path_factory):
    """Ensure key isolation outside the repository and generate demo artifacts if missing on fresh clone."""
    # Backup original demo invoice to keep git working tree clean across test runs
    demo_inv = ROOT / "cases" / "demo-overcharge" / "invoice.json"
    orig_demo_inv_bytes = demo_inv.read_bytes() if demo_inv.exists() else None

    # 1. Isolate keys into a temporary test directory so no key files are written to the repo
    test_key_dir = tmp_path_factory.mktemp("test_keys")
    os.environ["OVERCHARGE_KEY_DIR"] = str(test_key_dir)
    from auth import ensure_signing_key
    key_path = test_key_dir / "signing.key"
    ensure_signing_key(key_path)

    # 2. Check if demo artifacts exist and are signed with active session key; if not, generate them
    demo_receipt = ROOT / "cases" / "demo-overcharge" / "approvals" / "approval_receipt.json"
    needs_regen = not demo_receipt.exists()
    if not needs_regen:
        try:
            from approval_receipt import verify_approval_receipt
            from auth import load_signing_key
            kb = load_signing_key(key_path)
            rec = json.loads(demo_receipt.read_text(encoding="utf-8"))
            valid, _ = verify_approval_receipt(rec, kb)
            if not valid:
                needs_regen = True
        except Exception:
            needs_regen = True

    if needs_regen:
        try:
            from run_demo_suite import run_full_demo
            run_full_demo(base_dir=ROOT, clean_run=True, key_file=key_path)
        except Exception as exc:
            import warnings
            warnings.warn(f"Demo suite regeneration notice: {exc}")

    yield

    # Restore pristine state of demo-overcharge invoice if modified during test execution
    if orig_demo_inv_bytes and demo_inv.exists():
        demo_inv.write_bytes(orig_demo_inv_bytes)


@pytest.fixture
def root():
    return ROOT


@pytest.fixture
def vendor():
    return json.loads((ROOT / "seed" / "acme.json").read_text(encoding="utf-8"))


@pytest.fixture
def vendor_file(tmp_path):
    p = tmp_path / "acme.json"
    shutil.copy(ROOT / "seed" / "acme.json", p)
    return p


def make_invoice(lines, **over):
    # Test Fixture Factory: Builds canonical invoice dictionaries with authentic fingerprints
    inv = {
        "case_id": "OC-20261106-01",
        "vendor_name_as_written": "Acme Supplies Pvt Ltd",
        "invoice_number": "INV-1103",
        "invoice_date": "2026-11-03",
        "currency": "INR",
        "lines": lines,
        "stated_total": None,
        "source_file": "invoices/acme-inv-1103.txt",
        "source_sha256": "2c7d4c457e0b1d3f59092f997676589139738a89843c30da25824f1fbfe54543",
        "extraction_issues": [],
    }
    inv.update(over)
    return inv


def carton(qty=500, price=112, total=None, desc="Corrugated carton, 5-ply (CC-5)", n=1):
    return {"line_no": n, "description": desc, "quantity": qty, "unit": "unit",
            "unit_price": price, "line_total": qty * price if total is None else total}


def wrap(qty=40, price=250, total=None, n=2):
    return {"line_no": n, "description": "Pallet wrap roll (PW-1)", "quantity": qty, "unit": "unit",
            "unit_price": price, "line_total": qty * price if total is None else total}


@pytest.fixture
def mk():
    return make_invoice, carton, wrap
