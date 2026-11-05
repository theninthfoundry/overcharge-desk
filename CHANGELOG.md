# Changelog

All notable changes to Overcharge Desk are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.0.0] - 2026-11-05

### Added
- **Multi-User Identity & RBAC Domain** (`domain/identity/`, `domain/authorization/`):
  - Defined 6 enterprise finance operational roles: `ADMINISTRATOR`, `FINANCE_OPERATOR`, `REVIEWER`, `APPROVER`, `AUDITOR`, `PAYMENT_OPERATOR`.
  - Server-side permission enforcement and separation of duties (no user can approve their own case).
- **FastAPI Operations Backend Service** (`services/api/`):
  - RESTful API wrapping the existing deterministic Python financial engine without duplicating calculations.
  - Endpoints for case lifecycle management, reconciliation execution, approval processing, artifact streaming, and ledger audits.
- **Finance Operations Dashboard** (`apps/web/`):
  - Visual interface for case intake, rate discrepancy inspection, approval reviews, and audit exports.
- **Standalone Case Audit Package Exporter & Verifier** (`tools/export_audit_package.py`):
  - Self-contained audit bundle export (`case_audit/<case_id>/`) with cryptographic `audit_integrity_report.json`.
- **Signed Checkpoints for Tamper-Evident Ledger** (`tools/audit_ledger.py`, `tools/verify_ledger.py`):
  - HMAC-signed periodic checkpoints binding highest sequence number, chain digest, and head event hash.

---

## [2.1.0] - 2026-11-05

### Added
- **Central 4-Dimensional State Model** (`tools/state_model.py`):
  - Independent `VerificationStatus`, `CommercialStatus`, `ApprovalStatus`, and `PaymentRecommendationStatus`.
  - Machine-enforced cross-dimensional consistency validation.
- **Independent Stage 8 Verification Artifact** (`tools/validate_comparison.py`):
  - Generates formal `verification.json` and companion `.sha256` digest certifying source digest, rate parity, and line math.
- **Append-Only SQLite Triggers** (`tools/audit_ledger.py`):
  - Mechanical `BEFORE UPDATE/DELETE` abort triggers preventing direct database record alteration.
- **Controlled 4-Tier Output Routing** (`tools/pipeline.py`):
  - Segregated pre-approval `payment_preview.csv` (unauthorized) from `corrected_payment.csv` (strictly requires approval receipt).
- **Six Canonical Benchmark Demo Cases** (`tools/run_demo_suite.py`):
  - Expanded benchmark coverage to include Case E (Post-Approval Tampering Refusal) and Case F (Ledger Failure Abort).
- **Deterministic Cross-Platform Hashing**:
  - Enforced LF line endings via `.gitattributes` and verified 10/10 matrix jobs on GitHub Actions.

---

## [2.0.0] - 2026-11-04

### Added
- **Rebuilt Deterministic Financial Comparison Engine** (`tools/compare.py`):
  - Exact `decimal.Decimal` arithmetic and explicit `ROUND_HALF_UP` quantization across all monetary calculations.
  - Internal arithmetic discrepancy quarantine ($Qty \times Price \neq LineTotal$ triggers `STATUS_SOURCE_DISCREPANCY` and forces `BLOCKED`).
  - Schema 2.0.0 comparison result structure with companion SHA-256 digest.
- **Evidence Registry & Document Fingerprinting** (`tools/evidence.py`):
  - Full 64-character SHA-256 fingerprinting of all raw documents and comparison outputs.
- **Cryptographic Approval Protocol** (`tools/approval_gateway.py`, `tools/approval_receipt.py`):
  - Full 64-character hash digest binding into canonical HMAC-SHA-256 approval receipts.
  - Strict payable amount matching against contract schedule calculations.
- **Tamper-Evident SQLite Ledger** (`tools/audit_ledger.py`):
  - Continuous cryptographic hash chain anchored by genesis block (`0 * 64`).

---

## [1.0.0] - 2026-11-01

### Added
- Initial project prototype and canonical repository structure.
- Basic rate comparison CLI and Acme demo invoice fixtures.
- Baseline test suite.
