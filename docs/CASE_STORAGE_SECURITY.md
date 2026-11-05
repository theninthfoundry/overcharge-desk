# Overcharge Desk — Case Storage Isolation & Filesystem Security

> **Status**: Production Storage Security Baseline (Phase 3.2)  
> **Audience**: Systems Engineers, Security Auditors, Platform Developers

This specification defines the filesystem boundaries, path traversal protections, artifact registries, and atomic write guarantees enforced by `CaseStorage`.

---

## 1. Threat Model & Boundaries

Case artifacts contain sensitive financial data: extracted invoices, purchase contracts, reconciliation line matches, audit logs, and approval receipts.
Storage security must guarantee that:
1. No case operation can read, modify, or delete files outside its allocated case directory.
2. Attackers cannot leverage path traversal characters (`../`, `..\`, `%2e%2e`, null bytes) to traverse into parent directories or system files.
3. Attackers cannot use symlinks to reference external files (e.g. `/etc/passwd` or `config/signing.key`).
4. File sizes are bounded to prevent disk exhaustion attacks.
5. Incomplete or interrupted writes cannot corrupt active audit packages or state files.

---

## 2. Identifier Validation & Traversal Defenses

### 2.1 Case Identifier Regex
All case identifiers must strictly match:
```regex
^[a-zA-Z0-9_\-]{3,64}$
```
Any string containing path separators (`/`, `\`), relative path tokens (`..`), colons (`:`), percent signs (`%`), or null bytes (`\0`) is rejected immediately with a `StorageSecurityError`.

### 2.2 Canonical Path Containment
Before opening or creating any case folder, `CaseStorage` computes its canonical absolute path:
```python
clean_id = self.validate_case_id(case_id)
c_dir = (self.cases_dir / clean_id).resolve()
c_dir.relative_to(self.cases_dir)  # Raises ValueError if escaped
```
If the resolved path does not fall strictly within `self.cases_dir`, execution halts with an error.

### 2.3 Symlink Escape Prevention
When resolving artifacts within a case:
- `os.path.realpath` / `Path.resolve()` is called on candidate files.
- The resolved target must satisfy containment within the case directory:
```python
resolved_target.relative_to(c_dir)
```
If an artifact points to a symlink targeting files outside `c_dir`, `StorageSecurityError` is raised.

---

## 3. Allowed Artifact Registry & Size Boundaries

### 3.1 Closed Artifact Registry
Endpoints that read or serve artifacts cannot be manipulated into downloading arbitrary files. Only files registered in `ALLOWED_ARTIFACT_NAMES` are accessible:
- `invoice.json`
- `case.json`
- `evidence_registry.json`
- `compare.json` / `compare.json.sha256`
- `verification.json` / `verification.json.sha256`
- `manifest.json`
- `payment_preview.csv`
- `corrected_payment.csv`
- `partial_review.csv`
- `blocked_review_report.csv`
- `approval_receipt.json`
- `audit_integrity_report.json`

Requests for any unregistered file name (e.g. `signing.key`, `users.db`, `.env`) are rejected immediately.

### 3.2 File Size Constraints
All file reads are bounded by `MAX_FILE_SIZE_BYTES = 10,485,760` (10 MB). Attempting to load an artifact exceeding 10 MB raises a storage violation.

---

## 4. Atomic Write Guarantees

All case metadata, receipts, and JSON artifacts are written via `write_json_atomic`:
1. Payload is written to a unique temporary file in the target directory (`.<filename>.tmp.<uuid>`).
2. Data is flushed and synced to storage media (`os.fsync`).
3. An atomic filesystem replacement (`os.replace`) overwrites the destination path.

This guarantees that an application crash or power loss never leaves a partially-written or truncated JSON file on disk.
