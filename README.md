# Agent playbook

One place to point any new project so every agent already knows how to work,
and no instructions have to be retyped for each session.

Point a project at it once:

```powershell
python bootstrap.py "C:\path\to\project"
```

That writes a short, idempotent block into the project's `AGENTS.md` with the
canonical URL:

<https://raw.githubusercontent.com/prnvrai/agent-playbook/main/AGENTS.md>

Any agent that reads `AGENTS.md` (OpenCode, Codex, Claude Code, Gemini, Qwen,
Cursor, Windsurf, Cline, Roo, Continue, Junie, Aider, or a human) then finds the
full playbook without you pasting anything. Updates to this repository reach
every project immediately, because the projects link to the URL instead of
copying the text.

## What is in here

| File | Purpose |
|---|---|
| `AGENTS.md` | The canonical playbook: session start, safety rules, how to work, how to finish. |
| `references/plan-attack.md` | Full tool-agnostic reference for the pre-implementation plan-attack pass. |
| `POINTER.md` | The short block that `bootstrap.py` writes into a project. |
| `bootstrap.py` | Adds or refreshes that block in a project's `AGENTS.md`. Idempotent. |
| `install_global.py` | Installs the playbook into every agent's global instruction file on this machine, and the handoff kit into `~/.agent-handoff/`. |
| `~/.agent-handoff/install_global.py` | Self-contained copy written by the installer, for refreshing offline. |
| `handoff/` | The runtime behind `handoff.py adopt` / `save` / `resume`. |
| `SETUP.md` | First-time setup, per project and per machine, plus troubleshooting. |

## The handoff rule

Context and credits run out. The playbook requires that work is saved before
that happens, in a form the next session can read - not in chat history.

In any git repository:

```powershell
# once per repository
python "%USERPROFILE%\.agent-handoff\handoff.py" adopt

# at ~90% context, before a long task ends, or when credits are nearly gone
python "%USERPROFILE%\.agent-handoff\handoff.py" save --note "what remains"

# resume after a dead session
python "%USERPROFILE%\.agent-handoff\handoff.py" resume
```

`save` commits the working tree to a `wip/` branch, pushes it, writes
`HANDOFF.md` -> `## Open work` and `.handoff/checkpoint.json`, and opens or
refreshes a draft pull request. Nothing needs to be retyped, and no chat history
has to be reread.

## Quota watchdog and cross-agent resume

`handoff/handoff_quota.py` detects credit exhaustion in Codex
(`~/.codex/logs_2.sqlite`, read-only) and in OpenCode
(`~/.local/share/opencode/log/opencode.log`, read-only), checkpoints once per
event, and resumes only after the parsed reset has passed.

Cross-agent handoff is **off by default**. Opt in by creating
`~/.agent-handoff/config.json` (this file holds no secrets and is read-only to
the detector):

```json
{
  "cross_agent_resume": false,
  "opencode_agent": "strategic"
}
```

With `cross_agent_resume: false`, an expired Codex event resumes with
`codex exec resume <session-id> <brief>` in its own session. With it `true`, the
event starts a **new** OpenCode session with the bundled
`opencode-cli.exe run --session <new-uuid> --agent <opencode_agent> "<brief>"`
(fallback: `opencode` on PATH). Normal agent authority is used: no `--auto`,
`--full-auto` or `-y`. An OpenCode exhaustion (`Free usage limit reached` /
`Insufficient account funds`, which has no reset time) starts a fresh
`codex exec <brief>` in the repo resolved from the session, or from `--repo`.
Neither tool ever reuses the other's session id. Distinct log rows for one
session are distinct events; there is no per-session cooldown in this version.

Manual commands:

```powershell
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --status
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --scan-opencode
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --resume-now --repo "C:\path\to\project"
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --handoff --repo "C:\path\to\project"
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --poll --force-retry
python "%USERPROFILE%\.agent-handoff\handoff_install.py" --install-quota
```

`--resume-now` waits for the local clock to pass a Codex reset; OpenCode rows
have no reset time and are resumed only by this manual trigger (no clock gate).
`--handoff` starts the other agent immediately for a repo. Both require the
setting when the target is another tool; otherwise they report that
`cross_agent_resume` must be enabled and spend nothing. Events with no resolvable
repo are `error`/`needs-repo` and are never launched. A timeout marks the event
`unknown`; only `--force-retry` can relaunch it. Automatic checkpoints pass
`--no-push`, so they never push or open a pull request. `--dry-run` performs
detection and brief generation but launches nothing.

## Safety

Enabling the quota watchdog is a **one-way door**: the Task Scheduler task,
the OpenCode automation cron and the `/resume-codex` chat command can lead to
unattended model usage and credit spend. Plain `--install-quota` is a dry run;
do not add `--apply`, and do not set `cross_agent_resume: true`, without
**explicit owner approval**. The installer never calls a live automation API and
never edits `~/.codex/config.toml`; the cron (`*/5 * * * *`, notify-only) is
documented in `~/.agent-handoff/quota-cron-note.md` and must be registered by the
owner.
The playbook is otherwise fail-closed: no secrets in commits, no destructive
commands without confirmation, and never place, simulate or test a live trade,
order or payment. See the "Safety" section of [`AGENTS.md`](AGENTS.md).

## Using it from a project that is not on this machine

Copy the raw URL into the project's `AGENTS.md`, or run `bootstrap.py` there if
Python and this repository are available. If GitHub is unreachable, use
`~/.agent-handoff/INSTRUCTIONS.md`, which holds the same text.
