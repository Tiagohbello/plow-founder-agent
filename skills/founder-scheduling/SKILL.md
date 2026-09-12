---
name: founder-scheduling
description: "Find times, place holds, send proposals, confirm picks, and sweep stale holds for investor meetings, through founder-calendar, gmail, and investor-pipeline."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, investors, scheduling, calendar, holds]
    related_skills: [founder-context, founder-calendar, external-action, gmail, investor-pipeline]
---

# Founder Scheduling

Use for the investor hold lifecycle: proposing times, holding them, sending
them, confirming a pick, sweeping stale holds, and repurposing a hold to
another investor. This skill owns the workflow only. It delegates
availability reads to Latch's `google-workspace`, calendar writes to
`founder-calendar`/`external-action`, email to `gmail`, and the record to
`investor-pipeline`. It never sends anything on its own and never creates a
background job. Every step leaves each investor's row it touches true of
the calendar by the end of the same turn: `Holds` lists exactly the events
that still exist, `Proposed` describes what was actually sent, and `Status`
is one of `investor-pipeline`'s own words. A blank `Proposed` is never
proof that nothing went out — verify before acting on it. Every step
records what actually happened, never what was intended.

## Find times

Call `plow_list_skills` and read `google-workspace`, then read availability
across every calendar the founder shows, not just the configured ones.
Classify each conflict: hard (anything in Founder Profile `preferences`,
travel, medical, school logistics, or otherwise marked do-not-overbook) or
soft (internal standups, household services, optional blocks). Apply the
request's own rules — blackout days, deadlines, duration — and offer N
options in the counterparty's timezone, none overlapping another investor's
live `Holds` in `~/Plow/investors/pipeline.csv`. Explain a soft overlap to
the founder privately; never name it in outgoing text.

## Hold

Only on an explicit hold request. Through `founder-calendar`/
`external-action`, create one busy, attendee-free event per option on the
account and calendar the founder named, or the configured work default
when the founder did not identify one, titled `HOLD — <Investor> / <Firm>`
(drop ` / <Firm>` when `Firm` is blank), description `Tentative — no
invitation sent`, notifications off. Record the times and set `Status` to
`held`. Holding is never sending.

## Send

Only on an explicit send instruction, in the channel the founder named —
"text" never becomes email. Send email through `gmail`'s draft → approve →
send flow. For text or Plow, resolve the exact conversation before
sending: find the thread via `plow_list_chats` and confirm the
participant set is the intended investor — never send to a chat matched
only by name; when none exists, creating one with
`plow_start_group_message` is its own decision to put to the founder. Get
the founder's approval of that resolved conversation and the exact body
before sending, the same approval Gmail requires of recipient, thread,
subject, and body. Send once with `plow_send_message`, then read the
message back on the thread — an ambiguous or unverified result is
reported as unverified and never retried; a duplicate proposal to an
investor is worse than a delayed one. On a verified read-back, record
`Proposed` and set `Status` to `sent`. On an ambiguous or unverified
result, record `Proposed` noting the send was not confirmed and set
`Status` to `unverified`. Once sent, those times are fixed: a conflict
that surfaces later goes to the founder, never a silent swap.

## Pick

When the investor chooses, create the real invite from the account and
calendar the founder named, or the configured work default when the
founder did not identify one, with every attendee from the prior thread;
the conferencing link comes from `plow-gog`'s `--with-meet` on that
create, through `founder-calendar`'s normal write path. Delete the
sibling hold events, clear `Holds` (`"--holds", ""`), and set `Status` to
`confirmed`. A date agreed without a time is not confirmed — say so and
ask for the time.

## Sweep

On "are any of these holds real?" or "clear them", list the `HOLD —` events
in the window and find each one's pipeline row by title. Check email,
texts (Messages through Latch), and the agent's own Plow conversations
(`session_search`) for that investor at those exact times before deleting
a blank-`Proposed` hold — found evidence means it was sent, so ask the
founder rather than delete; no evidence means delete the event, through
`founder-calendar`/`external-action`, and report it. `Proposed` set means
show the founder the thread and ask before deleting. A hold with no
matching row falls back to the same evidence check before asking — that
hold has no row to write back to, so the record stays untouched. For a
hold matched to a pipeline row, verify
each delete from the API's own response, then update that row with
`investor-pipeline`'s `set` so `Holds` lists only what survives — empty
(`"--holds", ""`) if nothing does — and re-read the window to confirm the
rest remain.

## Repurpose

Moving held times to another investor renames the events (title and
description), through `founder-calendar`/`external-action`, and appends
them to the destination row's existing `Holds` — read first, `; `-joined
with what is already there, never overwritten — setting its `Status` to
`held` unless it is already further along (e.g. `confirmed`), then clears
them from the source row's `Holds` in the same turn — remaining entries
kept (`; `-joined), the cell emptied (`"--holds", ""`) when nothing is
left, the same write-back Sweep uses; attendees stay empty and
notifications stay off. Before moving a blank-`Proposed` hold, check
email, texts (Messages through Latch), and the agent's own Plow
conversations (`session_search`) for that investor at those exact times
— evidence found means ask the founder first, same as when `Proposed` is
set; no evidence means it moves freely. When `Proposed` is set, the
times were sent to the first investor: ask the founder before taking
them, and on a yes, set the source row's `Status` to `withdrawn` and
leave `Proposed` standing as the record of what was offered.
