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

## What this repository does not do

- It does not copy the playbook into every project. Projects hold a URL, so one
  edit here updates all of them. If a project must work offline, paste
  `AGENTS.md` into it and accept that it will drift.
- It does not set a global `core.hooksPath`. That would override each
  repository's own hooks, including security guards, so `adopt` is per project.
- It does not store secrets or credentials. Nothing here is sensitive; the
  repository can be made private at any time, at the cost of the raw URL working
  for anonymous agents.
