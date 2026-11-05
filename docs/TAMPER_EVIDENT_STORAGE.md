# Tamper-Evident Ledger Storage Architecture

> **Security Baseline**: Cryptographic Hash Chains & Merkle Integrity  
> **Storage Layer**: SQLite (`ledger.db`) & Case Directory Artifacts  
> **Invariant**: Invariant Rule 4.1 & Rule 4.2 (Honest Immutability Claims)

---

## 1. The Principle of Honest Immutability

Many software systems claim that append-only files or relational databases are "immutable" or "tamper-proof". Overcharge Desk explicitly rejects this claim:
- Any file or database on an OS filesystem can be modified, truncated, or rewritten by a process with write permissions.
- Therefore, Overcharge Desk provides **tamper-evident verification**, not speculative hardware immutability.
- If any byte of the ledger or an evidence artifact is modified, the cryptographic hash chain immediately breaks and verification fails closed.

---

## 2. SQLite Hash Chain Design

The central ledger records case transitions, audits, disputes, and approvals in a linear hash chain:

```
┌─────────────────────────────────┐
│          Genesis Event          │
│ prev_hash: 00000000... (64 '0's)│
│ event_hash: a1f3...             │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│      Case Ingestion Event       │
│ prev_hash: a1f3...              │
│ event_hash: b8c4...             │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     Human Approval Event        │
│ prev_hash: b8c4...              │
│ event_hash: e9d2... (Chain Head)│
└─────────────────────────────────┘
```

### 2.1 Hash Computation Formula
Every event hash is computed deterministically over normalized UTF-8 JSON:
$$H_i = \text{SHA256}(H_{i-1} \parallel \text{event\_type} \parallel \text{case\_id} \parallel \text{actor} \parallel \text{timestamp} \parallel \text{canonical\_payload})$$

If an adversary attempts to modify the payload of an earlier event or delete a record, all subsequent `prev_hash` links become invalid.

---

## 3. Evidence Artifact Preservation

For every case, artifacts are preserved in canonical directory structures:
- `cases/<case_id>/raw_invoice.txt` (intake fingerprint recorded)
- `cases/<case_id>/compare.json` (deterministic contract matching)
- `cases/<case_id>/audit/verification.json` (manifest of all artifacts)
- `cases/<case_id>/receipt.json` (cryptographically signed approval receipt)
- `cases/<case_id>/corrected_payment.csv` (final disbursement sheet)

### 3.1 Chain Verification CLI
To verify the entire ledger chain from genesis to head:
```bash
python tools/ledger.py verify
```
Expected output:
```json
{
  "total_events": 14,
  "chain_integrity": "VALID",
  "head_hash": "e9d2a4f...64char...",
  "verified_at": "2026-11-06T10:00:00Z"
}
```
