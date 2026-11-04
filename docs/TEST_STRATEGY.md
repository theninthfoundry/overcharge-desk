# Comprehensive Test Strategy: Overcharge Desk

**Version**: 1.1 (Phase 1 Baseline)  
**Test Framework**: pytest 7+  
**Target Coverage**: Financial calculations, schema parsing, CLI utilities, security boundaries, and adversarial datasets.

---

## 1. Test Architecture & Structure

All tests reside in the authoritative `tests/` directory at the repository root and are managed via `pytest.ini`:

```
tests/
├── conftest.py             # Test fixtures: temporary directories, sample invoices, and seed data
├── fixtures/               # Static mock payloads: example_invoice.json
├── test_compare.py         # Financial calculations, contract matching, rate schedules
└── test_tools.py           # CLI tools, atomic IO, ledger operations, CSV formula escaping
```

---

## 2. Test Categories & Verification Suites

### 2.1 Financial Correctness Tests (`tests/test_compare.py`)
Validates that monetary calculations are mathematically exact and fail closed when data is ambiguous:
- **Baseline Variance Verification**: Tests the canonical demo scenario (500 units @ ₹112 vs ₹100 = ₹6,000 variance, 12% overcharge).
- **Underbilling Isolation**: Confirms invoices with rates below contract are flagged as `"under"` without forcing price increases.
- **Awkward Decimal & Rounding Precision**: Tests odd quantities and fractional rates (e.g., $3 \times 10.335$) to ensure consistent `ROUND_HALF_UP` behavior without binary floating-point drift.
- **Date-Effective Rate Resolution**: Verifies that rates active on the invoice date are selected, expired rates are ignored, and overlapping rates raise explicit errors.
- **SKU & Word-Boundary Matching**: Ensures descriptions matching an explicit SKU (e.g., `CC-5`) match, while preventing substring overmatching (e.g., `CC-50` matching `CC-5`).
- **Currency Parity**: Rejects invoices where line currencies conflict with contract rates.

### 2.2 CLI & Tool Integration Tests (`tests/test_tools.py`)
Validates deterministic execution, exit codes, and file IO:
- **Sequential Case ID Generation**: Tests `tools/next_case_id.py` across sequential runs and empty case directories.
- **SHA-256 Fingerprinting**: Verifies full 64-character hash computation and 12-character slicing.
- **Atomic File Writing**: Tests `write_json_atomic` resiliency and proper permissions.
- **Pre-Flight Invoice Sanitation**: Verifies `tools/check_invoice.py` catches missing fields and internal arithmetic errors.
- **End-to-End CLI Pipeline**: Simulates a complete manual run from invoice intake through comparison, ledger update, and CSV payment sheet generation.

### 2.3 Security & Boundary Tests
- **CSV Formula Injection**: Tests `tools/payment_sheet.py` against dangerous prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`) to ensure single-quote escaping is applied.
- **Ledger Duplicate Prevention**: Tests `tools/ledger.py` rejection of existing case IDs (exit code 4).
- **Malformed Record Rejection**: Parametrized tests validating that incomplete, invalid-status, or malformed records are rejected before ledger write.

---

## 3. Exact Commands for Test Execution

### 3.1 Standard Test Execution (Authoritative)
```bash
# Run complete test suite quietly via Makefile
make test

# Run complete test suite with verbose output via pytest
python -m pytest -v

# Run with full assertion diffs and local variables on failure
python -m pytest -vv -l
```

### 3.2 Category-Specific Execution
```bash
# Run financial calculation and comparison tests only
python -m pytest tests/test_compare.py -v

# Run tool utilities, ledger, and CSV tests only
python -m pytest tests/test_tools.py -v

# Run a specific unit test by name
python -m pytest -k "test_demo_case_six_thousand_over"
python -m pytest -k "test_payment_sheet_blocks_formula_injection"
```

---

## 4. Fresh-Clone Verification Protocol

To verify that the repository is completely self-contained and reproducible from a fresh clone:

```bash
# 1. Clean environment checkout
git clone https://github.com/theninthfoundry/overcharge-desk.git
cd overcharge-desk

# 2. Install testing dependencies
python3 -m pip install -r requirements-dev.txt

# 3. Execute authoritative test suite
python3 -m pytest

# 4. Verify standalone CLI execution
python3 tools/next_case_id.py
python3 tools/compare.py tests/fixtures/example_invoice.json vendors/acme.json
python3 tools/sha.py invoices/acme-inv-1103.txt
```

---

## 5. Planned Phase 2–6 Test Extensions

The following test suites will be added in subsequent implementation phases:

| Phase | Test Suite | Scope |
|---|---|---|
| **Phase 2** | `tests/test_financial_invariants.py` | Discrepant line-total blocking (`SOURCE_DISCREPANCY`), positive quantity assertions, negative unit price rejection. |
| **Phase 3** | `tests/test_ledger_integrity.py` | Full 64-character SHA verification, tamper detection, hash chain integrity verification. |
| **Phase 4** | `tests/test_orchestrator.py` | State machine transitions, verifiable receipt (`receipt.json`) generation and verification. |
| **Phase 6** | `benchmarks/` | Adversarial multi-vendor scenarios (overlapping dates, currency conversions, edge-case tax items). |


<!-- Testing Section: Automated test execution via Makefile targets -->
