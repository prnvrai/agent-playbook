# ADR 0001: Quota watcher approval gate

Status: Accepted (owner-approved retro remedy)

## Context

The quota watchdog checkpoints work on credit exhaustion and can resume it
after reset. Several steps are not reversible and spend money or change live
state:

- activating the quota watcher and registering the Windows Task Scheduler task
  (`agent-handoff-quota-<id>`) via `schtasks /Create`;
- setting `cross_agent_resume=true`, which starts a new session in the other
  agent and can spend that tool's credits unattended;
- any unattended credit spend caused by an automatic resume.

These are **one-way doors**: each requires explicit owner approval *every
time*, not once at install and not by inheritance from "normal agent
authority". A future implementer reading the planning docs must not be able to
reintroduce an auto-approve flag (`--auto`, `--full-auto`, `-y`) into a
cross-agent launch.

This repo has no prior ADRs, so this record uses the standard
Context / Decision / Consequences format.

## Decision

1. Activation of the watcher, the Task Scheduler task, `cross_agent_resume=true`
   and unattended credit spend are one-way doors. They require fresh, explicit
   owner approval on each occasion.
2. `handoff_install.py` is **dry-run by default**. A plain `--install-quota`
   only prints the plan; registration happens only with `--apply` (with owner
   approval), which is the sole caller of `schtasks /Create`. Uninstall is
   similarly gated and removes only the installer-owned chat command.
3. `cross_agent_resume` defaults to **false** in
   `~/.agent-handoff/config.json`; an absent, malformed or non-boolean value
   fails closed to false.
4. `--resume-now` is a **manual** trigger launched only on the owner's direct
   request (CLI or the owner-invoked `/resume-codex` chat command). The
   scheduler poll checkpoints and reports but never performs a resume for an
   event that needs the manual trigger.
5. Cross-agent launches **never use `--auto`** (nor `--full-auto`, `-y`,
   `--no-verify`, `--force`). Guardrails stay in the brief and in the launch
   code.
6. Planning docs must not contain a stale `opencode run ... --auto` example.
   The only acceptable mention is an explicit `(no --auto)` on the same line.

### Mechanical enforcement

These rules are tests, not prose. The relevant checks in the suite are:

- Installer gating — `tests/test_handoff_hardening.py`:
  `InstallApplyTest::test_plain_invocation_never_registers_and_apply_does`.
  `tests/test_handoff_cross_agent.py`:
  `InstallQuotaTest::test_install_dry_run_registers_and_writes_nothing`,
  `InstallQuotaTest::test_real_install_is_idempotent_and_removes_only_chat_command`,
  `InstallQuotaTest::test_uninstall_dry_run_deletes_nothing`.
- Fail-closed setting — `tests/test_handoff_cross_agent.py`:
  `ConfigTest::test_defaults_are_fail_closed_and_no_file_is_written`,
  `ConfigTest::test_malformed_or_unsafe_config_falls_back`,
  `CrossAgentResumeTest::test_status_is_read_only_and_uses_temp_home`.
- Manual-only resume — `tests/test_handoff_cross_agent.py`:
  `CrossAgentResumeTest::test_poll_leaves_opencode_event_pending_without_clock_gate`,
  `CrossAgentResumeTest::test_resume_now_opencode_setting_off_reports_and_launches_nothing`,
  `InstallQuotaTest::test_install_dry_run_registers_and_writes_nothing`
  (asserts the chat command text carries `--resume-now`).
- No auto-approve flags — `tests/test_handoff_hardening.py`:
  `LoggingAndGuardrailTest::test_blocked_flags_are_refused_in_code_and_commands`,
  `tests/test_handoff_cross_agent.py`:
  `CrossAgentResumeTest::test_cross_agent_codex_starts_new_opencode_session`.
- No stale docs examples — `tests/test_handoff_hardening.py`:
  `PlanningDocsNoAutoTest::test_planning_docs_have_no_stale_opencode_run_auto_examples`,
  which scans `docs/specs/*.md` and `docs/tickets/*.md` and fails on any line
  with an `opencode run ... --auto` example unless that same line says
  `no --auto` (backticked or plain).

Full suite: `python -m unittest discover -s "...\tests" -v`.

## Consequences

- Registering or cancelling the scheduler task, enabling cross-agent resume
  and any credit-spending resume remain deliberate owner actions; no code path
  in this repo approves them on the owner's behalf.
- Documentation edits that reintroduce `--auto` in a command example fail CI
  through the doc scan, so the anti-pattern cannot be copied back into code.
- The watcher can checkpoint and prepare briefs unattended, but the actual
  launch stays gated. This makes the workflow safe to plan and review without
  activating a live path.
- The approval gate is human and per-event; it is intentionally not delegated
  to the resumed agent's "normal authority".
