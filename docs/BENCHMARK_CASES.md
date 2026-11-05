# Canonical Benchmark Cases Reference (Cases A – F)

> **Specification**: 6 Deterministic Financial Scenarios  
> **Runner**: `python tools/run_demo_suite.py --clean` or `python tools/quickstart.py`

---

## 1. Summary Matrix

| Case ID | Benchmark Name | Invoiced Total | Payable Total | Withheld Amount | System Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Case A** | Clean Rate Match | INR 30,000.00 | INR 30,000.00 | INR 0.00 | `VERIFIED` — 100% matched, zero variance. |
| **Case B** | Acme Rate Overcharge | INR 66,000.00 | INR 60,000.00 | INR 6,000.00 | `OVERCHARGE_WITHHELD` — Rate corrected, dispute package emitted. |
| **Case C** | Commercial Review | Partial | Reconciled portion | Quarantined | `REVIEW_REQUIRED` — Uncontracted items segregated in CSV. |
| **Case D** | Arithmetic Discrepancy | Stated total invalid | INR 0.00 | INR 0.00 | `SOURCE_DISCREPANCY` — Payment completely blocked. |
| **Case E** | Tampering Refusal | INR 66,000.00 | INR 0.00 | N/A | `TAMPERING_DETECTED` — Post-approval edit halts execution. |
| **Case F** | Ledger Storage Failure | N/A | INR 0.00 | N/A | `PIPELINE_ABORTED` — Unwriteable ledger halts pipeline. |

---

## 2. In-Depth Case Details

### Case A: Clean Rate Match (`OC-20261001-01`)
- **Input**: `invoices/acme-inv-1001.txt`
- **Contract**: `ACME-2026-01`
- **Result**: All lines match agreed unit rates. Reconciled goods subtotal equals invoiced subtotal. Final disbursement sheet released immediately.

### Case B: Acme Rate Overcharge (`OC-20261106-01`)
- **Input**: `invoices/acme-inv-1103.txt`
- **Contract**: `ACME-2026-01`
- **Variance**: Widget A billed at INR 3,300/unit (contract specifies INR 3,000/unit for 20 units).
- **Result**: Overcharge of INR 6,000.00 detected. Owner approves withholding. Corrected payment sheet written with INR 60,000.00 payable.

### Case C: Commercial Review (`OC-20261107-01`)
- **Condition**: Supplier invoices items not present in contracted Schedule A catalog.
- **Result**: Matches contracted lines, quarantines uncontracted items into `partial_review.csv` for procurement negotiation.

### Case D: Source Arithmetic Discrepancy (`OC-20261108-01`)
- **Condition**: Supplier invoice contains internal mathematical mismatch ($10 \times 5,000 = 55,000$).
- **Result**: System refuses to guess or silently fix the supplier's error. Case flagged as `SOURCE_DISCREPANCY`, automated payment blocked fail-closed.

### Case E: Post-Approval Tampering Refusal
- **Condition**: Simulated attack where an adversary alters `compare.json` on disk after human owner approval.
- **Result**: SHA-256 evidence integrity check fails immediately; payment release aborted.

### Case F: Ledger Write Failure
- **Condition**: Storage layer failure simulated by locking `ledger.db` as read-only.
- **Result**: System refuses to process disbursement without verifiable audit record. Fail-closed shutdown.
