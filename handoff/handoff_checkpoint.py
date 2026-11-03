"""Save an unambiguous, resumable checkpoint of the current work.

The watcher, a git hook, or any agent can run this when context is nearly
exhausted, when a session is compacted, or when the provider reports a quota
failure. The script is deliberately mechanical: it commits the
working tree on a `wip/` branch, pushes it, writes a short bullet into
`HANDOFF.md`, stores full detail in `.handoff/checkpoint.json`, and opens or
updates a draft pull request.

Nothing here touches a broker, a Google Sheet, a VM or a workflow run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
# A detached watcher has no console, so Windows would give every child its
# own console window (visible as flickering). Suppress that everywhere.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_HANDOFF = """# Handoff

Current state for this repository. The Open work section is the resume point;
full detail lives in `.handoff/checkpoint.json`.

## Current state
<!-- last-merge -->
_No merges recorded yet._

## Open work
_None._

## Hard constraints
- Never commit secrets, tokens or credentials.
- Never place, simulate or test a live broker order.
"""
BLOCK_START = "<!-- open-work: "
BLOCK_END = "<!-- /open-work -->"
PR_MARKER = "<!-- handoff-checkpoint -->"
STATE_DIR = ".handoff"
STATE_FILE = "checkpoint.json"
LOCK_FILE = ".git/handoff-checkpoint.lock"
LOCK_STALE_SECONDS = 900

SECRET_PATTERNS = (
    re.compile(r"(^|/)\.env(\.|$)", re.I),
    re.compile(r"(^|/)env\.(local|prod|production|stage|staging)$", re.I),
    re.compile(r"\.(pem|key|p12|pfx|keystore|jks)$", re.I),
    re.compile(r"(^|/)(id_rsa|id_ed25519|id_ecdsa)$", re.I),
    re.compile(r"(^|/)(credentials|secrets?|tokens?)(\.|$)", re.I),
    re.compile(r"(^|/)service[-_]?account.*\.json$", re.I),
)

NEXT_HINTS = (
    "next", "remaining", "todo", "to do", "still need", "still have",
    "pending", "follow-up", "follow up", "not yet", "left to",
)

REDACTIONS = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{10,}"), "gh*_REDACTED"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{10,}"), "github_pat_REDACTED"),
    (re.compile(r"sk-[A-Za-z0-9]{10,}"), "sk-REDACTED"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "xox-REDACTED"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{10,}"), r"\1REDACTED"),
    (re.compile(r"(?i)(https://api\.telegram\.org/bot)[A-Za-z0-9:_-]+"), r"\1REDACTED"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;\"']{6,}"),
     r"\1REDACTED"),
)


class CheckpointError(RuntimeError):
    """A checkpoint could not be written safely."""


def now_ist():
    return datetime.now(timezone.utc).astimezone(IST)


def stamp(moment):
    return moment.strftime("%Y-%m-%d %H:%M IST")


def slugify(text, limit=42):
    """Turn free text into a short, stable branch suffix."""
    words = re.findall(r"[A-Za-z0-9]+", (text or "").lower())
    stop = {"the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "is",
            "it", "this", "that", "with", "please", "can", "you"}
    picked = [word for word in words if word not in stop][:6] or words[:4] or ["work"]
    slug = "-".join(picked)
    if len(slug) > limit:
        slug = slug[:limit].rsplit("-", 1)[0] or slug[:limit]
    return slug or "work"


def secret_like(path):
    """True when a path looks like it carries credentials."""
    cleaned = path.replace("\\", "/").strip()
    return any(pattern.search(cleaned) for pattern in SECRET_PATTERNS)


def redact(text):
    """Remove common credential shapes before text is committed."""
    cleaned = text or ""
    for pattern, replacement in REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def trim(text, limit):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + " …"


def guess_next(text, limit=300):
    """Pick the lines of an assistant message that describe unfinished work."""
    lines = [line.strip(" \t-*•") for line in (text or "").splitlines()]
    picked = []
    for line in lines:
        low = line.lower()
        if not line or len(line) < 3:
            continue
        if any(hint in low for hint in NEXT_HINTS):
            picked.append(trim(line, limit))
        if len(picked) == 3:
            break
    if picked:
        return " / ".join(picked)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", trim(text, 4000)) if part.strip()]
    return trim(" ".join(sentences[-2:]), limit) if sentences else ""


def work_fingerprint(*, branch, goal, next_step, done, changed):
    """Stable hash of the facts that matter, ignoring the checkpoint timestamp."""
    payload = json.dumps([branch, goal, next_step, done, changed], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_block(*, branch, goal, next_step, done, changed, pr, trigger, ratio, updated):
    """Render one Open work block. Delimiters make updates idempotent."""
    head = "- **" + trim(goal or "Work in progress", 160) + "** — `" + branch + "`"
    if pr:
        head += " · draft PR [#" + str(pr["number"]) + "](" + str(pr["url"]) + ")"
    head += " · checkpoint " + stamp(updated)
    head += " · trigger " + trigger
    if ratio:
        head += " " + str(int(round(ratio * 100))) + "%"
    lines = [BLOCK_START + branch + " -->", head]
    if done:
        lines.append("  - Done: " + trim("; ".join(done[:3]), 260))
    if changed:
        lines.append("  - Files: " + trim(", ".join(changed[:6]), 260)
                     + (" (+" + str(len(changed) - 6) + " more)" if len(changed) > 6 else ""))
    lines.append("  - Next: " + trim(next_step or "Inspect the diff and continue the task.", 400))
    lines.append("  - Resume: `git fetch origin && git switch " + branch
                 + " && git diff main...HEAD` then read `.handoff/checkpoint.json`")
    lines.append("<!-- open-work-fingerprint: "
                 + work_fingerprint(branch=branch, goal=goal, next_step=next_step,
                                    done=done, changed=changed) + " -->")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def upsert_block(text, block, branch):
    """Replace the block for this branch in place, or insert it under Open work."""
    start = text.find(BLOCK_START + branch + " -->")
    if start >= 0:
        end = text.find(BLOCK_END, start)
        if end < 0:
            raise CheckpointError("HANDOFF.md has an unterminated open-work block")
        return text[:start] + block + text[end + len(BLOCK_END):]
    heading = "## Open work\n"
    index = text.find(heading)
    if index < 0:
        raise CheckpointError("HANDOFF.md is missing the Open work heading")
    body_start = index + len(heading)
    tail = text[body_start:]
    placeholder = re.search(r"^_None\._\s*$", tail, re.M)
    if placeholder:
        tail = tail[:placeholder.start()] + tail[placeholder.end():]
    return text[:body_start] + "\n" + block + "\n" + tail.lstrip("\n")


def remove_block(text, branch):
    start = text.find(BLOCK_START + branch + " -->")
    if start < 0:
        return text
    end = text.find(BLOCK_END, start)
    if end < 0:
        raise CheckpointError("HANDOFF.md has an unterminated open-work block")
    text = text[:start] + text[end + len(BLOCK_END):]
    if "## Open work\n" in text and BLOCK_START not in text:
        text = re.sub(r"(## Open work\n)(?!<!--)", r"\1_None._\n", text, count=1)
    return text


class Git:
    """Thin git/gh wrapper with predictable errors and no shell quoting."""

    def __init__(self, repo):
        self.repo = Path(repo)

    def run(self, *args, check=True, timeout=120, input_text=None):
        env = dict(os.environ)
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GH_PROMPT_DISABLED", "1")
        env["HANDOFF_INTERNAL"] = "1"
        result = subprocess.run(
            list(args), cwd=str(self.repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, input=input_text, env=env,
            creationflags=NO_WINDOW,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise CheckpointError("`" + " ".join(args[:3]) + "` failed: "
                                  + (detail[-1] if detail else "exit " + str(result.returncode)))
        return result

    def out(self, *args):
        return self.run(*args).stdout.strip()

    def has_commits(self):
        return self.run("git", "rev-parse", "--verify", "HEAD", check=False).returncode == 0

    def current_branch(self):
        return self.out("git", "branch", "--show-current")

    def branch_exists(self, branch, remote=False):
        if remote:
            return self.run("git", "rev-parse", "--verify", "origin/" + branch, check=False).returncode == 0
        return self.run("git", "rev-parse", "--verify", "refs/heads/" + branch, check=False).returncode == 0

    def identity_args(self):
        name = self.run("git", "config", "user.name", check=False).stdout.strip()
        email = self.run("git", "config", "user.email", check=False).stdout.strip()
        if name and email:
            return []
        return ["-c", "user.name=Agent Handoff", "-c", "user.email=handoff@agents.local"]

    def commit(self, message):
        # Snapshots must never be blocked by a pre-commit hook or a slow scanner.
        self.run("git", *(self.identity_args() + ["commit", "--no-verify", "-m", message]))

    def ensure_remote(self):
        return self.run("git", "remote", "get-url", "origin", check=False).returncode == 0


def changed_files(git):
    """Modified, staged and untracked paths, relative to the repository."""
    status = git.run("git", "status", "--porcelain", "--untracked-files=all").stdout
    paths = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return sorted(dict.fromkeys(paths))


BOOKKEEPING_COMMITS = (
    "WIP: checkpoint", "Record handoff checkpoint", "Link handoff checkpoint",
    "Clear the open-work checkpoint",
)


def commits_since_main(git):
    """Commit subjects that exist on this branch but not on origin/main."""
    base = "origin/main" if git.branch_exists("main", remote=True) else "main"
    if git.run("git", "rev-parse", "--verify", base, check=False).returncode != 0:
        return []
    log = git.run("git", "log", "--format=%h %s", base + "..HEAD", check=False).stdout
    commits = []
    for line in log.splitlines():
        line = line.strip()
        if line and not line.split(" ", 1)[-1].startswith(BOOKKEEPING_COMMITS):
            commits.append(line)
    return commits


def bookkeeping_path(path):
    """True for files the checkpoint writes itself."""
    cleaned = path.replace("\\", "/")
    return cleaned == "HANDOFF.md" or cleaned.startswith(STATE_DIR + "/")


def ensure_branch(git, session, goal):
    """Return a branch safe to commit on, creating a wip branch when on main."""
    current = git.current_branch()
    if current and current not in ("main", "master"):
        return current
    suffix = re.sub(r"[^A-Za-z0-9]", "", session or "")[:8].lower()
    branch = "wip/" + slugify(goal)
    if suffix:
        branch += "-" + suffix
    if git.branch_exists(branch):
        git.run("git", "switch", branch)
        return branch
    git.run("git", "switch", "-c", branch)
    return branch


def stage_changes(git):
    """Stage everything except files that look like credentials."""
    git.run("git", "add", "-A")
    skipped = []
    staged = git.run("git", "diff", "--cached", "--name-only").stdout.splitlines()
    for path in staged:
        if secret_like(path):
            git.run("git", "reset", "-q", "--", path, check=False)
            skipped.append(path)
    return skipped


def push_branch(git, branch):
    if not git.ensure_remote():
        return False, "no origin remote"
    result = git.run("git", "push", "-u", "origin", branch, check=False)
    if result.returncode == 0:
        return True, "pushed"
    git.run("git", "pull", "--rebase", "--autostash", "origin", branch, check=False)
    retry = git.run("git", "push", "-u", "origin", branch, check=False)
    if retry.returncode == 0:
        return True, "pushed after rebase"
    detail = (retry.stderr or retry.stdout).strip().splitlines()
    return False, detail[-1] if detail else "push failed"


def open_pr(git, branch, goal, body):
    """Create a draft PR, or refresh a checkpoint-owned PR body."""
    if not shutil.which("gh"):
        return None, "gh is not installed"
    listing = git.run("gh", "pr", "list", "--head", branch, "--state", "open",
                      "--json", "number,url,title,isDraft,body", check=False, timeout=90)
    if listing.returncode != 0:
        return None, (listing.stderr or "gh pr list failed").strip().splitlines()[-1]
    try:
        prs = json.loads(listing.stdout or "[]")
    except ValueError:
        prs = []
    if prs:
        pr = prs[0]
        if PR_MARKER in (pr.get("body") or "") and pr.get("isDraft", False):
            edit = git.run("gh", "pr", "edit", str(pr["number"]), "--body-file", "-",
                           check=False, timeout=90, input_text=body)
            if edit.returncode != 0:
                return pr, "PR exists; body refresh failed"
            return pr, "PR body refreshed"
        return pr, "PR exists (left untouched)"
    title = "WIP: " + trim(goal or "handoff checkpoint", 64)
    create = git.run("gh", "pr", "create", "--draft", "--base", "main", "--head", branch,
                     "--title", title, "--body-file", "-", check=False, timeout=120,
                     input_text=body)
    if create.returncode != 0:
        detail = (create.stderr or create.stdout).strip().splitlines()
        return None, detail[-1] if detail else "gh pr create failed"
    url = create.stdout.strip().splitlines()[-1]
    number = None
    match = re.search(r"/pull/(\d+)", url)
    if match:
        number = int(match.group(1))
    return {"number": number, "url": url}, "draft PR opened"


def pr_body(*, goal, next_step, done, changed, branch, updated, trigger, ratio,
            session, last_user, last_assistant):
    lines = [
        PR_MARKER,
        "> Automated checkpoint. Not ready to merge: this pull request exists so the",
        "> work survives an exhausted context, a dead session or a lost machine.",
        "",
        "## Goal",
        trim(goal or "Unknown", 600),
        "",
        "## Last request",
        trim(last_user or "Not captured", 600),
        "",
        "## Done",
    ]
    lines += ["- `" + item.split(" ", 1)[0] + "` " + trim(item.split(" ", 1)[-1], 200)
              for item in done[:8]] or ["- No commits yet; uncommitted changes were snapshotted."]
    lines += ["", "## Files changed"]
    lines += ["- `" + path + "`" for path in changed[:15]] or ["- (none)"]
    if len(changed) > 15:
        lines.append("- +" + str(len(changed) - 15) + " more (see the diff)")
    lines += [
        "",
        "## Next step",
        trim(next_step or "Read `.handoff/checkpoint.json` and continue.", 1200),
        "",
        "## Resume",
        "```sh",
        "git fetch origin",
        "git switch " + branch,
        "git diff main...HEAD",
        "python -m unittest discover -s tests",
        "python -m unittest discover -s portfolio-rebalance/tests",
        "```",
        "",
        "## Checkpoint metadata",
        "- Branch: `" + branch + "`",
        "- Session: `" + (session or "unknown") + "`",
        "- Trigger: `" + trigger + "`" + (" at " + str(int(round(ratio * 100))) + "% of context" if ratio else ""),
        "- Saved: " + stamp(updated),
        "- Full state: `.handoff/checkpoint.json`",
    ]
    if last_assistant:
        lines += ["", "## Last assistant message", "", "```text", trim(last_assistant, 2000), "```"]
    return "\n".join(lines) + "\n"


def read_state(path):
    if not path:
        return {}
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        data = json.loads(raw or "{}")
    except (OSError, ValueError) as exc:
        raise CheckpointError("could not read --state: " + str(exc))
    if not isinstance(data, dict):
        raise CheckpointError("--state must be a JSON object")
    return data


def acquire_lock(repo):
    lock = Path(repo) / LOCK_FILE
    if lock.exists():
        age = datetime.now().timestamp() - lock.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            return None
        lock.unlink(missing_ok=True)
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    os.close(descriptor)
    return lock


def in_progress_operation(repo):
    git_dir = Path(repo) / ".git"
    for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
        if (git_dir / name).exists():
            return name
    return ""


def checkpoint(args):
    repo = Path(args.repo).resolve()
    if not (repo / "HANDOFF.md").exists():
        # Any repository can be adopted, so seed a minimal handoff on first use.
        (repo / "HANDOFF.md").write_text(DEFAULT_HANDOFF, encoding="utf-8", newline="\n")
    state = read_state(args.state)
    git = Git(repo)
    if not git.has_commits():
        raise CheckpointError("repository has no commits")
    busy = in_progress_operation(repo)
    if busy:
        raise CheckpointError("a merge/rebase is in progress (" + busy + "); checkpoint skipped")

    session = str(state.get("session") or args.session or "")
    goal = redact(state.get("goal") or state.get("last_user") or args.goal or "")
    trigger = args.trigger or "manual"
    ratio = args.ratio if args.ratio is not None else state.get("ratio")
    branch_arg = args.branch

    if args.clear:
        branch = branch_arg or git.current_branch()
        if not branch:
            raise CheckpointError("cannot clear without a branch")
        text = (repo / "HANDOFF.md").read_text(encoding="utf-8")
        updated = remove_block(text, branch)
        if updated != text:
            (repo / "HANDOFF.md").write_text(updated, encoding="utf-8", newline="\n")
            git.run("git", "add", "HANDOFF.md")
            git.commit("Clear the open-work checkpoint for " + branch)
            if not args.dry_run and not args.no_push:
                push_branch(git, branch)
        return {"ok": True, "action": "cleared", "branch": branch}

    branch = branch_arg or ensure_branch(git, session, goal)
    before = changed_files(git)
    skipped = stage_changes(git)
    staged = git.run("git", "diff", "--cached", "--name-only").stdout.splitlines()
    if staged:
        message = "WIP: checkpoint " + trim(goal or "interrupted work", 60)
        message += "\n\nAutomatic checkpoint (" + trigger + "). Source: handoff watcher."
        if skipped:
            message += "\nLeft out secret-like paths: " + ", ".join(skipped)
        git.commit(message)

    done = commits_since_main(git)
    changed = sorted(dict.fromkeys(before + staged + [line for line in git.run(
        "git", "diff", "--name-only", "main...HEAD", check=False).stdout.splitlines() if line]))
    changed = [path for path in changed if not bookkeeping_path(path) and not secret_like(path)]
    next_step = redact(args.note or state.get("next") or guess_next(state.get("last_assistant") or "")
                       or "Read the checkpoint state, inspect the diff and continue.")

    updated_at = now_ist()
    text = (repo / "HANDOFF.md").read_text(encoding="utf-8")
    existing = ""
    existing_block = ""
    marker = BLOCK_START + branch + " -->"
    if marker in text:
        start = text.index(marker)
        end = text.find(BLOCK_END, start)
        existing_block = text[start:end + len(BLOCK_END)] if end >= 0 else ""
        tail = text.split(marker, 1)[1]
        match = re.search(r"^\s*- Next: (.*)$", tail, re.M)
        if match:
            existing = match.group(1).strip()
    if not args.note and not state.get("next") and existing:
        next_step = existing
    if not goal:
        goal = "Work in progress"

    fingerprint = work_fingerprint(branch=branch, goal=goal, next_step=next_step,
                                   done=done, changed=changed)
    if not staged and existing_block and ("open-work-fingerprint: " + fingerprint) in existing_block:
        return {"ok": True, "action": "noop", "branch": branch,
                "reason": "state is unchanged since the last checkpoint"}

    block = render_block(branch=branch, goal=goal, next_step=next_step, done=done,
                         changed=changed, pr=None, trigger=trigger, ratio=ratio,
                         updated=updated_at)
    (repo / "HANDOFF.md").write_text(upsert_block(text, block, branch),
                                     encoding="utf-8", newline="\n")

    state_dir = repo / STATE_DIR
    state_dir.mkdir(exist_ok=True)
    record = {
        "schema": 1,
        "saved": updated_at.isoformat(),
        "trigger": trigger,
        "ratio": ratio,
        "session": session,
        "model": state.get("model"),
        "branch": branch,
        "goal": goal,
        "next": next_step,
        "done": done,
        "changed": changed,
        "last_user": trim(redact(state.get("last_user") or ""), 4000),
        "last_assistant": trim(redact(state.get("last_assistant") or ""), 6000),
        "resume": "git fetch origin && git switch " + branch + " && git diff main...HEAD",
    }
    (state_dir / STATE_FILE).write_text(json.dumps(record, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    git.run("git", "add", "HANDOFF.md", STATE_DIR + "/" + STATE_FILE)
    if git.run("git", "diff", "--cached", "--quiet", check=False).returncode != 0:
        git.commit("Record handoff checkpoint for " + branch)

    result = {
        "ok": True,
        "action": "checkpoint",
        "branch": branch,
        "trigger": trigger,
        "ratio": ratio,
        "next": next_step,
        "done": done,
        "skipped_secret_paths": skipped,
        "pushed": False,
        "pr": None,
    }
    if args.dry_run:
        result["dry_run"] = True
        return result

    if not args.no_push:
        pushed, note = push_branch(git, branch)
        result["pushed"] = pushed
        result["push_note"] = note
        if pushed:
            body = pr_body(goal=goal, next_step=next_step, done=done, changed=changed,
                           branch=branch, updated=updated_at, trigger=trigger, ratio=ratio,
                           session=session, last_user=redact(state.get("last_user") or ""),
                           last_assistant=redact(state.get("last_assistant") or ""))
            pr, pr_note = open_pr(git, branch, goal, body)
            result["pr"] = pr
            result["pr_note"] = pr_note
            if pr:
                text = (repo / "HANDOFF.md").read_text(encoding="utf-8")
                block = render_block(branch=branch, goal=goal, next_step=next_step, done=done,
                                     changed=changed, pr=pr, trigger=trigger, ratio=ratio,
                                     updated=updated_at)
                (repo / "HANDOFF.md").write_text(upsert_block(text, block, branch),
                                                 encoding="utf-8", newline="\n")
                record["pr"] = pr
                (state_dir / STATE_FILE).write_text(json.dumps(record, indent=2) + "\n",
                                                    encoding="utf-8", newline="\n")
                git.run("git", "add", "HANDOFF.md", STATE_DIR + "/" + STATE_FILE)
                if git.run("git", "diff", "--cached", "--quiet", check=False).returncode != 0:
                    git.commit("Link handoff checkpoint to draft PR")
                    push_branch(git, branch)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--trigger", default="manual",
                        help="context, compaction, credits, error or manual")
    parser.add_argument("--ratio", type=float, default=None,
                        help="fraction of the model context window already used")
    parser.add_argument("--state", default="", help="JSON file with session, goal, last_user, last_assistant")
    parser.add_argument("--goal", default="")
    parser.add_argument("--note", default="", help="explicit next step for the next agent")
    parser.add_argument("--session", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--clear", action="store_true", help="remove the open-work block instead")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    lock = acquire_lock(args.repo)
    if lock is None:
        print(json.dumps({"ok": True, "action": "skipped", "reason": "another checkpoint is running"}))
        return 0
    try:
        result = checkpoint(args)
        print(json.dumps(result, default=str))
        return 0 if result.get("ok") else 2
    except CheckpointError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
