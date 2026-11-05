# Deterministic Reconciliation Engine

> **Subsystem**: Core Financial Comparison & Variance Engine  
> **Package**: `domain/calculator.py` & `tools/compare.py`  
> **Precision**: 100% `decimal.Decimal` (Zero `float`)

---

## 1. Engine Pipeline & Flow

The reconciliation engine evaluates invoices against agreed contract terms through four deterministic stages:

```
[Raw Invoice] ──> [Line Normalization] ──> [Schedule A Matching] ──> [Variance Calculation]
                                                                             │
                                                                             ▼
                                                                     [Disbursement Plan]
```

---

## 2. Line Item Classification Taxonomy

Every invoice line is assigned an immutable classification state:

| State | Definition | Settlement Policy |
| :--- | :--- | :--- |
| `MATCHED` | SKU present in contract; invoiced rate equals contracted rate; line math is exact. | Approved for full payment. |
| `OVERCHARGE` | SKU present; invoiced rate exceeds agreed contracted rate. | Invoiced rate adjusted to contract rate; overcharge difference withheld. |
| `UNDERCHARGE` | SKU present; invoiced rate is lower than agreed contracted rate. | Reconciled as stated (no speculative upward adjustment). |
| `UNMATCHED` | Item SKU is absent from Schedule A contract terms. | Quarantined; excluded from payment disbursement until reviewed. |
| `SOURCE_DISCREPANCY` | Internal calculation error on supplier invoice ($Qty \times Rate \neq Total$). | Payment completely blocked fail-closed; supplier notified. |

---

## 3. Mathematical Formulation

For any verified line item $i$:
$$LineTotal_{contract, i} = \text{quantize}_{2}(Qty_i \times Rate_{contract, i})$$
$$Variance_i = LineTotal_{stated, i} - LineTotal_{contract, i}$$

For the case disbursement:
$$TotalPayable = \sum_{i \in MATCHED \cup OVERCHARGE} LineTotal_{contract, i}$$
$$TotalWithheld = \sum_{i \in OVERCHARGE} Variance_i$$

Under **Invariant Rule 1.3**, line items are quantized individually prior to aggregation.
