# Overcharge Desk

A small team room where three AI agents and one human owner check a vendor
invoice against the contract, remember what that vendor did last time, and
produce a draft dispute email and a corrected payment sheet. Nothing is ever
sent, and the owner makes the only decision.

Built for the **Flip the Switch Hackathon** (WeMakeDevs x DevTools Academy x Switch).
**All vendors, contracts, invoices and amounts here are synthetic.**

## The problem

Small businesses pay invoices that nobody compares with the contract, and
nobody remembers whether the same vendor made the same mistake before.

## How it works

```
 Owner drops an invoice in the Mattermost room
        │
   [Switch room: shared context, roles, history]
        │
  READER ──► AUDITOR ──► (owner decides) ──► WRITER
  extracts   compares to    APPROVE / REJECT     records the decision,
  the data   contract +     with the audit       drafts the email and
             vendor history hash                 the payment sheet
```

| Agent | Job | May write |
|---|---|---|
| Reader | Turns the invoice into `invoice.json` | `cases/<id>/invoice.json` |
| Auditor | Compares to the contract and the vendor's history, with evidence | `cases/<id>/audit.json`, `compare.json` |
| Writer | Records the owner's decision, drafts the email and sheet | `ledger_record.json`, email, sheet, and the ledger **only through `tools/ledger.py`** |

The models read documents and explain findings. They never do arithmetic:
`tools/compare.py` does all the money maths in exact decimals.

## Where Switch fits

Switch is the room the agents and the owner share: hand-offs between agents
(a Claude Code agent and a Codex agent), the owner's decision in the same
timeline, and per-agent instructions. Without it these are three isolated
terminals.

What would *not* break without Switch: `vendors/acme.json` is a plain file, so
the vendor history itself survives. The README says so because it is true.
The demo proves the memory by restarting the agents and having the new
sessions find the earlier case (including a unique credit-note number) in the
ledger. See `DEMO_SCRIPT.md`.

## What is enforced, and what is only instructed

| Claim | Status |
|---|---|
| Money arithmetic is deterministic and tested | **Enforced** by `tools/compare.py` and 46 tests (`make test`) |
| Ledger is append-only, timestamps are tool-made, no overwrites | **Enforced** by `tools/ledger.py` for anyone who uses it. Agents are *instructed* to use only it |
| Nothing is sent to anyone | **Enforced**: no email or messaging tool or credential is configured |
| Only the owner can approve | **UNVERIFIED**: fill in after the Day-1 checks (instruction-level at minimum) |
| Reader and Auditor cannot write the ledger | **UNVERIFIED** until `git diff vendors/` is clean after a run |
| Approval is bound to the exact audit shown | Instruction-level (Writer checks the SHA-256 prefix) |

Update this table honestly after testing. Do not upgrade a row without a test.

## Run it

Requirements: Python 3.9+, Docker, Switch and its Console, one machine where
all three agents run **in this same repository folder** (they share files).

```bash
git clone <this repo> && cd overcharge-desk
python3 -m pip install -r requirements-dev.txt   # only needed for the tests
make test                                        # 46 tests, standard library at runtime
```

Then follow `SWITCH_SETUP.md` to create the room and paste in `agents/*.md`.

Try the tools without any agent:

```bash
python3 tools/next_case_id.py
python3 tools/compare.py tests/fixtures/example_invoice.json vendors/acme.json
```

## Repository map

```
agents/        READER.md, AUDITOR.md, WRITER.md   instructions pasted into Switch
tools/         compare, payment_sheet, ledger, check_invoice, next_case_id, sha, now
tests/         pytest suite
vendors/       acme.json  (contract + case history = the ledger)
seed/          acme.json  (clean copy for `make reset-demo`)
contracts/     acme-contract.md  (synthetic)
invoices/      two synthetic invoices
cases/         one folder per case, created by the agents
DEMO_SCRIPT.md two-minute demo and the verification checklist
```

## Limits (read these)

- Synthetic data only. Not accounting software, not tax-aware, no OCR.
- It checks prices against contract rates. It does not check that goods
  arrived, taxes, shipping, or verbal contract changes.
- Without Switch's room permissions confirmed, "owner-only approval" is an
  instruction the Writer follows, not a technical block.
- Text invoices only. PDFs need a text layer.
