"""Tests for the pure Codex quota detector (no live DB, no model calls)."""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handoff"))
import handoff_quota as quota  # noqa: E402

UUID_FULL = "01a21bbf-de86-7753-937d-fdeb6048b7b7"
UUID_TIME = "01a21c93-fb1a-7572-91ad-9af98eb039ba"
CWD_FULL = (r"C:\Users\Pranav\Documents\Codex\2026-11-27"
            r"\vm-handoff-oracle-cloud-instance-not")
CWD_TIME = r"C:\Users\Pranav\Documents\Codex\2026-11-27\other-session"
SECRET_CANARY = "sk-CANARY-NEVER-PRINT-4f81c2"
PROMPT_CANARY = "the secret prompt says never reveal this text"


def epoch(year, month, day, hour=0, minute=0, second=0):
    return dt.datetime(year, month, day, hour, minute, second).timestamp()


def log_body(session_id, phrase):
    # U+FFFD is how the apostrophe in "You've" appears in the real log DB.
    return ("\ufffdd You\ufffdve hit your usage limit for this model. "
            "try again at " + phrase + ". conversation.id=" + session_id + ". "
            + SECRET_CANARY + " " + PROMPT_CANARY)


def rollout(path, cwd):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"cwd": cwd, "source": "cli"},
    }) + "\n" + json.dumps({
        "type": "user_message",
        "payload": {"text": SECRET_CANARY + " " + PROMPT_CANARY},
    }) + "\n", encoding="utf-8", newline="\n")


class QuotaDetectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.db_file = self.root / "logs_2.sqlite"

        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, "
            "feedback_log_body TEXT)")
        self.rows = [
            (876270, epoch(2026, 11, 27, 23, 46, 56),
             log_body(UUID_FULL, "Nov 28th, 2026 3:04 AM")),
            (756652, epoch(2026, 11, 27, 16, 6, 40),
             log_body(UUID_TIME, "5:36 PM")),
        ]
        self.connection.executemany(
            "INSERT INTO logs (id, ts, feedback_log_body) VALUES (?, ?, ?)",
            self.rows)
        self.connection.commit()

        rollout(self.sessions / "2026" / "11" / "27" /
                ("rollout-2026-11-27T12-14-48-" + UUID_FULL + ".jsonl"), CWD_FULL)
        rollout(self.sessions / "2026" / "11" / "27" /
                ("rollout-2026-11-27T16-06-29-" + UUID_TIME + ".jsonl"), CWD_TIME)

    def test_parse_full_date_shape(self):
        self.assertEqual(
            quota.parse_reset_at(self.rows[0][2], reference_epoch=self.rows[0][1]),
            "2026-11-28T03:04",
        )

    def test_parse_time_only_shape_and_roll_forward(self):
        self.assertEqual(
            quota.parse_reset_at(self.rows[1][2], reference_epoch=self.rows[1][1]),
            "2026-11-27T17:36",
        )
        past = epoch(2026, 11, 27, 18, 0)
        self.assertEqual(quota.parse_reset_at(self.rows[1][2], reference_epoch=past),
                         "2026-11-28T17:36")

    def test_scan_returns_known_events_with_cwds(self):
        events = quota.scan(connection=self.connection, sessions_dir=self.sessions,
                            dry_run=True)
        self.assertEqual([event["log_id"] for event in events], [756652, 876270])
        self.assertEqual(events[0]["session_id"], UUID_TIME)
        self.assertEqual(events[0]["reset_at"], "2026-11-27T17:36")
        self.assertEqual(events[0]["cwd"], CWD_TIME)
        self.assertEqual(events[1]["session_id"], UUID_FULL)
        self.assertEqual(events[1]["reset_at"], "2026-11-28T03:04")
        self.assertEqual(events[1]["cwd"], CWD_FULL)
        self.assertTrue(all(event["dry_run"] for event in events))

    def test_resolve_cwd_warns_and_skips_compressed_rollout(self):
        compressed = self.sessions / "2026" / "11" / "27" / (
            "rollout-2026-11-27T16-00-00-" + UUID_TIME + ".jsonl.zst")
        compressed.write_bytes(b"not opened\n")
        warnings = []
        found = quota.resolve_cwd(UUID_TIME, self.sessions,
                                  warn=warnings.append)
        self.assertEqual(found, CWD_TIME)
        self.assertTrue(any("compressed rollout skipped" in w for w in warnings))

    def test_no_secret_leak_or_state_write(self):
        before = {path.relative_to(self.root) for path in self.root.rglob("*")}
        events = quota.scan(connection=self.connection, sessions_dir=self.sessions)
        report = json.dumps({"events": events})
        for canary in (SECRET_CANARY, PROMPT_CANARY, "feedback_log_body"):
            self.assertNotIn(canary, report)

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(quota, "scan", return_value=events), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = quota.main(["--scan", "--dry-run", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertTrue(parsed["dry_run"])
        self.assertEqual(len(parsed["events"]), 2)
        for canary in (SECRET_CANARY, PROMPT_CANARY):
            self.assertNotIn(canary, stdout.getvalue())
            self.assertNotIn(canary, stderr.getvalue())
        after = {path.relative_to(self.root) for path in self.root.rglob("*")}
        self.assertEqual(after, before, "detector must not write state files")

    def test_db_uri_is_always_read_only(self):
        uri = quota.db_uri(self.db_file)
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro"))
        self.assertNotIn("mode=rw", uri)


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Records calls instead of launching any CLI or model."""

    def __init__(self, on_run=None, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.on_run = on_run
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def run(self, args, cwd=None):
        args = [str(a) for a in args]
        self.calls.append((args, cwd))
        if self.on_run is not None:
            self.on_run(args, cwd)
        return FakeResult(self.returncode, self.stdout, self.stderr)


class QuotaResumeTest(unittest.TestCase):
    """Ticket 02: state, checkpoint dedupe, brief and crash-safe resume."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_root = self.root / "agent-handoff"
        self.state_root.mkdir()
        self.repo = self.root / "repo"
        (self.repo / ".handoff").mkdir(parents=True)
        (self.repo / "HANDOFF.md").write_text(
            "## Open work\n" + SECRET_CANARY + "\nfinish the ticket\n\n"
            "## Done\nolder work\n", encoding="utf-8", newline="\n")
        (self.repo / ".handoff" / "checkpoint.json").write_text(
            json.dumps({"goal": "resume", "last_user": SECRET_CANARY}),
            encoding="utf-8", newline="\n")
        self.now = epoch(2026, 11, 28, 4, 0)
        self.events = [{
            "log_id": 111, "session_id": UUID_FULL,
            "reset_at": "2026-11-28T03:04", "cwd": str(self.repo),
        }]
        self.key = quota.event_key(self.events[0])

    def test_checkpoint_once_per_event_and_dedupe(self):
        fake = FakeRunner()
        state = {}
        state, _ = quota.checkpoint(self.events, state, runner=fake,
                                    handoff_py=self.root / "handoff.py", now=self.now)
        self.assertEqual(len(fake.calls), 1)
        command, cwd = fake.calls[0]
        self.assertEqual(command[command.index("--trigger") + 1], "credits")
        self.assertIn("Codex quota exhausted; resume at 2026-11-28T03:04", command)
        self.assertEqual(cwd, str(self.repo))
        self.assertEqual(state[self.key]["status"], "pending")
        state, actions = quota.checkpoint(self.events, state, runner=fake, now=self.now)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(actions[0]["action"], "checkpoint-deduped")

    def test_resuming_persisted_before_launch_and_no_second_resume(self):
        state, _ = quota.checkpoint(self.events, {}, runner=FakeRunner(), now=self.now)
        seen = []

        def on_run(args, cwd):
            disk = quota.load_state(self.state_root)
            seen.append(disk.get(self.key, {}).get("status"))

        fake = FakeRunner(on_run=on_run)
        state, _ = quota.resume_due(self.events, state, root=self.state_root,
                                    runner=fake, now=self.now)
        self.assertEqual(seen, ["resuming"])
        self.assertEqual(len(fake.calls), 1)
        command = fake.calls[0][0]
        self.assertEqual(command[:4], ["codex", "exec", "resume", UUID_FULL])
        self.assertEqual(state[self.key]["status"], "done")
        self.assertTrue(quota.resume_log_path(self.state_root).exists())
        log = quota.resume_log_path(self.state_root).read_text(encoding="utf-8")
        self.assertNotIn(SECRET_CANARY, log)

        # Crash between the state write and the launch leaves status=resuming.
        disk = quota.load_state(self.state_root)
        disk[self.key]["status"] = "resuming"
        quota.save_state(disk, self.state_root)
        fake2 = FakeRunner()
        quota.resume_due(self.events, disk, root=self.state_root, runner=fake2,
                         now=self.now)
        self.assertEqual(fake2.calls, [])

    def test_dry_run_launches_nothing_and_brief_is_redacted(self):
        fake = FakeRunner()
        state, checkpoint_actions = quota.checkpoint(self.events, {}, runner=fake,
                                                     dry_run=True, now=self.now)
        state, resume_actions = quota.resume_due(self.events, state,
                                                 root=self.state_root, runner=fake,
                                                 dry_run=True, now=self.now)
        self.assertEqual(fake.calls, [])
        self.assertIn("checkpoint-planned", [a["action"] for a in checkpoint_actions])
        self.assertIn("resume-planned", [a["action"] for a in resume_actions])
        brief = (self.state_root / "quota-brief-111.md").read_text(encoding="utf-8")
        self.assertNotIn(SECRET_CANARY, brief)
        self.assertNotIn(PROMPT_CANARY, brief)
        self.assertIn("No live trade", brief)
        self.assertIn("No billing change", brief)
        self.assertIn("No force-push", brief)
        self.assertFalse(quota.state_path(self.state_root).exists())

    def test_redaction_and_launch_guardrail(self):
        sample = ("gho_abcdef123456 github_pat_abcdef123456 sk-abcdef123456 "
                  "Bearer abcdef123456 AKIAABCDEFGHIJKLMNOP "
                  "eyJabcdefghij.eyJabcdefghij.abcdefghij " + "a" * 40)
        redacted = quota.redact(sample)
        for token in ("gho_abcdef123456", "github_pat_abcdef123456",
                      "sk-abcdef123456", "Bearer", "AKIAABCDEFGHIJKLMNOP",
                      "eyJabcdefghij.eyJabcdefghij.abcdefghij", "a" * 40):
            self.assertNotIn(token, redacted)
        self.assertIn("[REDACTED]", redacted)
        self.assertTrue(quota.is_safe_launch(["codex", "exec", "resume", UUID_FULL, "brief"]))
        self.assertFalse(quota.is_safe_launch(["codex", "--force", "resume", "brief"]))

    def test_resume_now_waits_for_reset_then_launches(self):
        future = dict(self.events[0], reset_at="2099-01-01T00:00")
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = quota.resume_now_mode(events=[future], repo=str(self.repo),
                                         root=self.state_root, runner=fake,
                                         cli_path="codex", now=self.now)
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn("not reset yet", stdout.getvalue())

        fake2 = FakeRunner()
        stdout2 = io.StringIO()
        with contextlib.redirect_stdout(stdout2):
            code = quota.resume_now_mode(events=self.events, repo=str(self.repo),
                                         root=self.state_root, runner=fake2,
                                         cli_path="codex", now=self.now)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake2.calls), 2)  # checkpoint save, then resume
        self.assertIn("save", fake2.calls[0][0])
        self.assertEqual(fake2.calls[1][0][0], "codex")

    def test_poll_mode_dry_run_does_not_persist_or_launch(self):
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = quota.poll_mode(events=self.events, root=self.state_root,
                                   runner=fake, dry_run=True, now=self.now)
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn("dry-run", stdout.getvalue())
        self.assertFalse(quota.state_path(self.state_root).exists())

    def test_cli_path_from_config_is_read_only(self):
        cfg = self.root / "config.toml"
        cfg.write_text(r"CODEX_CLI_PATH = 'C:\codex.exe'" + "\n",
                       encoding="utf-8", newline="\n")
        self.assertEqual(quota.cli_path_from_config(cfg), r"C:\codex.exe")
        self.assertEqual(quota.cli_path_from_config(self.root / "missing.toml"), "codex")

    def test_subprocess_runner_runs_harmless_local_command(self):
        # A Python one-liner is not a model call; it only covers the real runner.
        result = quota.SubprocessRunner().run([sys.executable, "-c", "print(4242)"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("4242", result.stdout)

    def test_brief_guardrail_blocks_launch(self):
        self.assertTrue(quota.brief_has_guardrails(quota.build_brief(self.events[0])))
        state, _ = quota.checkpoint(self.events, {}, runner=FakeRunner(), now=self.now)
        fake = FakeRunner()
        with patch.object(quota, "build_brief", return_value="brief without guardrails"):
            state, actions = quota.resume_due(self.events, state, root=self.state_root,
                                              runner=fake, now=self.now)
        self.assertEqual(fake.calls, [])
        self.assertEqual(state[self.key]["status"], "error")
        self.assertEqual(actions[-1]["action"], "resume-refused")

    def test_resume_now_refuses_done_or_resuming(self):
        for status in ("done", "resuming"):
            with self.subTest(status=status):
                state, _ = quota.checkpoint(self.events, {}, runner=FakeRunner(),
                                            now=self.now)
                state[self.key]["status"] = status
                quota.save_state(state, self.state_root)
                fake = FakeRunner()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = quota.resume_now_mode(events=self.events, repo=str(self.repo),
                                                 root=self.state_root, runner=fake,
                                                 cli_path="codex", now=self.now)
                self.assertEqual(code, 0)
                self.assertEqual(fake.calls, [])
                self.assertIn("no relaunch", stdout.getvalue())

    def test_poll_dry_run_honours_done_state(self):
        state, _ = quota.checkpoint(self.events, {}, runner=FakeRunner(), now=self.now)
        state[self.key]["status"] = "done"
        quota.save_state(state, self.state_root)
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            quota.poll_mode(events=self.events, root=self.state_root, runner=fake,
                            dry_run=True, now=self.now)
        self.assertNotIn("resume-planned", stdout.getvalue())
        self.assertIn("checkpoint-deduped", stdout.getvalue())
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
