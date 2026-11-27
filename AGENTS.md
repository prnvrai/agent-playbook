# Agent playbook

Canonical instructions for every project owned by Pranav. Read this before
changing code. It is written for any agent, editor or model: OpenCode, Codex,
Claude Code, Gemini, Qwen, Cursor, Windsurf, Cline, Roo, Continue, Junie, Aider,
or a human.

Project files (`AGENTS.md`, `README.md`, `CONTRIBUTING.md`, CI configuration)
override this playbook where they are more specific. This file is the default
when a project says nothing.

## Start of a session

1. Read `HANDOFF.md` if it exists, especially `## Open work`.
2. Read `.handoff/checkpoint.json` if it exists.
3. Run `git status` and `git log --oneline -5`; do not assume a clean tree.
4. If the project has no handoff yet, run the adopt command below.

## Save work before context or credits run out

- Install once per repository:

  ```powershell
  python "%USERPROFILE%\.agent-handoff\handoff.py" adopt
  ```

  macOS/Linux: `python ~/.agent-handoff/handoff.py adopt`

- At about 90% context, before a long task ends, or when credits/quota are
  nearly exhausted:

  ```powershell
  python "%USERPROFILE%\.agent-handoff\handoff.py" save --note "what remains"
  ```

  This commits the working tree to a `wip/` branch, pushes it, updates
  `HANDOFF.md` and `.handoff/checkpoint.json`, and opens or refreshes a draft
  pull request.

- Resume after an interruption:

  ```powershell
  python "%USERPROFILE%\.agent-handoff\handoff.py" resume
  ```

  Then read `HANDOFF.md` -> `## Open work` and `.handoff/checkpoint.json`.

- Commit and push in small steps. A pushed commit survives a dead session; an
  unpushed change does not.

If the kit is missing on a machine, install it from this repository with
`python install_global.py` (see `SETUP.md`).

## Safety (non-negotiable)

- Never print, commit, paste or log secrets: passwords, API keys, tokens, TOTP
  seeds, cookies, session IDs, account payloads or webhook URLs.
- Never place, simulate or test a live trade, order, payment or other
  irreversible action without explicit written confirmation from the owner.
- Never force-push, rewrite shared history, delete branches you did not create,
  or run destructive commands without confirmation.
- Never enable a live path, change billing, or spend money without confirmation.
- Keep private repositories private and credentials out of git.

## How to work

- Read the relevant code before editing. Keep changes scoped to the request.
- Match the existing structure, naming and style; do not refactor unrelated code.
- Add or update tests for behaviour changes.
- Run the project's checks before proposing a pull request, and report exactly
  what ran.
- Never claim something works without evidence. Separate verified from
  unverified.
- Use small commits with clear messages. Never work directly on `main`; use a
  feature branch or a `wip/` branch.
- Write the pull request body for a human: problem, change, verification,
  remaining risk.
- Do not leave debug output, commented-out code or generated bulk files.
- Update documentation when behaviour or setup changes.

## Before building (spec-sized changes)

- A change too large for one paragraph/session: its written statement (Spec)
  needs a pre-implementation plan-attack pass; resolve all findings before coding.
- One context holder keeps the statement; 3-4 fresh-context reviewer sub-agents
  (or independent human reviewers) each attack exactly ONE invariant drawn from
  the project's ADRs, glossary rules and test expectations. No reviewer grades its own plan.
- Anything mechanically catchable becomes a test, lint rule or CI check (a
  Retro-style deterministic check), not prose. This is a planning step, not
  permission to write code before the owner agrees.
- Full reference: https://raw.githubusercontent.com/prnvrai/agent-playbook/main/references/plan-attack.md

## When blocked

- Try the obvious fix once, then report the exact error, what you tried, and the
  smallest question needed. Do not guess silently or loop.
- If a tool or permission is missing, say so and continue with what is possible.

## Finish a task

1. Run the verification commands the project documents.
2. Commit and push.
3. Update `HANDOFF.md` only through the handoff commands; the merge workflow
   clears the Open work block.
4. Report what changed, what was verified, and what remains.

## AI coding workflow (tool-agnostic)

- Before any non-trivial change: read handoff and git state, explore with a
  cheap read-only pass, then ask the owner concrete questions in one batch.
  Never fill a gap with a guess.
- Keep the agent set small and tune each agent or instruction file separately;
  resume a session for related work, start fresh for a new ticket. On a drifting
  or polluted thread, restart with a 3-5 line brief and exact file paths.
  Subtraction beats patching; one ticket per session.
- Scope large work into a written spec and small tickets. Effort is a budget:
  default low/medium, high only for verification, debugging and hard research.
- Determinism beats prompting: encode repeated mistakes as a lint rule, test,
  CI check, ADR or glossary term, not another paragraph of prose.
- Keep skills and instructions on-demand, short, with a name and description;
  keep deep material in references or scripts and verify with a repeatable
  check, not a happy-path demo. Avoid huge third-party bundles or unpinned
  downloads.
- Folder-local AGENTS.md compose with root rules; put folder-specific
  constraints there, not in the root.
- Never create overlapping end-to-end tests; drop smaller cases already covered
  by a larger flow.
- Verify with evidence: run the documented checks, quote exact output, and
  separate verified from unverified.
- Use the cheapest sufficient model for read-only exploration, a stronger one
  for implementation and verification. Never change provider, billing or quota
  settings, enable credit fallback, or put keys or tokens in files or chat
  without explicit owner approval.
- Merge danger gate: a two-way door with small blast radius can be merged and
  sampled; a one-way door (money, orders, credentials, deleted data, public
  exposure, pushed history) needs explicit approval every time.
- Retro every review: each human review comment becomes a deterministic check
  or is explicitly accepted as a one-off.
- Finish by pushing a resumable handoff; unpushed work does not survive a dead
  session.
