# DEMO_SCRIPT — Overcharge Desk (Full System Walkthrough)

> All vendors, invoices, amounts, and names are synthetic demo data.

This demo script proves that Overcharge Desk delivers deterministic verification, cryptographic human-in-the-loop authorization, tamper-evident audit chains, and strict fail-closed boundary controls inside a **Switch / Mattermost** collaborative multi-agent workflow.

---

## 🎯 What the Demonstration Proves

1. **Exact Decimal Arithmetic**: The system calculates ₹6,000 variance and 12% overcharge using `decimal.Decimal` and `ROUND_HALF_UP`, never floating-point math.
2. **Multi-Agent Orchestration on Switch**: Three specialized AI agents (**Reader**, **Auditor**, **Writer**) collaborate in Mattermost `#overcharge-desk`, operating deterministic tools via `tools/desk.py`.
3. **Vendor Memory Moment**: The Auditor agent queries historical cases across all ledger records (`tools/desk.py history --vendor acme`), recalling past invoice outcomes and withheld variances.
4. **Unforgeable Human Approval**: The business owner authorizes payments via an interactive terminal script (`tools/approve.py`) requiring TTY sessions and Argon2id password verification.
5. **Four-Tier Controlled Output Routing**:
   - `corrected_payment.csv` is ONLY produced upon cryptographic verification of a valid signed approval receipt.
   - `payment_preview.csv` is produced for pre-approval analysis (explicitly labeled `NOT AUTHORIZED FOR PAYMENT`).
   - `partial_review.csv` is produced for uncontracted lines (commercial investigation only).
   - `blocked_review_report.csv` is produced for arithmetic discrepancies with zero payable fields.
6. **Cryptographic Approval Receipts**: Decisions are signed using HMAC-SHA-256 tokens binding the full 64-char hashes of the case, invoice, comparison, and evidence.
7. **Tamper-Evident SQLite Ledger with Triggers & Checkpoints**: Events form an unbroken SHA-256 hash chain anchored by a genesis block (`0 * 64`) with database-level append-only triggers and signed checkpoint verification.
8. **Standalone Audit Package Export**: Self-contained evidence packages with verifiable `audit_integrity_report.json` and cryptographic certification.

---

## 📋 The 6 Canonical Benchmark Demo Cases

| Case | Directory | Invoice | Invoiced | Payable | Withheld | State | Result |
|---|---|---|---|---|---|---|---|
| **Case A** | `cases/demo-clean` | INV-1001 | ₹30,000.00 | ₹30,000.00 | ₹0.00 | `VERIFIED` | Clean payment sheet + approval receipt |
| **Case B** | `cases/demo-overcharge` | INV-1103 | ₹66,000.00 | ₹60,000.00 | ₹6,000.00 | `VERIFIED` | Corrected payment sheet (₹6k withheld) + Audit Package Export |
| **Case C** | `cases/demo-review` | INV-1201 | ₹54,500.00 | N/A | N/A | `REVIEW_REQUIRED` | Partial review artifact (investigation only) |
| **Case D** | `cases/demo-blocked` | INV-1301 | ₹68,000.00 | N/A | N/A | `BLOCKED` | Discrepancy report; gateway strictly refuses approval |
| **Case E** | `cases/demo-tampering` | INV-1001 | ₹30,000.00 | Refused | Refused | `TAMPERED` | Post-approval modification detected; payment refused fail-closed |
| **Case F** | `cases/demo-ledger-failure` | INV-1001 | ₹30,000.00 | Refused | Refused | `ABORTED` | Unwriteable ledger causes immediate fail-closed pipeline abort |

---

## ⚡ Automated 1-Command Demonstration

Run the automated demonstration suite that verifies all 6 benchmark cases, exports the audit package, and validates the SQLite ledger hash chain:

```bash
# 1. Quickstart Runner (Runs benchmarks, verifies ledger, and launches dashboard)
python tools/quickstart.py --serve

# 2. Standalone Switch Multi-Agent Simulator (Live terminal collaboration)
python tools/simulate_switch.py

# 3. Direct benchmark suite
python tools/run_demo_suite.py --clean
```

---

## 🎬 Step-by-Step Multi-Agent Walkthrough (Switch & Terminal)

### Step 1: Pre-flight Verification (30 seconds)
Show the passing automated test suite to establish radical engineering transparency:
```bash
python -m pytest -v
```
*Voice-over*: "Overcharge Desk operates under strict engineering invariants defined in AGENTS.md. 260 automated adversarial tests verify exact decimal arithmetic, path traversal guards, formula injection mitigation, and fail-closed security boundaries across Windows, Ubuntu, and Python 3.9 through 3.13."

---

### Step 2: The Switch Multi-Agent Flow (Case B: Acme Overcharge)

