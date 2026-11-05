# DEMO_SCRIPT — Overcharge Desk (Full System Walkthrough)

> All vendors, invoices, amounts, and names are synthetic demo data.

This demo script proves that Overcharge Desk delivers deterministic verification, cryptographic human-in-the-loop authorization, tamper-evident audit chains, and strict fail-closed boundary controls.

---

## 🎯 What the Demonstration Proves

1. **Exact Decimal Arithmetic**: The system calculates ₹6,000 variance and 12% overcharge using `decimal.Decimal` and `ROUND_HALF_UP`, never floating-point math.
2. **Three-Tier Output Control**:
   - `corrected_payment.csv` is ONLY produced for 100% verified audits with signed approval receipts.
   - `partial_review.csv` is produced for uncontracted lines (investigation only).
   - `blocked_review_report.csv` is produced for arithmetic discrepancies with zero payable fields.
3. **Cryptographic Approval Receipts**: Decisions are signed using HMAC-SHA-256 tokens binding the full 64-char hashes of the case, invoice, comparison, and evidence.
4. **Tamper-Evident SQLite Ledger**: Events form an unbroken SHA-256 hash chain anchored by a genesis block (`0 * 64`).

---

## 📋 The 4 Canonical Demo Cases

| Case | Directory | Invoice | Invoiced | Payable | Withheld | State | Result |
|---|---|---|---|---|---|---|---|
| **Case A** | `cases/demo-clean` | INV-1001 | ₹30,000.00 | ₹30,000.00 | ₹0.00 | `VERIFIED` | Clean payment sheet + approval receipt |
| **Case B** | `cases/demo-overcharge` | INV-1103 | ₹66,000.00 | ₹60,000.00 | ₹6,000.00 | `VERIFIED` | Corrected payment sheet (₹6k withheld) |
| **Case C** | `cases/demo-review` | INV-1201 | ₹54,500.00 | N/A | N/A | `REVIEW_REQUIRED` | Partial review artifact (investigation only) |
| **Case D** | `cases/demo-blocked` | INV-1301 | ₹68,000.00 | N/A | N/A | `BLOCKED` | Discrepancy report; gateway refuses approval |

---

## ⚡ Automated 1-Command Demonstration

Run the automated demonstration suite that verifies all 4 benchmark cases and validates the SQLite ledger hash chain:

```bash
python tools/run_demo_suite.py --clean
```

Expected output:
```json
{
  "ok": true,
  "all_cases_passed": true,
  "cases": {
    "case_a_clean": { "status": "PASSED", "verification_status": "VERIFIED", "payable_total": "30000.00", "withheld_total": "0.00" },
    "case_b_overcharge": { "status": "PASSED", "verification_status": "VERIFIED", "invoiced_total": "66000.00", "payable_total": "60000.00", "withheld_total": "6000.00" },
    "case_c_review_required": { "status": "PASSED", "verification_status": "REVIEW_REQUIRED", "unresolved_lines": 1 },
    "case_d_blocked": { "status": "PASSED", "verification_status": "BLOCKED", "approval_refused_fail_closed": true }
  },
  "ledger_summary": {
    "total_events": 18,
    "chain_valid": true
  }
}
```

---

## 🎬 Step-by-Step Manual Demo Script (Live Walkthrough)

### Step 1: Pre-flight Verification (30 seconds)
Show the passing automated test suite to establish radical engineering transparency:
```bash
python -m pytest -v
```
*Voice-over*: "Overcharge Desk operates under strict engineering invariants defined in AGENTS.md. 136 automated adversarial tests verify exact decimal arithmetic, path traversal guards, formula injection mitigation, and fail-closed security boundaries."

---

### Step 2: The Acme Overcharge Scenario (1 minute)

1. **Inspect Invoice and Contract**:
   - Invoice: `invoices/acme-inv-1103.txt` (500 CC-5 cartons @ ₹112.00, 40 pallet wraps @ ₹250.00)
   - Contract: `contracts/acme-contract.md` (Schedule A: CC-5 rate is ₹100.00, PW-1 rate is ₹250.00)

