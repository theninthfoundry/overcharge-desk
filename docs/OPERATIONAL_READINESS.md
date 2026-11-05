# Overcharge Desk — Operational Readiness & Reliability Guide

> **Status**: Production Operational Baseline (Phase 3.2)  
> **Audience**: Site Reliability Engineers (SRE), Operations Leads, System Administrators

This guide provides operational specifications, health monitoring protocols, and standard operating procedures for Overcharge Desk.

---

## 1. System Health Monitoring Architecture

Overcharge Desk exposes a multi-dimensional health probe at `GET /api/v1/health`.

### 1.1 Probing States
The health endpoint returns HTTP 200 with structured status information:

- **`READY`**:
  - All critical subsystems are operational.
  - The SQLite identity database is accessible and passed safety verification.
  - The active signing key is verified and accessible on disk.
  - The case storage directory is writeable and accessible.
  - Safe for load balancers to route live user traffic.
- **`DEGRADED`**:
  - One or more critical subsystems encountered an error (e.g. signing key missing, database lock, storage permission error).
  - `is_ready` evaluates to `false`.
  - Orchestrators (e.g. Kubernetes, AWS ECS) should stop routing traffic to this replica until the condition clears.

### 1.2 Health Response Schema
```json
{
  "status": "READY",
  "is_ready": true,
  "service": "overcharge-desk-api",
  "version": "3.2.0",
  "environment": "production",
  "checks": {
    "identity_database": "OK",
    "signing_key": "OK (key-20261105-a8f2)",
    "storage": "OK"
  }
}
```

---

## 2. Request Correlation & Distributed Tracing

Every inbound HTTP request receives or inherits an `X-Request-ID`:
- If provided by a reverse proxy (e.g. Envoy, NGINX, Cloudflare), the upstream ID is preserved.
- If omitted, a fresh 32-character hexadecimal UUID is generated.
- The `X-Request-ID` is echoed back in the response headers and attached to every ledger write, log line, and error event.

---

## 3. Standard Operating Procedures (SOPs)

### 3.1 Initial Production Bootstrapping
1. Set environment: `export APP_ENV=production`.
2. Generate signing key:
   ```bash
   python -c "import secrets; from pathlib import Path; Path('config/signing.key').write_text(secrets.token_hex(32))"
   chmod 600 config/signing.key
   ```
3. Provision the primary system administrator:
   ```bash
   python -m tools.bootstrap_admin --username primary_admin
   ```
4. Start the API gateway:
   ```bash
   uvicorn services.api.main:app --host 0.0.0.0 --port 8000
   ```

### 3.2 Signing Key Rotation
To rotate the HMAC signing key without invalidating past receipts:
```python
from domain.identity.key_manager import KeyManager

km = KeyManager(config_dir="config")
new_meta = km.rotate_key()
print(f"Activated key {new_meta.key_id}; prior key retired.")
```

### 3.3 Verifying Audit Ledger Integrity
To verify the tamper-evident cryptographic hash chain of the system audit ledger:
```bash
python tools/verify_ledger.py
```
Output:
```json
{
  "valid": true,
  "total_events": 28,
  "issues_count": 0,
  "head_hash": "9c6a378f7887e43b89498bcbd6b7e254bcab36d483a1a986366081c5696b0306"
}
```

### 3.4 Executing Canonical Benchmark Verification
To execute all 6 benchmark cases and certify financial calculations:
```bash
python tools/run_demo_suite.py --clean
```
All cases must report `PASSED`.
