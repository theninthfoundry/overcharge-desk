# DEMO_SCRIPT — Overcharge Desk (2 minutes)

All vendors, invoices, amounts and names are synthetic. Say so in the video
and the README.

## What the demo must prove

1. The three agents work in one Switch room, not three separate terminals.
2. The agent remembers an earlier case **because the workflow itself recorded it**.
3. Only the owner's decision moves the case forward.
4. Real files come out, and nothing is sent.

It does **not** prove that Switch is the only place the vendor file could live.
The ledger is a file in the repo and would survive without Switch. What would
not survive is the shared room: the hand-offs, the owner's identity and
decision, the common timeline, and agents from different vendors sharing one
context. Say this plainly. Judges respect it more than a stretched claim.

## Seed data (synthetic)

| Item | Value |
|---|---|
| Vendor | Acme Supplies Pvt Ltd |
| Contract | ACME-2026-01, Schedule A item 1: Corrugated carton 5-ply (CC-5), ₹100/unit, from 2026-01-01 |
| Contract item 2 | Pallet wrap roll, ₹250/unit |
| Case 1 invoice | INV-0914, dated 2026-09-14: 200 cartons at ₹112 = ₹22,400 (contract ₹20,000, difference ₹2,400) |
| Case 2 invoice | INV-1103, dated 2026-11-03: line 1: 500 cartons at ₹112 = ₹56,000 (contract ₹50,000, difference **₹6,000**, 12%); line 2: 40 wrap rolls at ₹250 = ₹10,000 (matches) |
| Case 2 totals | Invoiced ₹66,000, per contract ₹60,000, withheld ₹6,000 |

Line 2 is deliberate. It shows the Auditor says "matches" when it matches.
If you want the exact ₹50,000 vs ₹56,000 invoice only, delete line 2; the
withheld amount stays ₹6,000.

`vendors/acme.json` starts with the contract and an **empty** `cases` list.
Do not pre-write any case into it. `make reset-demo` restores this state
(and deletes `cases/OC-*`), and `make test` must pass before every recording.

## Setup done before filming (disclose it)

Do this at least a few hours before recording, on a different clock time from the demo.

1. Run **Case 1 for real** through the room: Reader, Auditor, then the owner
   types `APPROVE <case_id> <hash>`, then Writer.
2. The owner then types, in the room:
   `OUTCOME <case_id> Vendor acknowledged by phone, credit note CN-114 promised for ₹2,400`
   The unique token `CN-114` is the memory proof: the agent can only
   know it by reading the ledger or room history.
3. Stop all three agent sessions. Start fresh ones (new sessions, empty
   context). Screenshot or screen-record each session's start time.
4. Confirm the ledger now has one case, written by the Writer, with a
   timestamp from the earlier session.

On camera say: "Case 1 was processed earlier today with the same workflow.
This is its real record."

## The script

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:12 | Title card, then the room | "Small businesses pay vendor invoices that nobody checks against the contract, and nobody remembers what the vendor did last time." |
| 0:12–0:30 | Room member list: Reader (Claude Code), Auditor (Codex), Writer, owner. Scroll up to Case 1 with its timestamp and the `CN-114` outcome | "Three agents, two different vendors' tools, in one Mattermost room through Switch. Case 1 is from earlier today, and the agents have since been restarted." |
| 0:30–0:45 | Owner drops `acme-inv-1103.txt` into the room. Reader posts its handoff | "The Reader extracts the invoice and hands it on in the room. No copy-paste." |
| 0:45–1:10 | Auditor message: line 1 invoiced 112 vs contract 100, ₹6,000, 12%; line 2 matches. Then the history block quoting `CN-114` and "second occurrence" | "Numbers come from a Python script, not from the model. And it found Case 1. Look at what it quotes: a credit-note number only the ledger contains." |
| 1:10–1:30 | Owner types `APPROVE <case_id> <hash>`. Writer replies with the identity-check wording | "Only the owner's command counts. The Writer tells you exactly how it checked, and it is honest about whether Switch or the instructions enforce it." |
| 1:30–1:50 | Open `dispute_email.md` (header: DRAFT NOT SENT) and `corrected_payment.csv` (₹60,000 payable, ₹6,000 withheld) | "Two real files. The email cites only evidence from the audit, and nothing is sent. The owner decides." |
| 1:50–2:00 | Split screen: three bare terminals vs the room | "Without Switch, these are three terminals. The hand-offs, the owner's decision and the shared history are gone." |

Optional beat (only if tested and it works): ask the Auditor to approve its
own finding on camera and show it refuse.

## Memory proof checklist (do before filming)

- [ ] The Auditor's session start time is later than the Case 1 record timestamp.
- [ ] The Auditor's message shows it reading `vendors/acme.json` (tool output visible).
- [ ] It quotes `CN-114` exactly, with no invented details.
- [ ] Ask it "what did the vendor say about Case 1 if nothing is recorded?" on a
      scratch case and confirm it says "outcome not recorded".

## Day-1 checks (first hour on Nov 4)

Switch-specific behaviour is unverified until you test it. Fill the Status
column honestly, then set `ENFORCEMENT_LEVEL` in each agent file to match.

| Claim | How to test | Status |
|---|---|---|
| A file dropped in the room reaches the agent | Drop a .txt invoice; the Reader reads it | UNVERIFIED |
| Sender identity is visible to agents | Ask each agent who sent the last message | UNVERIFIED |
| Only the owner can instruct the Writer | Have a second account send `APPROVE`; see whether Switch blocks it | UNVERIFIED |
| Reader cannot write `vendors/` | Run a case, then `git diff vendors/` | UNVERIFIED |
| Auditor cannot write `vendors/` | Same | UNVERIFIED |
| Writer cannot send email | No email tool or credentials configured; confirm none exist | UNVERIFIED |
| Restarted agents keep nothing in context | Ask a fresh session about Acme before it reads any file | UNVERIFIED |

## What the README may claim

- "Instruction-level" for anything not blocked by Switch or the filesystem.
- "Enforced by Switch" only for rows you tested and marked VERIFIED, with how.
- Never "secure", "tamper-proof" or "audit-grade". It is a hackathon prototype
  on synthetic data.

## Recording tips

- Record the room at a readable size. Zoom in on the history block and the
  identity-check line.
- Do one take where it works; do not fake a retake of a failed run. If an
  agent errs, show the failure handling; that is part of the point.
- Keep the README's "how to run" to three commands, so it can be cloned and
  reproduced.

<!-- Step-by-step cold restart verification procedure -->

<!-- Pre-flight verification checklist for Switch room -->

<!-- Explicit synthetic data disclosure statement -->
