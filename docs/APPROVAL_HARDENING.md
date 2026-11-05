# Overcharge Desk — Approval Protocol Hardening & Separation of Duties

> **Status**: Production Authorization Baseline (Phase 3.2)  
> **Audience**: Financial Controllers, Compliance Officers, Security Architects

This document defines the cryptographic, procedural, and programmatic constraints governing human approval of financial disbursements in Overcharge Desk.

---

## 1. Principles of Authorization Integrity

The authorization subsystem enforces five non-negotiable security invariants:

1. **The Server Dictates Payable Amounts**:
   - The approval endpoint **never accepts a user-dictated payable amount**.
   - The authoritative payable amount is independently computed by the server from `compare.json` and verified line totals.
   - If an optional amount parameter is passed by the client, it is strictly validated against the server-calculated amount: any mismatch raises an authorization failure.
2. **Strict Verification Allowlisting**:
   - Only cases whose automated verification status is explicitly `VERIFIED` can receive approval.
   - Cases marked `BLOCKED` (e.g. arithmetic discrepancies, negative quantities, missing rates) or `REVIEW_REQUIRED` (unmatched contract lines) are unconditionally rejected for approval.
3. **Mandatory Separation of Duties (Four-Eyes Principle)**:
   - The actor who created or ingested a case cannot approve it (`creator != approver`).
   - Self-approval is mechanically prohibited regardless of administrative privileges.
4. **Immutable Evidence Binding**:
   - The generated `approval_receipt.json` cryptographically binds all supporting artifacts:
     `(case_id, invoice_sha256, contract_id, compare_sha256, evidence_digest_set, ledger_head, approved_amount, actor_id, key_id)`.
5. **Idempotent Decision Processing**:
   - Submitting an identical approval for a previously approved case returns the verified receipt with `idempotent: true`, preventing receipt duplication and hash divergence.

---

## 2. Approval Receipt Anatomy

A hardened receipt contains full 64-character SHA-256 digests and an HMAC-SHA-256 signature:

```json
{
  "receipt_version": "1.0.0",
  "receipt_id": "AR-OC-20261106-01-20261105T080000",
  "case_id": "OC-20261106-01",
  "verification_id": "VRF-OC-20261106-01-20261105T080000",
  "ledger_head_at_approval": "9c6a378f7887e43b89498bcbd6b7e254bcab36d483a1a986366081c5696b0306",
  "signing_key_id": "key-20261105-a8f2",
  "invoice_number": "INV-1103",
  "invoice_sha256": "2c7d4c457e0b1d3f59092f997676589139738a89843c30da25824f1fbfe54543",
  "contract_id": "ACME-2026-01",
  "compare_sha256": "d1eb6157d3448f22a21670da3449927ab188e85e26aaf618d3d03704329b324e",
  "evidence_digest_set": {
    "EV-001": "5d1698be89444a462512838c317585a93793fbd7bc602ca55303a111890a7595",
    "EV-002": "dbd9c7dd013a4b084fd61864c19d3262ec231a33ff3568fc67788746af5e1329"
  },
  "actor_id": "approver_alice",
  "actor_role": "APPROVER",
  "decision": "APPROVED",
  "approved_amount": "60000.00",
  "withheld_amount": "6000.00",
  "currency": "INR",
  "created_at": "2026-11-05T08:00:00Z",
  "receipt_hash": "a4b8...64-char-hex",
  "signature": "e9c1...64-char-hex"
}
```

---

## 3. Cryptographic Tamper-Detection Workflow

When an approved case is processed for payment sheet generation or audit export:
1. The invoice file is re-hashed; digest must match `invoice_sha256`.
2. The comparison file is re-hashed; digest must match `compare_sha256`.
3. The receipt canonical digest is recalculated and checked against `receipt_hash`.
4. The HMAC-SHA-256 signature is verified using the key corresponding to `signing_key_id`.

If **any single character** in `compare.json` or `invoice.json` has been altered after approval, verification fails closed, logging `SECURITY_ALERT: RECEIPT_DIGEST_MISMATCH` and halting payment generation.

