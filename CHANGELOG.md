# Changelog

All notable changes to Overcharge Desk are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.3.0] - 2026-11-05

### Added
- **Unified Agent CLI (`tools/desk.py`)**:
  - Deterministic agent interface providing `intake`, `audit`, `status`, `history`, and `finalize` subcommands.
  - Strict architectural omission of any `approve` subcommand; AI agents cannot authorize financial payments under any prompt or circumstance.
  - `history --vendor <vendor_id>` query mode returning historical cases, invoice dates, outcomes, and withheld variances to support the vendor memory moment in Switch rooms.
  - Emits full 64-character SHA-256 digests for `invoice_sha256`, `compare_sha256`, `verification_id`, and `ledger_head`.
- **Interactive Terminal Owner Approval CLI (`tools/approve.py`)**:
  - Out-of-band human authorization requiring an interactive TTY session (`sys.stdin.isatty()`); headless agents, pipes, and automated subshells are strictly refused.
  - Prompts securely for owner credentials using `getpass`, verifying against `IdentityRepository` with memory-hard Argon2id.
  - Computes exact payable amounts server-side from `compare.json`.
  - Produces full 64-character SHA-256 cryptographic receipt hash formatted for posting to the Switch room.
- **External Key Isolation Architecture**:
  - Signing keys and manifests reside strictly outside the repository tree via `OVERCHARGE_KEY_DIR` (defaulting to `~/.overcharge/keys/`) or `OVERCHARGE_SIGNING_KEY`.
  - Prohibits tests, demos, or agents from generating `.key` files inside the repository working directory.
- **Authentication Gateway Lockdown**:
  - `python tools/auth.py issue-token` strictly locked down with fail-closed refusal (exit code 4) unless explicit `--dev` flag is supplied.
- **Switch & Mattermost Multi-Agent Documentation**:
  - Rewrote `agents/READER.md`, `agents/AUDITOR.md`, and `agents/WRITER.md` to reference only `tools/desk.py` and 64-character receipt verification.
  - Removed leftover stray comment lines in `agents/WRITER.md`.
  - Updated `SWITCH_SETUP.md` with multi-agent orchestration architecture and TTY approval protocol.
  - Elevated Switch & Mattermost story upfront in `README.md` and added honest disclosure on same-OS-user process boundaries vs. container isolation.
- **Automated Test Suite Expansion**:
  - Added `tests/test_approve_cli.py` (6 tests) and `tests/test_desk_cli.py` (9 tests).
  - Test suite expanded to **227 automated test scenarios**, certified across Windows, Ubuntu, and Python 3.9–3.13.

---

## [3.2.0] - 2026-11-05

### Added
- **Argon2id Password Storage & Bound Checking** (`domain/identity/passwords.py`):
  - Memory-hard Argon2id ($64\text{ MB}$, 3 iterations, 4 parallelism) with PBKDF2-HMAC-SHA256 (600,000 rounds) fallback and automatic transparent rehash.
  - String length bounds enforcement (8–1024 characters) to neutralize password hashing DoS.
- **Persistent SQLite Identity Store & Opaque Bearer Tokens** (`domain/identity/repository.py`):
  - 32-byte cryptographic random session tokens stored exclusively as SHA-256 hashes (`token_hash`) with WAL mode and foreign key integrity.
  - Dedicated `/api/v1/auth/logout` endpoint for instant session token revocation.
- **Fail-Closed Cryptographic Key Management & Rotation** (`domain/identity/key_manager.py`):
  - Explicit key status lifecycle (`ACTIVE`, `RETIRED`, `REVOKED`), tracking historical keys for backwards verification.
  - Refusal to start in production if key manifest or active key files are missing or have insecure file permissions.
- **Strict Case Storage Isolation & Symlink Containment** (`domain/cases/storage.py`):
  - Enforced `^[a-zA-Z0-9_\-]{3,64}$` case identifier regex, prohibiting path traversal tokens (`..`, `/`, `\`, null bytes).
  - Explicit canonical containment assertions, symlink escape checks, 10MB artifact size limits, and allowed artifact registry.
- **Transactional Case State Machine with Optimistic Concurrency** (`domain/cases/transitions.py`):
  - Closed transition graph with optimistic version checks preventing race conditions and inconsistent lifecycle progression.
- **Controlled Payment Release & Destination Verification** (`domain/payments/`, `domain/vendors/`):
  - Payment instructions isolated behind verified approval receipts, single instruction per approval, and duplicate export prevention.
  - Remittance routing verification in `VendorRegistry` defeating invoice text BEC and routing spoofing.
- **API Perimeter Defense & Health Observability** (`services/api/middleware.py`, `services/api/main.py`):
  - Security headers (CSP, nosniff, DENY frame options, strict referrer, HSTS, `X-Request-ID`).
  - Sliding window brute-force lockout (5 attempts / 5 minutes) with generic error responses.
  - Operational health endpoint distinguishing `READY` and `DEGRADED` states across DB, storage, and key manager.
- **Automated Test Suite Expansion**:
  - Expanded test suite from 154 to 186 automated test scenarios across security, concurrency, payments, and recovery.

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

