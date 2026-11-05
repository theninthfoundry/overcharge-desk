# Fail-Closed Verification Architecture

> **Security & Operational Invariant**: Rule 3.4 & Rule 5.3  
> **Philosophy**: When in doubt or under discrepancy, refuse execution. Never fail open.

---

## 1. Principles of Fail-Closed Operations

Financial reconciliation systems must never degrade into optimistic assumptions. If a file is missing, a hash does not match, an arithmetic line does not sum, or an approval lacks cryptographic credentials, Overcharge Desk **immediately halts execution with an explicit error code**.

| Check Type | Trigger Condition | System Action | Error Taxonomy Code |
| :--- | :--- | :--- | :--- |
| **Arithmetic Integrity** | $Qty \times UnitRate \neq LineTotal$ | Flag discrepancy, quarantine line, block auto-payment. | `SOURCE_DISCREPANCY` |
| **Catalog Match** | Item SKU not in Schedule A contract | Mark item as `UNMATCHED`, withhold payment. | `UNMATCHED_CATALOG_ITEM` |
| **Digest Integrity** | File hash on disk $\neq$ registered SHA-256 | Halt verification, prevent approval. | `EVIDENCE_TAMPERING_DETECTED` |
| **Authentication** | Input stream is not a TTY or wrong password | Reject approval prompt, issue no receipt. | `AUTHENTICATION_FAILED` |
| **Receipt Binding** | Case ID or hash mismatch in `receipt.json` | Refuse disbursement, do not write payment CSV. | `INVALID_APPROVAL_BINDING` |

---

## 2. Arithmetic Discrepancy Quarantining

Under **Invariant Rule 1.4**:
- If an invoice states:
  - Qty: 10
  - Rate: INR 5,000
  - Line Total: INR 55,000 (arithmetic error: should be 50,000)
- The system **does not silently recalculate or fix the supplier's error**.
- The discrepancy is quarantined as `SOURCE_DISCREPANCY`.
- Only explicitly reconciled sub-totals are released:
  ```json
  {
    "status": "SOURCE_DISCREPANCY",
    "reconciliation_decision": "QUARANTINED",
    "stated_total": "55000.00",
    "calculated_total": "50000.00",
    "variance": "-5000.00",
    "payable_approved": "0.00"
  }
  ```

---

## 3. Cryptographic Evidence Chain Verification

Before any state transition (Audit $\rightarrow$ Approval $\rightarrow$ Finalize):
1. The case manifest `audit/verification.json` is read.
2. Every referenced file on disk (`invoices/invoice.txt`, `compare.json`, `audit/verification.json`) is re-hashed using SHA-256.
3. The newly computed 64-character hash is compared against the stored digest.
4. If a single bit differs, the process aborts:
   ```
   [ERROR] Authorization refused: Evidence integrity check failed on disk: EV-OC-20261001-01-004
   Computed: 9f8a... Stored: 4b3e...
   ```

---

## 4. Separation of Prompts from Financial Computation

Under **Invariant Rule 5.1**:
- AI agents formulate natural-language summaries and assist in communication.
- **Zero calculations take place in LLM context windows**.
- All amounts, variances, quantizations, and subtotals are generated strictly by deterministic Python standard library routines (`decimal.Decimal`).
