# SECURITY_MODEL.md — Overcharge Desk Threat Model & Security Controls

> **System**: Overcharge Desk — Evidence-First Vendor Reconciliation & Cryptographic Payment Control  
> **Version**: 3.0.0  
> **Authority**: [AGENTS.md](file:///d:/overcharge%20files/AGENTS.md)

---

## 1. Threat Model & Asset Boundaries

### 1.1 Protected Assets
1. **Financial Disbursements**: Preventing unauthorized, incorrect, or speculative payment recommendations.
2. **Contract Truth**: Preventing unauthorized alteration of contract terms, rates, effective dates, or vendor identities.
3. **Audit Trail Integrity**: Guaranteeing that historical disputes, credit promises, and rejections cannot be silently wiped or altered.
4. **Source Evidence**: Preserving original raw invoice documents against tampering or silent substitution.

### 1.2 Adversary Models
- **Malicious/Compromised AI Agent**: An LLM agent attempting to hallucinate arithmetic, skip verification steps, invent contract clauses, or forge approval commands.
- **Untrusted External Caller**: An unauthenticated user or script attempting to trigger payment recommendations from incomplete or blocked audits.
- **Adversarial Vendor**: A vendor submitting invoices with internal arithmetic mismatches, disguised SKUs, or formula injection payloads.
- **Insider/Storage Tampering**: An actor with partial filesystem access modifying historical JSON or SQLite rows.
- **Self-Approval / Collusion**: An operator attempting to approve their own initiated cases without secondary review.

---

## 2. Security Controls & Defense-in-Depth

### 2.1 Multi-User Role-Based Access Control (RBAC) & Separation of Duties

The enterprise production architecture establishes 6 distinct roles:

| Role | Permitted Operations | Approval Authority |
|---|---|---|
| `ADMINISTRATOR` | Manage users, roles, system configuration, key rotation. | Full |
| `FINANCE_OPERATOR` | Create cases, upload invoices, run reconciliation pipelines. | None |
| `REVIEWER` | Inspect comparison findings, view evidence, request approvals. | None |
| `APPROVER` | Review audited evidence, approve or reject eligible cases. | **Full (Positive Allowlist only)** |
| `AUDITOR` | Read-only inspection of cases, receipts, ledger, and checkpoints. | None (Read-only) |
| `PAYMENT_OPERATOR` | Export authorized payment instructions after approval. | None |

#### Mandatory Security Rules:
1. **Separation of Duties (Strict Default)**: No user can approve a case they created or initiated (`case.created_by != approver_id`). Attempting self-approval is refused fail-closed with HTTP 403 / exit code 4.
2. **Server-Side Enforcement**: All authorization decisions are evaluated by the backend service. Frontend UI states are purely informative.
3. **Immutability of Approved Amounts**: An approver cannot edit the monetary amount during approval. The approved amount must match the calculated contract payable goods amount down to the cent.
4. **Binding to Complete Evidence Set**: Every approval binds the exact full 64-character SHA-256 digests of the invoice, contract, comparison result, verification record, and intake evidence files.
5. **Revocation & Expiry**: Inactive or revoked actors cannot authorize cases. Expired tokens are rejected fail-closed.

---

## 2.2 Evidence Integrity & Cryptographic Bindings

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| Short hash collisions (e.g. 8-char prefixes) | Full 64-character SHA-256 hexadecimal digests required across all tools and receipts. | Strict regex `^[0-9a-fA-F]{64}$`. |
| Cross-case approval replay | Approval receipts bind `case_id`, `invoice_sha256`, `compare_sha256`, `verification_id`, and `evidence_digest_set`. Reusing a receipt on another case fails verification. | `approval_receipt.py:verify_approval_receipt()` |
| Modification of raw invoice after intake | Universal source referencing and intake fingerprinting. Any change to source file causes recalculation mismatch and triggers `BLOCKED`. | `compare.py` & `evidence.py` re-hash on disk. |
| Re-ordering or deletion of audit events | SQLite hash chain: each event incorporates previous event's SHA-256 hash. Any sequence gap breaks the chain. | `audit_ledger.py` & `verify_ledger.py`. |
| Unauthorized database modification | Mechanical append-only triggers (`trg_prevent_audit_update`, `trg_prevent_audit_delete`) abort direct SQLite `UPDATE` or `DELETE`. | Database-level triggers in `audit_ledger.py`. |
| Single point of ledger failure | Periodic HMAC-signed checkpoints exported to external audit storage. | `create_checkpoint()` & `verify_checkpoint()`. |

---

## 2.3 Input Sanitization & System Hardening

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| Path Traversal (`../../etc/passwd` or `..\..\secret`) | Normalizing separators (`\` and `/`), blocking `..` segments, rejecting leading slashes, UNC shares, and Windows drive colons. | `tools/common.py:is_safe_relative_path()` |
| CSV Spreadsheet Formula Injection | Prepending single quote (`'`) to any string field starting with `=`, `+`, `-`, `@`, `\t`, or `\r`. | `payment_sheet.py:safe_text()` |
| Non-finite numbers (`NaN`, `Infinity`) | Parsing through `decimal.Decimal` and checking `d.is_finite()`. | `tools/common.py:to_decimal()` |
| Floating point precision drift | Zero `float` usage; all financial math uses exact `decimal.Decimal` with explicit `ROUND_HALF_UP`. | `tools/common.py:q2()` |

---

## 2.4 Process Boundaries, Key Isolation & Human Authorization Gates

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| AI Agent autonomous payment self-approval | Unified agent CLI `tools/desk.py` strictly omits an `approve` subcommand. | Argument parser error; command does not exist. |
| Agent forging approval via piped subshell | `tools/approve.py` requires an interactive TTY session (`sys.stdin.isatty()`). | Immediate fail-closed abort (exit code 4) on pipes or headless calls. |
| Forged human approval token | Interactive password prompt verified against Argon2id SQLite identity store. | `IdentityService.authenticate()` via `tools/approve.py`. |
| Single OS user credential snooping | Signing keys provisioned outside repo tree via `OVERCHARGE_KEY_DIR` / `OVERCHARGE_SIGNING_KEY`. | `auth.py:get_default_key_dir()` defaults to `~/.overcharge/keys/`. |
| Unauthenticated CLI token issuance | `tools/auth.py issue-token` strictly locked down; fails closed without explicit `--dev`. | `auth.py` CLI handler exits code 4 without `--dev`. |

---

## 3. Honest Trust & Immutability Disclosures

1. **What HMAC-SHA-256 Signatures Prove and Do Not Prove**:
   - **What they prove**: That the token, receipt, or checkpoint was generated with knowledge of the provisioning key (`config/signing.key`), and that the bound artifact digests have not been modified since creation.
   - **What they do not prove**: HMAC is a symmetric secret mechanism. It does **not** provide asymmetric cryptographic non-repudiation (an administrator with key access could produce a signature), and it does not independently prove individual physical human identity without an authenticated user account / OIDC identity boundary.
2. **Honest Immutability Claims for SQLite Ledger**:
   - Plain JSON files and atomic replacements are **not** immutable.
   - The SQLite ledger is **tamper-evident**: tampering is detected via the unbroken SHA-256 hash chain and database-level abort triggers.
   - An attacker with root filesystem write access could theoretically alter historical rows and recompute the hash chain forward; therefore, periodic external signed checkpoints and standalone audit package exports (`case_audit/<case_id>/`) are provided for archiving in independent external storage.
3. **Distinction Between Payment Recommendation and Payment Execution**:
   - Overcharge Desk produces verified, authorized payment recommendation sheets (`corrected_payment.csv`).
   - It does **not** execute automated disbursements or direct bank transfers. Actual payment execution remains within external corporate banking systems.
4. **Same OS User Process Boundaries vs Container Isolation**:
   - When multiple agents execute under the same OS user process on a single workstation, they share operating system filesystem access. True enterprise multi-tenancy requires OS user boundaries or containerized sandboxes per agent.
   - To enforce strong separation of concerns, signing keys are provisioned outside the repository tree via `OVERCHARGE_KEY_DIR` / `OVERCHARGE_SIGNING_KEY`, agent token minting via `tools/auth.py issue-token` is locked down with fail-closed errors, and `tools/desk.py` contains no `approve` subcommand.
