"""Adversarial & Security Audit Remediation Tests for Overcharge Desk.

Covers all P0, P1, and P2 findings from the Repository Audit:
  - P0.1: Append-only evidence registration and re-intake collision refusal.
  - P0.2: Exact Decimal text invoice parsing (zero float usage) and strict identifier/date validation.
  - P0.3: Cryptographically hash-chained and HMAC-authenticated evidence_registry.json.
  - P1.1: Strict separation of demo identities from production authentication paths.
  - P1.2: Removal of config/signing.key fallback and atomic 0o600 key provisioning.
  - P1.3: End-to-end approval-to-evidence binding at finalization (stale approval refusal).
  - P1.4: Signed ledger checkpoints and HMAC package authentication on audit export.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import pytest
except ImportError:
    pytest = types.ModuleType("pytest")  # type: ignore

    class _RaisesCtx:
        def __init__(self, exc_type, match=None):
            self.exc_type = exc_type
            self.match = match
            self.value = None

        def __enter__(self):
            return self

        def __exit__(self, et, ev, tb):
            if et is None:
                raise AssertionError(f"Expected {self.exc_type.__name__} to be raised")
            if not issubclass(et, self.exc_type):
                return False
            self.value = ev
            if self.match and not re.search(self.match, str(ev)):
                raise AssertionError(f"{str(ev)!r} did not match {self.match!r}")
            return True

    pytest.raises = lambda exc_type, match=None: _RaisesCtx(exc_type, match)  # type: ignore

    class _Mark:
        def parametrize(self, *args, **kwargs):
            def dec(fn):
                return fn
            return dec

    pytest.mark = _Mark()  # type: ignore
    sys.modules["pytest"] = pytest

from common import ToolError, load_json, sha256_file, write_json_atomic
from tools.auth import REPO_ROOT, ensure_signing_key, issue_actor_token, load_signing_key
from tools.approval_gateway import process_approval_decision
from tools.approve import approve_case_cli
from tools.desk import parse_txt_invoice, run_audit, run_finalize, run_intake
from tools.evidence import (
    compute_registry_digest,
    get_evidence_digest_map,
    load_registry,
    register_evidence,
    verify_evidence,
)
from tools.export_audit_package import export_case_audit, verify_package_integrity
from tools.pipeline import run_pipeline
from tools.simulate_switch import run_simulation
from domain.identity.models import IdentityService, SystemRole
from domain.identity.passwords import hash_password
from domain.identity.repository import IdentityRepository


# ---------------------------------------------------------------------------
# P0.1 — Append-Only Evidence Registration & Re-Intake Collision Refusal
# ---------------------------------------------------------------------------
def test_p0_1_evidence_cannot_be_silently_replaced_on_re_registration(tmp_path):
    """Verify register_evidence refuses silent hash replacement for source_invoice."""
    case_dir = tmp_path / "OC-20261105-01"
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("Original Invoice Content", encoding="utf-8")

    rec1 = register_evidence(
        case_dir=case_dir,
        file_path=inv_file,
        evidence_type="source_invoice",
        case_id="OC-20261105-01",
    )
    orig_hash = rec1["content_hash"]

    # Idempotent re-registration with identical content succeeds without mutation
    rec_same = register_evidence(
        case_dir=case_dir,
        file_path=inv_file,
        evidence_type="source_invoice",
        case_id="OC-20261105-01",
    )
    assert rec_same["evidence_id"] == rec1["evidence_id"]
    assert rec_same["content_hash"] == orig_hash

    # Attempting to re-register modified content under the same evidence slot is refused
    inv_file.write_text("Tampered / Modified Invoice Content", encoding="utf-8")
    with pytest.raises(ToolError) as exc_info:
        register_evidence(
            case_dir=case_dir,
            file_path=inv_file,
            evidence_type="source_invoice",
            case_id="OC-20261105-01",
        )
    assert exc_info.value.code == 4
    assert "EVIDENCE_MUTATION_REFUSED" in str(exc_info.value)

    # Verify original hash in registry was preserved untouched
    reg = load_registry(case_dir)
    assert len(reg["evidence"]) == 1
    assert reg["evidence"][0]["content_hash"] == orig_hash


def test_p0_1_explicit_amendment_creates_versioned_append_only_record(tmp_path):
    """Verify explicit allow_amendment=True appends a new version and preserves the superseded record."""
    case_dir = tmp_path / "OC-20261105-02"
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("Version 1 Invoice", encoding="utf-8")

    rec1 = register_evidence(
        case_dir=case_dir,
        file_path=inv_file,
        evidence_type="source_invoice",
        case_id="OC-20261105-02",
    )
    v1_hash = rec1["content_hash"]

    inv_file.write_text("Version 2 Corrected Invoice", encoding="utf-8")
    rec2 = register_evidence(
        case_dir=case_dir,
        file_path=inv_file,
        evidence_type="source_invoice",
        case_id="OC-20261105-02",
        allow_amendment=True,
    )
    assert rec2["version"] == 2
    assert rec2["supersedes_evidence_id"] == rec1["evidence_id"]
    assert rec2["previous_content_hash"] == v1_hash

    reg = load_registry(case_dir)
    assert len(reg["evidence"]) == 2
    assert reg["evidence"][0]["content_hash"] == v1_hash
    assert reg["evidence"][0]["superseded_by"] == rec2["evidence_id"]


def test_p0_1_desk_intake_refuses_reusing_case_id_with_modified_invoice(tmp_path):
    """Verify run_intake refuses to overwrite an existing case when source invoice content changes."""
    con_file = tmp_path / "acme.json"
    con_file.write_text((REPO_ROOT / "seed" / "acme.json").read_text(encoding="utf-8"), encoding="utf-8")

    inv_file = tmp_path / "invoice_v1.json"
    sample_inv = json.loads((REPO_ROOT / "tests" / "fixtures" / "example_invoice.json").read_text(encoding="utf-8"))
    sample_inv["source_sha256"] = ""
    inv_file.write_text(json.dumps(sample_inv), encoding="utf-8")

    cases_dir = tmp_path / "cases"
    res1 = run_intake(
        invoice_path=inv_file,
        contract_path=con_file,
        case_id="OC-20261105-10",
        cases_dir=cases_dir,
        base_dir=tmp_path,
    )
    assert res1["ok"] is True

    # Modify invoice and attempt re-intake into the same case_id
    sample_inv["stated_total"] = "99999.00"
    inv_file.write_text(json.dumps(sample_inv), encoding="utf-8")

    with pytest.raises(ToolError) as exc_info:
        run_intake(
            invoice_path=inv_file,
            contract_path=con_file,
            case_id="OC-20261105-10",
            cases_dir=cases_dir,
            base_dir=tmp_path,
        )
    assert exc_info.value.code == 4
    assert "EVIDENCE_MUTATION_REFUSED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# P0.2 & P2.1 — Exact Decimal Text Invoice Parser & Strict Validation
# ---------------------------------------------------------------------------
def test_p0_2_txt_parser_uses_exact_decimal_and_no_float():
    """Verify tools/desk.py contains zero float() calls and parses values as exact Decimal strings."""
    desk_source = (REPO_ROOT / "tools" / "desk.py").read_text(encoding="utf-8")
    assert "float(" not in desk_source

    txt = (
        "Acme Supplies Pvt Ltd\n"
        "Invoice No: INV-2026-99\n"
        "Invoice Date: 2026-11-05\n"
        "Currency: INR\n"
        "1 | Corrugated carton, 5-ply (CC-5) | 500 | unit | 112.00 | 56000.00\n"
        "2 | Pallet wrap roll (PW-1) | 40.25 | unit | 250.00 | 10062.50\n"
        "Total: 66062.50\n"
    )
    parsed = parse_txt_invoice(
        text_content=txt,
        source_filename="inv-99.txt",
        source_sha256="a" * 64,
        case_id="OC-20261105-01",
        vendor_id="acme",
    )
    assert parsed["invoice_number"] == "INV-2026-99"
    assert parsed["invoice_date"] == "2026-11-05"
    assert parsed["stated_total"] == "66062.50"
    assert parsed["lines"][0]["quantity"] == "500"
    assert parsed["lines"][0]["unit_price"] == "112.00"
    assert parsed["lines"][0]["line_total"] == "56000.00"
    assert parsed["lines"][1]["quantity"] == "40.25"
    assert parsed["lines"][1]["line_total"] == "10062.50"


@pytest.mark.parametrize(
    "bad_txt,expected_msg",
    [
        (
            "Acme Supplies Pvt Ltd\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "Missing Invoice No",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "Missing Invoice Date",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-13-45\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "invoice_date is not an ISO date",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | NaN | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "not a finite number",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.129 | 1001.29\nTotal: 1001.29\n",
            "exceeds maximum supported precision",
        ),
    ],
)
def test_p0_2_txt_parser_rejects_malformed_or_missing_fields(bad_txt, expected_msg):
    """Verify parse_txt_invoice rejects missing invoice number/date, NaN, and unsupported precision."""
    with pytest.raises(ToolError) as exc_info:
        parse_txt_invoice(
            text_content=bad_txt,
            source_filename="bad.txt",
            source_sha256="b" * 64,
            case_id="OC-20261105-01",
            vendor_id="acme",
        )
    assert expected_msg.lower() in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# P0.3 — Cryptographically Authenticated & Hash-Chained Evidence Registry
# ---------------------------------------------------------------------------
def test_p0_3_evidence_registry_detects_simultaneous_file_and_json_tampering(tmp_path):
    """Verify that tampering with both an evidence file AND its hash in evidence_registry.json is caught."""
    case_dir = tmp_path / "OC-20261105-03"
    inv_file = case_dir / "inv.txt"
    case_dir.mkdir(parents=True)
    inv_file.write_text("Authentic Invoice 100.00", encoding="utf-8")

    register_evidence(
        case_dir=case_dir,
        file_path=inv_file,
        evidence_type="source_invoice",
        case_id="OC-20261105-03",
    )

    reg_before = load_registry(case_dir)
    assert reg_before["registry_sequence"] == 1
    assert len(reg_before["registry_digest"]) == 64

    # Attacker modifies BOTH the file on disk AND its content_hash inside evidence_registry.json
    inv_file.write_text("Forged Invoice 999.00", encoding="utf-8")
    forged_hash = sha256_file(inv_file)
    reg_path = case_dir / "evidence_registry.json"
    raw_reg = json.loads(reg_path.read_text(encoding="utf-8"))
    raw_reg["evidence"][0]["content_hash"] = forged_hash
    reg_path.write_text(json.dumps(raw_reg, indent=2), encoding="utf-8")

    # verify_evidence must detect that registry_digest / registry_signature no longer matches!
    res = verify_evidence(case_dir)
    assert res["ok"] is False
    assert any(f["evidence_id"] in ("REGISTRY", "REGISTRY_HMAC") for f in res["failures"])


# ---------------------------------------------------------------------------
# P1.1 — Demo Identity vs. Production Identity Separation
# ---------------------------------------------------------------------------
def test_p1_1_demo_accounts_refused_in_production(tmp_path, monkeypatch):
    """Verify demo accounts cannot authenticate or run simulations when APP_ENV=production."""
    db_path = tmp_path / "prod_identity.db"
    repo = IdentityRepository(db_path=db_path)
    repo.create_user(
        user_id="USR-DEMO-OWNER",
        username="owner",
        email="owner@demo.local",
        full_name="Demo Owner",
        role=SystemRole.APPROVER,
        password_hash=hash_password("owner123"),
        is_active=False,  # Inactive at startup so check_production_safety passes
        is_demo=True,
    )
    svc = IdentityService(repository=repo, db_path=db_path, app_env="production")

    # Even if someone activates the demo row in SQLite, authenticate() in production refuses is_demo=True
    repo.set_user_active("USR-DEMO-OWNER", True)
    assert svc.authenticate("owner", "owner123") is None

    # Simulator refuses to execute when APP_ENV=production
    monkeypatch.setenv("APP_ENV", "production")
    assert run_simulation(fast=True) == 4


# ---------------------------------------------------------------------------
# P1.2 — Signing-Key Isolation & Hardening
# ---------------------------------------------------------------------------
def test_p1_2_signing_key_isolation_and_permissions(tmp_path, monkeypatch):
    """Verify repo config/signing.key is rejected, production refuses auto-gen, and dev creates 0o600 key."""
    forbidden_path = REPO_ROOT / "config" / "signing.key"
    with pytest.raises(ToolError, match="Signing key inside repository config"):
        load_signing_key(forbidden_path)

    # Production refuses ephemeral key auto-generation
    monkeypatch.setenv("APP_ENV", "production")
    missing_prod_key = tmp_path / "prod.key"
    with pytest.raises(ToolError, match="Refusing to auto-generate ephemeral signing key in production"):
        ensure_signing_key(missing_prod_key)

    # Development atomically generates key with 0o600 permissions
    monkeypatch.setenv("APP_ENV", "development")
    dev_key_path = tmp_path / "keys" / "signing.key"
    kb = ensure_signing_key(dev_key_path)
    assert len(kb) >= 32
    mode = stat.S_IMODE(dev_key_path.stat().st_mode)
    if os.name != "nt":
        assert mode == 0o600


# ---------------------------------------------------------------------------
# P1.3 & P1.4 — Stale Approval Refusal & Signed Audit Package Export
# ---------------------------------------------------------------------------
def test_p1_3_and_p1_4_stale_approval_refused_and_audit_export_signed(tmp_path):
    """Verify finalization refuses stale approval when evidence changes post-approval, and export signs checkpoints."""
    key_file = tmp_path / "signing.key"
    key_bytes = ensure_signing_key(key_file)

    cfg = {
        "config_version": "1.0.0",
        "signing_key_file": str(key_file),
        "token_validity_seconds": 300,
        "actors": [
            {
                "actor_id": "owner_prod",
                "display_name": "Verified Owner",
                "role": "APPROVER",
                "active": True,
                "permissions": ["approve_case", "reject_case"],
            }
        ],
    }
    cfg_file = tmp_path / "actors.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    # Set up clean isolated workspace in tmp_path
    (tmp_path / "invoices").mkdir()
    (tmp_path / "vendors").mkdir()
    raw_txt = (
        "Acme Supplies Pvt Ltd\n"
        "Invoice No: INV-1103\n"
        "Invoice Date: 2026-11-03\n"
        "Currency: INR\n"
        "1 | Corrugated carton, 5-ply (CC-5) | 500 | unit | 112.00 | 56000.00\n"
        "2 | Pallet wrap roll (PW-1) | 40 | unit | 250.00 | 10000.00\n"
        "Total: 66000.00\n"
    )
    inv_txt = tmp_path / "invoices" / "acme-inv-1103.txt"
    inv_txt.write_text(raw_txt, encoding="utf-8")

    ven_json = tmp_path / "vendors" / "acme.json"
    ven_json.write_text((REPO_ROOT / "seed" / "acme.json").read_text(encoding="utf-8"), encoding="utf-8")

    cases_dir = tmp_path / "cases"
    db_path = tmp_path / "ledger.db"

    # 1. Intake & Audit
    intake_res = run_intake(
        invoice_path=inv_txt,
        contract_path=ven_json,
        case_id="OC-20261105-55",
        cases_dir=cases_dir,
        base_dir=tmp_path,
    )
    case_dir = Path(intake_res["case_dir"])
    run_audit("OC-20261105-55", cases_dir=cases_dir, base_dir=tmp_path, ledger_db=db_path)

    # 2. Approve
    token = issue_actor_token("owner_prod", key_bytes, config=cfg)
    app_res = process_approval_decision(
        case_dir=case_dir,
        actor_token=token,
        decision="APPROVED",
        amount="60000.00",
        key_file=key_file,
        config_file=cfg_file,
    )
    assert app_res["ok"] is True

    # 3. Export signed audit package and verify checkpoint + package HMAC signature (P1.4)
    pkg_dir = tmp_path / "exported_pkg"
    rep = export_case_audit(case_dir, out_dir=pkg_dir, ledger_db=db_path, key_file=key_file)
    assert rep["ledger_checkpoint_id"] is not None
    assert "package_signature" in rep
    pkg_ok, pkg_issues = verify_package_integrity(pkg_dir, key_file=key_file)
    assert pkg_ok is True, f"Unexpected package issues: {pkg_issues}"

    # 4. Now inject an unapproved pre-approval evidence record after approval (P1.3)
    rogue_file = case_dir / "rogue_addendum.json"
    rogue_file.write_text('{"note": "post-approval mutation"}', encoding="utf-8")
    register_evidence(
        case_dir=case_dir,
        file_path=rogue_file,
        evidence_type="review_artifact",
        case_id="OC-20261105-55",
        base_dir=tmp_path,
    )

    # Finalization must refuse because pre-approval evidence_digest_set no longer matches receipt!
    with pytest.raises(ToolError) as exc_info:
        run_finalize(
            "OC-20261105-55",
            cases_dir=cases_dir,
            base_dir=tmp_path,
            signing_key_file=key_file,
            ledger_db=db_path,
        )
    assert exc_info.value.code == 4
    assert "STALE_APPROVAL_REFUSED" in str(exc_info.value)


if __name__ == "__main__":
    tmp_root = Path(tempfile.mkdtemp())
    os.environ["OVERCHARGE_KEY_DIR"] = str(tmp_root / "keys")
    ensure_signing_key(tmp_root / "keys" / "signing.key")

    class _MonkeyPatch:
        def __init__(self):
            self.orig = {}

        def setenv(self, k, v):
            if k not in self.orig:
                self.orig[k] = os.environ.get(k)
            os.environ[k] = v

        def restore(self):
            for k, v in self.orig.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    test_p0_1_evidence_cannot_be_silently_replaced_on_re_registration(Path(tempfile.mkdtemp()))
    test_p0_1_explicit_amendment_creates_versioned_append_only_record(Path(tempfile.mkdtemp()))
    test_p0_1_desk_intake_refuses_reusing_case_id_with_modified_invoice(Path(tempfile.mkdtemp()))
    test_p0_2_txt_parser_uses_exact_decimal_and_no_float()
    for bad_txt, expected_msg in [
        (
            "Acme Supplies Pvt Ltd\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "Missing Invoice No",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "Missing Invoice Date",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-13-45\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "invoice_date is not an ISO date",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | NaN | unit | 100.00 | 1000.00\nTotal: 1000.00\n",
            "not a finite number",
        ),
        (
            "Acme Supplies Pvt Ltd\nInvoice No: INV-1\nInvoice Date: 2026-11-05\nCurrency: INR\n"
            "1 | Item | 10 | unit | 100.129 | 1001.29\nTotal: 1001.29\n",
            "exceeds maximum supported precision",
        ),
    ]:
        test_p0_2_txt_parser_rejects_malformed_or_missing_fields(bad_txt, expected_msg)

    test_p0_3_evidence_registry_detects_simultaneous_file_and_json_tampering(Path(tempfile.mkdtemp()))

    mp1 = _MonkeyPatch()
    try:
        test_p1_1_demo_accounts_refused_in_production(Path(tempfile.mkdtemp()), mp1)
    finally:
        mp1.restore()

    mp2 = _MonkeyPatch()
    try:
        test_p1_2_signing_key_isolation_and_permissions(Path(tempfile.mkdtemp()), mp2)
    finally:
        mp2.restore()

    test_p1_3_and_p1_4_stale_approval_refused_and_audit_export_signed(Path(tempfile.mkdtemp()))
    print("ALL REPOSITORY AUDIT REMEDIATION TESTS PASSED!")

