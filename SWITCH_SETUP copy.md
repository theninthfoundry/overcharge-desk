# SWITCH_SETUP

Follow the organisers' quickstart for the exact Switch install and Console
steps; menu names change, and I could not verify them. This file covers the
parts specific to Overcharge Desk. Anything marked CHECK must be tested, not assumed.

Official links: the Flip the Switch hackathon page, the Switch docs and
GitHub repository, and the WeMakeDevs build guide (all linked from the
hackathon page).

## 0. Rules to respect

- The Switch setup and the workflow must be built **during the hackathon
  window (Nov 4 to Nov 7, 2026)**. Before that: read docs, install Docker,
  run the quickstart, and prepare notes. Commit this repo's code after the
  window opens, and keep your commit history honest.
- Use synthetic data only.

## 1. Before the window

- [ ] Docker installed and running.
- [ ] Python 3.9+ installed. `make test` passes (46 tests).
- [ ] Switch quickstart completed once (a room, one agent answering).
- [ ] Join the hackathon Discord. Note where to ask questions.
- [ ] Two agent tools available on your machine: Claude Code and Codex
      (or whatever the quickstart supports). CHECK whether two agents of the
      same tool can run side by side; if not, use two different tools.

## 2. One machine, one folder

All three agents must run on **one computer, inside the same clone of this
repository**, because they hand work over through the files in `cases/` and
`vendors/`. If an agent runs elsewhere it will not see the other agents' files.

## 3. Create the room

1. Create a Mattermost channel, e.g. `#overcharge-desk` (name it as you like).
2. Add the owner account and three agents: **Reader**, **Auditor**, **Writer**.
3. Suggested assignment: Reader on Claude Code, Auditor on Codex, Writer on
   Claude Code. Using two different vendors is part of the demo.
4. For each agent, paste the matching file from `agents/` into its
   instructions in Switch Console. Replace `@owner` with the real owner handle.
5. Point each agent's working directory at the repository folder.

## 4. Day-1 checks (first hour)

Run these before building more. Record results in `DEMO_SCRIPT.md` and the
README table. Keep every `ENFORCEMENT_LEVEL` at `instruction-only` until a
check proves otherwise.

- [ ] CHECK: dropping `invoices/acme-inv-1103.txt` in the room reaches the Reader.
      If it does not, copy the file to `invoices/` yourself and give the path.
- [ ] CHECK: each agent can see who sent the last message.
- [ ] CHECK: a second (non-owner) account sends `APPROVE ...`. Does Switch
      stop it, or only the Writer's instructions?
- [ ] CHECK: after one full run, `git diff vendors/` shows changes only from
      the Writer's `ledger.py` call.
- [ ] CHECK: agents can run `python tools/...` from the repository root.
- [ ] CHECK: a restarted agent session has no memory of Acme until it reads files.

## 5. Dry run

```bash
make reset-demo        # clean state
# in the room: drop invoices/acme-inv-0914.txt, follow the prompts
# owner: APPROVE <case_id> <hash>    then    OUTCOME <case_id> ...
# restart all three agent sessions
# drop invoices/acme-inv-1103.txt and compare with DEMO_SCRIPT.md
```

Do the dry run on a day before recording. Record only a real run.

## 6. Submission checklist

- [ ] Public repo with this README, `make test` passing.
- [ ] Demo video of about two minutes, recorded from a real run, disclosing the earlier Case 1.
- [ ] README table updated with only what you verified.
- [ ] Optional: a short blog post about what you built and what Switch made easy or hard.