2. **Run Reconciliation Pipeline (Analysis Mode)**:
   ```bash
   python tools/pipeline.py cases/demo-overcharge/invoice.json vendors/acme.json cases/demo-overcharge/
   ```
   *Voice-over*: "The pipeline verifies the source document hash, executes deterministic comparison, validates math down to the byte, records events in the SQLite ledger, and registers evidence. It identifies a ₹12/unit overcharge on 500 cartons: ₹6,000 withheld."

3. **Issue Owner Authentication Token**:
   ```bash
   python tools/auth.py issue-token owner
   ```
   *Voice-over*: "Authorization does not rely on LLM prompts or chat strings. The owner receives a time-bound HMAC-SHA-256 authenticated token."

4. **Approve via Authorization Gateway**:
   ```bash
   python tools/approval_gateway.py approve cases/demo-overcharge --token "<owner_token>" --amount 60000.00
   ```
   *Voice-over*: "The gateway re-verifies evidence on disk, verifies that the comparison is clean, validates the approved amount matches the exact payable subtotal, and issues a cryptographic receipt binding all 64-character digests."

5. **Generate Final Payment Sheet**:
   ```bash
   python tools/pipeline.py cases/demo-overcharge/invoice.json vendors/acme.json cases/demo-overcharge/ --require-approval
   ```
   *Voice-over*: "With authorized approval verified, the pipeline outputs `corrected_payment.csv`. Over-billed lines pay contract amounts and withhold variances; matched lines pay as invoiced."

---

### Step 3: Adversarial Proof: Blocking Internal Discrepancies (30 seconds)

Show how the system handles an invoice where written math contradicts computed math:

1. **Run Blocked Discrepancy Case**:
   ```bash
   python tools/pipeline.py cases/demo-blocked/invoice.json vendors/acme.json cases/demo-blocked/
   ```
   *Voice-over*: "Line 1 claims $500 \times 112 = 58,000$, which is mathematically false ($56,000$). The system refuses to guess, flags `SOURCE_DISCREPANCY`, and enters `BLOCKED` status."

2. **Attempt Unauthorized Approval**:
   ```bash
   python tools/approval_gateway.py approve cases/demo-blocked --token "<owner_token>"
   ```
   *Voice-over*: "The Authorization Gateway immediately refuses with exit code 4: `Cannot approve BLOCKED audit`. No payment sheet is ever produced. Only discrepancy facts are exported to `blocked_review_report.csv` with zero payable fields."

---

### Step 4: Ledger Audit & Chain Verification (30 seconds)

Verify that all actions were committed to the SQLite ledger without tampering:

```bash
python tools/verify_ledger.py --strict
```

*Voice-over*: "Every case creation, comparison, approval, and payment recommendation is committed to an append-only SQLite ledger using a cryptographic SHA-256 hash chain starting from genesis. The independent verifier traverses the chain from start to finish and confirms zero broken links and zero altered payloads."

---

## 📊 Summary of Artifact Files Produced

- `cases/demo-overcharge/comparison/compare.json`: Deterministic comparison result (schema 2.0.0).
- `cases/demo-overcharge/comparison/compare.json.sha256`: Companion cryptographic digest.
- `cases/demo-overcharge/evidence_registry.json`: Registry of all fingerprinted intake documents.
- `cases/demo-overcharge/approvals/approval_receipt.json`: Signed human authorization receipt.
- `cases/demo-overcharge/corrected_payment.csv`: Final payment recommendation for owner review.
- `cases/demo-overcharge/manifest.json`: Full execution manifest for crash recovery and audit.
- `ledger.db`: SQLite database storing the unbroken tamper-evident audit chain.


<!-- Invariant Note: Demo script verified against all four canonical benchmark test cases -->
