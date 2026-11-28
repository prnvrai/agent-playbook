# Ticket 02 — Checkpoint, brief and resume runner

Repo: `C:\Users\Pranav\projects\agent-playbook`

Extend `handoff/handoff_quota.py`:

- State file `~/.agent-handoff/quota-state.json` keyed by `(log id, session id)`,
  with status `pending|resuming|done|error`, parsed reset time, cwd and target
  agent. Write `pending -> resuming` to disk before any launch.
- On first detection call `handoff.py save --trigger credits --note ...` once in
  the resolved repo; dedupe repeat scans.
- Build the brief from `handoff.py resume` output and `HANDOFF.md` open work;
  write `~/.agent-handoff/quota-brief-<id>.md`. Redact secrets; never copy raw
  log bodies.
- `--poll`: when `now >= reset_at` and status is `pending`, resume. Default
  command: `codex exec resume <session-id> <brief>` in the session cwd.
- `--resume-now [--repo <path>]`: manual mode chosen by the owner — compare local now with the latest parsed reset time and resume immediately only if reset has passed; never spend credits on a quota probe. If not passed, print reset time and exit.\n- `--dry-run` does detection/checkpoint/brief only, launches nothing.
- Guardrails in code and in the brief: no live trade/order, no billing, no
  force-push, no pushed-history rewrite, stop on approval need.

Acceptance:

```powershell
python -m unittest discover -s "$env:USERPROFILE\projects\agent-playbook\tests" -v
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py" --poll --dry-run
```

Tests use a fake CLI runner; no live model call. Assert one checkpoint per event
and no second launch after a simulated crash between state write and exec.
Distinct log rows for one session are distinct events (no per-session cooldown).
Checkpoints pass `--no-push`; a timeout leaves the event `unknown` and needs
explicit `--force-retry` to relaunch.

