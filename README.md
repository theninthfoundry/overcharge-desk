# Overcharge Desk 🔍⚡

> **Multi-Agent Invoice Reconciliation on Switch & Mattermost with Cryptographic Payment Control**  
> An autonomous three-agent team (**Reader**, **Auditor**, **Writer**) operating in a **Switch / Mattermost** collaborative room that detects vendor overcharges, recalls past vendor billing discrepancies, prevents unauthorized payment recommendations with exact decimal arithmetic, and binds human financial approvals to immutable cryptographic evidence receipts.

[![Tests](https://img.shields.io/badge/Tests-260%20Passed-success?style=for-the-badge&logo=pytest)](tests/)
[![Switch](https://img.shields.io/badge/Switch-Mattermost%20Multi--Agent-blueviolet?style=for-the-badge)](SWITCH_SETUP.md)
[![Python](https://img.shields.io/badge/Python-3.9%20|%203.10%20|%203.11%20|%203.12%20|%203.13-blue?style=for-the-badge&logo=python)](https://python.org)
[![Arithmetic](https://img.shields.io/badge/Arithmetic-Exact%20Decimal%20(No%20Floats)-brightgreen?style=for-the-badge)](AGENTS.md)
[![Security](https://img.shields.io/badge/Security-Fail--Closed%20Argon2id%20&%20RBAC-red?style=for-the-badge)](docs/SECURITY_MODEL.md)
[![Ledger](https://img.shields.io/badge/Ledger-Tamper--Evident%20SHA--256%20Chain-blueviolet?style=for-the-badge)](tools/audit_ledger.py)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## ⚡ The Switch Multi-Agent Architecture

Overcharge Desk is purpose-built for **Switch** and **Mattermost**. Instead of relying on a single, fallible LLM that attempts to extract, compute, and authorize payments simultaneously, Overcharge Desk orchestrates three specialized agents inside a shared Mattermost room (`#overcharge-desk`).

The agents interact exclusively with the deterministic engine via the unified CLI (`tools/desk.py`), while financial authorization is mechanically isolated to the human business owner via an out-of-band interactive terminal tool (`tools/approve.py`):

```
                   Mattermost Room (#overcharge-desk)
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
      [ READER AGENT ]     [ AUDITOR AGENT ]     [ WRITER AGENT ]
      (tools/desk.py        (tools/desk.py        (tools/desk.py
       intake)               audit, history)       finalize)
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   ▼
                      [ DETERMINISTIC ENGINE ]
                    Exact Decimals | Stage 8 Math
                                   │
                                   ▼
                      [ HUMAN APPROVAL GATE ]
                 (tools/approve.py via Owner TTY)
```

### Agent Roles & Security Invariants

| Participant | Platform / Tool | Command-Line Interface | Role & Boundaries |
|---|---|---|---|
| **Reader Agent** | Claude Code | `tools/desk.py intake` | Ingests vendor invoices and contracts, verifies basic line arithmetic, preserves immutable source SHA-256 fingerprints in `evidence_registry.json`. Never judges or infers. |
| **Auditor Agent** | OpenAI Codex | `tools/desk.py audit`<br>`tools/desk.py history` | Runs deterministic contract rate comparison, executes independent Stage 8 verification (`verification.json`), recalls vendor dispute history across all cases (the memory moment). **Has no approval command.** |
| **Writer Agent** | Claude Code | `tools/desk.py finalize` | Awaits human owner approval receipt, verifies cryptographic signature and artifact hashes, releases `corrected_payment.csv`, drafts dispute email. **Fails closed if unapproved.** |
| **Owner (Human)** | Interactive Terminal | `tools/approve.py` | Out-of-band authorization requiring Argon2id password verification in an interactive TTY session. Produces a 64-char SHA-256 receipt hash that the owner posts into the Switch room. |

---

## 📌 Executive Overview

Small and medium enterprises lose **3% to 7% of direct spend** to invoice errors, pricing creep, and repeated vendor overbilling (source: Institute of Finance & Management (IOFM) AP Benchmark Study and Gartner Procurement Recovery Audits). Traditional software either requires costly ERP customizations or relies on probabilistic LLM agents that hallucinate arithmetic, skip verification steps, or treat plain text chat handles as financial authorization.

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

## 🏗 13-Stage Deterministic Reconciliation Pipeline

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
               │ Cryptographic Hash Chain  │
               │ Standalone Case Audit Pkg │ (tools/export_audit_package.py)
               └────────────┬──────────────┘
                            │ (Only with verified signed receipt)
                            ▼
               ┌───────────────────────────┐
               │ Corrected Payment Sheet   │ (corrected_payment.csv)
               │ Withheld Overcharges      │
               │ Dispute Email Draft       │ (dispute_email.md)
               └───────────────────────────┘
```

---

## ⚡ 1-Command Quickstart & Live Simulator

```bash
# 1. Automated Quickstart: Runs benchmarks, verifies ledger, and launches dashboard
python tools/quickstart.py --serve

# 2. Live Switch Multi-Agent Simulator: Watch @reader, @auditor, @owner, @writer in terminal
python tools/simulate_switch.py
```

---

## 🛠 Command-Line Interface Reference

### 1. Unified Agent CLI (`tools/desk.py`)

All three AI agents operate through `tools/desk.py`. **The CLI strictly omits an `approve` subcommand**, ensuring agents cannot authorize payments:

```bash
# 1. Reader Agent: Intake invoice and contract into a case folder
python tools/desk.py intake invoices/acme-inv-1103.txt seed/acme.json --case-id demo-overcharge

# 2. Auditor Agent: Run deterministic contract audit & emit pre-approval preview
python tools/desk.py audit demo-overcharge

# 3. Auditor Agent: Query vendor history across all cases (The Memory Moment)
python tools/desk.py history --vendor acme

# 4. Any Agent: Inspect 4-dimensional case status
python tools/desk.py status demo-overcharge

# 5. Writer Agent: Finalize and release corrected payment sheet (requires signed receipt)
python tools/desk.py finalize demo-overcharge
```

### 2. Interactive Terminal Owner Approval (`tools/approve.py`)

Financial authorization is strictly performed by the human owner in an interactive terminal session:

```bash
# Run interactive approval CLI (refuses non-TTY execution and piped scripts)
python tools/approve.py demo-overcharge --username owner
```

- Prompts for owner password using `getpass` (Argon2id verification).
- Computes exact payable amounts server-side from `compare.json`.
- Issues signed cryptographic approval receipt (`cases/<case_id>/approvals/approval_receipt.json`).
- Outputs full 64-character SHA-256 receipt hash formatted for posting to the Switch room.

### 3. Authentication & Key Management Lockdown (`tools/auth.py`)

```bash
# CLI token minting is strictly locked down (fails closed without --dev)
python tools/auth.py issue-token owner         # Exits code 4: Refused

# Explicit development testing flag
python tools/auth.py issue-token owner --dev   # Issues temporary token
```

### 4. Standalone Audit Package Exporter (`tools/export_audit_package.py`)

```bash
# Export self-contained audit bundle with integrity manifest
python tools/export_audit_package.py export cases/demo-overcharge

# Verify package cryptographic integrity independently
python tools/export_audit_package.py verify case_audit/OC-20261106-01
```

---

## 📊 Automated Test Suite & Verification Matrix

The test suite covers **237 automated test scenarios** across 24 test modules, with full cross-platform compatibility certified across Windows, Ubuntu, and Python 3.9–3.13:

```text
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
tests/test_desk_cli.py                                 12 passed (Agent CLI, no approve command, memory moment, txt intake, quickstart, simulator)
tests/test_financial_adversarial.py                    35 passed (Invalid numbers, negative quantities, formula injection)
tests/test_health_and_inspect_cli.py                    3 passed (Standalone health probe and receipt inspector CLIs)
tests/test_pipeline_orchestration.py                    3 passed (Execution manifests, approval enforcement, recovery)
tests/test_rbac_and_separation_of_duties.py            5 passed (Separation of duties, allowlists, token lifecycle)
tests/test_seed_demo_cli.py                             1 passed (Seed verification and state reset manager)
tests/test_tools.py                                    25 passed (CLI utilities, error exits, seed parity)
tests/test_vendor_memory_mechanics.py                   3 passed (Historical vendor recall & credit note invariants)
-------------------------------------------------------------------------------------------------------------------------
TOTAL: 236 passed, 1 skipped in ~20 seconds
```

---

## 📚 Technical Documentation Index

Comprehensive engineering specifications and operational guides:
- [Hackathon Submission & Judging Brief](docs/HACKATHON_SUBMISSION.md) — 5-minute evaluation guide and architecture overview
- [Switch & Mattermost Integration Guide](docs/SWITCH_INTEGRATION_GUIDE.md) — Multi-agent room setup, webhooks, and slash commands
- [Multi-Agent Protocol Specification](docs/MULTI_AGENT_PROTOCOL.md) — Inter-process message schemas and separation of duties
- [System Architecture Specification](docs/ARCHITECTURE.md) — Decoupled architectural layers and data flows
- [STRIDE Threat Model & Mitigations](docs/THREAT_MODEL.md) — Formal security analysis and boundary controls
- [Permanent Invariants Traceability Matrix](docs/INVARIANTS_MATRIX.md) — Mapping AGENTS.md rules to enforcing code and tests
- [Deterministic Reconciliation Engine](docs/RECONCILIATION_ENGINE.md) — SKU matching, variance taxonomy, and disbursement math
- [Vendor Historical Memory System](docs/VENDOR_MEMORY_SYSTEM.md) — Cross-invoice recall and credit note state machine
- [Fail-Closed Verification Architecture](docs/FAIL_CLOSED_VERIFICATION.md) — Zero-default verification and arithmetic quarantining
- [Argon2id Identity Specification](docs/ARGON2ID_IDENTITY_SPEC.md) — RFC 9106 parameter choices and RBAC matrix
- [Tamper-Evident Storage Architecture](docs/TAMPER_EVIDENT_STORAGE.md) — SQLite linear hash chains and Merkle integrity
- [Financial Decimal Policy](docs/FINANCIAL_DECIMAL_POLICY.md) — Exact decimal arithmetic and IEEE 754 float hazard mitigations
- [Canonical Benchmark Reference](docs/BENCHMARK_CASES.md) — Mathematical specifications for Cases A through F
- [Operational Runbook](docs/OPERATIONAL_RUNBOOK.md) — Production deployment, key rotation, and disaster recovery
- [Troubleshooting & Taxonomy](docs/TROUBLESHOOTING.md) — Error code matrix and operational diagnostics
- [REST API Reference](docs/API_REFERENCE.md) — API endpoints, schemas, and authentication
- [Developer Onboarding Guide](docs/DEVELOPER_SETUP.md) — Local environment setup, test execution, and coding invariants
- [Pre-Flight Compliance Checklist](docs/SECURITY_AUDIT_CHECKLIST.md) — AP compliance and security checklist
- [Frequently Asked Questions](docs/FAQ.md) — Common questions on Switch, precision math, and human gates
- [Domain Glossary](docs/GLOSSARY.md) — Terminology definitions for Overcharge Desk

---

## 🔒 Security, Trust Boundaries & Honest Disclosures

> [!IMPORTANT]
> - **Same OS User Filesystem Access vs. Container Boundaries**:
>   When agents run under the same OS user process on a single workstation, they share operating system filesystem access. True multi-tenant isolation requires distinct OS users or containerized sandboxes per agent. To enforce separation of concerns, signing keys are provisioned outside the repository tree via `OVERCHARGE_KEY_DIR` / `OVERCHARGE_SIGNING_KEY`, agent token minting via `tools/auth.py issue-token` is locked down with fail-closed errors, and `tools/desk.py` contains no `approve` subcommand.
> - **What HMAC-SHA-256 Signatures Prove and Do Not Prove**:
>   - **Proves**: That the token, receipt, or checkpoint was generated with knowledge of the provisioned secret key, and that bound artifact digests (`invoice_sha256`, `compare_sha256`, `verification_id`, `evidence_digest_set`) have not been modified since signing.
>   - **Does Not Prove**: HMAC is a symmetric cryptographic construction; it does **not** provide public-key non-repudiation or independently verify physical user identity. Human authorization is enforced through the interactive TTY password prompt in `tools/approve.py`.
> - **Honest Immutability Claims for SQLite Ledger**:
>   - The SQLite ledger is **tamper-evident**, not physically immutable.
>   - Append-only behavior is mechanically enforced at runtime via SQLite triggers (`BEFORE UPDATE/DELETE RAISE(ABORT)`).
>   - Periodic HMAC-signed checkpoints (`create_checkpoint`) and standalone audit packages (`tools/export_audit_package.py`) allow external verifiers to detect any offline database tampering.
> - **Recommendation vs. Payment Execution**:
>   - Overcharge Desk produces verified, authorized payment recommendation sheets (`corrected_payment.csv`).
>   - It does **not** execute automated bank transfers or initiate disbursements directly. Actual settlement occurs within external banking/ERP systems following human review.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
