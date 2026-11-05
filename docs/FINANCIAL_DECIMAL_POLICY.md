# Financial Decimal Arithmetic Policy & IEEE 754 Hazard Mitigations

> **Standard**: Python `decimal.Decimal` Mandatory Across Entire Core Engine  
> **Precision**: Explicit Quantization (`Decimal("0.01")`, `ROUND_HALF_UP`)  
> **Invariant**: Invariant Rule 1.1, Rule 1.2, Rule 1.3

---

## 1. The Binary Floating-Point Hazard

Standard computer architecture represents numbers using IEEE 754 binary floating-point representation (`float`). Because binary cannot precisely represent base-10 fractions (such as 0.1 or 0.05), cumulative rounding errors inevitably corrupt financial reconciliation:

```python
# IEEE 754 Float Hazard:
>>> 0.1 + 0.2
0.30000000000000004
>>> 1000 * 0.07
70.00000000000001
```

In high-volume accounts payable reconciliation, micro-variances compound across thousands of line items, triggering false-positive variance alerts or masking fraudulent line-item leakage.

---

## 2. Invariant Rules for Exact Arithmetic

### 2.1 Rule 1.1: Strict Ban on Float
- The use of `float` for monetary amounts, unit rates, quantities, and line totals is strictly forbidden.
- All numeric inputs must be parsed directly from text strings into `decimal.Decimal`:
  ```python
  # Correct:
  rate = Decimal(str(row["unit_rate"]))
  
  # Strictly Forbidden:
  rate = Decimal(float(row["unit_rate"]))  # Loss of precision occurs prior to Decimal instantiation
  ```

### 2.2 Rule 1.2: Per-Line Quantization
- Every individual line item calculation ($Quantity \times UnitRate$) must be quantized to 2 decimal places using `ROUND_HALF_UP`:
  ```python
  CENTS = Decimal("0.01")
  line_total = (qty * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
  ```
- Grand totals and subtotals must be computed by summing already-quantized line items. Under no circumstances may grand totals be rounded separately to conceal line-level discrepancies.

### 2.3 Rule 1.3: String-Based JSON Serialization
To prevent upstream and downstream web browsers or JSON parsers from coercing numbers into IEEE 754 floats:
- All monetary fields in REST responses and JSON artifacts are serialized as formatted string literals (`"60000.00"`, `"6000.00"`).

