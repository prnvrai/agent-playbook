# Spec: Codex quota watchdog and cross-agent resume

## Goal

Add a credit-exhaustion watchdog to the portable handoff kit so that work is
checkpointed before a limit stops the agent, and continuation starts
automatically when the quota resets. With a setting enabled, the same event can
hand the work to the other agent (Codex <-> OpenCode) instead of waiting for the
same tool. Both agents can resume each other's **work**, never each other's
foreign session IDs.

Agreed in grilling:

- Watcher runs in **both** places: a Windows Task Scheduler task (works with the
  apps closed) and an OpenCode automation cron (notification/brief).
- On reset, resume the **same Codex session** with `codex exec resume <id>` and a
  short brief from `handoff.py resume` / `HANDOFF.md`.
- Owner explicitly chose **normal agent authority** for the resumed agent.
- Watch **all repos** derived from exhausted sessions (cwd from session JSONL).
- Cross-agent setting lives in `~/.agent-handoff/config.json`, key
  `cross_agent_resume`, **default false**. Both directions when enabled.
- Cross-agent handoff starts a **new session in the other tool** with the brief.
- Trigger: credit exhaustion automatically, plus a manual command. Manual means "resume immediately if quota is back": compare local now with the parsed reset time, launch only if reset has passed, and do not spend credits on a probe. The manual trigger is also available from an OpenCode chat command, so the owner can type `/resume-codex` here.

## Non-goals

- No edits to `~/.codex/config.toml` (its `notify` hook is owned by Codex Desktop).
- No credit purchasing, billing changes, ChatGPT web scraping or API reverse
  engineering.
- No reuse of a Codex session ID in OpenCode or vice versa.
- No second automatic resume for the same exhaustion event. Distinct log rows
  for **one session are distinct events**; there is no per-session cooldown in
  this version. A timeout leaves the event `unknown`, and relaunch needs an
  explicit `--force-retry`.
- No live trade/order, no pushed-history rewrite, no force-push. These stay
  one-way doors requiring fresh explicit approval even under normal authority.
- No live automation API call: the OpenCode cron is **documented only** in
  `~/.agent-handoff/quota-cron-note.md`; the owner registers/cancels it manually.
  Manual `--resume-now` / `--handoff` launches are by design because the owner
  explicitly asked for a manual trigger. `adopt`'s existing autostart entry is
  pre-existing behaviour, accepted here as a one-off; this ticket does not change
  `adopt`.

## Terms and ADRs

- Uses existing terms from `ouroboros-trading-engine/docs/glossary.md`:
  One-way door, Two-way door, Grill, Spec, Ticket, Retro, Smart zone/dumb zone.
- No new glossary term is introduced by this spec.
- ADRs touched: none in this repo. The invariant of
  `ouroboros-trading-engine/docs/adr/0003*` (no live orders) is preserved by the
  guardrail above.

## Design

1. **Detect.** `handoff/handoff_quota.py --scan` opens
   `~/.codex/logs_2.sqlite` read-only (`file:...?mode=ro`) and selects rows in
   `logs` where `feedback_log_body` contains `You've hit your usage limit`.
   Each row is identified by its integer `id` and contains
   `conversation.id=<uuid>` and `try again at <time>`. Parse both observed
   shapes: `Nov 28th, 2026 3:04 AM` and time-only `5:36 PM` (roll to next day if
   not in the future).
2. **Locate work.** Find the rollout file
   `~/.codex/sessions/**/rollout-*<uuid>.jsonl[.zst]`, read the first
   `session_meta` line, take `payload.cwd` as the repo. Never log prompt text.
3. **Checkpoint once.** On each new `(log id, session id)`, run
   `handoff.py save --trigger credits --note "Codex quota exhausted; resume at <iso>"`
   in that repo, then record the event in
   `~/.agent-handoff/quota-state.json` with status `pending`.
4. **Wake at reset.** Task Scheduler polls every 5 minutes; OpenCode automation
   polls on the same cadence. When `now >= reset_at` and status is `pending`,
   write a short brief to `~/.agent-handoff/quota-brief-<id>.md` from
   `handoff.py resume` output (truncated, secrets redacted) and mark status
   `resuming` **before** launching anything (crash-safe, no double spend).
