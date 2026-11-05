# STRIDE Threat Model & Security Controls

> **Scope**: Overcharge Desk System, Multi-Agent Coordination, and Financial Ledger  
> **Methodology**: Microsoft STRIDE Threat Modeling Framework

---

## 1. Threat Analysis Matrix

| STRIDE Category | Specific Attack Vector | Target Asset | Architectural Mitigation | Residual Risk |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | Autonomous LLM agent poses as finance owner (`@owner`) in chatroom or invokes CLI. | Payment approval gate | `tools/approve.py` requires interactive TTY (`sys.stdin.isatty()`) and Argon2id password verification. Agents cannot type passwords in headless subshells. | Single-OS-user process memory access if not containerized (honestly documented). |
| **Tampering** | Rogue process or compromised agent modifies `compare.json` to alter payable amount. | Calculation artifacts | Artifacts are cryptographically hashed at intake and verification. Hash parity is verified fail-closed before approval and payment. | OS filesystem corruption requires restoring from backup. |
| **Repudiation** | Finance approver denies approving a withholding or settlement. | Audit trail | Every approval event produces an HMAC-SHA-256 receipt committed to the linear hash chain in SQLite with timestamp and actor ID. | Loss of private signing key. |
| **Information Disclosure** | LLM prompt leaks private keys or credentials. | Signing keys | Keys reside strictly outside repo directory (`OVERCHARGE_KEY_DIR`); no keys committed to git. | Insecure permissions on key directory. |
| **Denial of Service** | Malicious input with 10MB password to exhaust Argon2id hashing resources. | Identity service | Strict input bounds checking (8–1024 characters) enforced at API and CLI boundaries. | Resource exhaustion under DDoS. |
| **Elevation of Privilege** | Agent invokes `desk.py approve` to bypass human gate. | Final disbursement | `tools/desk.py` architecturally omits the `approve` subcommand entirely. Payment release strictly requires external receipt. | None at CLI layer. |

---

## 2. Invariant Verification

All threat mitigations are validated via automated regression tests in:
- `tests/test_approve_cli.py`
- `tests/test_desk_cli.py`
- `tests/test_tamper_evidence.py`
- `tests/test_auth_lockdown.py`
