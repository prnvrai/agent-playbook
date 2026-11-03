"""One command surface for the repo-independent handoff kit.

`handoff_global_install.py` copies this file to `~/.agent-handoff/handoff.py`, so
the same commands work in any repository without copying anything into it.

    handoff adopt    install hooks, watcher and autostart for the current repo
    handoff save     take a checkpoint now (the 90% rule)
    handoff resume   print the open work and the checkpoint detail
    handoff status   show hooks, watcher and autostart state
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MARK_START = "<!-- agent-handoff:start -->"
MARK_END = "<!-- agent-handoff:end -->"

BLOCK = """<!-- agent-handoff:start -->
## Save work in any repository (agent-agnostic)

This machine has a repo-independent handoff kit at `~/.agent-handoff/`
(Windows: `%USERPROFILE%\\.agent-handoff\\`). Use it for every coding task in
every git repository, whatever the editor or model is.

1. **First time in a repository** - run once:
   `python ~/.agent-handoff/handoff.py adopt`
   It installs the wake-up git hooks, the detached watcher and a per-user
   autostart entry. Existing hooks are kept. On Windows use
   `python "%USERPROFILE%\\.agent-handoff\\handoff.py" adopt`.
2. **At ~90% context, before a long task ends, or when credits/quota are nearly
   exhausted** - run:
   `python ~/.agent-handoff/handoff.py save --note "what remains"`
   It commits the working tree to a `wip/` branch, pushes it, updates
   `HANDOFF.md` and `.handoff/checkpoint.json`, and opens or refreshes a draft
   pull request.
3. **To resume after a dead session** - run
   `python ~/.agent-handoff/handoff.py resume`, then read `HANDOFF.md` ->
   `## Open work` and `.handoff/checkpoint.json`.

Commit and push in small steps: a pushed commit is what survives a dead
session. Never commit secrets or credentials. Never place, simulate or test a
live broker order.
<!-- agent-handoff:end -->"""

POINTER = """<!-- agent-handoff:start -->
## Handoff for every repository

This machine has a reusable handoff kit at `~/.agent-handoff/`. In any git repo:

- first time: `python "%USERPROFILE%\\.agent-handoff\\handoff.py" adopt`
- at ~90% context or when credits are nearly gone:
  `python "%USERPROFILE%\\.agent-handoff\\handoff.py" save --note "what remains"`
- resume after an interruption:
  `python "%USERPROFILE%\\.agent-handoff\\handoff.py" resume`

Read `HANDOFF.md` -> `## Open work` and `.handoff/checkpoint.json` before
continuing. Commit and push small steps; never commit secrets.
<!-- agent-handoff:end -->"""

EXCLUDES = (
    "# agent-handoff runtime files",
    ".handoff/watch.log",
    ".handoff/watch.cmd",
    ".handoff/*.pid",
)


def run(args, cwd=None, timeout=900):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout,
                          creationflags=NO_WINDOW)


def git_text(cwd, *args):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def repo_root(path="."):
    code, out, _ = git_text(path, "rev-parse", "--show-toplevel")
    return Path(out) if code == 0 and out else None


def upsert_block(text, block=BLOCK):
    start = text.find(MARK_START)
    end = text.find(MARK_END)
    if start >= 0 and end > start:
        return text[:start] + block + text[end + len(MARK_END):]
    if not text.strip():
        return block + "\n"
    return text.rstrip() + "\n\n" + block + "\n"


def add_excludes(repo):
    code, out, _ = git_text(repo, "rev-parse", "--git-path", "info/exclude")
    if code != 0 or not out:
        return None
    path = Path(out)
    if not path.is_absolute():
        path = repo / path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    added = [line for line in EXCLUDES[1:] if line not in text.splitlines()]
    if added:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if not text.endswith("\n") and text:
                handle.write("\n")
            handle.write("\n".join(EXCLUDES) + "\n")
    return path


def adopt(repo, no_autostart=False):
    agents = repo / "AGENTS.md"
    text = agents.read_text(encoding="utf-8", errors="replace") if agents.exists() else ""
    agents.write_text(upsert_block(text), encoding="utf-8", newline="\n")
    exclude = add_excludes(repo)
    args = [HERE / "handoff_install.py", "--repo", repo]
    if no_autostart:
        args.append("--no-autostart")
    result = run(args, cwd=repo)
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except ValueError:
        payload = {"raw": (result.stdout or result.stderr or "").strip()[-600:]}
    return {"ok": result.returncode == 0, "repo": str(repo),
            "agents": str(agents), "exclude": str(exclude) if exclude else None,
            "install": payload}


def resume(repo):
    handoff = repo / "HANDOFF.md"
    if not handoff.exists():
        print("No HANDOFF.md in " + str(repo) + ". Run: handoff adopt")
        return 1
    text = handoff.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"<!-- open-work: (.+?) -->\n(.*?)<!-- /open-work -->",
                        text, flags=re.S)
    if not blocks:
        print("No open work recorded in " + str(handoff) + ".")
    for branch, body in blocks:
        print("## " + branch)
        print(body.strip())
        print()
    state = repo / ".handoff" / "checkpoint.json"
    if state.exists():
        print("--- .handoff/checkpoint.json ---")
        print(state.read_text(encoding="utf-8", errors="replace").strip())
    return 0


def split_repo(rest):
    rest = list(rest)
    repo = Path.cwd()
    if "--repo" in rest:
        index = rest.index("--repo")
        if index + 1 < len(rest):
            repo = Path(rest[index + 1]).resolve()
        del rest[index:index + 2]
    return repo, rest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print(BLOCK)
        return 0
    command, rest = argv[0], argv[1:]
    repo, rest = split_repo(rest)
    root = repo_root(repo)
    if command != "where" and root is None:
        print("Not inside a git repository: " + str(repo), file=sys.stderr)
        return 2
    target = root or repo

    if command == "adopt":
        result = adopt(target, no_autostart="--no-autostart" in rest)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if command == "save":
        result = run([HERE / "handoff_checkpoint.py", "--repo", target, *rest], cwd=target)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    if command == "resume":
        return resume(target)
    if command == "status":
        result = run([HERE / "handoff_install.py", "--repo", target, "--check"], cwd=target)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return result.returncode
    if command == "where":
        print(HERE)
        return 0
    print("Unknown command: " + command, file=sys.stderr)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
