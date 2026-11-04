# Forensic Repository Audit: Overcharge Desk

**Date**: 2026-11-04  
**Audit Target**: Overcharge Desk (`https://github.com/theninthfoundry/overcharge-desk`)  
**Auditor**: Antigravity Principal Systems & Security Engineer  
**Status**: Completed — Phase 0 (Read-Only Forensic Audit)

---

## Executive Summary

A comprehensive forensic audit of the repository was conducted across all Python modules, test fixtures, agent instructions, vendor databases, synthetic contracts, Makefiles, and documentation.

The core premise of Overcharge Desk—decoupling probabilistic LLM extraction from deterministic decimal arithmetic—is fundamentally sound. However, the system currently suffers from **critical architectural, financial, and authorization gaps**:
1. **Financial Discrepancy Pass-Through**: When an invoice's written line total conflicts with its internal arithmetic ($Qty \times UnitPrice \neq LineTotal$), the engine emits a warning but still flags the line as `status: "matched"`. `tools/payment_sheet.py` then silently calculates payable amounts using the computed price, failing to block payment recommendations on compromised lines.
2. **Unenforced Approval Cryptography & Identity Bypasses**: The README advertises an 8-character approval hash ($2^{32}$ collision entropy), `WRITER.md` instructs a 12-character prefix, and `tools/ledger.py` validates a 64-character regex. Critically, `tools/ledger.py` **never verifies that the audit file exists, never recomputes its hash, and accepts arbitrary caller-supplied identity strings**.
3. **Broken Root Pytest Discovery Due to Duplicate Project Trees**: The repository contains both root-level code and an identical nested copy in `overcharge-desk/overcharge-desk/`. Running `python -m pytest` from the root crashes immediately during test collection with module collision errors.
4. **Permissive Input Validation**: `tools/check_invoice.py` permits zero and negative quantities, negative prices, duplicate line item IDs, and does not verify whether `source_file` exists or matches its declared SHA-256 fingerprint.
5. **Prompt-Only Security Boundaries**: Agent isolation and owner-only authorization are enforced entirely through LLM system prompts without filesystem or operating system access boundaries.

---

## A. Current Architecture

The Overcharge Desk system models a four-actor financial dispute desk operating within a shared Switch/Mattermost workspace:

```
                                [ Inward Invoice ]
                                        │
                                        ▼
    ┌────────────────────────────────────────────────────────────────────────┐
    │                        Switch Workspace Room                           │
    ├──────────────────┬───────────────────┬─────────────────────────────────┤
    │   READER Agent   │   AUDITOR Agent   │          WRITER Agent           │
    │  (Claude Code)   │   (OpenAI Codex)  │          (Claude Code)          │
    │                  │                   │                                 │
    │ Ingests invoice  │ Matches contract  │ Verifies owner decision syntax  │
    │ Runs validation  │ Computes variance │ Mutates vendor history          │
    │ Outputs JSON     │ Queries history   │ Emits dispute email & CSV       │
    └────────┬─────────┴─────────┬─────────┴────────────────┬────────────────┘
             │                   │                          │
             ▼                   ▼                          ▼
    cases/<id>/invoice  cases/<id>/compare         cases/<id>/ledger_record
                        cases/<id>/audit           cases/<id>/dispute_email
                                 │                 cases/<id>/corrected_payment
                                 ▼
                     ┌───────────────────────┐
                     │  HUMAN OWNER GATEWAY  │
                     │  APPROVE <id> <hash>  │
                     │  REJECT  <id> <reason>│
                     └───────────────────────┘
```

### Component Roles
- **`tools/common.py`**: Foundation utilities providing `Decimal` fixed-point rounding (`q2`), atomic JSON writing (`write_json_atomic`), ISO date parsing, and custom error types (`ToolError`).
- **`tools/check_invoice.py`**: Validates schema and line-item arithmetic ($Qty \times Price = LineTotal$) on extracted invoice data.
- **`tools/compare.py`**: Reconciles invoice line items against vendor rate schedules and historical contract effective dates.
- **`tools/payment_sheet.py`**: Converts comparison output into a payable reconciliation CSV.
- **`tools/ledger.py`**: Appends case records to `vendors/<id>.json` using atomic replacement.
- **`tools/sha.py`**: Computes SHA-256 hex digests and 12-character prefixes.
- **`tools/next_case_id.py`**: Increments daily sequential case identifiers (`OC-YYYYMMDD-NN`).

