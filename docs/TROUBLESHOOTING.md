# Troubleshooting & Error Code Taxonomy

> **System**: Overcharge Desk Diagnostics & Remediation Matrix  
> **Philosophy**: Explicit error boundaries; no silent failures.

---

## 1. Error Taxonomy Reference Table

| Code | Trigger Condition | Common Root Cause | Remediation Procedure |
| :--- | :--- | :--- | :--- |
| `AUTH_TTY_REQUIRED` | `sys.stdin.isatty()` returned False | Script invoked in automated pipeline or headless runner. | Approvals must be executed by a human in an interactive TTY. In headless testing, pass `--dev` or use programmatic fixtures. |
| `AUTH_ARGON2_FAILED` | Password verification returned False | Typos or incorrect credentials for approver/owner account. | Verify password against the persistent identity store. Check for whitespace. |
| `EVIDENCE_TAMPERING_DETECTED` | Computed artifact SHA-256 $\neq$ recorded hash | Artifact file (`compare.json`, `verification.json`) modified on disk. | Re-run intake to establish a clean case baseline, or restore artifact from immutable backup. |
| `RECEIPT_REQUIRED` | `desk.py finalize` executed without `--receipt-file` | Settlement agent attempted to release payment before approval. | Execute `tools/approve.py <case_id>` first and provide the resulting receipt JSON to finalize. |
| `SIGNATURE_VERIFICATION_FAILED` | Receipt HMAC signature validation failed | Receipt JSON was altered, or signing key differed. | Ensure the same key directory was used for signing and verification. Re-issue approval if necessary. |
| `SOURCE_DISCREPANCY` | Invoice $Qty \times Rate \neq Total$ | Vendor invoice has internal mathematical errors. | Quarantine invoice. Notify vendor of internal arithmetic error. |
| `UNMATCHED_CATALOG_ITEM` | Invoice item SKU not found in Schedule A | Supplier billed an item not covered by contract. | Quarantine item as `UNMATCHED`. Escalate to procurement for contract addendum. |
| `KEY_DIR_NOT_FOUND` | Production mode active, but key directory missing | `OVERCHARGE_KEY_DIR` environment variable not exported. | Set `export OVERCHARGE_KEY_DIR=/path/to/secure/keys` before starting services. |

---

## 2. Common Operational Issues

### 2.1 "Chain Integrity: INVALID"
**Problem**: `python tools/ledger.py verify` reports invalid hash chain.  
**Diagnostic**:
```bash
python tools/ledger.py dump --broken-only
```
**Fix**: Inspect the row where hash link broke. If accidental manual edit occurred, restore `ledger.db` from backup.

### 2.2 Symlink Resolution in Sandboxes
**Problem**: Tests on restricted Windows sandboxes raise symlink escape warnings.  
**Resolution**: Overcharge Desk uses canonical realpath containment checks (`is_relative_to` or path traversal safeguards) rather than assuming symlink creation permissions.
