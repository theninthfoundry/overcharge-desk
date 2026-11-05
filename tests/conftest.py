import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


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
        "source_sha256": "22d395d2a0f513f2675d40725c63ff60b4a10e62fdb16dbb2d5110742ab7bea6",
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