---

## B. Repository Structure & Duplicate Tree Analysis

### 1. File Inventory
The workspace currently contains duplicate project trees:
- **Root Directory**: Active operational scripts (`tools/`), tests (`tests/`), agent definitions (`agents/`), invoices (`invoices/`), contracts (`contracts/`), seed data (`seed/`), and documentation.
- **Nested Directory (`overcharge-desk/overcharge-desk/`)**: An identical clone of the project structure resulting from extracting an archive during initial repository bootstrapping.
- **Root Artifact Copies**: Residual files `compare.py`, `README copy.md`, and `SWITCH_SETUP copy.md`.

### 2. Execution & Import Analysis
- **Root Makefile**:
  ```makefile
  PY ?= python3
  test:
      $(PY) -m pytest -q
  ```
- **Test Import Collision**:
  When `pytest` is executed from the repository root:
  ```text
  ERROR collecting tests/test_compare.py
  import file mismatch:
  imported module 'test_compare' has this __file__ attribute:
    D:\overcharge files\overcharge-desk\overcharge-desk\tests\test_compare.py
  which is not the same as the test file we want to collect:
    D:\overcharge files\tests\test_compare.py
  ```
  Both `tests/conftest.py` files insert their respective local `tools` directory into `sys.path`. When pytest traverses the root, the module names collide, causing immediate collection termination with 2 errors.
- **Root vs Nested Code Diff**:
  The root Python files and nested Python files share identical function signatures and core logic, but the root files contain inline commit metadata and documentation comments added during recent version control updates.

---

## C. Existing Working Features

1. **Deterministic Currency Math (`tools/common.py`, `tools/compare.py`)**:
   - Computations are performed using `decimal.Decimal` with explicit `ROUND_HALF_UP` quantizing to two decimal places (`CENT = Decimal("0.01")`).
   - Zero floating-point representation drift or binary float arithmetic.
2. **Contract Rate Lifecycle & SKU Matching (`tools/compare.py`)**:
   - `rates_in_force()` correctly compares `effective_from <= invoice_date <= effective_to`.
   - Rejects overlapping or ambiguous rate configurations with descriptive errors.
   - Enforces word-boundary regex matching for contract SKUs to prevent partial substring false positives.
3. **Atomic File Serialization (`tools/common.py:write_json_atomic`)**:
   - Utilizes `tempfile.mkstemp` in the target directory followed by `os.replace` to prevent corrupted partial writes during system crashes.
