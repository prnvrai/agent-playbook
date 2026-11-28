"""Install the universal handoff plumbing for this clone.

One command wires the repository so that *any* agent, editor or human is covered:

- wake-up hooks are copied into the active hooks directory (never replacing an
  existing hook), so commit/checkout/merge/push start the watcher.
- `handoff_watch.py` runs detached and snapshots changes to a `wip/` branch.
- a per-user autostart entry restarts the watcher every few minutes, so a fresh
  session is covered even if it never runs a git command.

The autostart entry lives outside the repository (Task Scheduler, launchd or a
systemd user timer) because no in-repo mechanism can start before an agent does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[1]
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
WATCH = HERE.with_name("handoff_watch.py")
QUOTA = HERE.with_name("handoff_quota.py")
WAKE_HOOKS = ("post-commit", "post-checkout", "post-merge", "pre-push")

# --- Ticket 03: quota watchdog install (opt-in, one-way door) ----------------
QUOTA_TASK_PREFIX = "agent-handoff-quota-"
CHAT_COMMAND = Path.home() / ".config" / "opencode" / "commands" / "resume-codex.md"
CRON_NOTE = Path.home() / ".agent-handoff" / "quota-cron-note.md"

# The OpenCode automation is *documented*, never registered by this installer.
# No automation API is called anywhere in this file.
QUOTA_CRON = {
    "name": "agent-handoff-quota",
    "schedule": "*/5 * * * *",
    "every_minutes": 5,
    "intent": "Poll quota state every 5 minutes and notify; no agent launch, "
              "no credit spend and no automation registration without owner approval.",
    "registration": "manual, by the owner, through the OpenCode automation UI",
}
CHAT_COMMAND_TEXT = """---
description: Check quota state and resume a handoff when the reset has passed
---
Run `python "%USERPROFILE%\\.agent-handoff\\handoff_quota.py" --resume-now` yourself
(macOS/Linux: `python ~/.agent-handoff/handoff_quota.py --resume-now`) and report the
real command output verbatim. Do not guess the output, do not spend credits on a
probe, do not edit agent config, and do not enable unattended spend or automation
without explicit owner approval.
"""
CRON_NOTE_TEXT = """# Quota watchdog cron (planned, not registered)

- Automation name: agent-handoff-quota
- Schedule: */5 * * * * (every 5 minutes)
- Intent: poll quota state and notify. No agent launch, no credit spend, no
  billing change and no API-driven registration without explicit owner approval.
- The installer never calls an automation API. Registration and cancellation are
  manual, through the OpenCode automation UI.
- Windows counterpart: Task Scheduler task agent-handoff-quota-<repo-id>,
  every 5 minutes, running `pythonw ... handoff_quota.py --poll`.

