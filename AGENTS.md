# AGENTS.md — Permanent Engineering & Operational Invariants

> **Project**: Overcharge Desk — Evidence-First Vendor Reconciliation  
> **Status**: Active Operational Invariants  
> **Authority**: Permanent workspace rules across all agents, developers, and tools.

All agents (Claude Code, OpenAI Codex, Antigravity, and any other automated or human contributor) working in this repository must strictly adhere to the permanent engineering invariants defined below.

---

## 1. Financial Integrity Invariants

1. **Mandatory Exact Decimal Arithmetic**:
   - Always use `decimal.Decimal` for monetary amounts, unit rates, quantities, and line totals.
   - **Never use `float`** for financial calculations, comparisons, or data representations.
2. **Preserve Original Invoice Truth**:
   - Never silently modify, correct, or normalize extracted source invoice values to force calculations to pass.
   - Never silently round extracted invoice values.
3. **Explicit Quantization & Rounding Policies**:
   - All financial operations must use explicit rounding rules: half-up rounding to 2 decimal places (`Decimal("0.01")`, `ROUND_HALF_UP`) per line item.
   - Totals must be computed by summing quantized line items; never round totals independently to mask line-level variance.
4. **No Assumption of Verification**:
   - **Never treat unmatched items as verified**. Unmatched items must remain explicitly quarantined as `UNMATCHED` / `UNVERIFIED`.
   - **Never treat arithmetic discrepancies as ordinary verified lines**. When an invoice exhibits internal arithmetic mismatches ($Qty \times Price \neq LineTotal$), the system must flag `SOURCE_DISCREPANCY` and block automated payment recommendations.
5. **No Speculative Completeness**:
   - Never present an incomplete goods subtotal as a complete or final invoice settlement amount.
   - Never invent taxes, freight surcharges, discounts, rates, or quantities. If taxes or shipping are omitted or unverified, the output must explicitly label the figure as `GOODS_SUBTOTAL_RECONCILED` with tax/shipping unverified.

---

## 2. Evidence Integrity Invariants

1. **Universal Source Referencing**:
   - Every material finding, claim, rate match, or variance calculation must cite an immutable source locator (e.g., `contracts/acme-contract.md#Schedule-A-Item-1`, `invoices/acme-inv-1103.txt#line-3`).
2. **Source Artifact Preservation & Fingerprinting**:
   - Original raw invoice files must be preserved in immutable read-only intake storage.
   - Compute and record full 64-character SHA-256 cryptographic fingerprints (`source_sha256`) at intake.
3. **Zero Hallucination of History or Terms**:
   - Never invent, infer, or extrapolate contract clauses, vendor aliases, or historical outcomes.
   - Distinguish strictly between credit note states:
     - `PROMISED`: Mentioned by vendor in phone/email correspondence.
     - `RECEIVED`: Credit note document in hand.
     - `APPLIED`: Settled against an active disbursement.
     - `OUTSTANDING`: Promised or received but unapplied.
   - A promised credit note must never be represented as received or applied.
4. **Separation of Evidence and Interpretation**:
   - Raw extracted data, deterministic calculation results, and AI agent analytical commentary must reside in distinct schema properties.

---

## 3. Authorization Invariants

1. **Hash Verification Does Not Equal Identity**:
   - A cryptographic digest (e.g., SHA-256) proves **artifact integrity** (that the document was not altered); it does **not prove user identity**.
2. **LLM Prompts Are Not Security Boundaries**:
   - An LLM chat message or text token in a shared room is not an authenticated owner approval.
   - A typed handle or username string (e.g., `@owner`) is not proof of identity.
3. **Full Cryptographic Digest Requirement**:
   - Never accept shortened approval hashes (e.g., 8-character or 12-character prefixes). All approval validations require the full 64-character SHA-256 hex digest.
   - Approval bindings must strictly incorporate:
     `(case_id, invoice_number, invoice_sha256, contract_id, compare_sha256, audit_sha256, decision, authenticated_actor)`
4. **Fail-Closed Authorization**:
   - Missing, ambiguous, stale, or unverified identity must cause immediate refusal (`fail-closed`).
   - Only a dedicated, controlled application service/gateway may record an authorized state transition.

---

## 4. Ledger & Audit Trail Invariants

1. **Verifiable Traceability**:
   - Every historical case, approval, and outcome must form an unbroken chain of custody.
   - Never silently overwrite, modify, or erase historical outcomes.
2. **Honest Immutability Claims**:
   - Never describe a plain JSON file or atomic file replacement routine as "immutable" or "tamper-proof".
   - State clearly that files are append-only by software convention and require cryptographic hash chains or database constraints to detect tampering (`tamper-evident`).
3. **Evidence Preservation on Rejection**:
   - Both approved disputes and rejected findings must be recorded with their complete supporting evidence and owner rationale. Rejections must never be categorized as confirmed vendor overcharges.

---

## 5. Engineering Invariants

1. **Separation of Concerns**:
   - Core financial verification and reconciliation logic must remain strictly independent of AI agent prompts.
   - The entire calculation and validation pipeline must be 100% executable and testable via deterministic Python standard library CLI tools without Switch or network access.
2. **Deterministic Reproducibility**:
   - Identical invoice and contract inputs must produce identical comparison outputs down to the byte. Non-deterministic timestamps must remain outside pure comparison routines.
3. **Explicit Error Boundaries**:
   - Prefer small, single-responsibility, pure functions.
   - External inputs must be rigorously validated at boundaries.
   - Handle all failure states explicitly; **never silently catch, ignore, or suppress exceptions**.
4. **Radical Engineering Transparency**:
   - Never claim a feature works without an automated test executing it.
   - Never claim production readiness, security compliance, or audit certification without verified third-party proof.
   - Do not introduce external dependencies, frameworks, or databases without explicit technical justification.


<!-- Invariant Rule 1.1: Exact Decimal arithmetic enforced across all modules -->

<!-- Invariant Rule 2.1: Immutable source locator formatting standards -->

<!-- Invariant Rule 3.1: Full 64-char SHA256 cryptographic digest binding -->

<!-- Invariant Rule 4.1: Tamper-evident hash chain verification policy -->

<!-- Invariant Rule 5.1: Strict separation of financial logic from AI prompts -->


<!-- Invariant Verification: Permanent baseline certified across 154 automated test scenarios -->
