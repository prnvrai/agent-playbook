# Setup

Two setups, both idempotent: once per machine, and once per project.

## 1. Once per machine

```powershell
git clone https://github.com/prnvrai/agent-playbook.git
cd agent-playbook
python install_global.py
python install_global.py --check
```

This copies `handoff/` to `~/.agent-handoff/` and writes the full playbook,
wrapped in `<!-- agent-handoff:start/end -->` markers, into:

| Agent | Global file |
|---|---|
| OpenCode | `~/.config/opencode/AGENTS.md` |
| Codex | `~/.codex/AGENTS.md` (and `AGENTS.override.md` when present) |
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| Qwen Code | `~/.qwen/QWEN.md` |
| Cursor | `~/.cursor/rules/handoff.mdc` (frontmatter preserved) |
| Windsurf | `~/.codeium/windsurf/memories/global_rules.md` |
| Cline | `~/Documents/Cline/Rules/handoff.md` |
| Roo Code | `~/.roo/rules/handoff.md` |
| Continue | `~/.continue/rules/handoff.md` |
| Junie | `~/.junie/guidelines.md` |
| Any tool that walks up to home | `~/AGENTS.md` (short pointer only) |

Existing text in those files is kept. Re-running replaces the block in place, so
it never duplicates. `--check` prints one line per target and is the fastest way
to see what is missing. `--home <dir>` installs into a temporary home, which is
how the installer is tested.

`~/AGENTS.md` gets the `<!-- agent-playbook:start/end -->` pointer instead of the
full text, because OpenCode loads both its global file and `~/AGENTS.md`.

### Tools that keep rules in a settings box

Write the URL once in their custom-instructions field:

- **GitHub Copilot (VS Code):** `github.copilot.chat.codeGeneration.instructions`
  -> `{ "text": "Follow https://raw.githubusercontent.com/prnvrai/agent-playbook/main/AGENTS.md" }`
- **Cursor:** Settings -> Rules -> User Rules
- **JetBrains Junie:** Settings -> Tools -> Junie -> Guidelines
- **Hosted chat (DeepSeek, ChatGPT, etc.):** paste the raw URL, or the content
  of `~/.agent-handoff/INSTRUCTIONS.md`, into the custom-instructions box.

`~/.agent-handoff/GLOBAL-SETUP.md` repeats these steps on the machine.

### Aider

`install_global.py` creates `~/.aider.conf.yml` when it does not exist:

```yaml
read:
  - ~/.agent-handoff/INSTRUCTIONS.md
```

If the file already exists, add that `read:` entry yourself.

## 2. Once per project

```powershell
python bootstrap.py "C:\path\to\project"
python bootstrap.py "C:\path\to\project" --check
```

`bootstrap.py` appends this to the project's `AGENTS.md`:

```
<!-- agent-playbook:start -->
## Shared agent instructions

Read and follow the canonical playbook before changing code:
https://raw.githubusercontent.com/prnvrai/agent-playbook/main/AGENTS.md
...
<!-- agent-playbook:end -->
```

It keeps the project's own instructions above the block, creates `AGENTS.md`
when it is missing, and replaces the block instead of duplicating it.
`--dry-run` reports what would change without writing.

Then adopt the handoff kit once in that repository:

```powershell
python "%USERPROFILE%\.agent-handoff\handoff.py" adopt
```

macOS/Linux: `python ~/.agent-handoff/handoff.py adopt`

`adopt` installs the wake-up git hooks (`post-commit`, `post-checkout`,
`post-merge`, `pre-push`), starts the detached watcher as `pythonw.exe`, and adds
a per-user autostart entry. Existing hooks are never replaced. Only watcher
runtime files (`.handoff/watch.log`, `.handoff/watch.cmd`, `.handoff/*.pid`) go
into `.git/info/exclude`; `.gitignore` is not touched.

Commit the resulting `AGENTS.md` so teammates and agents get the pointer.

## Daily use

```powershell
python "%USERPROFILE%\.agent-handoff\handoff.py" save --note "what remains"
python "%USERPROFILE%\.agent-handoff\handoff.py" resume
python "%USERPROFILE%\.agent-handoff\handoff.py" status
```

- `save` is the ~90% command. The working tree goes to a `wip/` branch, is
  pushed, `HANDOFF.md` and `.handoff/checkpoint.json` are updated, and a draft
  pull request is opened or refreshed. On a repository with no `HANDOFF.md`, the
  first checkpoint creates one.
- `resume` prints the open work and the checkpoint detail.
- `status` shows hooks, watcher and autostart.

Stop the watcher in a repository before long edits on `main`:

```powershell
python "%USERPROFILE%\.agent-handoff\handoff_watch.py" --stop --repo "C:\path\to\project"
```

A `git switch` or any commit restarts it through the hooks.

