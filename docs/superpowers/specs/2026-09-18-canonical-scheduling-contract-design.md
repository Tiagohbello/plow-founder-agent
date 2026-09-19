# Canonical Scheduling Contract Decision

**Status:** Implemented

## Decision

`skills/founder-scheduling/SKILL.md` is the sole operational source of truth for
the contact-scheduling lifecycle. README summarizes it; `pipeline-monitor`,
`external-action`, and the runtime persona describe only their own orchestration
and authorization boundaries.

The existing `calendar_plan` gains one semantic `effect` field. The monitor
validates lifecycle transitions before persisting them, and the existing
external-action ledger uses that field to authorize only the three planned
tentative holds for a pending `new_options` suggestion.

No service, database table, scheduler, or generalized state machine is added.

## Ownership

- `founder-scheduling` owns ideal behavior.
- SQLite suggestions, drafts, and operation ledgers own pending work and
  external-effect state.
- Wiki contact pages project verified facts for people.
- Provider read-back remains the authority for Gmail and calendar effects.

## Authorization boundary

The opted-in monitor may create only exact `effect: hold` operations belonging
to a valid `new_options` plan, and only on the available configured default
calendar. Gmail holds remain blocked until the matching proposal exists as a
verified provider draft; text and Plow retain a durable permission-ready local
draft. The existing `intent` field carries validated structured calendar
parameters, so automatic holds cannot add attendees, send notifications, or
appear free.

Sending communication, creating invitations, deleting holds, and every other
calendar mutation retain their existing specific-approval requirement.

## Why this shape

Prompt-only consolidation would leave incomplete plans executable. A separate
contact state machine would duplicate the existing suggestion and action
ledgers. One discriminator plus validation at the current observation and
external-action seams provides enforcement without introducing another owner.

## Verification

Regression tests cover three-hold proposals, required drafts, derived provider
operations, exact operation authorization, invitation-first confirmation plans,
and deletion targets matching the recorded sibling-hold identities. The
repository's full unittest discovery command is the canonical gate.
