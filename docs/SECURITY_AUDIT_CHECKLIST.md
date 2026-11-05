# Financial Security & Compliance Audit Checklist

> **Auditor Target**: Enterprise AP Security & Compliance Officers  
> **Standard**: Evidence-First Audit Standards & Cryptographic Integrity

---

## 1. Cryptographic Controls Checklist

- [x] **No Keys in Source Code**: Zero private keys, API secrets, or certificates committed to git history.
- [x] **Configurable Key Storage**: Key directory configurable via `OVERCHARGE_KEY_DIR` external to repo tree.
- [x] **Full 64-Character SHA-256 Digests**: No truncated (8-char or 12-char) hashes accepted in approval receipts.
- [x] **HMAC Signature Verification**: Approval receipts cryptographically signed with HMAC-SHA-256 over canonical JSON.
- [x] **Linear Hash Chain**: SQLite ledger links each event to previous event hash ($H_i = \text{SHA256}(H_{i-1} \parallel \dots)$).

---

## 2. Authentication & Authorization Checklist

- [x] **Memory-Hard Password Hashing**: Passwords stored using Argon2id ($m=64\text{MB}, t=3, p=4$).
- [x] **Interactive TTY Enforcement**: Approval CLI requires live terminal session (`sys.stdin.isatty()`).
- [x] **Token Revocation**: Dedicated logout endpoint and persistent token revocation table.
- [x] **Separation of Duties**: Unified agent CLI (`tools/desk.py`) omits `approve` subcommand entirely.
- [x] **No Agent Payment Authority**: Settlement agent requires signed human receipt before releasing disbursement.

---

## 3. Financial Integrity Checklist

- [x] **Exact Decimal Math**: All currency, quantities, and rates computed with `decimal.Decimal`.
- [x] **Zero IEEE 754 Floats**: No binary floating-point representation in financial calculations.
- [x] **Per-Line Quantization**: Round half-up to 2 decimal places computed per line item.
- [x] **No Arithmetic Assumptions**: Internal invoice discrepancies flagged as `SOURCE_DISCREPANCY` and blocked.
- [x] **Quarantine Unmatched Lines**: Line items not present in contracted Schedule A quarantined as `UNMATCHED`.
