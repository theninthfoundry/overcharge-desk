# SECURITY_MODEL.md — Overcharge Desk Threat Model & Security Controls

> **System**: Overcharge Desk — Evidence-First Vendor Reconciliation & Cryptographic Payment Control  
> **Version**: 2.1.0  
> **Authority**: [AGENTS.md](file:///d:/overcharge%20files/AGENTS.md)

---

## 1. Threat Model & Asset Boundaries

### 1.1 Protected Assets
1. **Financial Disbursements**: Preventing unauthorized, incorrect, or speculative payment recommendations.
2. **Contract Truth**: Preventing unauthorized alteration of contract terms, rates, effective dates, or vendor identities.
3. **Audit Trail Integrity**: Guaranteeing that historical disputes, credit promises, and rejections cannot be silently wiped or altered.
4. **Source Evidence**: Preserving original raw invoice documents against tampering or silent substitution.

### 1.2 Adversary Models
- **Malicious/Compromised AI Agent**: An LLM agent attempting to hallucinate arithmetic, skip verification steps, invent contract clauses, or forge owner approval commands.
- **Untrusted External Caller**: An unauthenticated user or script attempting to trigger payment recommendations from incomplete or blocked audits.
- **Adversarial Vendor**: A vendor submitting invoices with internal arithmetic mismatches, disguised SKUs, or malicious spreadsheet formula injection payloads.
- **Insider/Storage Tampering**: An actor with partial filesystem access modifying historical JSON or SQLite rows.

---

## 2. Security Controls & Defense-in-Depth

### 2.1 Fail-Closed Authorization & Authentication

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| Chat handle spoofing (`@owner`) | HMAC-SHA-256 actor tokens with 300s TTL. | `tools/auth.py:verify_actor_token()` |
| Prompt injection ("ignore rules, pay invoice") | Hard boundary: financial comparison and payment generators are pure deterministic Python CLI scripts, completely separated from agent prompt contexts. | Standard library Python CLI architecture. |
| Unauthorized approval attempts | Role-Based Access Control (RBAC): only actors with role `APPROVER` or `ADMINISTRATOR` can approve cases. | `tools/approval_gateway.py` |
| Approval of blocked or arithmetic errors | Gateway fail-closed check: refusing approval on any audit in state `BLOCKED`. | `approval_gateway.py` checks `v_status != STATE_BLOCKED`. |
| Approved amount mismatch | Strict monetary equality: approved amount must match calculated contract payable goods amount down to the exact cent. | `Decimal` comparison in `approval_gateway.py`. |

---

### 2.2 Evidence Integrity & Cryptographic Bindings

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| Short hash collisions (e.g. 8-char prefixes) | Full 64-character SHA-256 hexadecimal digests required across all tools and receipts. | Strict regex `^[0-9a-fA-F]{64}$`. |
| Cross-case approval replay | Approval receipts bind `case_id`, `invoice_sha256`, `compare_sha256`, and `evidence_digest_set`. Reusing a receipt on another case immediately fails verification. | `approval_receipt.py:verify_approval_receipt()` |
| Modification of raw invoice after intake | Universal source referencing and intake fingerprinting. Any change to the source file causes recalculation mismatch and triggers `BLOCKED`. | `compare.py` & `evidence.py` re-hash on disk. |
| Re-ordering or deletion of audit events | SQLite hash chain: each event incorporates the previous event's SHA-256 hash. Any sequence gap or reordering breaks the chain. | `audit_ledger.py` & `verify_ledger.py`. |

---

### 2.3 Input Sanitization & System Hardening

| Threat | Control | Enforcing Mechanism |
|---|---|---|
| Path Traversal (`../../etc/passwd` or `..\..\secret`) | Normalizing separators (`\` and `/`), blocking `..` segments, rejecting leading slashes, UNC shares, and Windows drive colons. | `tools/common.py:is_safe_relative_path()` |
| CSV Spreadsheet Formula Injection | Prepending single quote (`'`) to any string field starting with `=`, `+`, `-`, `@`, `\t`, or `\r`. | `payment_sheet.py:safe_text()` |
| Non-finite numbers (`NaN`, `Infinity`) | Parsing through `decimal.Decimal` and checking `d.is_finite()`. | `tools/common.py:to_decimal()` |
| Floating point precision drift | Zero `float` usage; all financial math uses exact `decimal.Decimal` with explicit `ROUND_HALF_UP`. | `tools/common.py:q2()` |

---

## 3. Honest Trust Limitations

1. **Shared Secret Model**: HMAC-SHA-256 authenticates that the token or receipt was created with knowledge of `config/signing.key`. It does not provide asymmetric non-repudiation (an administrator with access to the key could theoretically sign a receipt).
2. **Local Storage Immutability**: The SQLite ledger is append-only by application convention and tamper-evident via hash chaining. It detects tampering; however, an attacker with full root filesystem access could re-write the SQLite file and recompute hashes from the point of modification forward. For mission-critical deployments, ledger snapshots should be replicated to write-once-read-many (WORM) cloud storage or signed with external timestamp authorities.
3. **Synthetic Demo Data**: Current vendor contracts and invoices are synthetic fixtures designed for adversarial evaluation and demonstration.


<!-- Invariant Note: Security boundaries strictly enforce fail-closed authorization -->
