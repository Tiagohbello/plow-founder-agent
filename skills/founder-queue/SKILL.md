---
name: founder-queue
description: "Persist and prioritize the small set of company work that deserves attention."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, queue, priorities, focus]
    related_skills: [founder-memory, founder-focus]
---

# Founder Queue

Use this skill for `What needs me?`, for adding an explicit queue item, or for
updating an item's state after real evidence. The queue is a short operational
list, not a dump of memory.

## Store

Use the bundled helper:

```sh
python3 "$HERMES_HOME/skills/founder-queue/queue.py" list
```

The SQLite store lives at `$HERMES_HOME/founder-queue/queue.db` (or the path in
`FOUNDER_QUEUE_DB`). It survives conversations and container restarts. Queue
items keep status and priority plus stable source/evidence, an optional memory
link, action kind, effort estimate, and an artifact reference such as a draft
PR URL.

Valid statuses are `watching`, `ready`, `needs_founder`, `working`, and `done`.
Valid priorities are `low`, `medium`, `high`, and `urgent`. `done` is hidden
from normal listing and never reappears as current work.

## Rules

- Add one item per coherent piece of work. The helper deduplicates normalized
  titles and stable source references; update the existing item when evidence changes.
- Use `needs_founder` for a decision, approval, or blocker only the founder can
  resolve. Use `ready` for safe preparation and `working` only when work has
  actually begun.
- A `watching` item is context, not a task. A deferred memory record remains
  deferred; it must not be promoted to `ready` merely because it was mentioned.
- `can_agent_handle` describes capability, not authorization. Memory never
  grants permission to edit code, send communication, open a PR, or deploy.
- A deferred feature blocks `action_kind=implement`, not adjacent work such as
  `communicate`, `investigate`, or `review` that respects the decision.
- After opening a verified draft PR, store its URL as `artifact_ref`, set
  `artifact_kind=draft_pr`, and create/update a `needs_founder` review item.

## What needs me?

Read active memory and the queue, exclude `done` and deferred work, then return
the small set of `needs_founder` items in priority order. Explain the evidence
behind each item. Do not execute any queue item from this question.

For a time-boxed request, use `founder-focus` and return one main recommendation
plus at most one alternative. Do not create a scheduler or a numeric scoring
system.

## State changes

Only record `working` after beginning an approved local task. Record `done`
only with evidence of completion. If work is prepared but still awaits the
founder, keep it `needs_founder` and say what is prepared.
