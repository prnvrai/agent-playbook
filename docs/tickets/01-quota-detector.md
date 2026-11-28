# Ticket 01 — Quota detector and reset-time parser

Repo: `C:\Users\Pranav\projects\agent-playbook`

Create `handoff/handoff_quota.py` with:

- `--scan [--dry-run] [--json]`: read `~/.codex/logs_2.sqlite` read-only, select
  `logs` rows containing `You've hit your usage limit`, extract `conversation.id`
  and `try again at <time>`.
- Parse `Nov 28th, 2026 3:04 AM` and time-only `5:36 PM` (roll forward if past).
- Resolve cwd by finding `~/.codex/sessions/**/rollout-*<uuid>.jsonl[.zst]` and
  reading `payload.cwd` from the first `session_meta` line. Compressed files may
  be skipped with an explicit warning in this ticket.
- No prompt text, token or credential is written to stdout, a log or a state
  file. DB access uses URI `mode=ro`.
- Keep detection pure (no checkpoint, no agent launch).

Acceptance:

```powershell
python -m py_compile "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py"
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py" --scan --dry-run --json
```

Unit tests with fixture rows must assert reset times `2026-11-28T03:04` and
`2026-11-27T17:36` and cwd resolution for session
`01a21bbf-de86-7753-937d-fdeb6048b7b7`.
