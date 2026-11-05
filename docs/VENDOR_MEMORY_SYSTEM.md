# Vendor Historical Memory System

> **Subsystem**: Deterministic Cross-Invoice Vendor Dispute Recall  
> **Interface**: `tools/desk.py history --vendor <name>` & SQLite Ledger  
> **Invariant**: Zero Hallucination of History or Credit Terms (Rule 2.3)

---

## 1. Overview & Operational Problem

Vendors frequently repeat billing discrepancies across multiple invoice cycles:
- Re-invoicing previously disputed line items.
- Reverting negotiated contract discounts to list prices.
- Claiming credit notes were issued when they remain unapplied or unreceived.

Overcharge Desk implements a **deterministic vendor memory system** that inspects past case records and ledger events to present historical context during live invoice audits.

---

## 2. CLI Interface & Usage

### 2.1 Vendor History Query
```bash
python tools/desk.py history --vendor acme
```

### 2.2 Output Schema
```json
{
  "vendor_query": "acme",
  "total_cases_found": 2,
  "historical_records": [
    {
      "case_id": "OC-20261001-01",
      "invoice_number": "INV-1090",
      "stated_total": "66000.00",
      "settlement_status": "APPROVED",
      "withheld_amount": "6000.00",
      "discrepancy_type": "UNIT_RATE_MISMATCH",
      "notes": "Acme billed Widget A at INR 3,300 vs contract INR 3,000"
    },
    {
      "case_id": "OC-20261106-01",
      "invoice_number": "INV-1103",
      "stated_total": "66000.00",
      "settlement_status": "PENDING_APPROVAL",
      "withheld_amount": "6000.00",
      "discrepancy_type": "UNIT_RATE_MISMATCH",
      "notes": "Repeat billing of Widget A at INR 3,300"
    }
  ],
  "cumulative_withholding": "12000.00"
}
```

---

## 3. Credit Note Lifecycle Invariants

Under **Invariant Rule 2.3**, credit notes must never be speculative or prematurely marked as cash recoveries:

```
[Phone/Email Discussion]
           │
           ▼
     ┌───────────┐
     │ PROMISED  │  Mentioned by vendor; no formal document.
     └─────┬─────┘
           │ Formal credit memo received
           ▼
     ┌───────────┐
     │ RECEIVED  │  Cryptographically fingerprinted document in hand.
     └─────┬─────┘
           │ Deducted from active payment disbursement
           ▼
     ┌───────────┐
     │  APPLIED  │  Settled against active payment run.
     └───────────┘
```

A credit note in `PROMISED` or `RECEIVED` status remains `OUTSTANDING` until certified against a disbursement run.

---

## 4. Multi-Agent Memory Interlude

When the Auditor Agent performs an audit:
1. It executes `tools/desk.py audit <case_id>`.
2. It immediately checks vendor history via `tools/desk.py history --vendor <name>`.
3. If prior disputes exist for the same line item, it alerts the human owner in Switch:
   > *"Notice: Acme Industrial Supplies has repeated this exact discrepancy (INR 300/unit rate inflation) across Invoice INV-1090 (Case OC-20261001-01) and current Invoice INV-1103. Cumulative withholding across both cycles: INR 12,000.00."*
