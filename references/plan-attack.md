# The pre-implementation plan-attack pass

Tool-agnostic: any agent, editor, model or human can run it; no special tools.

## Purpose

An agent cannot reliably grade its own homework — the context that built a plan
biases the check. Fresh-context attackers find holes while the plan is still
cheap to change, before code is written or any Ticket is implemented.

## When to use

Spec-sized changes only: work too large for one paragraph or one session, where
a written Spec coordinates several Tickets. Small reversible changes go straight
to implementation. This is planning, not permission to code before owner agrees.

## Terms

- **Spec** — written statement of a change too large for one session.
- **Ticket** — one self-contained unit of work cut from the Spec.
- **Retro** — turning a finding into a deterministic check (test, lint, CI).

## Roles

- **Context holder (1)** — keeps the agreed Spec, assigns invariants, collects
  findings and folds resolutions in. Does not grade its own plan.
- **Reviewers (3-4)** — fresh-context sub-agents or independent human reviewers.
  Each attacks exactly ONE invariant from the ADRs, glossary rules or test
  expectations; no reviewer grades its own plan.

## Attack list template

Assign one slot per reviewer, with its source of truth:

1. **Architecture constraints (ADRs)** — does the plan contradict any recorded
   ADR, boundary or dependency rule?
2. **Data/provenance rules** — does every relied-on value have an authoritative
   source, and are stale or unverified inputs rejected?
3. **External exposure / live-action rules** — does the plan expose an
   unauthenticated endpoint, touch money/orders/credentials, or mutate shared
   data without an explicit owner gate?
4. **Test coverage** — is each behaviour-changing claim tested at the public
   interface, with no overlapping end-to-end tests?

Four slots are canonical. With three reviewers, the context holder drops the slot
whose source of truth is inapplicable to this Spec and records the omission in the
Spec; never assign two slots to one reviewer.

## Output contract

One finding per assigned invariant, with:

- **Finding** — what breaks, and under what condition.
- **Evidence** — ADR/glossary/test reference, or `not applicable`.
- **Severity** — blocking or advisory.
- **Retro check** — whether it becomes a test, lint rule or CI check, and which.

## Resolution rule

Findings go back into the Spec, resolved in writing, before any Ticket cut from
it is implemented. Catchable mechanically, it becomes a Retro check, not prose.

## Anti-patterns

- Running the attack in the session that wrote the plan (no fresh context).
- Letting the planner grade its own plan.
- One reviewer covering all invariants.
- Adding prose where a test, lint rule or CI check would do.

## Worked example

A Spec adds a cache to a read endpoint. Four reviewers attack four invariants:
an ADR requires stateless reads (blocking — the Spec drops the cache); provenance
is `not applicable` once the key has a source; no external exposure changes; the
cache-miss path has no test, so a Retro check is filed. The Spec records all
four results before a Ticket is implemented.
