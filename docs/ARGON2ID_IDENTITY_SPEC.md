# Argon2id Password Hashing & Identity Architecture

> **Security Baseline**: RFC 9106 Recommended Parameters  
> **Package**: `argon2-cffi`  
> **Invariant**: Invariant Rule 6.1 (Memory-hard Credential Storage)

---

## 1. Security Rationale

Standard cryptographic hashes (SHA-256, SHA-512) and fast message digests are unsuitable for user authentication because modern GPUs can compute billions of SHA-256 hashes per second, making dictionary and brute-force attacks trivial.

Overcharge Desk implements **Argon2id** (the hybrid variant of Argon2), which offers:
1. **Memory Hardness**: Requires significant RAM (64 MiB per hash), defeating ASIC and GPU-parallelized attacks.
2. **Side-Channel Resistance**: Combines data-independent memory access (Argon2i) with data-dependent memory access (Argon2d) to resist cache-timing attacks.

---

## 2. Parameter Configuration

Overcharge Desk configures Argon2id according to RFC 9106 standards:

| Parameter | Value | Rationale |
| :--- | :--- | :--- |
| **Type** | `Argon2id` | Standard hybrid mode offering side-channel and tradeoff resistance. |
| **Memory Cost ($m$)** | `65536` KiB (64 MiB) | Prevents efficient massive-scale parallelism in GPU hardware. |
| **Time Cost ($t$)** | `3` iterations | Provides adequate latency budget (~150ms) per password verification. |
| **Parallelism ($p$)** | `4` threads | Scales across multi-core processors. |
| **Hash Length** | `32` bytes | Cryptographically strong digest length. |
| **Salt Length** | `16` bytes | Random CSPRNG salt generated per password. |

---

## 3. Separation of Duties Matrix

Overcharge Desk defines explicit roles enforcing separation of duties:

| Role | Intake Invoice | Run Rate Audit | Query History | Issue Settlement Receipt | Release Payment |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `auditor` | Yes | Yes | Yes | **No** | **No** |
| `admin` | Yes | Yes | Yes | **No** | Yes |
| `approver` | No | Yes | Yes | **Yes** | **No** |
| `owner` | Yes | Yes | Yes | **Yes** | Yes |

### 3.1 Two-Man Rule for Approvals
An auditor who prepares the audit verification cannot sign off as the approver. The approval signature must be issued by a separate verified human identity with `approver` or `owner` privileges.

---

## 4. Key Management & Environment Isolation

In production environments:
1. The HMAC signing key and private credentials must reside outside the repository root via `OVERCHARGE_KEY_DIR`.
2. Under Invariant Rule 6.1, if `OVERCHARGE_KEY_DIR` is not set in production mode, the application fails closed rather than falling back to in-repo insecure keys.
3. The interactive CLI tool `tools/approve.py` checks `sys.stdin.isatty()` to ensure an interactive human operator is entering credentials.
