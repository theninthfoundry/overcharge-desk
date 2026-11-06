# SWITCH_SETUP — Overcharge Desk Multi-Agent Deployment

Follow the organisers' quickstart for the exact Switch install and Console
steps. This document specifies the deployment and configuration steps for
operating Overcharge Desk inside a Switch / Mattermost multi-agent environment.

---

## 0. Hackathon & Engineering Rules

- The Switch setup and workflow are built for the **Flip the Switch Hackathon (Nov 4 to Nov 7, 2026)**.
- Commits are made progressively with transparent, test-verified milestones.
- Synthetic commercial invoices and vendor contracts are used exclusively.
- Permanent engineering invariants in `AGENTS.md` apply to all agents.

---

## 1. Environment & Pre-requisites

- [x] Docker installed and running for Mattermost and Switch runtime.
- [x] Python 3.9–3.13 installed. Full test suite passing (**260 automated tests**).
- [x] Switch Console initialized with Mattermost team channel `#overcharge-desk`.
- [x] AI Agent CLI engines provisioned (Claude Code and OpenAI Codex).
- [x] Repository cloned into shared agent working directory.

---

## 2. Architecture: Multi-Agent Workspace

All three AI agents run in the **same workspace clone**, communicating and coordinating
through Switch / Mattermost messages and driving the deterministic financial engine via `tools/desk.py`:

```
                 Mattermost Room (#overcharge-desk)
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
    [ READER AGENT ]     [ AUDITOR AGENT ]     [ WRITER AGENT ]
    (tools/desk.py        (tools/desk.py        (tools/desk.py
     intake)               audit, history)       finalize)
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 ▼
                    [ DETERMINISTIC ENGINE ]
                  Exact Decimals | Stage 8 Math
                                 │
                                 ▼
                    [ HUMAN APPROVAL GATE ]
               (tools/approve.py via Owner TTY)
```

---

## 3. Creating the Switch Room & Agent Roles

1. **Create the Mattermost Channel**: `#overcharge-desk`.
2. **Add Participants**:
   - `@owner`: Business financial owner account (human approver).
   - `@reader`: Reader agent (intake & evidence preservation).
   - `@auditor`: Auditor agent (contract audit & vendor history).
   - `@writer`: Writer agent (settlement & dispute generation).
3. **Configure Instructions in Switch Console**:
   - For Reader: Paste contents of `agents/READER.md`.
   - For Auditor: Paste contents of `agents/AUDITOR.md`.
   - For Writer: Paste contents of `agents/WRITER.md`.
4. **Set Working Directory**: Point all agents to the root of this repository.

---

## 4. Operational Workflow & Approval Protocol

1. **Intake**:
   - Owner drops invoice in `#overcharge-desk`.
   - Reader runs `python tools/desk.py intake invoices/<invoice> seed/<vendor>.json`.
   - Reader computes source SHA-256 and registers evidence.
2. **Audit & Memory Moment**:
   - Auditor runs `python tools/desk.py audit <case_id>`.
   - Auditor runs `python tools/desk.py history --vendor <vendor_id>` to recall past cases and outcomes.
   - Auditor reports full 64-character hashes and financial findings in the room.
3. **Unforgeable Human Approval**:
   - Owner runs interactive terminal script:
     ```bash
     python tools/approve.py <case_id>
     ```
   - Enforces interactive TTY and prompts for owner password (Argon2id verification).
   - Prints 64-character receipt hash; owner copies the notification into the room.
4. **Finalization & Settlement**:
   - Writer runs `python tools/desk.py finalize <case_id>`.
   - Script verifies the cryptographic receipt signature and generates `cases/<case_id>/corrected_payment.csv`.
   - Writer drafts dispute email and posts confirmation to the room.

---

## 5. Verification Checks

Run these checks to confirm proper configuration:
- [x] **TTY Gate**: Running `python tools/approve.py <case_id>` from a pipe or subshell fails closed (code 4).
- [x] **Agent Approval Block**: Running `python tools/desk.py approve` fails (subcommand does not exist).
- [x] **Token Minting Lockdown**: Running `python tools/auth.py issue-token owner` fails closed without `--dev`.
- [x] **Key Isolation**: No `.key` or `keys_manifest.json` files reside in `config/` or repository tree.
- [x] **Full Hashes**: Audit reports emit full 64-character digests (no truncated prefixes).
- [x] **Vendor History**: `tools/desk.py history --vendor acme` returns historical cases and withheld variances.

---

## 6. Full Test Suite Execution

```bash
# Execute complete unit, integration, and security test suite
python -m pytest -v
```

---

## 7. Standalone Switch Multi-Agent Simulator

For local rehearsal, judging demonstration, or running the multi-agent room without Docker:

```bash
# Run realistic terminal simulation of the #overcharge-desk Switch room
python tools/simulate_switch.py

# Or run instantly without typing delays
python tools/simulate_switch.py --fast
```

This tool steps through the 4-turn multi-agent collaboration in real time with styled terminal badges, executing actual deterministic tools (`tools/desk.py intake`, `audit`, `history`, `approve.py`, `finalize`) and verifying SQLite ledger chain integrity.