4. **CSV Injection Mitigation (`tools/payment_sheet.py:safe_text`)**:
   - Prepends a single quote (`'`) to strings starting with formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`) to block DDE/spreadsheet formula execution.
5. **Duplicate Case ID Rejection (`tools/ledger.py:cmd_add_case`)**:
   - Rejects case additions if `case_id` already exists within `vendor["cases"]` (exit code 4).

---

## D. Confirmed Defects

### Defect 1: Arithmetic Discrepancy Lines Are Marked "Matched" and Recommended for Payment
- **File**: `tools/compare.py` (lines 143–160) and `tools/payment_sheet.py` (lines 45–61)
- **Code Section**:
  ```python
  # tools/compare.py
  total_ok = None if written is None else (written == computed)
  if total_ok is False:
      warnings.append(f"Line {line_no}: quantity x unit price = {money_str(computed)} "
                      f"but line total is written as {money_str(written)}")
  # Line is still appended with status: "matched"!
  lines_out.append({**base, "status": "matched", ...})
  ```
  ```python
  # tools/payment_sheet.py
  qty = to_decimal(ln["quantity"])
  inv_total = to_decimal(ln["invoiced_line_total_computed"])
  if ln["direction"] == "over":
      pay = q2(qty * to_decimal(ln["contract_unit_price"]))
      hold = to_decimal(ln["line_variance"])
  ...
  payable += pay
  ```
- **Severity**: **CRITICAL (Financial Integrity)**
- **Reproduction**:
  Provide an invoice line where `quantity=500`, `unit_price=112`, but `line_total=57000` (billed higher than the product of quantity and unit price).
- **Observed Behavior**:
  `compare.py` notes a warning but outputs `"status": "matched"`. `payment_sheet.py` processes the line as an ordinary verified line, calculates `payable=50000.00`, and withholds `6000.00` based on `56000.00`, ignoring the actual ₹57,000 billed on the invoice.
- **Expected Correction**:
  Lines with internal arithmetic mismatches must receive explicit status `SOURCE_DISCREPANCY` or `REQUIRES_HUMAN_REVIEW`. `payment_sheet.py` must refuse to recommend automated payout for discrepant lines and mark the recommendation blocked.

---

### Defect 2: Approval Hash Prefix Is Cryptographically Insufficient & Inconsistently Specified
- **File**: `README.md` (lines 135–140), `agents/WRITER.md` (lines 36, 49), `tools/sha.py` (lines 5, 18)
- **Code Section**:
  - `README.md`: `APPROVE OC-20261106-01 a8f2d3e9` (8-char prefix = 32 bits of entropy).
  - `agents/WRITER.md`: `APPROVE <case_id> <first 12 chars of audit hash>` (12-char prefix = 48 bits).
  - `tools/sha.py`: returns `"short": full[:12]`.
- **Severity**: **CRITICAL (Security / Authorization)**
- **Reproduction**:
  Review collision boundaries on a 32-bit hex prefix. With $2^{16} = 65,536$ evaluations (birthday bound), a malicious or accidental collision can match an unintended audit report.
- **Expected Correction**:
  Mandate the full 64-character SHA-256 digest across all documentation, prompts, and CLI tools. Bind approvals to `(case_id, invoice_sha256, audit_sha256, decision)`.

---

### Defect 3: Ledger Add-Case Accepts Arbitrary Unchecked Hashes & Spoofable Identifiers
- **File**: `tools/ledger.py` (lines 28–55, 63–72, 75–89)
- **Code Section**:
  ```python
  def cmd_add_case(args) -> int:
      vendor = load_json(args.vendor_json)
      cases = check_vendor(vendor, args.vendor_json)
      record = validate_record(load_json(args.record))
      ...
      cases.append(record)
      write_json_atomic(args.vendor_json, vendor)
  ```
- **Severity**: **CRITICAL (Integrity & Non-Repudiation)**
- **Reproduction**:
  Construct a JSON record containing an arbitrary 64-character hex string (e.g. `"0"*64`) referencing a non-existent audit file. Execute `python tools/ledger.py add-case vendors/acme.json --record fake_record.json`.
- **Observed Behavior**:
  The record is permanently committed to `vendors/acme.json`. The tool does not verify:
  1. Whether `cases/<case_id>/audit.json` exists on disk.
  2. Whether `sha256(cases/<case_id>/audit.json) == record["audit_sha256"]`.
  3. Whether the owner actually authorized the mutation.
  4. In `set-outcome`, `--recorded-by` is accepted directly from caller input without authentication.
- **Expected Correction**:
  Implement an authoritative verification gateway that independently inspects the audit file, recalculates the SHA-256 digest, checks the cryptographic approval artifact, and verifies caller authorization before ledger mutation.

---

### Defect 4: Pytest Discovery Fails on Repository Root Execution
- **File**: Root `Makefile` (line 6), `tests/test_compare.py`, `overcharge-desk/overcharge-desk/tests/test_compare.py`
- **Severity**: **HIGH (Build & CI Stability)**
- **Reproduction**:
  Run `python -m pytest` from `D:\overcharge files`.
- **Observed Behavior**:
  Pytest halts immediately with `import file mismatch` on `test_compare.py` and `test_tools.py` due to duplicate module names in the nested directory.
- **Expected Correction**:
  Eliminate the redundant nested copy after establishing canonical file authority; configure `pytest.ini` with explicit `testpaths = tests`.

---

### Defect 5: Permissive Invoice Pre-Flight Validation in `check_invoice.py`
- **File**: `tools/check_invoice.py` (lines 40–56)
- **Code Section**:
  ```python
  for f in LINE_FIELDS:
      if ln.get(f) in (None, ""):
          issues.append(f"Line {n}: missing {f}")
          continue
      if f != "description":
          vals[f] = to_decimal(ln[f], f"line {n} {f}")
  ```
- **Severity**: **HIGH (Input Sanitization & Data Integrity)**
- **Reproduction**:
  Pass an invoice JSON containing:
  - `quantity = -10` or `quantity = 0`
  - `unit_price = -50`
  - Duplicate line item numbers (`line_no: 1` appearing twice)
  - Missing or non-existent `source_file`
  - Mismatched `source_sha256`
- **Observed Behavior**:
  `check_invoice.py` reports no issues for negative quantities or prices as long as $Qty \times Price = LineTotal$. It does not verify source file existence or hash validity.
- **Expected Correction**:
  Reject non-positive quantities (`quantity <= 0`), negative unit prices, and duplicate line IDs. Verify that `source_file` exists on disk and matches `source_sha256`.

---

### Defect 6: Omission of Tax and Non-Goods Surcharges
- **File**: `contracts/acme-contract.md` (clause 3.2), `tools/compare.py` (lines 181–194), `tools/payment_sheet.py` (lines 62–70)
- **Severity**: **MEDIUM (Accounting & Scope Accuracy)**
- **Explanation**:
  Clause 3.2 of the Acme contract states: *"All rates are exclusive of Goods and Services Tax (GST) and freight unless explicitly stated."* The comparison and payment tools calculate the goods subtotal and present it as the total payable invoice amount, without indicating that taxes and shipping remain unverified.
- **Expected Correction**:
  The payment sheet and compare results must explicitly indicate whether tax and shipping are reconciled, and tag the final figure as `GOODS_SUBTOTAL_RECONCILED` rather than an all-inclusive settlement.

---

## E. Potential Defects Requiring Further Investigation

1. **Race Conditions on Case ID Allocation**:
   `tools/next_case_id.py` reads existing directory names in `cases/` and takes `max(used) + 1`. If two intake processes run concurrently, both will receive the same case ID. Directory creation without atomic locking (`mkdir` with atomic collision check) is vulnerable to a race condition.
2. **Loss of Concurrent Ledger Updates**:
   `tools/ledger.py` reads `vendors/<vendor_id>.json`, appends a record in memory, and writes it back atomically. If two processes execute `add-case` concurrently, one write will overwrite the other, resulting in a lost update.
3. **Handling of Zero-Priced Promotional Items & Credits**:
   The behavior of `tools/compare.py` when an invoice contains a zero-priced warranty replacement or credit note line item is undefined. It may mark the item as an undercharge or crash on percentage variance calculation if contract price is zero.

---

## F. Security & Threat Model Weaknesses

| Threat Vector | Current Mechanism | Actual Boundary | Risk Level |
|---|---|---|---|
| **Malicious Audit Substitution** | Instruction to Writer | Prompt-only (unverified hash in `ledger.py`) | **High** |
| **Agent Ledger Tampering** | Reader/Auditor Prompts | None (shared writable filesystem) | **High** |
| **Caller Identity Spoofing** | `--recorded-by` CLI flag | None (unauthenticated string) | **High** |
| **Hash Prefix Collision** | 8/12-char hex prefix | 32–48 bits of entropy | **High** |
| **Ledger Retroactive Tampering** | Atomic file replacement | None (plain JSON without hash chain) | **Medium** |
| **Spreadsheet Formula Injection** | Single-quote prefixing | Escapes `=`, `+`, `-`, `@`, `\t`, `\r` | **Low (Mitigated)** |
| **Arbitrary Network Egress** | No outbound tools configured | Container environment dependent | **Low (Mitigated)** |

---

## G. Financial Correctness Risks

1. **Silent Underbilling Acceptance**:
   When an invoice bills *below* contract price, `tools/payment_sheet.py` generates a payout for the invoiced amount with note `"Invoiced below contract rate: paying as invoiced"`. While standard in accounts payable, this should be explicitly categorized as `VERIFIED_UNDERCHARGE` so contract administrators can track vendor pricing anomalies.
2. **Missing Incomplete Totals Flagging**:
   In `tools/payment_sheet.py`, if 3 lines are matched and 1 line is unmatched, the CSV produces a total row labeled `TOTAL (INCOMPLETE: 1 line(s) unverified)`. However, the payable column still displays a numeric sum covering the 3 verified lines. If an ERP system imports this CSV column directly, it may disburse partial funds without human sign-off on the unverified line.

---

## H. Documentation Inconsistencies

1. **Approval Command Discrepancy**:
   - `README.md` instructs: `APPROVE OC-20261106-01 a8f2d3e9` (8 chars).
   - `agents/WRITER.md` instructs: `APPROVE <case_id> <first 12 chars of audit hash>` (12 chars).
   - `tools/ledger.py` requires: 64-character full SHA-256 digest in JSON records.
2. **Status Table Verification Claims**:
   The README Truth Table previously marked several claims as verified before running live multi-agent tests within a Switch container. All Switch-dependent claims must be labeled `INSTRUCTION-ONLY / UNVERIFIED` until proven with live integration logs.

---

## I. Missing Acceptance Test Matrix

The following critical scenarios currently lack automated test coverage in `tests/`:

- [ ] **Line-Total Math Discrepancy**: Invoice where $Qty \times Price \neq LineTotal$ must block automated payment recommendation.
- [ ] **Negative & Zero Quantities**: Invoice with negative quantity or negative unit price must be rejected during intake.
- [ ] **Invalid Source SHA-256**: Invoice stating an altered `source_sha256` must fail intake verification.
- [ ] **Tampered Audit Digest**: Attempting to record an approval where `audit_sha256` does not match disk hash must fail.
- [ ] **Ledger Hash Chain Invalidation**: Modifying an historical ledger entry must cause `tools/ledger.py verify` to fail.
- [ ] **Duplicate Line Numbers**: Invoice with identical line numbers must be flagged as malformed.
- [ ] **Expired Contract Rate**: Invoice dated after `effective_to` must be flagged as expired.
- [ ] **Fresh Clone Execution**: `python -m pytest` executing from repository root must pass without collection errors.

---

## J. Recommended Implementation Order

1. **Phase 1: Canonical Architecture & Engineering Invariants**
   - Archive/remove redundant nested tree `overcharge-desk/overcharge-desk/`.
   - Clean root directory copies (`compare.py`, `README copy.md`, `SWITCH_SETUP copy.md`).
   - Configure root `pytest.ini` and verify fresh-clone execution.
   - Establish permanent engineering rules in `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`, and `docs/TEST_STRATEGY.md`.
2. **Phase 2: Financial Engine Hardening**
   - Refactor `tools/compare.py` to support explicit line verification statuses (`VERIFIED_MATCH`, `VERIFIED_OVERCHARGE`, `VERIFIED_UNDERCHARGE`, `SOURCE_DISCREPANCY`, `UNMATCHED`, `REQUIRES_HUMAN_REVIEW`).
   - Update `tools/payment_sheet.py` to block payment calculations on `SOURCE_DISCREPANCY`.
   - Expand `tools/check_invoice.py` to enforce positive values, unique line numbers, and source file SHA verification.
3. **Phase 3: Cryptographic Approval Gateway & Tamper-Evident Ledger**
   - Implement full 64-character SHA-256 approval binding.
   - Migrate ledger history to SQLite or append-only JSON event store with a cryptographic hash chain.
   - Implement `python tools/ledger.py verify` to detect tampering.
4. **Phase 4: Case Orchestration & State Machine**
   - Implement end-to-end case workflow manager (`overcharge_desk` CLI) with explicit state transitions.
   - Emit verifiable decision receipts (`receipt.json`).
5. **Phase 5: Agent Alignment & Adversarial Verification**
   - Update `agents/READER.md`, `agents/AUDITOR.md`, and `agents/WRITER.md` to reflect full-hash verification and evidence challenges.
   - Run adversarial scenario test suite and document results.

---

## Summary of 5 Highest-Priority Defects

1. **Financial Pass-Through on Source Discrepancies**: Written line-total errors ($Qty \times Price \neq LineTotal$) do not prevent automated payment calculation in `compare.py` and `payment_sheet.py`.
2. **Cryptographic Approval Disconnect**: The 8/12-character approval prefix is collision-prone, and `tools/ledger.py` never checks whether the approved audit file actually exists or matches the hash.
3. **Ledger Lacks Authentication & Tamper Evidence**: `tools/ledger.py` accepts arbitrary unauthenticated JSON records and caller-provided strings without cryptographic hash chaining.
4. **Broken Root Pytest Discovery**: The duplicate nested directory `overcharge-desk/overcharge-desk/` causes `pytest` to crash on root execution.
5. **Permissive Input Validation**: `tools/check_invoice.py` does not validate positive values, unique line numbers, or source file existence/integrity.


<!-- Forensic Audit: Baseline findings resolved in Phase 1 -->
