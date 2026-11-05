# Overcharge Desk — Identity & Access Security Specification

> **Status**: Production Security Baseline (Phase 3.2)  
> **Audience**: Security Engineers, System Administrators, Compliance Auditors

This document details the identity, authentication, credential storage, and session management architecture in Overcharge Desk.

---

## 1. Password Storage & Hashing Architecture

Overcharge Desk strictly forbids plaintext passwords, unsalted digests, and general-purpose hash algorithms (e.g., MD5, plain SHA-256, SHA-512) for user authentication.

### 1.1 Primary Hasher: Argon2id
All user passwords are hashed using **Argon2id**, the winner of the Password Hashing Competition (PHC) and the gold standard for resisting GPU/ASIC hardware attacks and side-channel timing attacks.

- **Parameters**:
  - Memory cost ($m$): $65,536\text{ KiB}$ ($64\text{ MB}$)
  - Time cost ($t$): $3\text{ iterations}$
  - Parallelism ($p$): $4\text{ threads}$
  - Salt: $16\text{ bytes}$ generated via OS cryptographically secure pseudorandom number generator (`os.urandom`)
- **Encoding**: PHC-compliant string format `$argon2id$v=19$m=65536,t=3,p=4$...`

### 1.2 Zero-Dependency Fallback & Automatic Rehash
If the native `argon2` module is not present in a minimalist runtime, the system falls back to **PBKDF2-HMAC-SHA256**:
- **Iterations**: $600,000\text{ rounds}$ (matching OWASP recommendations)
- **Salt**: $16\text{ bytes}$
- **Rehash Policy**: `needs_rehash(password_hash)` evaluates whether an existing hash matches the current desired Argon2id parameters. When a user authenticates successfully with an older PBKDF2 hash, their hash is immediately, transparently upgraded to Argon2id in the database.

### 1.3 Input Bounds & Denial-of-Service Defense
Password inputs are bounded between **8 characters minimum** and **1024 characters maximum**. Extremely large payloads are rejected at the schema boundary before hashing to prevent CPU-exhaustion denial-of-service attacks.

---

## 2. Session Management & Opaque Tokens

### 2.1 Cryptographic Opaque Bearer Tokens
Rather than transmitting serialized signed tokens (such as JWTs) that share secret keys or expose claims to client modification, Overcharge Desk uses **opaque bearer tokens**:
- Generated with $32\text{ bytes}$ ($256\text{ bits}$) of high-entropy randomness (`secrets.token_urlsafe(32)`).
- **Hashed Storage**: Raw tokens are **never stored in the database**. The system persists only `hashlib.sha256(raw_token.encode("utf-8")).hexdigest()`.
- A database leak cannot compromise active user sessions without cracking 256-bit entropy.

### 2.2 Session Lifecycle & Revocation
- **TTL**: Sessions expire 24 hours after creation.
- **Revocation**: Calling `POST /api/v1/auth/logout` immediately deletes the session record from SQLite, rendering subsequent requests with that token instantly invalid.
- **Database Engine**: The user and session store is hosted in SQLite configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and foreign key constraints enabled.

---

## 3. Brute-Force & Enumeration Defenses

### 3.1 Rate Limiting & Account Lockout
- **Threshold**: 5 consecutive failed authentication attempts within a rolling 5-minute window will lock out further login attempts for that username/client.
- **Response**: The API returns `HTTP 429 Too Many Requests` with a generic lockout notice.

### 3.2 Generic Error Messages
All authentication failures return an identical generic response:
```json
{
  "detail": "Invalid username or password"
}
```
The API never indicates whether a supplied username exists, thwarting user enumeration attacks.

---

## 4. Secure Administrator Bootstrapping

Production deployments must never rely on hardcoded default credentials.

### 4.1 CLI Bootstrap Tool
Initial system administrators are provisioned using the dedicated CLI tool:
```bash
python -m tools.bootstrap_admin --username <admin_username>
```
- Prompts interactively for a secure password using `getpass` with verification.
- Prohibits creating duplicate active administrator accounts without explicit flags.
- By default, demo accounts (`operator`, `reviewer`, `approver`, `auditor`, `pay_operator`) are **not seeded**.
- Development environments can explicitly pass `--seed-demo` to provision test personas.

### 4.2 Production Safety Gate
At server startup, `IdentityRepository.check_production_safety()` executes:
- When `APP_ENV=production`:
  - If any active account has `is_demo = 1` or demo usernames (`admin`, `operator`, `reviewer`, `approver`, `auditor`, `pay_operator`) with default credentials, startup fails immediately (`ToolError`, exit code 4).

