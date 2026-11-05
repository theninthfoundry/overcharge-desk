# REST API Reference Guide

> **Base URL**: `http://localhost:8000/api/v1`  
> **Authentication**: HTTP Bearer JWT (`Authorization: Bearer <token>`)  
> **Format**: JSON (Strict string-formatted exact decimals)

---

## 1. Authentication Endpoints

### 1.1 `POST /auth/login`
Authenticates a user identity against the Argon2id persistent store.

**Request**:
```json
{
  "username": "owner",
  "password": "owner_secure_password"
}
```

**Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "username": "owner",
    "role": "owner"
  }
}
```

### 1.2 `GET /auth/me`
Returns current authenticated identity and permissions.

---

## 2. Health & Monitoring

### 2.1 `GET /health`
Returns system operational status and dependencies.

**Response (200 OK)**:
```json
{
  "status": "HEALTHY",
  "version": "3.3.0",
  "database": "CONNECTED",
  "ledger_chain": "VALID",
  "signing_key_configured": true
}
```

---

## 3. Case Lifecycle Endpoints

### 3.1 `GET /cases`
Lists all cases with status, vendor, and amounts.

### 3.2 `POST /cases`
Creates a new invoice case.

### 3.3 `GET /cases/{case_id}`
Returns full case metadata, original stated amounts, and current state.

### 3.4 `POST /cases/{case_id}/audit`
Executes deterministic rate verification against contract Schedule A.

**Response (200 OK)**:
```json
{
  "case_id": "OC-20261106-01",
  "status": "AUDITED",
  "stated_total": "66000.00",
  "verified_total": "60000.00",
  "variance": "6000.00",
  "discrepancies": [
    {
      "item": "Industrial Widget A",
      "billed_rate": "3300.00",
      "contract_rate": "3000.00",
      "variance": "6000.00"
    }
  ]
}
```

### 3.5 `POST /cases/{case_id}/approve`
Records owner approval. Requires `owner` or `approver` role.

### 3.6 `POST /cases/{case_id}/finalize`
Releases the corrected payment CSV disbursement. Requires verified approval receipt.

