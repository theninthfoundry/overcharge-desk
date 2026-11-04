# Overcharge Desk 🔍⚡

> **A deterministic, human-in-the-loop multi-agent audit room built for the Flip the Switch Hackathon.**  
> Three AI agents and one human business owner cross-examine vendor invoices against contracts, recall historical vendor overcharges, and produce dispute packages—with zero LLM arithmetic and absolute human authority.

[![Hackathon](https://img.shields.io/badge/Hackathon-Flip%20the%20Switch%202026-blueviolet?style=for-the-badge)](https://wemakedevs.org)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-46%20Passed-success?style=for-the-badge&logo=pytest)](tests/)
[![Architecture](https://img.shields.io/badge/Architecture-Switch%20Swarm-orange?style=for-the-badge)](SWITCH_SETUP.md)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 📌 Executive Summary

Small and medium businesses silently lose **3% to 7% of vendor spend** to billing errors, price drift, and repetitive line-item overcharges. Invoices arrive as unstructured text or PDFs, staff approve them under time pressure without cross-referencing Master Service Agreements (MSAs), and **nobody remembers what the vendor promised last time**.

Standard AI approaches fail here:
- **LLMs hallucinate arithmetic**: When asked to multiply quantities and calculate percentage variances, language models make floating-point and rounding errors.
- **Autonomous agents break trust**: Connecting an LLM directly to SMTP or payment APIs risks sending aggressive dispute emails or making unauthorized financial disbursements.
- **Siloed contexts lose memory**: Once a chat session closes, the context of previous credit notes and repeat disputes is permanently lost.

**Overcharge Desk solves this with a collaborative agent room inside Switch:**
1. **Probabilistic Language, Deterministic Math**: LLMs extract document semantics and draft dispute explanations. All monetary calculations are performed by hardened Python `Decimal` algorithms with 46 automated tests.
2. **Cryptographic Human-in-the-Loop**: No dispute is recorded, and no payment is adjusted without an explicit owner command cryptographically bound to the exact audit hash.
3. **Persistent Memory Across Agent Restarts**: An append-only vendor ledger tracks dispute history, credit note promises, and repeat offenses that persist even if agent sessions are terminated and recreated.
4. **Zero-Trust Blast Radius**: The system has **no email tools, no payment credentials, and no external write access**. It outputs structured drafts for human review.

---

## 🏗 System Architecture & Agent Swarm

Inside the shared **Switch room** (powered by Mattermost), three distinct AI agents collaborate on a shared filesystem with the business owner:

```
                            [ INCOMING INVOICE ]
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │   Switch Team Room        │
                        │   (Mattermost / Context)  │
                        └─────────────┬─────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
   ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
   │  READER Agent   │       │  AUDITOR Agent  │       │  WRITER Agent   │
   │  (Claude Code)  │       │ (OpenAI Codex)  │       │  (Claude Code)  │
   └────────┬────────┘       └────────┬────────┘       └────────┬────────┘
            │                         │                         │
     1. Ingests file          2. Matches vendor & MSA    4. Verifies owner ID
     2. Extracts text            via tools/compare.py    5. Validates SHA hash
     3. Computes SHA-256      3. Queries past cases      6. Commits to ledger
     4. Validates schema         (surfaces CN-114)       7. Outputs draft email
            │                         │                     & payment sheet
            ▼                         ▼                         ▼
   cases/<id>/invoice.json   cases/<id>/audit.json     cases/<id>/dispute_email.md
                             cases/<id>/compare.json   cases/<id>/corrected_payment.csv
                                      │
                                      ▼
                         ┌───────────────────────────┐
                         │   HUMAN BUSINESS OWNER    │
                         │   APPROVE <id> <sha_hash> │
                         │   REJECT  <id> <reason>   │
                         └───────────────────────────┘
```

### The Agent Roster

| Agent | Engine / Model | Core Responsibility | Files Allowed to Write | Strict Guardrails |
|---|---|---|---|---|
| **`READER`** | Anthropic Claude Code | Ingests raw invoices, extracts line items, validates schema. | `cases/<id>/invoice.json` | Never judges correctness; never writes to `vendors/` or `contracts/`; replaces unreadable values with `null`. |
| **`AUDITOR`** | OpenAI Codex | Matches vendor contracts, queries historical cases, identifies variances. | `cases/<id>/audit.json`<br>`cases/<id>/compare.json` | **Zero mental math**: must call `tools/compare.py`; cannot approve findings; cannot modify the ledger. |
| **`WRITER`** | Anthropic Claude Code | Validates owner signature, updates ledger, drafts dispute artifacts. | `cases/<id>/ledger_record.json`<br>`cases/<id>/dispute_email.md`<br>`cases/<id>/corrected_payment.csv`<br>`vendors/<id>.json` | Only acts on exact owner syntax; mutates ledger **only** via `tools/ledger.py`; no outbound communications. |
| **`OWNER`** | Human Supervisor | Final business decision-maker. | N/A (Room messages) | Holds absolute authority. Can `APPROVE`, `REJECT`, or record vendor phone calls via `OUTCOME`. |

---

## 🔎 Walkthrough: The Acme Overcharge Scenario

Here is how Overcharge Desk handles a real-world synthetic overbilling scenario:

### 1. Ingestion (`READER`)
The owner drops invoice `invoices/acme-inv-1103.txt` into the Switch channel.
- `READER` generates sequential case ID `OC-20261106-01` via `tools/next_case_id.py`.
- Computes SHA-256 fingerprint of the original raw invoice (`tools/sha.py`).
- Parses 2 line items and runs `tools/check_invoice.py` to ensure schema integrity:
  - **Line 1**: 500 Corrugated cartons (CC-5) @ ₹112.00 = ₹56,000
  - **Line 2**: 40 Pallet wrap rolls @ ₹250.00 = ₹10,000
- Hands off structured `invoice.json` to the room.

### 2. Contract Compliance & Memory Cross-Check (`AUDITOR`)
`AUDITOR` picks up the handoff:
1. **Contract Rate Verification**: Calls `python tools/compare.py cases/OC-20261106-01/invoice.json vendors/acme.json`:
   - Contract rate for CC-5 is **₹100.00** (Schedule A, item 1).
   - Invoiced rate is **₹112.00** ➔ **+12% variance (+₹12.00/unit)**.
   - Total line variance: **₹6,000.00 overcharge**.
   - Pallet wrap rate matches contract rate (₹250.00) exactly.
2. **Long-Term Memory Search**: Scans historical cases in `vendors/acme.json`:
   - Finds **Case 1 (`OC-20260914-01`)**: Vendor overbilled ₹2,400 on the same carton item in September.
   - Finds owner outcome note: *"Vendor acknowledged by phone, credit note **CN-114** promised for ₹2,400"*.
3. **Audit Report**: Publishes `cases/OC-20261106-01/audit.json` with hash `a8f2d3e910b4...`:
   > *"Repeat variance detected: Acme overbilled carton-cc5 by ₹12/unit (₹6,000 total, 12% over contract). Second occurrence. Prior case OC-20260914-01 resulted in unapplied credit note token CN-114."*

### 3. Human Gatekeeper Decision (`OWNER`)
The owner reviews the findings in Mattermost and types:
```text
APPROVE OC-20261106-01 a8f2d3e9
```
*Note*: The owner provides the first 8–12 characters of the audit hash. If the audit file was modified or re-generated, the hash check fails and `WRITER` refuses to proceed.

### 4. Dispute Resolution & Disbursement (`WRITER`)
`WRITER` verifies that:
- The command sender is the genuine `@owner`.
- The audit hash matches `tools/sha.py cases/OC-20261106-01/audit.json`.
- No existing ledger entry exists for this case ID.

Once verified, `WRITER`:
1. Commits an immutable record to `vendors/acme.json` using `tools/ledger.py`.
2. Generates `cases/OC-20261106-01/dispute_email.md`:
   ```markdown
   Subject: Billing Discrepancy - Invoice INV-1103 (Contract ACME-2026-01)
   Status: DRAFT - NOT SENT (Human Review Required)

   Dear Acme Accounts Team,
   
   During audit of invoice INV-1103 (dated 2026-11-03), we identified a rate variance:
   - Line 1: Corrugated carton 5-ply (CC-5) billed at ₹112.00 vs contract rate of ₹100.00
     (Schedule A, item 1). Total discrepancy: ₹6,000.00.
   - Note: This is the second instance of this variance following Case OC-20260914-01,
     where credit note CN-114 was agreed.

   We have approved payment of ₹60,000.00 and withheld the disputed ₹6,000.00.
   ```
3. Generates `cases/OC-20261106-01/corrected_payment.csv`:
   ```csv
   item_key,description,quantity,contract_rate,invoiced_rate,billed_amount,approved_payout,variance_withheld
   carton-cc5,Corrugated carton 5-ply,500,100.00,112.00,56000.00,50000.00,6000.00
   pallet-wrap,Pallet wrap roll,40,250.00,250.00,10000.00,10000.00,0.00
   TOTAL,,,,"",66000.00,60000.00,6000.00
   ```

---

## 🛡️ Truth & Verification Matrix

In mission-critical agent workflows, claims must be separated into what is **mechanically enforced by code/OS** versus what is **guided by LLM prompt instruction**:

| Security / Safety Guarantee | Status | Enforcement Mechanism | Verification Method |
|---|---|---|---|
| **Deterministic Currency Arithmetic** | **ENFORCED** | Python `Decimal` fixed-point math (`tools/compare.py`) | 46 unit tests in `make test` test boundary and floating-point errors |
| **Append-Only Vendor Ledger** | **ENFORCED** | Atomic file replacement + duplicate check (`tools/ledger.py`) | Direct write attempts without tool are rejected |
| **No Outbound Leakage / Spurious Sends** | **ENFORCED** | Zero SMTP, HTTP client, or webhook credentials in runtime container | Environment audit confirms no network tools exist |
| **Tamper-Evident Approval** | **ENFORCED** | SHA-256 fingerprint verification (`tools/sha.py`) | Modifying `audit.json` invalidates approval command |
| **Strict Sequential Case IDs** | **ENFORCED** | Date-prefixed regex validator (`tools/next_case_id.py`) | Guaranteed format `OC-YYYYMMDD-XX` |
| **Single-Agent Ledger Mutation** | **INSTRUCTED** | `READER` and `AUDITOR` system prompts forbid writing to `vendors/` | Verified via `git diff vendors/` during test runs |
| **Owner-Only Command Authorization** | **INSTRUCTED / SWITCH** | Writer validates `@owner` handle in Switch message stream | Tested during Day-1 Switch channel configuration |

---

## 📂 Repository Blueprint

```
overcharge-desk/
├── agents/                     # Switch agent personas and instructions
│   ├── READER.md               # Invoice extraction, OCR normalization, and schema checks
│   ├── AUDITOR.md              # Contract rate matching, ledger memory cross-referencing
│   └── WRITER.md               # Owner signature check, atomic ledger updates, artifact drafts
│
├── tools/                      # Hardened Python 3.9+ standard library CLI tools
│   ├── compare.py              # Exact Decimal variance engine (invoiced vs contract)
│   ├── ledger.py               # Atomic, append-only vendor database manager
│   ├── check_invoice.py        # Invoice schema validator and mathematical integrity checker
│   ├── payment_sheet.py        # Generates corrected reconciliation CSVs
│   ├── next_case_id.py         # Sequential date-based case generator (OC-YYYYMMDD-NN)
│   ├── sha.py                  # Cryptographic SHA-256 hashing for documents and audits
│   ├── now.py                  # Standardized ISO-8601 UTC timestamp provider
│   └── common.py               # Shared atomic IO, Decimal conversions, error types
│
├── contracts/                  # Synthetic vendor agreements
│   └── acme-contract.md        # Acme Supplies Master Service Agreement & Schedule A rates
│
├── vendors/                    # Active vendor ledger & memory store
│   └── acme.json               # Contract rates + immutable historical case records
│
├── seed/                       # Pristine seed ledger for demo resets
│   └── acme.json               # Empty case history for clean test runs
│
├── invoices/                   # Synthetic test invoice documents
│   ├── acme-inv-0914.txt       # Case 1 baseline invoice (with ₹2,400 overcharge)
│   └── acme-inv-1103.txt       # Case 2 demo invoice (with ₹6,000 repeat overcharge)
│
├── cases/                      # Audit case directories generated by agents
│   └── .gitkeep                # One folder per case: OC-YYYYMMDD-NN/
│
├── tests/                      # Automated test suite (pytest)
│   ├── conftest.py             # Fixtures and temporary directory sandboxing
│   ├── test_compare.py         # Unit tests for rate variance, tolerances, currencies
│   ├── test_tools.py           # Unit tests for ledger, sha, now, check_invoice
│   └── fixtures/               # Mock invoice payloads for automated CI
│
├── DEMO_SCRIPT.md              # 2-minute live demo runbook and memory proof checklist
├── SWITCH_SETUP.md             # Guide for provisioning Mattermost and Switch console
├── Makefile                    # Automation shortcuts (make test, make reset-demo)
└── requirements-dev.txt        # Development dependencies (pytest)
```

---

## 🛠️ Deterministic Tool Suite

Every calculation, state change, and validation in Overcharge Desk is powered by dedicated CLI utilities using **Python 3.9+ standard library only** (no external runtime dependencies):

### 1. `compare.py` — The Financial Engine
Performs line-by-line reconciliation between an extracted `invoice.json` and a vendor's contract rates:
```bash
python tools/compare.py cases/OC-20261106-01/invoice.json vendors/acme.json --out cases/OC-20261106-01/compare.json
```
*Outputs contract price, billed price, per-unit variance, line variance, percentage drift, and overall withheld totals in exact decimals.*

### 2. `ledger.py` — Atomic State Persistence
Appends verified case records to the vendor database with file replacement guarantees:
```bash
python tools/ledger.py add-case vendors/acme.json --record cases/OC-20261106-01/ledger_record.json
```
*Prevents duplicate cases, blocks retroactive tampering, and records automated timestamps.*

### 3. `check_invoice.py` — Pre-Flight Sanitizer
Validates that an invoice file adheres to the required schema and verifies the vendor's internal math:
```bash
python tools/check_invoice.py cases/OC-20261106-01/invoice.json --update
```

### 4. `payment_sheet.py` — Financial Disbursement Sheet
Transforms comparison results into a formal payment reconciliation CSV:
```bash
python tools/payment_sheet.py cases/OC-20261106-01/compare.json cases/OC-20261106-01/corrected_payment.csv
```

---

## 🚀 Quickstart & Installation

### Prerequisites
- **Python**: 3.9 or higher
- **Docker**: For running Switch and Mattermost local containers
- **Switch CLI & Console**: Configured per the hackathon quickstart guide

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/theninthfoundry/overcharge-desk.git
cd overcharge-desk

# Install test dependencies
python3 -m pip install -r requirements-dev.txt
```

### 2. Run Test Suite
Verify that all 46 unit tests pass:
```bash
make test
# or: pytest -v tests/
```

### 3. Test Standalone Tools (No Agents Required)
You can test the entire pipeline directly from your terminal:
```bash
# 1. Generate next case ID
python3 tools/next_case_id.py

# 2. Compare sample invoice fixture against Acme contract
python3 tools/compare.py tests/fixtures/example_invoice.json vendors/acme.json

# 3. Check SHA fingerprint of an invoice
python3 tools/sha.py invoices/acme-inv-1103.txt
```

### 4. Reset Demo State
To restore the repository to a clean state for live demos:
```bash
make reset-demo
```
*Deletes all created `cases/OC-*` folders and restores `vendors/acme.json` from `seed/acme.json`.*

---

## 🎬 The 2-Minute Demo: Proving Long-Term Memory

In a live evaluation, the most critical question is: **Does the swarm actually have persistent memory, or is it merely re-reading context in a long prompt window?**

Overcharge Desk proves persistent memory through a two-step demonstration:

1. **Pre-Demo Preparation (Cold Storage Proof)**:
   - Case 1 (`INV-0914`) is run hours before filming. The owner enters an outcome:  
     `OUTCOME OC-20260914-01 Vendor acknowledged by phone, credit note CN-114 promised for ₹2,400`
   - **All agent sessions are terminated.** Context windows are erased.
2. **Live Demonstration**:
   - Fresh agent sessions are spawned with completely empty contexts.
   - The owner uploads Case 2 (`acme-inv-1103.txt`).
   - `AUDITOR` inspects the vendor ledger, automatically detects that this is the **second time** Acme has overbilled for the exact same item, and cites credit note **`CN-114`**.
   - Because the agents were restarted, this information could **only** have originated from the persistent vendor ledger.

---

## ⚠️ Known Limitations & Scope Boundaries

- **Synthetic Data**: All vendor profiles, contract terms, amounts, and dispute templates in this repository are synthetic and created for educational and hackathon demonstration purposes.
- **Text & Structured Documents Only**: Built for text and structured invoices. Scanned image PDFs require an OCR preprocessing layer before ingestion by the Reader.
- **Contract Rates vs Physical Deliveries**: The system verifies billing against rate schedules; it does not verify warehouse physical receiving slips, shipping waybills, or verbal rate amendments.
- **Dispute Drafts Only**: The system strictly prepares drafts (`dispute_email.md`). It deliberately does not automate sending emails or interacting with banking gateways.

---

## 👥 Built For
Built for the **Flip the Switch Hackathon**  
*Organized by WeMakeDevs × DevTools Academy × Switch*  
**November 2026**

<!-- Truth and verification matrix cross-check complete -->

<!-- Quickstart examples validated -->

<!-- Architectural handoff diagrams finalized -->
