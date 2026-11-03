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

## Safety

The playbook is fail-closed: no secrets in commits, no destructive commands
without confirmation, and never place, simulate or test a live trade, order or
payment. See the "Safety" section of [`AGENTS.md`](AGENTS.md).

## Using it from a project that is not on this machine

Copy the raw URL into the project's `AGENTS.md`, or run `bootstrap.py` there if
Python and this repository are available. If GitHub is unreachable, use
`~/.agent-handoff/INSTRUCTIONS.md`, which holds the same text.
