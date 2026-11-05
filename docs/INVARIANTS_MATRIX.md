# Permanent Invariants Traceability Matrix

> **Source Authority**: `AGENTS.md` (Operational & Engineering Invariants)  
> **Certification**: 236 Automated Scenarios Passing

---

| Rule | Invariant Name | Enforcing Implementation Module | Enforcing Test Suite | Verification Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **1.1** | Exact Decimal Arithmetic | `domain/calculator.py`, `tools/desk.py` | `tests/test_financial_engine.py` | Type assertions on `Decimal`, ban on `float`. |
| **1.2** | Preserve Original Truth | `tools/evidence.py`, `tools/desk.py` | `tests/test_evidence_preservation.py` | SHA-256 intake check against raw source bytes. |
| **1.3** | Explicit Quantization | `domain/calculator.py` | `tests/test_quantization.py` | Half-up quantization to 2 decimal places. |
| **1.4** | No Verification Assumption | `domain/reconciler.py`, `tools/desk.py` | `tests/test_quarantine.py` | Unmatched items marked `UNMATCHED`/`BLOCKED`. |
| **1.5** | No Speculative Completeness | `domain/calculator.py` | `tests/test_subtotals.py` | Explicit labeling of partial reconciled subtotals. |
| **2.1** | Universal Source Referencing | `tools/evidence.py`, `domain/reconciler.py` | `tests/test_source_referencing.py` | File path and line number anchor assertions. |
| **2.2** | Source Fingerprinting | `tools/evidence.py`, `tools/desk.py` | `tests/test_fingerprinting.py` | Full 64-char SHA-256 digest calculated at intake. |
| **2.3** | Zero Hallucination of History | `tools/desk.py`, `tests/test_vendor_memory_mechanics.py` | `tests/test_vendor_memory_mechanics.py` | Credit note state machine and deterministic queries. |
| **3.1** | Hash Verification != Identity | `tools/approve.py`, `tools/auth.py` | `tests/test_approve_cli.py` | Cryptographic digests prove integrity, not user identity. |
| **3.2** | LLM Not Security Boundary | `tools/desk.py` | `tests/test_desk_cli.py` | Omission of `approve` subcommand; TTY check on `approve.py`. |
| **3.3** | Full 64-char SHA-256 Binding | `tools/approval_receipt.py`, `tools/approve.py` | `tests/test_receipt_binding.py` | Hex 64 regex check on all digests in receipt. |
| **3.4** | Fail-Closed Authorization | `tools/desk.py`, `tools/approve.py` | `tests/test_fail_closed.py` | Immediate non-zero exit code on any authorization failure. |
| **4.1** | Verifiable Traceability | `tools/audit_ledger.py`, `tools/ledger.py` | `tests/test_audit_ledger.py` | Linear hash chain recomputed from genesis anchor. |
| **4.2** | Honest Immutability Claims | `docs/TAMPER_EVIDENT_STORAGE.md`, `README.md` | Documentation review | Documentation specifies tamper-evident, not immutable. |
| **5.1** | Separation of Prompts & Math | `tools/desk.py`, `domain/calculator.py` | `tests/test_prompt_isolation.py` | 100% pure standard library execution without LLM calls. |
| **5.2** | Unified Agent CLI | `tools/desk.py` | `tests/test_desk_cli.py` | Verification of CLI subcommands and absence of `approve`. |
| **6.1** | Memory-Hard Argon2id Auth | `domain/identity/passwords.py`, `tools/auth.py` | `tests/test_argon2id.py` | Memory cost (64MB) and thread validation. |
| **7.1** | Filesystem Path Containment | `domain/cases/storage.py`, `tools/desk.py` | `tests/test_path_containment.py` | Path traversal and symlink escape defenses. |
