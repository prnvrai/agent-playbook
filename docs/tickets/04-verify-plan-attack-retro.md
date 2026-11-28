# Ticket 04 — Verify, plan-attack pass and Retro

Repo: `C:\Users\Pranav\projects\agent-playbook`

- Run the verification commands from `docs/specs/codex-quota-resume.md` and
  report exact command output. Use the `verifier` and `reviewer` subagents.
- Run the required pre-implementation plan-attack pass from the spec with 3-4
  fresh-context reviewers attacking one invariant each: no double resume,
  no secret leakage, correct session->cwd->repo mapping, guardrails. Resolve
  findings back into the spec before closing this ticket.
- Convert every review comment into a lint rule, test, CI check, ADR or glossary
  term, or explicitly record it as a one-off. No new prose-only instructions.
- Confirm no scheduler task is enabled without explicit owner approval.

Acceptance: verifier PASS with output, reviewer summary, and a Retro entry for
each review comment in `docs/retro/` or the repo's check files.
