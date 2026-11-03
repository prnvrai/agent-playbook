"""Keep a checkpoint current without depending on any agent or editor.

The watcher polls the working tree, and whenever the content, the index or HEAD
changes it asks `handoff_checkpoint.py` for a snapshot. That makes the mechanism
independent of the LLM: OpenCode, Codex, Claude Code, Gemini, Cursor, Aider or a
human editing in Notepad all get the same behaviour.

It is started by the git hooks in `.githooks/` and by the per-user autostart
entry that `handoff_install.py` registers, so a new session never has to opt in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from handoff_checkpoint import Git, NO_WINDOW, STATE_DIR  # noqa: E402

HERE = Path(__file__).resolve()
CHECKPOINT = HERE.with_name("handoff_checkpoint.py")
DEFAULT_INTERVAL = 20
DEFAULT_SETTLE = 8
DEFAULT_IDLE_EXIT = 12 * 60 * 60


def gui_python():
    """A Python with no console window, so background work stays invisible."""
    if os.name != "nt":
        return Path(sys.executable)
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def git_dir(repo):
    result = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(repo),
                            capture_output=True, text=True, encoding="utf-8",
                            creationflags=NO_WINDOW)
    if result.returncode != 0:
        return Path(repo) / ".git"
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else (Path(repo) / path)


def pid_path(repo):
    return git_dir(repo) / "handoff-watch.pid"


def log_path(repo):
    return Path(repo) / STATE_DIR / "watch.log"


def pid_alive(pid):
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return code.value == 259  # STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def running(repo):
    path = pid_path(repo)
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0
    if pid_alive(pid):
        return pid
    path.unlink(missing_ok=True)
    return 0


def log(repo, message):
    path = log_path(repo)
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def repo_signature(repo):
    """Hash the parts of the repository that a checkpoint must capture."""
    git = Git(repo)
    parts = [
        git.run("git", "rev-parse", "HEAD", check=False).stdout.strip(),
        git.run("git", "status", "--porcelain=v1", "-z",
                "--untracked-files=all", check=False).stdout,
        git.run("git", "diff", "--binary", check=False).stdout,
        git.run("git", "diff", "--cached", "--binary", check=False).stdout,
    ]
    status = git.run("git", "status", "--porcelain=v1", "-z",
                     "--untracked-files=all", check=False).stdout
    for entry in status.split("\0"):
        if not entry.startswith("?? "):
            continue
        path = Path(repo) / entry[3:]
        try:
            stat = path.stat()
        except OSError:
            continue
        parts.append(entry[3:] + ":" + str(stat.st_size) + ":" + str(int(stat.st_mtime)))
    return hashlib.sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()


def has_work(repo):
    """True when there is something a checkpoint should actually record."""
    git = Git(repo)
    if git.run("git", "status", "--porcelain", "--untracked-files=all",
               check=False).stdout.strip():
        return True
    branch = git.run("git", "branch", "--show-current", check=False).stdout.strip()
    if not branch or branch in ("main", "master"):
        return False
    try:
        record = json.loads((Path(repo) / STATE_DIR / "checkpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    if record.get("branch") == branch:
        return True
    base = "origin/main" if git.run("git", "rev-parse", "--verify", "origin/main",
                                    check=False).returncode == 0 else "main"
    ahead = git.run("git", "rev-list", "--count", base + "..HEAD", check=False).stdout.strip()
    return ahead not in ("", "0")


def snapshot(repo, trigger="watch"):
    """Run one checkpoint and return its parsed result."""
    result = subprocess.run(
        [sys.executable, str(CHECKPOINT), "--repo", str(repo), "--trigger", trigger],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, creationflags=NO_WINDOW,
    )
    line = (result.stdout or "").strip().splitlines()
    try:
        payload = json.loads(line[-1]) if line else {}
    except ValueError:
        payload = {"ok": False, "raw": (result.stdout or result.stderr or "")[-400:]}
    if result.returncode != 0 and payload.get("ok"):
        payload["ok"] = False
    return payload


def loop(repo, interval, settle, idle_exit):
    pid = pid_path(repo)
    pid.write_text(str(os.getpid()), encoding="ascii")
    log(repo, "watcher started in " + str(repo))
    last_signature = None
    checkpointed = None
    changed_at = time.time()
    try:
        while True:
            signature = repo_signature(repo)
            now = time.time()
            if signature != last_signature:
                last_signature = signature
                changed_at = now
            elif signature != checkpointed and now - changed_at >= settle:
                if not has_work(repo):
                    checkpointed = signature
                    last_signature = signature
                    changed_at = now
                    time.sleep(interval)
                    continue
                result = snapshot(repo)
                checkpointed = repo_signature(repo)
                last_signature = checkpointed
                changed_at = now
                action = result.get("action") or ("error: " + str(result.get("error")))
                log(repo, "checkpoint " + action + " branch=" + str(result.get("branch")))
            if idle_exit and now - changed_at > idle_exit:
                log(repo, "idle exit")
                break
            time.sleep(interval)
    finally:
        try:
            if pid.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid.unlink(missing_ok=True)
        except OSError:
            pass


def ensure(repo):
    """Start the watcher detached unless it is already running."""
    pid = running(repo)
    if pid:
        return pid, "already running"
    state = Path(repo) / STATE_DIR
    state.mkdir(exist_ok=True)
    logfile = log_path(repo)
    handle = logfile.open("a", encoding="utf-8")
    kwargs = {
        "cwd": str(repo), "stdin": subprocess.DEVNULL, "stdout": handle,
        "stderr": handle, "close_fds": True,
    }
    if os.name == "nt":
        # DETACHED_PROCESS | NEW_PROCESS_GROUP | CREATE_NO_WINDOW. The last flag
        # keeps every child (git, gh, checkpoint) off the desktop.
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        [str(gui_python()), str(HERE), "--repo", str(repo), "--foreground"], **kwargs)
    pid_path(repo).write_text(str(process.pid), encoding="ascii")
    handle.close()
    return process.pid, "started"


def stop(repo):
    pid = running(repo)
    if not pid:
        return False, "not running"
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=NO_WINDOW)
        else:
            os.kill(pid, 15)
    except OSError as exc:
        return False, str(exc)
    pid_path(repo).unlink(missing_ok=True)
    log(repo, "watcher stopped")
    return True, "stopped"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(HERE.parents[1]))
    parser.add_argument("--ensure", action="store_true", help="start in the background if needed")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("--once", action="store_true", help="take one checkpoint if needed, then exit")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--settle", type=int, default=DEFAULT_SETTLE)
    parser.add_argument("--idle-exit", type=int, default=DEFAULT_IDLE_EXIT)
    args = parser.parse_args(argv)
    repo = str(Path(args.repo).resolve())

    if args.ensure:
        pid, note = ensure(repo)
        print(json.dumps({"ok": True, "pid": pid, "note": note}))
        return 0
    if args.stop:
        ok, note = stop(repo)
        print(json.dumps({"ok": ok, "note": note}))
        return 0 if ok else 1
    if args.status:
        pid = running(repo)
        print(json.dumps({"ok": True, "running": bool(pid), "pid": pid}))
        return 0
    if args.once:
        signature = repo_signature(repo)
        if not has_work(repo):
            print(json.dumps({"ok": True, "action": "noop", "reason": "no unsaved work",
                              "signature": signature}))
            return 0
        result = snapshot(repo, "watch")
        print(json.dumps({"ok": result.get("ok", False), "signature": signature,
                          "result": result}))
        return 0 if result.get("ok") else 2
    loop(repo, max(2, args.interval), max(0, args.settle), max(0, args.idle_exit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
