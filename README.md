# Overcharge Desk 🔍⚡

> **Deterministic, Evidence-First Vendor Reconciliation & Cryptographic Payment Control**  
> Verifies commercial invoices against contracts with exact decimal arithmetic, binds human approvals to immutable cryptographic evidence receipts, logs append-only event chains in a tamper-evident SQLite ledger, and strictly prevents unauthorized or unverified payment recommendations.

[![Tests](https://img.shields.io/badge/Tests-211%20Passed-success?style=for-the-badge&logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/Python-3.9%20|%203.10%20|%203.11%20|%203.12%20|%203.13-blue?style=for-the-badge&logo=python)](https://python.org)
[![Arithmetic](https://img.shields.io/badge/Arithmetic-Exact%20Decimal%20(No%20Floats)-brightgreen?style=for-the-badge)](AGENTS.md)
[![Security](https://img.shields.io/badge/Security-Fail--Closed%20Argon2id%20&%20RBAC-red?style=for-the-badge)](docs/SECURITY_MODEL.md)
[![Ledger](https://img.shields.io/badge/Ledger-Tamper--Evident%20SHA--256%20Chain-blueviolet?style=for-the-badge)](tools/audit_ledger.py)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 📌 Executive Overview

Small and medium enterprises lose **3% to 7% of direct spend** to invoice errors, pricing creep, and repeated vendor overbilling. Traditional software either requires costly ERP customizations or relies on probabilistic LLM agents that hallucinate arithmetic, skip verification steps, or treat plain text chat handles as financial authorization.

**Overcharge Desk** replaces fragile autonomous LLM actions with a **deterministic financial verification engine** wrapped in a **cryptographic authorization gateway** and a **tamper-evident audit ledger**:

1. **Zero LLM Arithmetic**: All price checks, variance calculations, and subtotal aggregations use `decimal.Decimal` with explicit half-up rounding (`ROUND_HALF_UP`) to two decimal places. Floating-point calculations are strictly forbidden.
2. **Fail-Closed Verification**: Invoices exhibiting internal arithmetic mismatches ($Qty \times Price \neq LineTotal$) or missing source documents immediately trigger `BLOCKED` status, preventing any automated payment recommendation.
3. **Four-Dimensional State Model**: Independent tracking of `VerificationStatus`, `CommercialStatus`, `ApprovalStatus`, and `PaymentRecommendationStatus` with strict cross-dimensional consistency validation.
4. **Independent Stage 8 Verification Artifact**: Produces a formal `verification.json` certifying schema validity, source digest parity, contract schedule rate matching, and mathematical integrity.
5. **Cryptographic Approval Binding**: Human approvals require full 64-character SHA-256 digests binding `(case_id, invoice_number, invoice_sha256, contract_id, compare_sha256, verification_id, ledger_head, decision, authenticated_actor)`. No shortened prefixes.
6. **Tamper-Evident SQLite Ledger with Triggers & Checkpoints**: Every action forms an append-only cryptographic hash chain anchored by a genesis block (`0 * 64`), guarded by database-level `BEFORE UPDATE/DELETE` abort triggers, and verifiable against HMAC-signed checkpoints.
7. **Four-Tier Controlled Output Routing**:
   - `payment_preview.csv`: Pre-approval analysis artifact (explicitly labeled `NOT AUTHORIZED FOR PAYMENT`).
   - `corrected_payment.csv`: Only emitted upon cryptographic verification of a valid signed approval receipt.
   - `partial_review.csv`: Uncontracted items routed for commercial review (zero final settlement).
   - `blocked_review_report.csv`: Arithmetic errors or tampered inputs (zero payable fields).
8. **Standalone Audit Package Exporter**: Packages complete evidence, verification records, receipts, and ledger history into `case_audit/<case_id>/` with an independently verifiable `audit_integrity_report.json`.

---

## 🏗 System Architecture & 13-Stage Pipeline

```
                         [ INCOMING INVOICE ]
                                  │
      ┌───────────────────────────┴───────────────────────────┐
      │  Stage 1: Load invoice JSON & vendor metadata         │
      │  Stage 2: Strict schema validation & bounds checking   │
      │  Stage 3: Currency & Vendor matching                  │
      │  Stage 4: Document preservation & SHA-256 intake      │
      │  Stage 5: Recalculate SHA-256 digest of source file   │
      │  Stage 6: Verify source digest against declaration    │
      │  Stage 7: Deterministic contract rate comparison      │
      │  Stage 8: Independent Verification (verification.json)│
      │  Stage 9: Fail-closed Evidence Registration           │
      │  Stage 10: SQLite Append-Only Audit Ledger Recording  │
      └───────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
                     [ 4-Tier Output Routing ]
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
   [ VERIFIED ]          [ REVIEW_REQUIRED ]          [ BLOCKED ]
   (100% matched,          (Uncontracted SKU,         (Math mismatch,
    sound math)             ambiguous desc)            tampered hash)
         │                        │                        │
         ├──────────────────┐     ▼                        ▼
         │ (Pre-Approval)   │   partial_review.csv   blocked_review_report.csv
         │                  │   (Investigation only) (Zero payable fields)
         ▼                  │
   payment_preview.csv      │
   (UNAUTHORIZED PREVIEW)   │
                            ▼
               ┌───────────────────────────┐
               │   Authorization Gateway   │ (tools/approval_gateway.py)
               │  Strict Positive Allowlist│
               │  HMAC-SHA-256 RBAC Token  │
               │  Evidence Disk Re-check   │
               │  Cryptographic Receipt    │ (tools/approval_receipt.py)
               └────────────┬──────────────┘
                            │
                            ▼
               ┌───────────────────────────┐
               │ Tamper-Evident Ledger     │ (tools/audit_ledger.py)
               │ Append-Only Triggers      │
               │ Signed Checkpoints        │
               └────────────┬──────────────┘
                            │
                            ▼
               corrected_payment.csv
               (Authorized contract rates & withheld overcharges)
                            │
                            ▼
               Stage 13: Execution Manifest (manifest.json)
               Standalone Audit Package Export (tools/export_audit_package.py)
```

---

## 🛡 Core Engineering Invariants (AGENTS.md)

| Category | Invariant | Mechanical Enforcement |
|---|---|---|
| **Financial** | Mandatory Exact Decimal Arithmetic | `decimal.Decimal` with `ROUND_HALF_UP` on every line; floats raise `TypeError` or `ToolError`. |
| **Financial** | Source Invoice Truth Preservation | Source extracted values are never silently rounded or normalized to force passing. |
| **Financial** | Discrepancy Quarantine | Internal arithmetic errors ($Qty \times Price \neq LineTotal$) trigger `STATUS_SOURCE_DISCREPANCY` and set system to `BLOCKED`. |
| **Financial** | Recommendation vs Execution | Verified outputs are authorized recommendations; actual banking disbursement is strictly separated. |
| **Evidence** | Universal Source Referencing | Every line item and variance references immutable locators (`invoices/acme-inv-1103.txt#line-1`). |
| **Evidence** | Cryptographic Fingerprinting | Raw source artifacts are fingerprinted with full 64-character SHA-256 digests upon registration. |
| **Security** | Fail-Closed Authorization | Missing, stale, or unauthenticated identities cause immediate refusal with exit code 4. |
| **Security** | Full 64-char Hash Digest Requirement | Shortened hash prefixes (e.g. 8-char) are rejected. Receipts bind all artifact digests into HMAC signatures. |
| **Ledger** | Tamper-Evident Hash Chain | Each event incorporates `previous_event_hash` in its canonical SHA-256 digest, starting from genesis. |
| **Ledger** | Database-Level Append-Only Triggers | SQLite triggers prevent direct `UPDATE` and `DELETE` on historical audit events. |

---

## 🚀 Quickstart & Installation

### Requirements
- Python 3.9+ (Standard Library only for core verification; no external runtime dependencies).
- `pytest` for running the automated test suite.

### Setup
```bash
# Clone the repository
git clone https://github.com/theninthfoundry/overcharge-desk.git
cd overcharge-desk

# Install test dependencies
pip install -r requirements-dev.txt

# Run full test suite (154 tests)
python -m pytest -v
```

---

## 🧪 The Six Canonical Benchmark Demo Cases

Overcharge Desk includes 6 benchmark test cases demonstrating the complete lifecycle and failure modes:

| Case | Directory | Invoice | Invoiced | Payable | Withheld | State | Result |
|---|---|---|---|---|---|---|---|
| **Case A** | `cases/demo-clean` | INV-1001 | ₹30,000.00 | ₹30,000.00 | ₹0.00 | `VERIFIED` | Clean payment sheet + approval receipt |
| **Case B** | `cases/demo-overcharge` | INV-1103 | ₹66,000.00 | ₹60,000.00 | ₹6,000.00 | `VERIFIED` | Corrected payment sheet (₹6k withheld) + Audit Package |
| **Case C** | `cases/demo-review` | INV-1201 | ₹54,500.00 | N/A | N/A | `REVIEW_REQUIRED` | Partial review artifact (investigation only) |
| **Case D** | `cases/demo-blocked` | INV-1301 | ₹68,000.00 | N/A | N/A | `BLOCKED` | Discrepancy report; gateway strictly refuses approval |
| **Case E** | `cases/demo-tampering` | INV-1001 | ₹30,000.00 | Refused | Refused | `TAMPERED` | Post-approval modification detected; payment refused fail-closed |
| **Case F** | `cases/demo-ledger-failure` | INV-1001 | ₹30,000.00 | Refused | Refused | `ABORTED` | Unwriteable ledger causes immediate fail-closed pipeline abort |

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
Deterministic contract rate verification (schema 2.0.0) with commercial status categorization:
```bash
python tools/compare.py cases/demo-overcharge/invoice.json vendors/acme.json --out compare.json --save-digest
```

### 3. Independent Verification Engine (`tools/validate_comparison.py`)
Independent auditor verifying math down to the byte and generating formal `verification.json`:
```bash
python tools/validate_comparison.py compare.json --out-verification verification.json --strict
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
Enforces strict positive allowlist, re-verifies evidence on disk, and signs approval receipts:
```bash
# Approve case with exact payable amount check
python tools/approval_gateway.py approve cases/demo-overcharge --token "<owner_token>" --amount 60000.00

# Reject case with required owner rationale
python tools/approval_gateway.py reject cases/demo-overcharge --token "<owner_token>" --reason "Supplier agreed to reissue"
```

### 6. Tamper-Evident SQLite Ledger (`tools/audit_ledger.py` & `tools/verify_ledger.py`)
Append-only cryptographic event logging and signed checkpoints:
```bash
# Create HMAC-signed checkpoint
python tools/audit_ledger.py checkpoint --out checkpoint.json --key-file config/signing.key

# Verify complete hash chain and checkpoint
python tools/verify_ledger.py --strict --checkpoint checkpoint.json --key-file config/signing.key
```

### 7. Controlled Pipeline Orchestrator (`tools/pipeline.py`)
Runs the full 13-stage controlled reconciliation flow:
```bash
# Pass 1: Pre-approval preview (outputs payment_preview.csv)
python tools/pipeline.py cases/demo-overcharge/invoice.json vendors/acme.json cases/demo-overcharge/

# Pass 2: Authorized payment release (requires signed receipt)
python tools/pipeline.py cases/demo-overcharge/invoice.json vendors/acme.json cases/demo-overcharge/ --require-approval
```

### 8. Standalone Audit Package Exporter (`tools/export_audit_package.py`)
Exports self-contained evidence bundles certified by cryptographic integrity reports:
```bash
# Export case audit package
python tools/export_audit_package.py export cases/demo-overcharge

# Verify package integrity independently
python tools/export_audit_package.py verify case_audit/OC-20261106-01
```

---

## 📊 Test Suite & Verification Matrix

The test suite covers **186 automated test cases** across 17 test modules:

```text
tests/test_api.py                                      10 passed (FastAPI endpoints, auth, cases, artifacts, audit, vendors)
tests/test_audit_ledger.py                             11 passed (Genesis, hash links, triggers, tampering, checkpoints)
tests/test_auth_and_approval.py                        15 passed (HMAC tokens, TTL, role permissions, signed receipts)
tests/test_boundary_audit.py                           20 passed (4-tier routing, path traversal, injection, digests)
tests/test_case_manager_and_evidence.py                 8 passed (Directory layout, state transitions, SHA-256 tracking)
tests/test_compare.py                                  21 passed (Decimal precision, rounding, SKU boundaries, dates)
tests/test_financial_adversarial.py                    35 passed (Invalid numbers, negative quantities, formula injection)
tests/test_pipeline_orchestration.py                    3 passed (Execution manifests, approval enforcement, recovery)
tests/test_rbac_and_separation_of_duties.py            5 passed (Separation of duties, allowlists, token lifecycle)
tests/test_tools.py                                    25 passed (CLI utilities, error exits, seed parity)
tests/test_demo_cases.py                                1 passed (Full 6-case end-to-end benchmark & export suite)
tests/concurrency/test_concurrency_and_transitions.py   3 passed (Optimistic concurrency, version checks, lifecycle graph)
tests/payments/test_payment_instructions.py             4 passed (Payment instructions, single export, unverified bank block)
tests/security/test_api_security.py                    5 passed (Security headers, CSP, brute-force lockout, generic auth)
tests/security/test_bootstrap_admin.py                  3 passed (Interactive CLI bootstrap, demo seed isolation)
tests/security/test_key_manager.py                      4 passed (Key lifecycle, retirement, revocation, rotation)
tests/security/test_operational_health.py               3 passed (LIVE, READY, and DEGRADED operational health probes)
tests/security/test_password_security.py                5 passed (Argon2id hashing, bounds checking, constant-time compare)
tests/security/test_storage_security.py                 5 passed (Path traversal guards, symlink containment, 10MB limits)
-------------------------------------------------------------------------------------------------------------------------
TOTAL: 186 passed, 1 skipped in ~20 seconds
```

---

## 🔒 Security, Trust Boundaries & Honest Immutability Disclosures

> [!IMPORTANT]
> - **What HMAC-SHA-256 Signatures Prove and Do Not Prove**:
>   - **Proves**: That the token, receipt, or checkpoint was generated with knowledge of the provisioning key (`config/signing.key`), and that bound artifact digests (`invoice_sha256`, `compare_sha256`, `verification_id`, `evidence_digest_set`) have not been altered since signing.
>   - **Does Not Prove**: HMAC is a symmetric cryptographic construction; it does **not** provide public-key non-repudiation or independently verify physical user identity. In enterprise production, HMAC tokens are paired with an authenticated OIDC provider and server-side session controls.
> - **Honest Immutability Claims for SQLite Ledger**:
>   - The SQLite database is **tamper-evident**, not physically immutable.
>   - Append-only behavior is mechanically enforced at runtime via SQLite triggers (`BEFORE UPDATE/DELETE RAISE(ABORT)`).
>   - An attacker with raw disk write access could theoretically rewrite historical rows and recompute hashes forward; therefore, periodic external signed checkpoints (`create_checkpoint`) and exportable audit packages are provided for independent external archiving.
> - **Distinction Between Recommendation and Payment Execution**:
>   - Overcharge Desk produces verified, authorized payment recommendation sheets (`corrected_payment.csv`).
>   - It does **not** execute automated bank transfers or initiate disbursements directly. Actual settlement execution occurs within external banking/ERP systems following human review.
> - **Spreadsheet Formula Injection Mitigation**:
>   - All CSV exports sanitize leading characters (`=`, `+`, `-`, `@`, `\t`, `\r`) with single quotes to prevent formula execution when opened in Microsoft Excel or Google Sheets.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
