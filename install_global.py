"""Install the playbook and the handoff kit for every agent on this machine.

    python install_global.py
    python install_global.py --check
    python install_global.py --home C:\\temp\\home

It copies `handoff/` to `~/.agent-handoff/`, writes the full playbook into each
agent's global instruction file, and puts a short pointer in `~/AGENTS.md`.
Re-running replaces the block in place and never duplicates it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS = (HERE / "AGENTS.md").read_text(encoding="utf-8").strip()
POINTER = (HERE / "POINTER.md").read_text(encoding="utf-8").strip()
FULL_START = "<!-- agent-handoff:start -->"
FULL_END = "<!-- agent-handoff:end -->"
POINTER_START = "<!-- agent-playbook:start -->"
POINTER_END = "<!-- agent-playbook:end -->"
FULL = FULL_START + "\n" + AGENTS + "\n" + FULL_END
WAKE_HOOKS = ("post-commit", "post-checkout", "post-merge", "pre-push")

TARGETS = (
    ".config/opencode/AGENTS.md",
    ".codex/AGENTS.md",
    ".claude/CLAUDE.md",
    ".gemini/GEMINI.md",
    ".qwen/QWEN.md",
    ".cursor/rules/handoff.mdc",
    ".codeium/windsurf/memories/global_rules.md",
    "Documents/Cline/Rules/handoff.md",
    ".roo/rules/handoff.md",
    ".continue/rules/handoff.md",
    ".junie/guidelines.md",
)
MDC_HEADER = ("---\n"
              "description: Shared agent playbook and handoff rules\n"
              "alwaysApply: true\n"
              "---\n\n")


def strip(text, start, end):
    first = text.find(start)
    last = text.find(end)
    if first >= 0 and last > first:
        return text[:first] + text[last + len(end):]
    return text


def upsert(text, block, start, end):
    first = text.find(start)
    last = text.find(end)
    if first >= 0 and last > first:
        return text[:first] + block + text[last + len(end):]
    if not text.strip():
        return block + "\n"
    return text.rstrip() + "\n\n" + block + "\n"


def build_kit(home):
    kit = home / ".agent-handoff"
    kit.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted((HERE / "handoff").glob("*.py")):
        shutil.copy2(path, kit / path.name)
        copied.append(path.name)
    # Only the wake hooks. A repository's own pre-commit guard (secret scan,
    # linter) must never be shipped to another repository.
    hooks = HERE / "handoff" / ".githooks"
    target = kit / ".githooks"
    target.mkdir(exist_ok=True)
    for name in WAKE_HOOKS:
        source = hooks / name
        if not source.is_file():
            continue
        shutil.copy2(source, target / name)
        try:
            (target / name).chmod(0o755)
        except OSError:
            pass
    (kit / "INSTRUCTIONS.md").write_text(AGENTS + "\n", encoding="utf-8", newline="\n")
    (kit / "GLOBAL-SETUP.md").write_text(manual_steps(home), encoding="utf-8", newline="\n")
    return kit, copied


def manual_steps(home):
    return """# Global setup notes

`install_global.py` wrote the full playbook to:

- `~/.config/opencode/AGENTS.md`
- `~/.codex/AGENTS.md`
- `~/.claude/CLAUDE.md`
- `~/.gemini/GEMINI.md`
- `~/.qwen/QWEN.md`
- `~/.cursor/rules/handoff.mdc`
- `~/.codeium/windsurf/memories/global_rules.md`
- `~/Documents/Cline/Rules/handoff.md`
- `~/.roo/rules/handoff.md`
- `~/.continue/rules/handoff.md`
- `~/.junie/guidelines.md`
- `~/AGENTS.md` (short pointer to the canonical file)

## Settings-only tools

Add `https://raw.githubusercontent.com/prnvrai/agent-playbook/main/AGENTS.md`
once in the tool's custom-instructions UI:

- GitHub Copilot (VS Code): `github.copilot.chat.codeGeneration.instructions`
- Cursor: Settings -> Rules -> User Rules
- JetBrains Junie: Settings -> Tools -> Junie -> Guidelines
- Any hosted model chat: paste the URL or the content of `INSTRUCTIONS.md`

## Aider

`~/.aider.conf.yml` should contain:

```yaml
read:
  - ~/.agent-handoff/INSTRUCTIONS.md
```
"""


def install_targets(home):
    written, updated = [], []
    for relative in TARGETS:
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        text = path.read_text(encoding="utf-8", errors="replace") if existed else ""
        had = FULL_START in text
        if relative.endswith(".mdc") and not existed:
            text = MDC_HEADER
        path.write_text(upsert(text, FULL, FULL_START, FULL_END),
                        encoding="utf-8", newline="\n")
        (updated if had else written).append(str(path))

    home_agents = home / "AGENTS.md"
    text = home_agents.read_text(encoding="utf-8", errors="replace") \
        if home_agents.exists() else ""
    text = strip(text, FULL_START, FULL_END)
    home_agents.write_text(upsert(text, POINTER, POINTER_START, POINTER_END),
                           encoding="utf-8", newline="\n")

    override = home / ".codex" / "AGENTS.override.md"
    if override.exists():
        text = override.read_text(encoding="utf-8", errors="replace")
        if FULL_START not in text:
            override.write_text(upsert(text, FULL, FULL_START, FULL_END),
                                encoding="utf-8", newline="\n")
            written.append(str(override))
    aider = home / ".aider.conf.yml"
    if not aider.exists():
        aider.write_text("read:\n  - ~/.agent-handoff/INSTRUCTIONS.md\n",
                         encoding="utf-8", newline="\n")
        written.append(str(aider))
    return {"written": written, "updated": updated}


def check(home):
    kit = home / ".agent-handoff"
    targets = {}
    for relative in TARGETS:
        path = home / relative
        targets[str(path)] = bool(
            path.exists() and FULL_START in path.read_text(encoding="utf-8", errors="replace"))
    home_agents = home / "AGENTS.md"
    return {"kit_ready": (kit / "handoff.py").is_file(),
            "home_pointer": bool(home_agents.exists()
                                 and POINTER_START in home_agents.read_text(
                                     encoding="utf-8", errors="replace")),
            "targets": targets}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    home = Path(args.home).resolve()
    if args.check:
        print(json.dumps(check(home), indent=2))
        return 0
    kit, copied = build_kit(home)
    targets = install_targets(home)
    print(json.dumps({"ok": True, "kit": str(kit), "copied": copied,
                      "targets": targets}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
