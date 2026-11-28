# Ticket 03 — Scheduler install and cross-agent setting

Repo: `C:\Users\Pranav\projects\agent-playbook`

- Add `cross_agent_resume` (default false) plus optional OpenCode `--agent` to
  `~/.agent-handoff/config.json`; read it in `handoff_quota.py` without ever
  writing secrets to it.
- When enabled and Codex exhausts: start
  `opencode run --session <new-id> --agent <name> "<brief>"` in the same repo
  (normal agent authority, no `--auto`); record the new session id in state. Reverse
  direction (OpenCode exhaustion): start a fresh `codex exec <brief>` in the same
  repo. Neither tool attempts to reuse the other tool's session ID.
- `--handoff --repo <path>` writes a brief and immediately starts the other agent.
- Extend `handoff_install.py` with idempotent `--install-quota`,
  `--uninstall-quota` (Task Scheduler `agent-handoff-quota-<id>`, every 5 min,
  `pythonw ... --poll`) and document the OpenCode automation cron (owner registers
  it manually; no automation API call). Update
  `README.md` / `SETUP.md` with the setting and safety note.
- `--install-quota` also writes a reversible chat command at `~/.config/opencode/commands/resume-codex.md` whose prompt tells the agent to run `handoff_quota.py --resume-now` and report the actual command output. `--uninstall-quota` removes only that file.\n- `--status` reports scheduler task, cron and chat command presence.

Acceptance:

```powershell
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_install.py" --install-quota --dry-run
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py" --status
```

Activation of the real scheduled task is a one-way door: ask the owner before
running without `--dry-run`. `--install-quota` is dry-run by default; only
`--apply` with explicit approval calls `schtasks /Create`. The OpenCode cron is
documented only (`*/5 * * * *`, notify-only) and registered manually by the
owner; no automation API is called. Manual `--resume-now` / `--handoff` launches
are by design (the owner asked for a manual trigger); `adopt`'s autostart is
pre-existing and unchanged by this ticket. Distinct log rows for one session are
distinct events; no per-session cooldown in this version.

