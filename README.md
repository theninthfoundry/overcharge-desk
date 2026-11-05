# Overcharge Desk 🔍⚡

> **Deterministic, Evidence-First Vendor Reconciliation & Cryptographic Payment Control**  
> Verifies commercial invoices against contracts with exact decimal arithmetic, binds human approvals to immutable cryptographic evidence receipts, logs append-only event chains in a tamper-evident SQLite ledger, and strictly prevents unauthorized or unverified payment recommendations.

[![Tests](https://img.shields.io/badge/Tests-136%20Passed-success?style=for-the-badge&logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/Python-3.9%20|%203.10%20|%203.11%20|%203.12%20|%203.13-blue?style=for-the-badge&logo=python)](https://python.org)
[![Arithmetic](https://img.shields.io/badge/Arithmetic-Exact%20Decimal%20(No%20Floats)-brightgreen?style=for-the-badge)](AGENTS.md)
[![Security](https://img.shields.io/badge/Security-Fail--Closed%20RBAC-red?style=for-the-badge)](docs/SECURITY_MODEL.md)
[![Ledger](https://img.shields.io/badge/Ledger-Tamper--Evident%20SHA--256%20Chain-blueviolet?style=for-the-badge)](tools/audit_ledger.py)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 📌 Executive Overview

Small and medium enterprises lose **3% to 7% of direct spend** to invoice errors, pricing creep, and repeated vendor overbilling. Traditional software either requires costly ERP customizations or relies on probabilistic LLM agents that hallucinate arithmetic, skip verification steps, or treat plain text chat handles as financial authorization.

**Overcharge Desk** replaces fragile autonomous LLM actions with a **deterministic financial verification engine** wrapped in a **cryptographic authorization gateway** and a **tamper-evident audit ledger**:

1. **Zero LLM Arithmetic**: All price checks, variance calculations, and subtotal aggregations use `decimal.Decimal` with explicit half-up rounding (`ROUND_HALF_UP`) to two decimal places. Floating-point calculations are strictly forbidden.
2. **Fail-Closed Verification**: Invoices exhibiting internal arithmetic mismatches ($Qty \times Price \neq LineTotal$) or missing source documents immediately trigger `BLOCKED` status, preventing any automated payment recommendation.
3. **Cryptographic Approval Binding**: Human approvals require full 64-character SHA-256 digests binding `(case_id, invoice_number, invoice_sha256, contract_id, compare_sha256, audit_sha256, decision, authenticated_actor)`. No 8-character abbreviations.
4. **Tamper-Evident SQLite Audit Ledger**: Every action forms an append-only, sequential cryptographic hash chain anchored by a genesis block (`0 * 64`). Any historical modification, reordering, or deletion is detected.
5. **Three-Tier Output Control**: Artifacts are strictly segregated into `corrected_payment.csv` (100% verified), `partial_review.csv` (investigation only, no final settlement), and `blocked_review_report.csv` (discrepancy facts only, zero payable fields).

---

## 🏗 System Architecture

```
                       [ INCOMING INVOICE ]
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │   Evidence Registry   │ (tools/evidence.py)
                     │   Full SHA-256 Intake │
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │ Financial Verification│ (tools/compare.py)
                     │ Exact Decimal Engine  │
                     └───────────┬───────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
    [ VERIFIED ]       [ REVIEW_REQUIRED ]        [ BLOCKED ]
    (100% matched,       (Uncontracted SKU,       (Math mismatch,
     sound math)          ambiguous desc)          tampered hash)
          │                      │                      │
          │                      ▼                      ▼
          │             partial_review.csv      blocked_review_report.csv
          │             (Investigation only)    (Zero payable fields)
          │
          ▼
┌───────────────────────────┐
│   Authorization Gateway   │ (tools/approval_gateway.py)
│  HMAC-SHA-256 RBAC Token  │
│  Cryptographic Receipt    │ (tools/approval_receipt.py)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│ SQLite Audit Ledger       │ (tools/audit_ledger.py)
│ Append-Only Hash Chain    │
└─────────────┬─────────────┘
              │
              ▼
    corrected_payment.csv
    (Contract payable amounts & withheld sums)
```

---

## 🛡 Core Engineering Invariants (AGENTS.md)

| Category | Invariant | Mechanical Enforcement |
|---|---|---|
| **Financial** | Mandatory Exact Decimal Arithmetic | `decimal.Decimal` with `ROUND_HALF_UP` on every line; floats raise `TypeError` or `ToolError`. |
| **Financial** | Source Invoice Truth Preservation | Source extracted values are never silently rounded or normalized to force passing. |
| **Financial** | Discrepancy Quarantine | Internal arithmetic errors ($Qty \times Price \neq LineTotal$) trigger `STATUS_SOURCE_DISCREPANCY` and set system to `BLOCKED`. |
| **Evidence** | Universal Source Referencing | Every line item and variance references immutable locators (`invoices/acme-inv-1103.txt#line-1`). |
| **Evidence** | Cryptographic Fingerprinting | Raw source artifacts are fingerprinted with full 64-character SHA-256 digests upon registration. |
| **Security** | Fail-Closed Authorization | Missing, stale, or unauthenticated identities cause immediate refusal with exit code 4. |
| **Security** | Full 64-char Hash Digest Requirement | Shortened hash prefixes (e.g. 8-char) are rejected. Receipts bind all artifact digests into HMAC signatures. |
| **Ledger** | Tamper-Evident Hash Chain | Each event incorporates `previous_event_hash` in its canonical SHA-256 digest, starting from genesis. |

---

## 🚀 Quickstart & Installation

### Requirements
- Python 3.9+ (Standard Library only; no external runtime dependencies).
- `pytest` for running the automated test suite.

### Setup
```bash
# Clone the repository
git clone https://github.com/theninthfoundry/overcharge-desk.git
cd overcharge-desk

# Install test dependencies
pip install -r requirements-dev.txt

# Run full test suite (136 tests)
python -m pytest -v
```

---

## 🧪 The Four Benchmark Demo Cases

Overcharge Desk includes 4 reference test cases demonstrating the complete lifecycle:

### Case A: Clean Match (`cases/demo-clean`)
- **Invoice**: 200 cartons @ ₹100.00 + 40 rolls @ ₹250.00 = ₹30,000.00.
- **Contract**: Exactly matches Schedule A rates.
- **Outcome**: `VERIFIED`, ₹30,000.00 payable, ₹0.00 withheld.
- **Receipt**: Signed approval receipt `AR-OC-20261001-01-...` issued.

### Case B: Acme Overcharge (`cases/demo-overcharge`) — Benchmark ₹6,000 Variance
- **Invoice**: 500 cartons @ ₹112.00 (₹56,000) + 40 rolls @ ₹250.00 (₹10,000) = ₹66,000.00.
- **Contract**: Schedule A CC-5 rate is ₹100.00 (+12% overcharge).
- **Outcome**: `VERIFIED`, ₹60,000.00 payable, **₹6,000.00 withheld**.
- **Action**: Owner approves contract rate payout with variance withheld; outputs `corrected_payment.csv`.

### Case C: Commercial Review Required (`cases/demo-review`)
- **Invoice**: 500 cartons @ ₹100.00 + 100 uncontracted straps @ ₹45.00 = ₹54,500.00.
- **Outcome**: `REVIEW_REQUIRED`, routes strictly to `partial_review.csv`.
- **Safety**: Refuses to generate final payment sheet without human contract amendment.

### Case D: Tampered / Arithmetic Discrepancy (`cases/demo-blocked`)
- **Invoice**: 500 cartons @ ₹112.00, but line total written as ₹58,000.00 (math mismatch).
- **Outcome**: `BLOCKED`, routes to `blocked_review_report.csv`.
- **Safety**: Zero payable fields emitted; Authorization Gateway refuses approval fail-closed.

### Running the End-to-End Demo Suite
```bash
python tools/run_demo_suite.py --clean
```

---

## 🧰 CLI Tool Reference

### 1. Invoice Validation (`tools/check_invoice.py`)
Validates schema structure, source file presence, and mathematical parity:
```bash
python tools/check_invoice.py cases/demo-overcharge/invoice.json --strict
```

### 2. Rate Comparison Engine (`tools/compare.py`)
Deterministic contract rate verification (schema 2.0.0) with companion digest:
```bash
python tools/compare.py cases/demo-overcharge/invoice.json vendors/acme.json --out compare.json --save-digest
```

### 3. Independent Comparison Validator (`tools/validate_comparison.py`)
Independent auditor verifying schema, decimal arithmetic, and companion SHA-256 digests:
```bash
python tools/validate_comparison.py compare.json --digest compare.json.sha256 --strict
```

### 4. Actor Model & Token Authentication (`tools/auth.py`)
Issues and validates HMAC-SHA-256 tokens for role-based access:
```bash
# Issue 5-minute token for owner
python tools/auth.py issue-token owner

# Verify token validity
python tools/auth.py verify-token "<token>"
```

### 5. Authorization Gateway (`tools/approval_gateway.py`)
Validates actor identity, re-verifies evidence on disk, and signs approval receipts:
```bash
# Approve case with exact payable amount check
python tools/approval_gateway.py approve cases/demo-overcharge --token "<owner_token>" --amount 60000.00

# Reject case with required owner rationale
python tools/approval_gateway.py reject cases/demo-overcharge --token "<owner_token>" --reason "Supplier agreed to reissue"
```

### 6. Tamper-Evident SQLite Ledger (`tools/audit_ledger.py` & `tools/verify_ledger.py`)
Append-only cryptographic event logging:
```bash
# Verify complete hash chain from genesis to head
python tools/verify_ledger.py --strict
```

### 7. Controlled Pipeline Orchestrator (`tools/pipeline.py`)
Runs the full 13-stage controlled reconciliation flow:
```bash
python tools/pipeline.py cases/demo-overcharge/invoice.json vendors/acme.json out_dir/ --strict
```

---

## 📊 Test Suite & Verification Matrix

The test suite covers **136 automated test cases** across 8 test modules:

```text
tests/test_audit_ledger.py              8 passed (Genesis, hash links, tampering detection, reordering)
tests/test_auth_and_approval.py         15 passed (HMAC tokens, TTL, role permissions, signed receipts)
tests/test_boundary_audit.py            20 passed (3-tier artifact model, path traversal, injection)
tests/test_case_manager_and_evidence.py  8 passed (Directory layout, state transitions, SHA-256 tracking)
tests/test_compare.py                   21 passed (Decimal precision, rounding, SKU boundaries, dates)
tests/test_financial_adversarial.py     35 passed (Invalid numbers, negative quantities, formula injection)
tests/test_pipeline_orchestration.py     3 passed (Execution manifests, approval enforcement, recovery)
tests/test_tools.py                     25 passed (CLI utilities, error exits, seed parity)
tests/test_demo_cases.py                 1 passed (Full 4-case end-to-end benchmark suite)
-----------------------------------------------------------------------------------------------------
TOTAL: 136 passed in ~5 seconds
```

---

## 🔒 Security & Trust Boundaries

> [!IMPORTANT]
> - **HMAC-SHA-256 Signatures**: Authenticate that the token or receipt was created by an entity in possession of the shared signing key. They do not provide cryptographic non-repudiation.
> - **Tamper-Evident Ledger**: The SQLite hash chain detects accidental corruption, row reordering, and unauthorized updates. A party with direct file access could recalculate the chain from a tampered node forward; external periodic checkpointing or remote append-only logging is recommended for untrusted host environments.
> - **Spreadsheet Formula Injection**: All CSV exports sanitize leading characters (`=`, `+`, `-`, `@`, `\t`, `\r`) with single quotes to prevent code execution when opened in Excel or Google Sheets.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
