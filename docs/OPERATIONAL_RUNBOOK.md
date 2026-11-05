# Operational Runbook: Deployment, Key Rotation & Incident Response

> **Target Audience**: Financial Operations Engineers & System Administrators  
> **Classification**: Internal Operational Procedure

---

## 1. Production Deployment Prerequisites

Before processing live vendor invoices:
1. **Configure Isolated Key Directory**:
   ```bash
   export OVERCHARGE_KEY_DIR="/var/secure/overcharge/keys"
   mkdir -p "$OVERCHARGE_KEY_DIR"
   chmod 700 "$OVERCHARGE_KEY_DIR"
   ```
2. **Provision Production Identities**:
   Initialize the persistent SQLite identity store with unique administrator credentials. Never use demo passwords in production.
3. **Execute Baseline Certification**:
   ```bash
   python -m pytest -q
   python tools/quickstart.py
   ```

---

## 2. Key Management & Rotation Procedure

Overcharge Desk uses cryptographic signatures for owner approval receipts. Periodic key rotation follows this protocol:

### Step 1: Generate New Keypair / Secret
```bash
python -c "import secrets; print(secrets.token_hex(32))" > "$OVERCHARGE_KEY_DIR/signing_key_2026_q4.key"
chmod 600 "$OVERCHARGE_KEY_DIR/signing_key_2026_q4.key"
```

### Step 2: Update Active Key Pointer
Update the environment variable or symlink pointing to the current active signing key:
```bash
ln -sf "$OVERCHARGE_KEY_DIR/signing_key_2026_q4.key" "$OVERCHARGE_KEY_DIR/active_signing.key"
```

### Step 3: Archive Historical Keys
Historical keys must be preserved in read-only mode so historical receipts and audits remain deterministically verifiable.

---

## 3. Incident Response Playbooks

### 3.1 Playbook A: Ledger Tampering Alert (`CHAIN_INTEGRITY_FAIL`)
- **Symptom**: `python tools/ledger.py verify` exits with non-zero status.
- **Action**:
  1. Immediately quarantine the affected instance from processing further disbursements.
  2. Locate the event ID where `prev_hash != computed_hash`.
  3. Compare against verified off-site cold storage ledger replicas.
  4. File a security audit ticket with the event timestamp and actor ID.

### 3.2 Playbook B: Evidence Hash Mismatch (`EVIDENCE_TAMPERING_DETECTED`)
- **Symptom**: `tools/desk.py audit` or `tools/approve.py` fails with hash discrepancy.
- **Action**:
  1. Inspect the case directory `cases/<case_id>/`.
  2. Check if a human operator or process touched `compare.json` or `raw_invoice.txt`.
  3. Re-run `tools/desk.py intake` to create a new case if the source was legitimate, or reject the case as contaminated.

