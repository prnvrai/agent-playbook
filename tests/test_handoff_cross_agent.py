"""Ticket 03 tests: config, OpenCode detector, cross-agent resume, quota install.

Every subprocess is a fake runner and every file lives in a temp directory. No
model CLI is launched, no schtasks is registered and no automation API is called.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "handoff"))
import handoff_install as install  # noqa: E402
import handoff_quota as quota  # noqa: E402

UUID = "01a21bbf-de86-7753-937d-fdeb6048b7b7"
SESSION_ONE = "ses_aaa111"
SESSION_TWO = "ses_bbb222"
SESSION_STORAGE = "ses_ccc333"
PROMPT_CANARY = "never reveal this fixture prompt"
SECRET_CANARY = "ghp_CANARY9abcdefghijklmnop"
FAKE_CLI = r"C:\tools\opencode-cli.exe"


def epoch(year, month, day, hour=0, minute=0):
    return dt.datetime(year, month, day, hour, minute).timestamp()


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, returncode=0, on_run=None):
        self.calls = []
        self.returncode = returncode
        self.on_run = on_run

    def run(self, args, cwd=None):
        args = [str(a) for a in args]
        self.calls.append((args, cwd))
        if self.on_run is not None:
            self.on_run(args, cwd)
        return FakeResult(self.returncode)


class FakeInstallRun:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, *args, timeout=None):
        self.calls.append(args)
        return FakeResult(self.returncode)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_defaults_are_fail_closed_and_no_file_is_written(self):
        self.assertEqual(quota.load_config(self.root),
                         {"cross_agent_resume": False,
                          "opencode_agent": "strategic"})
        self.assertFalse((self.root / "config.json").exists())

    def test_reads_setting_and_agent_without_writing(self):
        (self.root / "config.json").write_text(json.dumps({
            "cross_agent_resume": True,
            "opencode_agent": "reviewer",
            "token": SECRET_CANARY,
        }), encoding="utf-8", newline="\n")
        before = (self.root / "config.json").read_bytes()
        config = quota.load_config(self.root)
        self.assertTrue(config["cross_agent_resume"])
        self.assertEqual(config["opencode_agent"], "reviewer")
        self.assertEqual((self.root / "config.json").read_bytes(), before)
        self.assertNotIn(SECRET_CANARY, json.dumps(config))

    def test_malformed_or_unsafe_config_falls_back(self):
        (self.root / "config.json").write_text("not json", encoding="utf-8")
        self.assertFalse(quota.cross_agent_enabled(quota.load_config(self.root)))
        (self.root / "config.json").write_text(json.dumps({
            "cross_agent_resume": "true", "opencode_agent": "--force; rm -rf",
        }), encoding="utf-8", newline="\n")
        config = quota.load_config(self.root)
        self.assertFalse(config["cross_agent_resume"])
        self.assertEqual(config["opencode_agent"], "strategic")

    def test_cli_discovery_and_fresh_session_id(self):
        local = self.root / "LocalAppData"
        exe = local / "Programs" / "ai.opencode.desktop" / "resources" / "opencode-cli.exe"
        self.assertEqual(quota.opencode_cli_path(local), "opencode")
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"fake")
        self.assertEqual(quota.opencode_cli_path(local), str(exe))
        fresh = quota.new_foreign_session_id("abc")
        self.assertTrue(quota.UUID_RE.match(fresh))
        self.assertNotEqual(fresh, "abc")


class OpenCodeDetectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / "opencode.log"
        self.storage = self.root / "storage" / "session"
        self.demo_repo = self.root / "repo-demo"
        self.storage_repo = self.root / "from-storage"
        for repo in (self.demo_repo, self.storage_repo):
            (repo / ".git").mkdir(parents=True)
        self.log.write_text("\n".join([
            'timestamp=2026-11-27T17:37:25.335Z level=ERROR run=r1 '
            'message="Failed to drain Session" cause="Session.StepFailedError: '
            'Free usage limit reached. ' + PROMPT_CANARY + '" sessionID=' + SESSION_ONE,
            'timestamp=2026-11-27T18:17:22.414Z level=ERROR run=r1 '
            'message="Failed to drain Session" cause="AI.Error: Insufficient account '
            'funds ' + SECRET_CANARY + '" sessionID=' + SESSION_TWO
            + ' directory="' + str(self.demo_repo).replace("\\", "\\\\") + '"',
            'timestamp=2026-11-27T17:37:25.335Z level=ERROR run=r1 '
            'message="Failed to drain Session" cause="Free usage limit reached" '
            'sessionID=' + SESSION_ONE,
            'timestamp=2026-11-27T18:00:00.000Z level=INFO message="all good" '
            'sessionID=ses_unrelated ' + PROMPT_CANARY,
        ]) + "\n", encoding="utf-8", newline="\n")
        stored = self.storage / "project" / (SESSION_STORAGE + ".json")
        stored.parent.mkdir(parents=True)
        stored.write_text(json.dumps({"directory": str(self.storage_repo)}),
                          encoding="utf-8", newline="\n")
        self.log.write_text(self.log.read_text(encoding="utf-8") + "\n".join([
            'timestamp=2026-11-27T19:00:00.000Z level=ERROR run=r1 '
            'message="Failed to drain Session" cause="Free usage limit reached" '
            'sessionID=' + SESSION_STORAGE,
        ]) + "\n", encoding="utf-8", newline="\n")

    def test_detects_both_fragments_without_echoing_prompt_or_secret(self):
        events = quota.scan_opencode(self.log, self.storage)
        self.assertEqual(len(events), 3)  # duplicate line deduped, INFO ignored
        self.assertEqual([e["reason"] for e in events],
                         ["free-usage-limit", "insufficient-funds", "free-usage-limit"])
        self.assertTrue(all(e["reset_at"] is None for e in events))
        self.assertEqual(events[1]["cwd"], str(self.demo_repo))
        self.assertEqual(events[2]["cwd"], str(self.storage_repo))
        report = json.dumps(events)
        for canary in (PROMPT_CANARY, SECRET_CANARY, "cause=", "feedback_log_body"):
            self.assertNotIn(canary, report)
        before = {p for p in self.root.rglob("*")}
        quota.scan_opencode(self.log, self.storage)
        self.assertEqual({p for p in self.root.rglob("*")}, before)

    def test_missing_log_is_empty_and_no_storage_cwd_is_none(self):
        events = quota.scan_opencode(self.root / "missing.log", self.storage)
        self.assertEqual(events, [])
        (self.log.parent / "bare.log").write_text(
            'timestamp=2026-11-27T17:00:00.000Z cause="Insufficient account funds" '
            'sessionID=ses_unknown\n', encoding="utf-8", newline="\n")
        found = quota.scan_opencode(self.log.parent / "bare.log", self.storage)
        self.assertEqual(len(found), 1)
        self.assertIsNone(found[0]["cwd"])


class CrossAgentResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_root = self.root / "agent-handoff"
        self.repo = self.root / "repo"
        (self.repo / ".handoff").mkdir(parents=True)
        (self.repo / "HANDOFF.md").write_text(
            "## Open work\nfinish the ticket\n" + PROMPT_CANARY + "\n",
            encoding="utf-8", newline="\n")
        self.now = epoch(2026, 11, 28, 4, 0)
        self.codex_event = {"log_id": 111, "session_id": UUID, "source": "codex",
                            "reset_at": "2026-11-28T03:04", "cwd": str(self.repo)}
        self.opencode_event = {"log_id": "oc-abc123", "session_id": SESSION_ONE,
                               "source": "opencode", "reason": "free-usage-limit",
                               "reset_at": None, "cwd": str(self.repo)}
        self.key = quota.event_key(self.codex_event)

    def _pending(self, events, runner=None):
        state, _ = quota.checkpoint(events, {}, runner=runner or FakeRunner(),
                                    now=self.now)
        return state

    def test_default_keeps_codex_resume_with_foreign_session(self):
        fake = FakeRunner()
        state = self._pending([self.codex_event], fake)
        end = len(fake.calls)
        state, _ = quota.resume_due([self.codex_event], state, root=self.state_root,
                                    runner=fake, now=self.now)
        command = fake.calls[end][0]
        self.assertEqual(command[:4], ["codex", "exec", "resume", UUID])
        self.assertEqual(state[self.key]["target_agent"], "codex")
        self.assertNotIn("new_session_id", state[self.key])

    def test_cross_agent_codex_starts_new_opencode_session(self):
        fake = FakeRunner()
        state = self._pending([self.codex_event], fake)
        seen = []
        verify = FakeRunner(on_run=lambda args, cwd: seen.append(
            quota.load_state(self.state_root).get(self.key, {}).get("status")))
        state, actions = quota.resume_due(
            [self.codex_event], state, root=self.state_root, runner=verify,
            now=self.now, cross_agent=True, opencode_agent="strategic",
            opencode_cli=FAKE_CLI)
        self.assertEqual(seen, ["resuming"])
        command = verify.calls[0][0]
        self.assertEqual(command[0], FAKE_CLI)
        self.assertEqual(command[1], "run")
        new_id = command[3]
        self.assertEqual(command[2], "--session")
        self.assertTrue(quota.UUID_RE.match(new_id))
        self.assertNotEqual(new_id, UUID)
        self.assertEqual(command[4:6], ["--agent", "strategic"])
        self.assertTrue(quota.brief_has_guardrails(command[-1]))
        for blocked in ("--auto", "--full-auto", "-y", "--no-verify"):
            self.assertNotIn(blocked, command)
        self.assertNotIn(UUID, command)
        self.assertEqual(actions[0]["action"], "resume-launched")
        done_state = quota.load_state(self.state_root)
        quota.state_path(self.state_root).unlink(missing_ok=True)
        preview_state = self._pending([self.codex_event])
        _, preview_actions = quota.resume_due(
            [self.codex_event], preview_state, root=self.state_root, runner=FakeRunner(),
            dry_run=True, now=self.now, cross_agent=True, opencode_agent="strategic",
            opencode_cli=FAKE_CLI)
        self.assertIn("<brief>", preview_actions[0]["command"])
        self.assertEqual(state[self.key]["new_session_id"], new_id)
        self.assertEqual(state[self.key]["target_agent"], "opencode")
        self.assertEqual(done_state[self.key]["status"], "done")

    def test_poll_leaves_opencode_event_pending_without_clock_gate(self):
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            quota.poll_mode(events=[self.opencode_event], root=self.state_root,
                            runner=fake, now=self.now)
        self.assertEqual(len(fake.calls), 1)  # checkpoint only, never a resume
        self.assertIn("save", fake.calls[0][0])
        self.assertEqual(quota.load_state(self.state_root)[
            quota.event_key(self.opencode_event)]["status"], "pending")
        self.assertIn("checkpoint-saved", stdout.getvalue())

    def test_resume_now_opencode_cross_agent_uses_fresh_codex_exec(self):
        event = dict(self.opencode_event, cwd=None)
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            quota.resume_now_mode(
                events=[event], repo=str(self.repo), root=self.state_root,
                runner=fake, now=self.now, cli_path="codex",
                config={"cross_agent_resume": True, "opencode_agent": "strategic"})
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][1], str(self.repo))  # checkpoint in --repo
        command = fake.calls[1][0]
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertNotIn("resume", command)
        for arg in command:
            self.assertNotIn(SESSION_ONE, str(arg))
        self.assertEqual(quota.load_state(self.state_root)[
            quota.event_key(event)]["target_agent"], "codex")

    def test_resume_now_opencode_setting_off_reports_and_launches_nothing(self):
        fake = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            quota.resume_now_mode(events=[self.opencode_event], root=self.state_root,
                                  runner=fake, now=self.now)
        self.assertEqual(fake.calls, [])
        self.assertIn("cross_agent_resume enabled", stdout.getvalue())
        self.assertNotIn(PROMPT_CANARY, stdout.getvalue())
        self.assertFalse(quota.state_path(self.state_root).exists())

    def test_handoff_honours_source_and_setting(self):
        cfg = {"cross_agent_resume": True, "opencode_agent": "reviewer"}
        fake = FakeRunner()
        with contextlib.redirect_stdout(io.StringIO()):
            quota.handoff_mode(repo=str(self.repo), root=self.state_root, runner=fake,
                               now=self.now, config=cfg, source="codex",
                               opencode_cli=FAKE_CLI)
        command = fake.calls[-1][0]
        self.assertEqual(command[0], FAKE_CLI)
        self.assertEqual(command[1], "run")
        self.assertEqual(command[2], "--session")
        self.assertEqual(command[4:6], ["--agent", "reviewer"])
        self.assertTrue(quota.UUID_RE.match(command[3]))

        fake2 = FakeRunner()
        with contextlib.redirect_stdout(io.StringIO()):
            quota.handoff_mode(repo=str(self.repo), root=self.state_root, runner=fake2,
                               now=self.now + 1, config=cfg, source="opencode")
        command2 = fake2.calls[-1][0]
        self.assertEqual(command2[1], "exec")
        self.assertNotIn("resume", command2)
        self.assertNotIn(SESSION_ONE, command2)

        fake3 = FakeRunner()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = quota.handoff_mode(repo=str(self.repo), root=self.state_root,
                                      runner=fake3, now=self.now)
        self.assertEqual(code, 0)
        self.assertEqual(fake3.calls, [])
        self.assertIn("cross_agent_resume enabled", stdout.getvalue())

    def test_preview_masks_briefs_and_session_ids(self):
        brief = "brief with " + PROMPT_CANARY
        preview = quota.preview_command(
            ["codex", "exec", "resume", UUID, brief, SESSION_ONE], brief)
        self.assertIn("<brief>", preview)
        self.assertEqual(preview.count("<session>"), 2)
        self.assertNotIn(UUID, preview)
        self.assertNotIn(SESSION_ONE, preview)
        self.assertNotIn(PROMPT_CANARY, " ".join(preview))

    def test_status_is_read_only_and_uses_temp_home(self):
        with patch.object(quota, "DEFAULT_STATE_ROOT", self.state_root), \
                patch.object(quota, "CODEX_CONFIG", self.root / "config.toml"), \
                patch.object(quota, "DEFAULT_DB", self.root / "logs_2.sqlite"), \
                patch.object(quota, "OPENCODE_LOG", self.root / "opencode.log"):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = quota.main(["--status"])
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["config_path"], str(self.state_root / "config.json"))
        self.assertFalse(report["cross_agent_resume"])
        self.assertEqual(report["opencode_agent"], "strategic")
        self.assertFalse((self.state_root / "config.json").exists())
        self.assertFalse((self.state_root / "quota-state.json").exists())


class InstallQuotaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.chat = self.root / "commands" / "resume-codex.md"
        self.note = self.root / "quota-cron-note.md"
        self.fake_run = FakeInstallRun()
        patches = (
            patch.object(install, "CHAT_COMMAND", self.chat),
            patch.object(install, "CRON_NOTE", self.note),
            patch.object(install, "run", self.fake_run),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_install_dry_run_registers_and_writes_nothing(self):
        result = install.install_quota(str(self.repo), dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["applied"])
        self.assertEqual(self.fake_run.calls, [])
        self.assertFalse(self.chat.exists())
        self.assertFalse(self.note.exists())
        scheduler = result["plan"]["scheduler"]
        self.assertTrue(scheduler["task"].startswith("agent-handoff-quota-"))
        self.assertEqual(scheduler["schedule"], {"type": "MINUTE", "modulo": 5})
        self.assertIn("handoff_quota.py", scheduler["command"])
        self.assertIn("--poll", scheduler["command"])
        self.assertEqual(result["plan"]["cron"]["schedule"], "*/5 * * * *")
        self.assertEqual(result["plan"]["cron"]["registration"],
                         "manual, by the owner, through the OpenCode automation UI")
        self.assertEqual(result["plan"]["chat_command"]["path"], str(self.chat))
        self.assertIn("--resume-now", result["plan"]["chat_command"]["text"])

    def test_uninstall_dry_run_deletes_nothing(self):
        self.chat.parent.mkdir(parents=True)
        self.chat.write_text("keep me\n", encoding="utf-8", newline="\n")
        result = install.uninstall_quota(str(self.repo), dry_run=True)
        self.assertEqual(self.fake_run.calls, [])
        self.assertEqual(self.chat.read_text(encoding="utf-8", errors="replace"), "keep me\n")
        self.assertIn("/Delete", result["delete"])

    def test_uninstall_keeps_foreign_chat_command(self):
        self.chat.parent.mkdir(parents=True)
        self.chat.write_text("someone else's command\n", encoding="utf-8", newline="\n")
        result = install.uninstall_quota(str(self.repo))
        self.assertFalse(result["chat_command_removed"])
        self.assertTrue(result["chat_command_kept"])
        self.assertEqual(self.chat.read_text(encoding="utf-8"), "someone else's command\n")

    def test_status_reports_scheduler_cron_and_chat_command(self):
        status = install.quota_status(str(self.repo))
        self.assertTrue(status["scheduler_task"])
        self.assertFalse(status["cron_note"]["present"])
        self.assertFalse(status["chat_command"]["present"])
        self.assertFalse(status["cron_note"]["registered_by_installer"])
        self.note.write_text("note\n", encoding="utf-8", newline="\n")
        self.chat.parent.mkdir(parents=True)
        self.chat.write_text("command\n", encoding="utf-8", newline="\n")
        self.fake_run.returncode = 1
        status = install.quota_status(str(self.repo))
        self.assertFalse(status["scheduler_task"])
        self.assertTrue(status["cron_note"]["present"])
        self.assertTrue(status["chat_command"]["present"])

    def test_real_install_is_idempotent_and_removes_only_chat_command(self):
        first = install.install_quota(str(self.repo), dry_run=False, apply=True)
        self.assertTrue(first["applied"])
        self.assertTrue(self.chat.exists())
        self.assertTrue(self.note.exists())
        self.assertIn("/Create", self.fake_run.calls[0])
        self.assertEqual(first["files_written"], [str(self.note), str(self.chat)])
        second = install.install_quota(str(self.repo), dry_run=False, apply=True)
        self.assertEqual(second["files_written"], [])
        removed = install.uninstall_quota(str(self.repo))
        self.assertTrue(removed["chat_command_removed"])
        self.assertFalse(self.chat.exists())
        self.assertTrue(self.note.exists())
        self.assertIn("/Delete", self.fake_run.calls[-1])


if __name__ == "__main__":
    unittest.main()
