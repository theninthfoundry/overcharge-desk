# TEST_STRATEGY.md — Adversarial Testing & Verification Strategy

> **System**: Overcharge Desk — Evidence-First Vendor Reconciliation & Cryptographic Payment Control  
> **Version**: 3.0.0  
> **Authority**: [AGENTS.md](file:///d:/overcharge%20files/AGENTS.md) Invariant 5 (Radical Engineering Transparency)

---

## 1. Test Architecture & Coverage Summary

Overcharge Desk enforces a zero-trust, test-driven engineering culture. No feature or security boundary is considered complete without automated test execution verifying both nominal and adversarial behaviors.

The automated test suite contains **227 passing tests** across 21 test modules:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.0
rootdir: D:\overcharge files
configfile: pytest.ini
testpaths: tests
collected 227 items

tests/concurrency/test_concurrency_and_transitions.py   6 passed (Optimistic locking, rollback, version race)
tests/payments/test_payment_instructions.py             6 passed (Instruction lifecycle, single export, audit trail)
tests/payments/test_vendor_registry.py                  2 passed (Verified bank account gates, unverified block)
tests/security/test_api_security.py                     7 passed (Security headers, CSP, brute-force lockout, generic auth)
tests/security/test_bootstrap_admin.py                  4 passed (Interactive getpass, demo seed isolation, duplicate block)
tests/security/test_identity_repository.py              3 passed (Argon2id persistence, session tokens, audit logging)
tests/security/test_key_manager.py                      7 passed (Key rotation, retirement, revocation, production gates)
tests/security/test_operational_health.py               4 passed (LIVE, READY, DEGRADED probes, component health)
tests/security/test_password_security.py                8 passed (Argon2id hashing, bounds checking, constant-time compare)
tests/security/test_storage_security.py                 9 passed (Path traversal guards, symlink containment, 10MB limits)
tests/test_api.py                                      10 passed (FastAPI endpoints, auth, cases, artifacts, audit)
tests/test_approve_cli.py                               6 passed (TTY enforcement, Argon2id auth, 64-char receipt hash)
tests/test_audit_ledger.py                             11 passed (Genesis block, triggers, tamper detection, checkpoints)
tests/test_auth_and_approval.py                        15 passed (HMAC tokens, TTL, role permissions, signed receipts)
tests/test_boundary_audit.py                           20 passed (4-tier routing, path traversal, injection prevention)
tests/test_case_manager_and_evidence.py                 8 passed (Directory layout, state transitions, SHA-256 tracking)
tests/test_compare.py                                  21 passed (Decimal precision, half-up rounding, SKU boundaries)
tests/test_demo_cases.py                                1 passed (Full 6-case benchmark & package export suite)
tests/test_desk_cli.py                                  9 passed (Agent CLI, no approve command, memory moment, key isolation)
tests/test_financial_adversarial.py                    35 passed (Invalid numbers, negative quantities, formula injection)
tests/test_pipeline_orchestration.py                    3 passed (Execution manifests, approval enforcement, recovery)
tests/test_rbac_and_separation_of_duties.py            5 passed (Separation of duties, allowlists, token lifecycle)
tests/test_tools.py                                    25 passed (CLI utilities, error exits, seed parity)
============================= 227 passed in ~14s =============================
```

---

## 2. Test Suites Detailed Breakdown

### 2.1 Financial Adversarial Suite (`test_financial_adversarial.py` — 35 tests)
Covers all arithmetic edge cases, malformed numeric strings, and boundary anomalies:
- **Scenario 1–4**: Nominal contracts (exact match, overcharge calculation, undercharge calculation, zero variance).
- **Scenario 5–7**: Internal arithmetic discrepancies ($Qty \times Price \neq LineTotal$, stated total mismatch, missing line total).
- **Scenario 8–14**: Missing quantities, zero quantity, negative quantities, negative prices, `NaN` / `Infinity`, invalid strings, duplicate line numbers.
- **Scenario 15–21**: Unknown SKUs, ambiguous SKU matches, expired contract rates, future contract rates, overlapping contract rates, currency mismatches.
- **Scenario 22–24**: Missing source files, source digest mismatches, cross-platform path traversal attempts.
- **Scenario 25–29**: Mixed matched/unmatched items, multiple simultaneous errors, rounding boundaries, large and sub-cent numbers.
- **Scenario 30–35**: Spreadsheet formula injection, malformed comparison JSON, tampered comparison digests, blocked-draft refusal, incomplete totals defense.

### 2.2 Boundary Audit Suite (`test_boundary_audit.py` — 20 tests)
Verifies operational trust boundaries and the four-tier artifact model:
- Enforcing pre-approval preview (`payment_preview.csv`) on unapproved runs.
- Enforcing refusal of `corrected_payment.csv` without signed approval receipts.
- Verification that `partial_review.csv` contains zero payable recommendations.
- Verification that `blocked_review_report.csv` contains zero payable columns and values.
- Comprehensive path traversal testing (Windows backslashes, POSIX forward slashes, mixed slashes, UNC paths, drive colons).
- Companion digest tampering and missing digest detection.

### 2.3 Authorization & Approval Gateway Suite (`test_auth_and_approval.py` — 15 tests)
Verifies identity, tokens, and cryptographic receipt issuance:
- HMAC-SHA-256 token generation and validation.
- Token expiration (fail-closed on expired tokens).
- Tampered token signature rejection.
- Unknown and disabled actor rejection.
- Role-Based Access Control (RBAC) permission checking.
- Cryptographic approval receipt generation and signature validation.
- Rejection of tampered amounts or cross-case receipt replay.
- Gateway fail-closed check refusing approval on non-`VERIFIED` audits.
- Gateway strict check matching approved amount to calculated contract payable goods amount.
- Rejection recording requiring mandatory owner rationale.

### 2.4 Audit Ledger Suite (`test_audit_ledger.py` — 11 tests)
Verifies SQLite transaction safety, cryptographic hash chains, triggers, and checkpoints:
- Genesis event has `previous_event_hash == "0" * 64`.
- Monotonic sequence numbering and unbroken hash chaining across events.
- Database triggers aborting direct `UPDATE` and `DELETE` on audit events.
- Detection of modified payload in historical events.
- Detection of deleted events (sequence gaps).
- Detection of reordered events or broken hash links.
- Generation and independent cryptographic verification of HMAC-signed checkpoints.

### 2.5 Case Manager & Evidence Registry Suite (`test_case_manager_and_evidence.py` — 8 tests)
Verifies case directory lifecycle and file fingerprinting:
- Standardized directory layout initialization.
- Legal state transitions across case lifecycle (`CREATED` $\to$ `INTAKE_VERIFIED` $\to$ `COMPARED` $\to$ `VERIFIED` $\to$ `APPROVED` $\to$ `CLOSED`).
- Refusal of illegal state transitions or transitions out of terminal `CLOSED` state.
- Evidence registration with full 64-character SHA-256 calculation.
- Evidence re-verification detecting modified or missing files on disk.

### 2.6 Pipeline Orchestration Suite (`test_pipeline_orchestration.py` — 3 tests)
Verifies end-to-end controlled pipeline execution:
- Execution manifest (`manifest.json`) recording 13 stage results, durations, artifact references, and hashes.
- Evidence registry auto-population and fail-closed error handling.
- Pipeline requiring approval fails closed when approval receipt is missing.
- Pipeline succeeds and emits `corrected_payment.csv` when valid approval receipt is provided.

### 2.7 End-to-End Demo Suite (`test_demo_cases.py` — 1 test)
Continuously runs the complete 6-case benchmark suite in CI:
- **Case A** (Clean match)
- **Case B** (Overcharge with ₹6,000 withholding)
- **Case C** (Review required with uncontracted line)
- **Case D** (Blocked arithmetic discrepancy)
- **Case E** (Post-approval evidence tampering refusal)
- **Case F** (Audit ledger failure abort)
- Plus standalone Case Audit Package export and cryptographic verification.

### 2.8 Terminal Owner Approval Suite (`test_approve_cli.py` — 6 tests)
Verifies out-of-band interactive human approval boundaries:
- Mandatory interactive TTY gate refusing piped and automated script execution.
- Fail-closed refusal on empty or invalid approver passwords.
- Refusal of users lacking `APPROVER` or `ADMINISTRATOR` authority.
- Refusal to approve non-`VERIFIED` cases (e.g. arithmetic discrepancies).
- Generation of full 64-character SHA-256 receipts and Switch notification text.
- Token minting lockdown (`tools/auth.py issue-token` requires explicit `--dev`).

### 2.9 Unified Agent Desk CLI Suite (`test_desk_cli.py` — 9 tests)
Verifies multi-agent command boundaries:
- Strict rejection of `approve` subcommand (ensures agents cannot approve payments).
- `status` command returning 4-dimensional state tracking and financial totals.
- `audit` command emitting full 64-character SHA-256 digests and pre-approval previews.
- `audit` failing closed with exit code 2 on arithmetic discrepancies.
- `history --vendor acme` querying past cases across all ledger records (memory moment).
- `finalize` failing closed without signed approval receipts.
- `finalize` releasing authorized payment sheet upon valid receipt.
- `intake` workflow copying evidence, registering source SHA-256 fingerprints.
- Invariant verification confirming zero `.key` or `keys_manifest.json` files reside in repo tree.