1. **Reader Agent Intake**:
   - The owner uploads `invoices/acme-inv-1103.txt` into `#overcharge-desk`.
   - Reader agent executes deterministic intake:
     ```bash
     python tools/desk.py intake invoices/acme-inv-1103.txt seed/acme.json --case-id demo-overcharge
     ```
   - *Voice-over*: "Reader validates the invoice file, preserves immutable source SHA-256 fingerprints, and registers evidence in `evidence_registry.json`. It never infers or modifies values."

2. **Auditor Agent Deterministic Audit & Memory Moment**:
   - Auditor agent runs the comparison and checks vendor history:
     ```bash
     python tools/desk.py audit demo-overcharge
     python tools/desk.py history --vendor acme
     ```
   - *Voice-over*: "Auditor detects an uncontracted ₹12/unit variance on 500 CC-5 cartons: ₹6,000 withheld. It queries the audit ledger to recall past vendor outcomes—this is the memory moment. Auditor emits full 64-character hashes and pre-approval preview `payment_preview.csv` (labeled NOT AUTHORIZED FOR PAYMENT). Auditor has no approval command."

3. **Human Owner Interactive Terminal Authorization**:
   - The owner runs the dedicated approval CLI in their terminal:
     ```bash
     python tools/approve.py demo-overcharge --username owner
     ```
   - *Voice-over*: "Financial approval is strictly isolated from LLM prompts. `approve.py` refuses piped execution, enforces an interactive TTY session, prompts for the owner's Argon2id password, independently computes the payable subtotal server-side, signs an immutable receipt, and emits a full 64-character receipt hash."
   - The owner copies the notification hash into `#overcharge-desk`.

4. **Writer Agent Payment Finalization**:
   - Writer agent runs:
     ```bash
     python tools/desk.py finalize demo-overcharge
     ```
   - *Voice-over*: "Writer verifies the cryptographic approval receipt and releases `corrected_payment.csv` paying contract rates and withholding ₹6,000 overcharge. Writer drafts `dispute_email.md` and posts the settlement summary."

---

### Step 3: Adversarial Proof: Arithmetic Discrepancy (30 seconds)

1. **Run Blocked Discrepancy Case**:
   ```bash
   python tools/desk.py audit demo-blocked
   ```
   *Voice-over*: "Line 1 claims $500 \times 112 = 58,000$, which is mathematically false ($56,000$). The system refuses to guess, flags `SOURCE_DISCREPANCY`, and enters `BLOCKED` status."

2. **Attempt Unauthorized Approval**:
   ```bash
   python tools/approve.py demo-blocked --username owner
   ```
   *Voice-over*: "The system immediately refuses with exit code 4: `Only 'VERIFIED' cases may be approved`. No payment sheet is ever produced. Only discrepancy facts are exported to `blocked_review_report.csv` with zero payable fields."

---

### Step 4: Standalone Case Audit Package & Independent Verification

Export the full evidence package and independently verify its cryptographic integrity:

```bash
python tools/export_audit_package.py export cases/demo-overcharge
python tools/export_audit_package.py verify case_audit/OC-20261106-01
```

*Voice-over*: "All artifacts, raw inputs, comparison outputs, verification records, approval receipts, and ledger event histories are packaged into a standalone case audit bundle certified by a cryptographic SHA-256 integrity report."

---

### Step 5: Ledger Audit & Chain Verification

Verify that all actions were committed to the SQLite ledger without tampering:

```bash
python tools/audit_ledger.py verify
```

*Voice-over*: "Every case creation, comparison, approval, and payment recommendation is committed to an append-only SQLite ledger using a cryptographic SHA-256 hash chain starting from genesis. The independent verifier traverses the chain from start to finish and confirms zero broken links and zero altered payloads."

---

## 📊 Summary of Artifact Files Produced

- `cases/demo-overcharge/compare.json`: Deterministic comparison result (schema 2.0.0).
- `cases/demo-overcharge/compare.json.sha256`: Companion cryptographic digest.
- `cases/demo-overcharge/audit/verification.json`: Formal independent verification artifact.
- `cases/demo-overcharge/evidence_registry.json`: Registry of all fingerprinted intake documents.
- `cases/demo-overcharge/approvals/approval_receipt.json`: Signed human authorization receipt.
- `cases/demo-overcharge/payment_preview.csv`: Pre-approval payment preview (unauthorized).
- `cases/demo-overcharge/corrected_payment.csv`: Final authorized payment recommendation.
- `cases/demo-overcharge/manifest.json`: Full 13-stage execution manifest for crash recovery and audit.
- `case_audit/OC-20261106-01/audit_integrity_report.json`: Self-contained audit package manifest.
- `ledger.db`: SQLite database storing the unbroken tamper-evident audit chain.
- `identity.db`: Persistent SQLite store for users, Argon2id credentials, and hashed session tokens.
- `GET /api/v1/health`: Operational readiness endpoint returning READY/DEGRADED across all subsystems.
