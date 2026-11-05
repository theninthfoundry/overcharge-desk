# Overcharge Desk — Hackathon Submission & Judging Brief

> **Project Name**: Overcharge Desk — Evidence-First Vendor Reconciliation  
> **Platform**: Switch Multi-Agent Orchestration & Mattermost  
> **Repository**: [https://github.com/theninthfoundry/overcharge-desk](https://github.com/theninthfoundry/overcharge-desk)  
> **Certified Test Baseline**: 236 Automated Tests Passing (Windows & Ubuntu Matrix)

---

## 1. Executive Summary

Every enterprise loses 3% to 7% of indirect procurement spend to vendor billing drift: contract rates silently reverting to list prices, unapplied credit notes, arithmetic errors, and uncontracted items slipping through Accounts Payable.

Autonomous AI agents could audit every invoice, but giving LLMs autonomous payment authority creates catastrophic financial risk (prompt injections, hallucinations, unauthorized disbursements).

**Overcharge Desk solves this with an unforgeable Separation of Duties**:
- **3 Autonomous Agents** (Intake, Auditor, Settlement) coordinate in Switch `#overcharge-desk`.
- **Zero Payment Authority for Agents**: The unified `tools/desk.py` agent CLI provides `intake`, `audit`, `history`, and `finalize`—**it omits `approve` entirely**.
- **Human Interactive Authorization Gate**: The finance owner approves via `tools/approve.py`, requiring an interactive TTY and memory-hard Argon2id password verification.
- **Fail-Closed Settlement**: `desk.py finalize` cryptographically validates the HMAC-SHA-256 receipt before releasing `corrected_payment.csv`.

---

## 2. Core Technical Architecture & Invariants

```
┌────────────────────────────────────────────────────────┐
│             Switch Mattermost Channel                  │
│               (#overcharge-desk)                       │
└───────┬──────────────────────┬──────────────────┬──────┘
        │                      │                  │
        ▼                      ▼                  ▼
┌──────────────┐       ┌──────────────┐   ┌──────────────┐
│ Intake Agent │       │Auditor Agent │   │Settle Agent  │
└───────┬──────┘       └───────┬──────┘   └───────┬──────┘
        │                      │                  │
        ▼                      ▼                  ▼
┌────────────────────────────────────────────────────────┐
│            Unified Agent CLI (tools/desk.py)           │
│       intake  │  audit  │  history  │  finalize        │
│          (Strictly NO approve subcommand)              │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│            Deterministic Financial Engine              │
│       100% decimal.Decimal  │  0% IEEE 754 float       │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│           Tamper-Evident SQLite Ledger                 │
│         Cryptographic Linear Hash Chain                │
└──────────────────────────▲─────────────────────────────┘
                           │
         ┌─────────────────┴─────────────────┐
         │ Interactive TTY Human Owner Gate  │
         │         (tools/approve.py)        │
         │  Argon2id Auth + 64-char Binding  │
         └───────────────────────────────────┘
```

### Key Engineering Invariants
1. **Financial Precision**: 100% `decimal.Decimal`, per-line `ROUND_HALF_UP` quantization.
2. **Zero Hallucination of History**: Historical recall checks past verified cases deterministically via `desk.py history --vendor <name>`.
3. **Fail-Closed Security**: Missing files, tampered hashes, arithmetic discrepancies, or non-TTY execution cause immediate non-zero refusal.
4. **Honest Boundaries**: In-depth transparency regarding single-OS-user vs container isolation.

---

## 3. Five-Minute Verification for Judges

### 3.1 1-Command Rehearsal & Live Switch Simulator
To experience the entire multi-agent dialogue in terminal with ANSI styling:
```bash
python tools/simulate_switch.py
```

### 3.2 1-Command System Benchmark & Ledger Audit
```bash
python tools/quickstart.py
```

### 3.3 Verify Full Test Suite
```bash
python -m pytest -q
```
*Expected Result*: 236 passed, 0 failures.

### 3.4 Verify Cryptographic Hash Chain
```bash
python tools/audit_ledger.py verify
```
*Expected Result*: `Chain Integrity: VALID (Unbroken Genesis Anchor)`.