## Quota watchdog (opt-in, owner approval required)

The optional quota watchdog checkpoints work before credits run out and resumes
it after the reset. Create `~/.agent-handoff/config.json` to choose behaviour;
it holds no secrets and is never written by the detector:

```json
{
  "cross_agent_resume": false,
  "opencode_agent": "strategic"
}
```

`cross_agent_resume` defaults to `false`. When false, Codex resumes its own
session with `codex exec resume <session-id> <brief>`. When true, Codex
exhaustion starts a new OpenCode session (bundled
`opencode-cli.exe`, fallback `opencode` on PATH) and OpenCode exhaustion starts
a fresh `codex exec <brief>`. The optional `opencode_agent` defaults to
`strategic` and is passed as `--agent`; no `--auto`/`--full-auto`/`-y` is used,
because the owner chose normal agent authority. Checkpoints pass `--no-push`.
No tool ever reuses the other tool's session id, and `~/.codex/config.toml` is
never edited. Distinct log rows for one session are distinct events; there is no
per-session cooldown in this version.

Manual commands:

```powershell
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --status
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --resume-now --repo "C:\path\to\project"
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --handoff --repo "C:\path\to\project"
python "%USERPROFILE%\.agent-handoff\handoff_quota.py" --poll --force-retry
python "%USERPROFILE%\.agent-handoff\handoff_install.py" --status
python "%USERPROFILE%\.agent-handoff\handoff_install.py" --install-quota
```

`--resume-now` checks the local clock against the parsed Codex reset and spends
nothing before it has passed. OpenCode exhaustion rows have no reset time, so
they stay pending and are resumed only by this manual trigger; with the setting
off the command reports that manual handoff needs `cross_agent_resume` enabled.
`--handoff` starts the other agent for a repo immediately (source from
`--source` or the newest detected event). Events without a resolvable repo are
`error`/`needs-repo` and are never launched. A timeout marks an event `unknown`;
only `--force-retry` can relaunch it. Plain `--install-quota` prints the Task
Scheduler plan (`agent-handoff-quota-<id>`, every 5 minutes, `pythonw ...
handoff_quota.py --poll`), the cron note and the chat command without applying
them; only `--apply` registers the task. `--uninstall-quota --dry-run` shows the
inverse. The applied install writes a reversible
`~/.config/opencode/commands/resume-codex.md` that asks the agent to run
`--resume-now` and report the real output.

**Safety:** enabling the scheduled task, the OpenCode automation cron or the
chat command can lead to unattended credit spending. That is a one-way door:
get explicit owner approval before adding `--apply` to `--install-quota` or
before setting `cross_agent_resume: true`. The installer calls no live automation
API; the cron schedule (`*/5 * * * *`, notify-only) and intent are documented in
`~/.agent-handoff/quota-cron-note.md` for manual registration. `--status` reports
the scheduler task, cron note and chat-command presence.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Not inside a git repository` | Run the command inside the project, or pass `--repo "C:\path"`. |
| `save` reports `"push_note": "no origin remote"` | The commit is local. Add a remote, then `git push -u origin <branch>`. |
| No console window appears, but nothing happens | Expected: the watcher runs detached as `pythonw.exe`. Check `handoff.py status`, then `.handoff/watch.log`. |
| The block appears twice | An agent that loads two global files. Keep the full text only in the per-agent file; `~/AGENTS.md` stays a pointer. Re-run `install_global.py` to collapse it. |
| A commit is blocked in another repository | A project-specific `pre-commit` hook is in the hooks directory, not the playbook. The playbook installs only the four wake hooks. |
| The raw URL does not resolve | The repository may have been made private, or the file was renamed. Use `~/.agent-handoff/INSTRUCTIONS.md`, which holds the same text. |
| Credits or context are nearly gone | Run `save` immediately, then `resume` in the next session. Do not keep working without a checkpoint. |
| `--resume-now` prints "not reset yet" | The local clock is before the parsed reset. No credits were spent; rerun later. |
| "manual handoff needs cross_agent_resume enabled" | Cross-agent handoff is opt-in. Ask the owner before editing `~/.agent-handoff/config.json`. |
| Event status `needs-repo` | The session/cwd could not be resolved. Rerun with `--repo "C:\path"`. |
| Event status `unknown` | A launch timed out and its outcome is unknown. Ask the owner, then use `--force-retry`. |

## What this repository does not do

- It does not copy the playbook into every project. Projects hold a URL, so one
  edit here updates all of them. If a project must work offline, paste
  `AGENTS.md` into it and accept that it will drift.
- It does not set a global `core.hooksPath`. That would override each
  repository's own hooks, including security guards, so `adopt` is per project.
- It does not store secrets or credentials. Nothing here is sensitive; the
  repository can be made private at any time, at the cost of the raw URL working
  for anonymous agents.