"""


def quota_task_name(repo):
    return QUOTA_TASK_PREFIX + task_id(repo)


def quota_task_command(repo):
    return '"' + str(pythonw()) + '" "' + str(QUOTA) + '" --poll'


def quota_plan(repo):
    return {
        "scheduler": {
            "task": quota_task_name(repo),
            "schedule": {"type": "MINUTE", "modulo": 5},
            "command": quota_task_command(repo),
            "create": ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5",
                       "/TN", quota_task_name(repo), "/TR", quota_task_command(repo)],
        },
        "cron": dict(QUOTA_CRON),
        "cron_note": str(CRON_NOTE),
        "chat_command": {"path": str(CHAT_COMMAND), "text": CHAT_COMMAND_TEXT},
    }


def has_quota_task(repo):
    result = run("schtasks", "/Query", "/TN", quota_task_name(repo), timeout=30)
    return result.returncode == 0


def write_quota_files():
    """Write only our own note/chat command, and only when content differs."""
    written = []
    for path, text in ((CRON_NOTE, CRON_NOTE_TEXT), (CHAT_COMMAND, CHAT_COMMAND_TEXT)):
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(str(path))
    return written


def install_quota(repo, dry_run=True, apply=False):
    """Idempotent and dry-run by default; only --apply may call schtasks /Create."""
    plan = quota_plan(repo)
    if dry_run or not apply:
        return {"dry_run": True, "applied": False, "plan": plan,
                "note": "pass --apply with explicit owner approval to register"}
    create = run("schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5",
                 "/TN", quota_task_name(repo), "/TR", quota_task_command(repo), timeout=60)
    if create.returncode != 0:
        return {"dry_run": False, "applied": False, "task": quota_task_name(repo),
                "error": (create.stderr or create.stdout).strip()[-300:]}
    return {"dry_run": False, "applied": True, "task": quota_task_name(repo),
            "every_minutes": 5, "files_written": write_quota_files(),
            "cron": "documented only; owner registers manually"}


def uninstall_quota(repo, dry_run=False):
    """Remove the scheduler task and only our chat command file."""
    if dry_run:
        return {"dry_run": True, "applied": False,
                "task": quota_task_name(repo), "delete": ["schtasks", "/Delete", "/F",
                                                          "/TN", quota_task_name(repo)],
                "chat_command_remove": str(CHAT_COMMAND)}
    delete = run("schtasks", "/Delete", "/F", "/TN", quota_task_name(repo), timeout=30)
    removed_file = False
    kept_foreign = False
    if CHAT_COMMAND.is_file():
        try:
            content = CHAT_COMMAND.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        if content == CHAT_COMMAND_TEXT:
            CHAT_COMMAND.unlink(missing_ok=True)
            removed_file = True
        else:
            # Never delete a file we did not write at that path.
            kept_foreign = True
    return {"dry_run": False, "removed_task": delete.returncode == 0,
            "chat_command_removed": removed_file, "chat_command_kept": kept_foreign,
            "cron": "note kept as record; owner cancels the automation manually"}


def quota_status(repo):
    return {
        "scheduler_task": has_quota_task(repo),
        "task_name": quota_task_name(repo),
        "cron_note": {"present": CRON_NOTE.is_file(), "path": str(CRON_NOTE),
                      "schedule": QUOTA_CRON["schedule"],
                      "registered_by_installer": False},
        "chat_command": {"present": CHAT_COMMAND.is_file(), "path": str(CHAT_COMMAND)},
    }


def task_id(repo):
    return hashlib.sha256(str(Path(repo).resolve()).lower().encode("utf-8")).hexdigest()[:10]


def run(*args, timeout=60):
    return subprocess.run(list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NO_WINDOW)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60,
                          creationflags=NO_WINDOW)


def hooks_path(repo):
    result = git(repo, "config", "--get", "core.hooksPath")
    return result.stdout.strip()


def effective_hooks_dir(repo):
    """Where git actually looks for hooks, honouring an existing hooksPath."""
    configured = hooks_path(repo)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else Path(repo) / path
    return Path(repo) / ".git" / "hooks"


def hook_source(repo):
    """Find the wake hooks next to the repository or next to this script."""
    for candidate in (Path(repo) / ".githooks", HERE.parent / ".githooks"):
        probe = candidate / "post-commit"
        if probe.is_file() and "handoff_watch.py" in probe.read_text(
                encoding="utf-8", errors="replace"):
            return candidate
    return Path(repo) / ".githooks"


def install_hooks(repo):
    """Copy only the wake-up hooks; never activate or replace other hooks."""
    target = effective_hooks_dir(repo)
    target.mkdir(parents=True, exist_ok=True)
    source = hook_source(repo)
    installed, skipped = [], []
    for name in WAKE_HOOKS:
        origin = source / name
        if not origin.is_file():
            skipped.append(name)
            continue
        destination = target / name
        if destination.exists() and "handoff_watch.py" not in destination.read_text(
                encoding="utf-8", errors="replace"):
            skipped.append(name + " (existing hook kept)")
            continue
        shutil.copy2(origin, destination)
        try:
            destination.chmod(0o755)
        except OSError:
            pass
        installed.append(name)
    return {"dir": str(target), "installed": installed, "skipped": skipped,
            "hooksPath": hooks_path(repo) or None}


def pythonw():
    """Python without a console, so a scheduled run never shows a window."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def autostart_windows(repo):
    name = "agent-handoff-" + task_id(repo)
    command = ('"' + str(pythonw()) + '" "' + str(WATCH) + '" --ensure --repo "'
               + str(repo) + '"')
    create = run("schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5",
                 "/TN", name, "/TR", command, timeout=60)
    if create.returncode != 0:
        return {"installed": False, "name": name,
                "error": (create.stderr or create.stdout).strip()[-300:]}
    return {"installed": True, "name": name, "every_minutes": 5}