5. **Resume.** When `cross_agent_resume` is false, run
   `codex exec resume <session-id> <brief>` in the session cwd. When true, run
   `opencode run --session <new-id> --agent <opencode_agent> "<brief>"` (no `--auto`) in the same repo with
   `--agent` from config (default `strategic`), and record the new session id.
   Mirror the reverse direction for OpenCode exhaustion: launch
   `codex exec <brief>` in a fresh Codex session. Capture stdout/stderr to
   `~/.agent-handoff/quota-resume.log` with no tokens, prompts or credentials.
6. **Manual.** `handoff_quota.py --handoff --repo <path>` writes the brief and
   starts the other agent immediately, regardless of quota state.
7. **Chat trigger.** The installer also writes `~/.config/opencode/commands/resume-codex.md` (frontmatter description + prompt instructing the agent to run `handoff_quota.py --resume-now` and report output). This is reversible and does not edit agent config files.\n8. **Manual now.** `--resume-now [--repo <path>]` compares local now with the latest parsed reset time and, only if the reset has passed, resumes immediately; otherwise it prints the reset time and exits without spending credits. Accepted exception: OpenCode exhaustion rows carry no reset time, so they bypass the clock gate and only run from this explicit manual trigger. Events with no resolvable repo are `error`/`needs-repo`, never launched.\n9. **Install.** `handoff_install.py` gains `--install-quota` / `--uninstall-quota`
   to create/remove the Task Scheduler entry
   (`agent-handoff-quota-<id>`, every 5 minutes, `pythonw ... --poll`). Plain
   `--install-quota` is a dry run; only `--apply` with owner approval calls
   `schtasks /Create`. The OpenCode cron is documented (schedule `*/5 * * * *`,
   notify-only intent) in a note file, never registered through an automation
   API. `--status` reports the scheduler task, the cron note and the chat command.

## Acceptance criteria

- [ ] Detector finds the two known log rows (ids 876270, 756652) in fixture DB
      and parses reset times `2026-11-28T03:04` and `2026-11-27T17:36`.
- [ ] Time-only reset in the past rolls to the next day.
- [ ] Session `01a21bbf-de86-7753-937d-fdeb6048b7b7` resolves to its cwd from
      the rollout JSONL and no prompt text is written to any log or brief from
      the raw log body.
- [ ] One `handoff.py save --trigger credits --no-push` per exhaustion event;
      a second scan with the same log id is a no-op. Distinct log rows for one
      session are distinct events (no per-session cooldown).
- [ ] State transition `pending -> resuming` is persisted before launching the
      agent; a killed process cannot trigger a second resume.
- [ ] `cross_agent_resume` defaults to false; when true, Codex exhaustion starts
      a new OpenCode session and OpenCode exhaustion starts a new Codex session,
      both with the brief and both recorded in state.
- [ ] `--dry-run` performs detection, checkpoint and brief generation but
      launches nothing and spends no credits.
- [ ] Guardrails enforced in the brief and in code: no live trade/order, no
      billing, no force-push, no pushed-history rewrite, stop on approval need.
- [ ] Install/uninstall are idempotent and `--status` shows scheduler + cron.
- [ ] Unit tests cover parsing, dedupe, state transitions and command building;
      no test calls a live model.

## Verification commands

```powershell
python -m py_compile "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py"
python -m unittest discover -s "$env:USERPROFILE\projects\agent-playbook\tests" -v
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py" --scan --dry-run
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_quota.py" --status
python "$env:USERPROFILE\projects\agent-playbook\handoff\handoff_install.py" --install-quota --dry-run
```

## Pre-implementation plan-attack pass (required, spec-sized)

One context-holding agent keeps this agreed statement and launches 3-4 fresh
reviewer sub-agents; each attacks exactly ONE invariant and none grades its own
plan:

1. No double resume / double credit spend after crash or retry.
2. No secret or prompt leakage into logs, briefs or state files.
3. Correct session-id -> cwd -> repo mapping for both tools.
4. Guardrails: no live orders, billing, force-push or pushed-history rewrite.

Resolve findings back into this spec before Ticket 4 is implemented. Anything
mechanically catchable becomes a Retro check (lint rule, test or CI check).

## Tickets

- `docs/tickets/01-quota-detector.md`
- `docs/tickets/02-checkpoint-and-resume.md`
- `docs/tickets/03-install-cross-agent.md`
- `docs/tickets/04-verify-plan-attack-retro.md`



