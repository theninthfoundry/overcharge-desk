# Phase 1 Engineering Report: Canonical Repository & Engineering Invariants

**Date**: 2026-11-04  
**Project**: Overcharge Desk — Evidence-First Vendor Reconciliation  
**Milestone**: Phase 1 Complete (Clean Foundation & Invariants Established)  
**Status**: Passed All Acceptance Criteria

---

## 1. Executive Summary

Phase 1 established an authoritative single-tree repository structure, eliminated duplicate module conflicts, unified test discovery under `pytest.ini`, and codified strict permanent engineering rules in `AGENTS.md` and `docs/`.

Crucially:
- **Zero changes were made to the financial calculation engine** or business logic in this phase.
- **All 46 pre-existing unit tests are 100% preserved and passing** directly from the repository root.
- The dual-tree module collision bug that prevented `pytest` from discovering tests has been permanently resolved.

---

## 2. Directory Structure & File Reconciliation

### 2.1 Files Retained (Authoritative Canonical Tree)
The root directory was verified as the complete, authoritative implementation containing all active tools, agent prompts, test suites, and synthetic reference data:
- `tools/`: `common.py`, `check_invoice.py`, `compare.py`, `ledger.py`, `next_case_id.py`, `now.py`, `payment_sheet.py`, `sha.py`.
- `tests/`: `conftest.py`, `test_compare.py`, `test_tools.py`, `fixtures/example_invoice.json`.
- `agents/`: `READER.md`, `AUDITOR.md`, `WRITER.md`.
- `contracts/`: `acme-contract.md`.
- `invoices/`: `acme-inv-0914.txt`, `acme-inv-1103.txt`.
- `seed/` & `vendors/`: `acme.json`.
- `cases/`: `.gitkeep`.
- Root project files: `Makefile`, `README.md`, `SWITCH_SETUP.md`, `DEMO_SCRIPT.md`, `requirements-dev.txt`.

### 2.2 Files Removed & Justifications
Prior to removal, all candidate files were analyzed via cryptographic SHA-256 comparison and Python AST function inspection:
1. **`overcharge-desk/` nested directory (27 files)**:
   - *Justification*: Redundant duplicate tree resulting from initial archive extraction. AST analysis confirmed that `overcharge-desk/overcharge-desk/tests/` contained the exact same 46 test functions as `tests/`. Root files contained more up-to-date commit documentation and comments. Removing the nested directory eliminated test collection collisions.
2. **`compare.py` (at root)**:
   - *Justification*: Stale duplicate copy of `tools/compare.py`. All documentation and tests invoke `tools/compare.py`.
3. **`README copy.md` & `SWITCH_SETUP copy.md` (at root)**:
   - *Justification*: Ephemeral OS file-copy duplicates of `README.md` and `SWITCH_SETUP.md`.

---

## 3. Test Discovery Configuration

### 3.1 The Problem
Previously, running `python -m pytest` from the root crashed during collection with:
```text
import file mismatch: imported module 'test_compare' has this __file__ attribute:
  D:\overcharge files\overcharge-desk\overcharge-desk\tests\test_compare.py
which is not the same as the test file we want to collect:
  D:\overcharge files\tests\test_compare.py
```

### 3.2 The Solution
1. Configured root `pytest.ini` with explicit test discovery boundaries:
   ```ini
   [pytest]
   testpaths = tests
   python_files = test_*.py
   ```
2. Removed the redundant nested test folder.
3. Verified that `tests/conftest.py` cleanly resolves imports to `tools/` via `sys.path.insert(0, str(ROOT / "tools"))`.

---

## 4. Actual Test Results

Executed from the repository root:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.1.0, pluggy-1.6.0
rootdir: D:\overcharge files
configfile: pytest.ini
testpaths: tests
collected 46 items

tests/test_compare.py .....................                              [ 45%]
tests/test_tools.py .........................                            [100%]

============================= 46 passed in 1.43s ==============================
```

- **Collected Tests**: 46
- **Passed**: 46
- **Failed**: 0
- **Skipped**: 0
- **Collection Errors**: 0

---

## 5. Documentation Created

1. **`AGENTS.md`**: Permanent, non-negotiable workspace invariants covering:
   - *Financial Integrity*: Mandatory `Decimal`, zero float, no silent rounding, no promotion of source discrepancies into ordinary verified lines, no speculative tax/freight additions.
   - *Evidence Integrity*: Explicit locators, raw source preservation, 64-char SHA-256 fingerprinting, separation of credit note lifecycle states (`PROMISED` vs `RECEIVED` vs `APPLIED`).
   - *Authorization*: Disconnecting hash integrity from user identity; rejection of truncated hashes; fail-closed authorization.
   - *Ledger & Audit Trail*: Transparent tamper-evident claims; non-repudiation.
   - *Engineering*: Pure functions, deterministic CLI independence, zero silent exception suppression.
2. **`docs/ARCHITECTURE.md`**: Comprehensive architectural blueprint, actor boundaries, data and artifact flows, CLI entry points, and current vs. planned capabilities.
3. **`docs/SECURITY_MODEL.md`**: Rigorous threat model mapping protected assets, threat actors, prompt injection mitigations, CSV formula injection sanitization, and unresolved identity boundaries.
4. **`docs/TEST_STRATEGY.md`**: Strategy covering unit, integration, CLI, boundary, and fresh-clone verification protocols.
5. **`pytest.ini`**: Declarative test runner configuration.
6. **`.gitignore`**: Hardened gitignore preventing accidental commits of test caches, virtual environments, ephemeral cases, or temporary files.

---

## 6. Remaining Defects & Next Focus (Phase 2)

With repository hygiene, canonical imports, and permanent rules established, the core architectural defects identified in Phase 0 are ready to be resolved in Phase 2:
1. **Financial Pass-Through on Source Discrepancies**: Refactor `tools/compare.py` to assign explicit verification statuses (`VERIFIED_MATCH`, `VERIFIED_OVERCHARGE`, `VERIFIED_UNDERCHARGE`, `SOURCE_DISCREPANCY`, `UNMATCHED`, `REQUIRES_HUMAN_REVIEW`) and update `tools/payment_sheet.py` to block payment recommendation when `SOURCE_DISCREPANCY` occurs.
2. **Permissive Input Validation**: Enforce positive quantities ($Qty > 0$), positive unit prices, unique line numbers, and verify `source_file` existence and SHA-256 digest in `tools/check_invoice.py`.

---

## 7. Verification Reproducibility Commands

To independently reproduce this verification from the repository root:

```bash
# 1. Verify test discovery and execution (46 tests)
python -m pytest -v

# 2. Verify Makefile automation target
make test

# 3. Verify Python module imports
python -c "import sys; sys.path.insert(0, 'tools'); import common, compare, ledger, check_invoice, next_case_id, now, payment_sheet, sha; print('OK')"

# 4. Verify standalone CLI tool execution
python tools/next_case_id.py
python tools/now.py
python tools/sha.py invoices/acme-inv-1103.txt
python tools/compare.py tests/fixtures/example_invoice.json vendors/acme.json
```

