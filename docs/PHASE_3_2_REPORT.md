# Phase 3.2 Engineering Report: Security Hardening & Operational Integrity

> **Project**: Overcharge Desk — Evidence-First Vendor Reconciliation & Cryptographic Payment Control  
> **Status**: Completed & Certified  
> **Repository**: [theninthfoundry/overcharge-desk](https://github.com/theninthfoundry/overcharge-desk)  
> **Test Suite**: 186 passed, 1 skipped across 17 test modules  
> **Benchmark Suite**: 6/6 canonical benchmark cases passing with 100% verified ledger integrity  

---

## 1. Executive Summary

Phase 3.2 elevates Overcharge Desk from an operational prototype to an enterprise-grade financial verification and payment release system. Following the successful delivery of Phase 3.1 (API gateway, multi-user RBAC, separation of duties, and operations dashboard), Phase 3.2 systematically remediated every security, concurrency, storage, and authorization gap identified during the architectural review.

Critically, all security hardening was built **around** the core deterministic financial engine without modifying its exact `decimal.Decimal` calculations or introducing artificial external dependencies.

---

## 2. Hardened Architecture & Subsystems

### 2.1 Password Storage & Bound Checking (`domain/identity/passwords.py`)
- **Argon2id Integration**: Passwords hashed using memory-hard Argon2id ($64\text{ MB}$, 3 iterations, 4 parallelism threads) using unique 16-byte cryptographically secure random salts.
- **Zero-Dependency Fallback**: PBKDF2-HMAC-SHA256 ($600,000\text{ rounds}$) fallback for minimal Python environments.
- **Transparent Rehash**: `needs_rehash()` automatically detects legacy PBKDF2 hashes upon successful authentication and rehashes them to Argon2id in SQLite.
- **Algorithmic DoS Neutralization**: Password lengths are strictly bounded between 8 and 1024 characters.

### 2.2 Secure Admin Bootstrapping & Production Credential Gating (`tools/bootstrap_admin.py`, `domain/identity/repository.py`)
- **Interactive CLI Bootstrap**: Primary administrators are provisioned via `python -m tools.bootstrap_admin` using secure `getpass` input.
- **Zero Production Defaults**: Hardcoded demo credentials are eliminated in production.
- **Fail-Closed Startup Safety Check**: `check_production_safety()` runs at application startup; if `APP_ENV=production` and any demo accounts or default passwords remain active, startup fails immediately with exit code 4.
- **Hashed Opaque Session Tokens**: Session tokens are 32-byte cryptographically secure random strings (`secrets.token_urlsafe(32)`). Only their SHA-256 hashes (`token_hash`) are persisted in SQLite, ensuring database breaches do not compromise active sessions.

### 2.3 Signing Key Lifecycle Management (`domain/identity/key_manager.py`)
- **Explicit Lifecycle States**: Keys transition through `ACTIVE` $\rightarrow$ `RETIRED` $\rightarrow$ `REVOKED`.
- **Historical Receipt Verification**: Older retired keys are retained on disk and indexed in `keys_manifest.json`, ensuring key rotation does not invalidate past receipts or ledger checkpoints.
- **Fail-Closed Production Gates**: In production, missing key files or manifests cause immediate startup refusal. On POSIX platforms, insecure file permissions ($> 0600$) fail startup.

### 2.4 Case Storage Isolation & Symlink Containment (`domain/cases/storage.py`)
- **Strict Identifier Validation**: Case IDs must strictly match `^[a-zA-Z0-9_\-]{3,64}$`. Path traversal tokens (`..`, `/`, `\`, colons, null bytes) are rejected with `StorageSecurityError`.
- **Path Containment Assertions**: Canonical absolute paths are verified with `c_dir.relative_to(storage_root)`.
- **Symlink Escape Defense**: Artifact resolution follows realpaths and asserts containment within the case folder, preventing symlink traversals to system files.
- **Closed Artifact Registry**: Only 14 whitelisted artifact names can be accessed; arbitrary file reads are blocked.
- **Resource Boundaries**: File reads are capped at 10 MB (`MAX_FILE_SIZE_BYTES`). Atomic writes via temporary files prevent corrupted artifacts.

### 2.5 Approval Protocol Hardening & Separation of Duties (`domain/cases/service.py`, `services/api/routes/cases.py`)
- **Server-Side Payable Amount Calculation**: The API never permits callers to dictate payable amounts. The server independently calculates payable totals from `compare.json` and verified line matches. Any client-supplied amount is verified against the server total; mismatches raise `HTTP 403`.
- **Strict Positive Allowlist**: Approvals are mechanically restricted to cases with status `VERIFIED`. `BLOCKED` or `REVIEW_REQUIRED` cases cannot be approved.
- **Separation of Duties (Four-Eyes Principle)**: The user who created a case cannot approve it (`creator != approver`).
- **Cryptographic Evidence Binding**: Approval receipts bind `(case_id, invoice_sha256, contract_id, compare_sha256, evidence_digest_set, ledger_head, approved_amount, actor_id, key_id)`.
- **Idempotency**: Submitting redundant approval requests returns the existing verified receipt (`idempotent: true`).

### 2.6 Transactional Case Lifecycle & Optimistic Concurrency (`domain/cases/transitions.py`)
- **Explicit Transition Graph**: Legal states (`CREATED`, `RECONCILIATION_RUNNING`, `VERIFIED`, `REVIEW_REQUIRED`, `BLOCKED`, `AWAITING_APPROVAL`, `APPROVED`, `REJECTED`, `PAYMENT_INSTRUCTION_READY`, `EXPORTED`, `CLOSED`) enforce strict forward progression.
- **Optimistic Concurrency**: Transitions require matching expected version numbers, preventing concurrent update races.

### 2.7 Payment Instruction Release Controls (`domain/payments/`, `domain/vendors/`)
- **Release Boundary**: Separation between verified dispute findings and bank disbursement execution.
- **Single Instruction Guarantee**: Exactly one active payment instruction per approved receipt.
- **Duplicate Export Prevention**: Once exported, payment instructions cannot be downloaded again without administrative override.
- **Vendor Destination Verification**: Bank routing numbers cannot be extracted from untrusted invoice text (BEC defense); they must be verified against `VendorRegistry`.
- **CSV Injection Defenses**: Formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`) are sanitized in all exports.

### 2.8 API Security & Operational Health Observability (`services/api/middleware.py`, `services/api/main.py`)
- **Security Headers**: CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and `X-Request-ID`.
- **Brute-Force Lockout**: 5 failed login attempts trigger a 5-minute lockout returning `HTTP 429`. Authentication errors return generic messages to thwart user enumeration.
- **Operational Health Probe**: `/api/v1/health` distinguishes `READY` and `DEGRADED` states across database, signing keys, and storage subsystems.

---

## 3. Test Verification & Benchmark Results

### 3.1 Complete Pytest Execution
The test suite expanded from 154 to **186 automated test scenarios**:

```text
tests\concurrency\test_concurrency_and_transitions.py ...                [  1%]
tests\payments\test_payment_instructions.py ....                         [  3%]
tests\security\test_api_security.py .....                                [  6%]
tests\security\test_bootstrap_admin.py ...                               [  8%]
tests\security\test_key_manager.py ....                                  [ 10%]
tests\security\test_operational_health.py ...                            [ 11%]
tests\security\test_password_security.py .....                           [ 14%]
tests\security\test_storage_security.py ....s.                           [ 17%]
tests\test_api.py ..........                                             [ 22%]
tests\test_audit_ledger.py ...........                                   [ 28%]
tests\test_auth_and_approval.py ...............                          [ 36%]
tests\test_boundary_audit.py ....................                        [ 47%]
tests\test_case_manager_and_evidence.py ........                         [ 51%]
tests\test_compare.py .....................                              [ 63%]
tests\test_demo_cases.py .                                               [ 63%]
tests\test_financial_adversarial.py ...................................  [ 82%]
tests\test_pipeline_orchestration.py ...                                 [ 83%]
tests\test_rbac_and_separation_of_duties.py .....                        [ 86%]
tests\test_tools.py .........................                            [100%]

======================= 186 passed, 1 skipped in 21.19s =======================
```

### 3.2 Canonical Benchmark Verification (`tools/run_demo_suite.py --clean`)
All 6 canonical benchmark cases execute deterministically and pass with full integrity verification:

| Case | Scenario | Expected Status | Verified Status | Payable Amount | Withheld Amount |
|---|---|---|---|---|---|
| **Case A** | Clean invoice matching contract rates | `VERIFIED` | `PASSED` | ₹30,000.00 | ₹0.00 |
| **Case B** | Acme ₹6,000 overcharge on Item 1 | `VERIFIED` | `PASSED` | ₹60,000.00 | ₹6,000.00 |
| **Case C** | Uncontracted item / ambiguous description | `REVIEW_REQUIRED` | `PASSED` | ₹0.00 | ₹0.00 |
| **Case D** | Arithmetic error ($Qty \times Rate \neq Total$) | `BLOCKED` | `PASSED` | ₹0.00 | ₹0.00 |
| **Case E** | Post-approval file tampering attempt | `SECURITY_ALERT` | `PASSED` | Blocked fail-closed | Blocked fail-closed |
| **Case F** | Audit ledger filesystem failure | `FATAL_ERROR` | `PASSED` | Blocked fail-closed | Blocked fail-closed |

- **Audit Package Export**: Standalone package `case_audit/OC-20261106-01` verified with `audit_integrity_report.json`.
- **Cryptographic Hash Chain**: Full 28-event unbroken ledger chain verified from genesis block.

---

## 4. Phase 3.2 Artifact Deliverables

The following specifications and implementations are committed in the repository:

1. `domain/identity/passwords.py`: Argon2id password hashing, bounds checking, and auto-rehash.
2. `domain/identity/repository.py`: Persistent SQLite user and session store with hashed opaque tokens.
3. `domain/identity/key_manager.py`: Cryptographic key manager supporting rotation, retirement, and revocation.
4. `domain/cases/storage.py`: Strict filesystem isolation, path containment, and allowed artifact registry.
5. `domain/cases/transitions.py`: State machine with legal transitions and optimistic concurrency checking.
6. `domain/vendors/models.py`: Verified vendor remittance destination registry.
7. `domain/payments/`: Payment instruction domain, export controls, and CSV/JSON generators.
8. `tools/bootstrap_admin.py`: Secure interactive administrative user bootstrap CLI.
9. `docs/IDENTITY_SECURITY.md`: Detailed identity, hashing, and token specification.
10. `docs/KEY_MANAGEMENT.md`: Cryptographic key management and rotation guide.
11. `docs/API_SECURITY.md`: API perimeter defenses, CORS, and security headers.
12. `docs/CASE_STORAGE_SECURITY.md`: Filesystem isolation and storage containment specifications.
13. `docs/APPROVAL_HARDENING.md`: Authorization protocol, separation of duties, and evidence binding.
14. `docs/PAYMENT_INSTRUCTION_PROTOCOL.md`: Payment instruction release controls and duplicate prevention.
15. `docs/OPERATIONAL_READINESS.md`: Observability, health monitoring, and operational runbooks.
