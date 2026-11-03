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
