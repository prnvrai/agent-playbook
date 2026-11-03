"""Point a project at the shared playbook.

    python bootstrap.py "C:\\path\\to\\project"
    python bootstrap.py . --dry-run

The block is idempotent: re-running replaces it in place. Existing project
instructions are kept; the block is appended after them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCK = (HERE / "POINTER.md").read_text(encoding="utf-8").strip()
START = "<!-- agent-playbook:start -->"
END = "<!-- agent-playbook:end -->"


def upsert(text):
    start = text.find(START)
    end = text.find(END)
    if start >= 0 and end > start:
        return text[:start] + BLOCK + text[end + len(END):]
    if not text.strip():
        return "# Agent instructions\n\n" + BLOCK + "\n"
    return text.rstrip() + "\n\n" + BLOCK + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when the project has no playbook pointer")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if not project.is_dir():
        print("Not a directory: " + str(project), file=sys.stderr)
        return 2
    path = project / "AGENTS.md"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if args.check:
        ok = START in text
        print(json.dumps({"ok": ok, "path": str(path)}, indent=2))
        return 0 if ok else 1
    updated = upsert(text)
    changed = updated != text
    if changed and not args.dry_run:
        path.write_text(updated, encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "path": str(path), "changed": changed,
                      "dry_run": args.dry_run}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
