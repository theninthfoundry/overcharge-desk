# TEST_STRATEGY.md — Adversarial Testing & Verification Strategy

> **System**: Overcharge Desk — Evidence-First Vendor Reconciliation & Cryptographic Payment Control  
> **Version**: 3.0.0  
> **Authority**: [AGENTS.md](file:///d:/overcharge%20files/AGENTS.md) Invariant 5 (Radical Engineering Transparency)

---

## 1. Test Architecture & Coverage Summary

Overcharge Desk enforces a zero-trust, test-driven engineering culture. No feature or security boundary is considered complete without automated test execution verifying both nominal and adversarial behaviors.

The automated test suite contains **139 passing tests** across 9 test modules:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.0
rootdir: D:\overcharge files
configfile: pytest.ini
testpaths: tests
collected 139 items

tests/test_audit_ledger.py .............. [11 tests: Genesis, chain links, triggers, tampering, gaps, checkpoints]
tests/test_auth_and_approval.py ......... [15 tests: HMAC tokens, TTL, role permissions, signed receipts, gateway]
tests/test_boundary_audit.py ............ [20 tests: 4-tier artifact model, path traversal, injection, digests]
tests/test_case_manager_and_evidence.py . [ 8 tests: Directory layout, state transitions, SHA-256 tracking]
tests/test_compare.py .................. [21 tests: Exact decimal precision, rounding, SKU boundaries, dates]
tests/test_financial_adversarial.py .... [35 tests: Non-finite inputs, negative numbers, formula injection]
tests/test_pipeline_orchestration.py .... [ 3 tests: Manifest generation, approval enforcement, recovery]
tests/test_tools.py .................... [25 tests: CLI utilities, error exits, seed parity]
tests/test_demo_cases.py ................ [ 1 test:  Full 6-case benchmark suite + audit package export]

============================= 139 passed in ~8s =============================
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