def autostart_macos(repo):
    label = "com.agent-handoff." + task_id(repo)
    folder = Path.home() / "Library" / "LaunchAgents"
    folder.mkdir(parents=True, exist_ok=True)
    plist = folder / (label + ".plist")
    log = Path(repo) / ".handoff" / "watch.log"
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string><string>{WATCH}</string>
    <string>--ensure</string><string>--repo</string><string>{repo}</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""", encoding="utf-8", newline="\n")
    run("launchctl", "unload", str(plist), timeout=30)
    result = run("launchctl", "load", "-w", str(plist), timeout=30)
    return {"installed": result.returncode == 0, "name": label,
            "path": str(plist), "error": (result.stderr or "").strip()[-300:]}


def autostart_linux(repo):
    label = "agent-handoff-" + task_id(repo)
    folder = Path.home() / ".config" / "systemd" / "user"
    folder.mkdir(parents=True, exist_ok=True)
    log = Path(repo) / ".handoff" / "watch.log"
    service = folder / (label + ".service")
    service.write_text(
        "[Unit]\nDescription=Agent-agnostic handoff watcher\n\n"
        "[Service]\nType=oneshot\n"
        "ExecStart=" + shlex_join([sys.executable, str(WATCH), "--ensure", "--repo", str(repo)]) + "\n"
        "StandardOutput=append:" + str(log) + "\n"
        "StandardError=append:" + str(log) + "\n", encoding="utf-8", newline="\n")
    timer = folder / (label + ".timer")
    timer.write_text(
        "[Unit]\nDescription=Keep the agent-agnostic handoff watcher alive\n\n"
        "[Timer]\nOnBootSec=2min\nOnUnitActiveSec=5min\n"
        "\n[Install]\nWantedBy=timers.target\n", encoding="utf-8", newline="\n")
    if run("systemctl", "--user", "daemon-reload", timeout=30).returncode != 0:
        return {"installed": False, "name": label, "path": str(timer),
                "error": "systemd user session is unavailable"}
    result = run("systemctl", "--user", "enable", "--now", label + ".timer", timeout=30)
    return {"installed": result.returncode == 0, "name": label, "path": str(timer),
            "error": (result.stderr or "").strip()[-300:]}


def shlex_join(parts):
    return " ".join('"' + part.replace('"', '\\"') + '"' if " " in part else part for part in parts)


def autostart(repo):
    if os.name == "nt":
        return autostart_windows(repo)
    if sys.platform == "darwin":
        return autostart_macos(repo)
    return autostart_linux(repo)


def remove_autostart(repo):
    if os.name == "nt":
        name = "agent-handoff-" + task_id(repo)
        result = run("schtasks", "/Delete", "/F", "/TN", name, timeout=30)
        return {"removed": result.returncode == 0, "name": name}
    if sys.platform == "darwin":
        label = "com.agent-handoff." + task_id(repo)
        plist = Path.home() / "Library" / "LaunchAgents" / (label + ".plist")
        run("launchctl", "unload", str(plist), timeout=30)
        plist.unlink(missing_ok=True)
        return {"removed": True, "name": label}
    label = "agent-handoff-" + task_id(repo)
    run("systemctl", "--user", "disable", "--now", label + ".timer", timeout=30)
    folder = Path.home() / ".config" / "systemd" / "user"
    (folder / (label + ".timer")).unlink(missing_ok=True)
    (folder / (label + ".service")).unlink(missing_ok=True)
    run("systemctl", "--user", "daemon-reload", timeout=30)
    return {"removed": True, "name": label}


def status(repo):
    watch = run(sys.executable, str(WATCH), "--status", "--repo", str(repo), timeout=30)
    try:
        watcher = json.loads(watch.stdout.strip() or "{}")
    except ValueError:
        watcher = {"running": False}
    hooks = effective_hooks_dir(repo)
    hooks_ok = all((hooks / name).exists() for name in WAKE_HOOKS)
    return {"hooks_path": hooks_path(repo) or None, "hooks_dir": str(hooks),
            "hooks_ready": hooks_ok, "watcher": watcher,
            "autostart": has_autostart(repo), "quota": quota_status(repo)}


def has_autostart(repo):
    if os.name == "nt":
        result = run("schtasks", "/Query", "/TN", "agent-handoff-" + task_id(repo), timeout=30)
        return result.returncode == 0
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "LaunchAgents"
                / ("com.agent-handoff." + task_id(repo) + ".plist")).exists()
    return (Path.home() / ".config" / "systemd" / "user"
            / ("agent-handoff-" + task_id(repo) + ".timer")).exists()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--check", "--status", dest="check", action="store_true",
                        help="print status (including quota install) as JSON")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--install-quota", action="store_true",
                        help="plan the opt-in quota watchdog (dry-run by default)")
    parser.add_argument("--apply", action="store_true",
                        help="required with --install-quota to actually register")
    parser.add_argument("--uninstall-quota", action="store_true",
                        help="remove the quota scheduler task and chat command")
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the quota plan without registering anything")
    args = parser.parse_args(argv)
    repo = str(Path(args.repo).resolve())

    if args.check:
        print(json.dumps(status(repo), indent=2))
        return 0
    if args.install_quota:
        register = bool(args.apply) and not args.dry_run
        print(json.dumps(install_quota(repo, dry_run=not register, apply=register), indent=2))
        return 0
    if args.uninstall_quota:
        print(json.dumps(uninstall_quota(repo, dry_run=args.dry_run), indent=2))
        return 0
    if args.uninstall:
        stopped = run(sys.executable, str(WATCH), "--stop", "--repo", repo, timeout=30)
        removed = remove_autostart(repo)
        target = effective_hooks_dir(repo)
        for name in WAKE_HOOKS:
            hook = target / name
            if hook.is_file() and "handoff_watch.py" in hook.read_text(
                    encoding="utf-8", errors="replace"):
                hook.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "watcher": stopped.stdout.strip(),
                          "autostart": removed, "hooks_removed": list(WAKE_HOOKS)}, indent=2))
        return 0

    installed = install_hooks(repo)
    started = run(sys.executable, str(WATCH), "--ensure", "--repo", repo, timeout=30)
    autostart_result = {"installed": False, "skipped": True}
    if not args.no_autostart:
        autostart_result = autostart(repo)
    print(json.dumps({
        "ok": True,
        "repo": repo,
        "hooks": installed,
        "watcher": started.stdout.strip(),
        "autostart": autostart_result,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
