---
name: founder-scheduling
description: "Find times, place holds, send proposals, confirm picks, and sweep stale holds for investor meetings, through founder-calendar, gmail, and the wiki pipeline."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, investors, scheduling, calendar, holds]
    related_skills: [founder-context, founder-calendar, external-action, gmail, pipeline-monitor]
---

# Founder Scheduling

Use for the contact hold lifecycle (investors, customers, and other contacts): proposing times, holding them, sending
them, confirming a pick, sweeping stale holds, and repurposing a hold to
another investor. This skill owns the workflow only. It delegates
availability reads to Latch's `google-workspace`, calendar writes to
`founder-calendar`/`external-action`, email to `gmail`, and the record to the
contact's page in the pipeline root, through `pipeline-monitor`'s write-back
protocol — one destination, so an approved action cannot leave the page stale.
It never sends anything on its own. Only `pipeline-monitor`
may configure the explicitly opted-in background check; that check prepares
suggestions, writes the contact page's `next_step`, and places or clears
private HOLDs when a draft suggests times. Invitations and sends still
need specific founder approval and fresh evidence, with `--suggestion-id` on
calendar ledger preparations. Use its existing linked draft for a communication send.
Every step leaves each contact's page it touches true of
the calendar by the end of the same turn: `holds` lists exactly the events
that still exist, `proposed` describes what was actually sent, and `status`
is one of this skill's own words. A blank `proposed` is never
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
live holds in the pipeline root. Read the contact's page for them. Explain a soft overlap to
the founder privately; never name it in outgoing text.

## Hold

On an explicit hold request, or during a pipeline-monitor check whenever a
draft suggests times. Never ask for a go-ahead to place or remove those HOLDs.
Through `founder-calendar` / `external-action`, create one busy, attendee-free
event per option on the account and calendar the founder named, or the
configured work default when the founder did not identify one, titled
`HOLD — <Investor> / <Firm>`
(drop ` / <Firm>` when `Firm` is blank), description `Tentative — no
invitation sent`, notifications off. For monitor work, use `create_private_hold`
with the suggestion's `hold_plan` rather than an invitation `calendar_plan`.
Record the times — read the page's
existing `holds` first and pass the complete `; `-joined value, the same
append Repurpose uses, so a second hold request never drops the events the
first one left standing — and set `status` to `held`. Holding is never
sending. On the next revisit of that contact (time confirmed, rescheduled, or
cancelled), delete or update obsolete HOLDs so the calendar matches; do not
ask. Re-preparing the same slot must not create a duplicate event.

## Send

Only on an explicit send instruction, in the channel the founder named —
"text" never becomes email.

Every channel goes through `external-action`'s durable draft → approve → claim →
verify flow. Email then uses `gmail`; text and Plow use the agent's Plow line,
with `plow_list_chats` resolving an existing conversation and
`plow_send_message` sending. Never use the founder's Mac Messages identity,
substitute another channel, create a new Plow conversation, or use a chat
matched only by name. Before preparing the draft, confirm the exact
conversation's participant set is the intended investor and record its stable
id plus the canonical external participant identifiers in deterministic order.
Show the founder that channel, conversation, participant set, and exact body
before recording approval.

After approval and immediately before claiming or sending, run a fresh
`plow_list_chats` lookup. Canonicalize the live external participant handles in
the same deterministic order and compare them exactly with the approved
draft's `recipient`. If the conversation is missing or any handle differs, do
not claim or send; prepare the changed record and request approval again.

After a successful claim, send once and retain `message_id` from the successful
`plow_send_message` receipt. That receipt is not verification: separately read
the message back from that exact conversation and verify its body before
passing the retained id to `mark-sent`, recording `proposed`, and setting
`status` to `sent`. If the send receipt, its id, or the body read-back is
ambiguous or unavailable — including a warning that the message was not
mirrored or no live session owns the chat — mark the draft uncertain, record
`proposed` noting the send was not confirmed, and set `status` to `unverified`;
never report success or retry. A claim reporting `already_sent` or
`verification_required` never authorizes another send.

Once sent, those times are fixed: a conflict that surfaces later goes to
the founder, never a silent swap.

## Pick

When the investor chooses, create the real invite from the account and
calendar the founder named, or the configured work default when the
founder did not identify one, with every attendee from the prior thread;
for a video meeting the conferencing link comes from `plow-gog`'s `--with-meet`
on that create, through `founder-calendar`'s normal write path. Honor the approved
meeting format and stored preference; do not substitute phone for requested video,
and omit a conferencing link for an explicitly approved phone/in-person meeting.
Fetch and verify the
created invitation before deleting any holds. Then delete only the matching
sibling hold events, clear `holds` (merge it empty), and set `status` to
`confirmed`. A date agreed without a time is not confirmed — say so and
ask for the time. A partial or uncertain operation stops the remaining steps:
reconcile the existing ledger records, never recreate a verified invitation.
Write only the fields the page's schema names and leave the rest of the page
alone — `wiki_page.merge` does that for you. If a needed field is absent from
the schema, ask for it rather than inventing one. Private suggestion state already lives in SQLite.

## Sweep

On "are any of these holds real?" or "clear them", list the `HOLD —` events
in the window and find each one's pipeline page by title. Check email,
texts (Messages through Latch), and the agent's own Plow conversations
(`session_search`) for that investor at those exact times before deleting
a blank-`proposed` hold — found evidence means it was sent, so ask the
founder rather than delete; no evidence means delete the event, through
`founder-calendar`/`external-action`, and report it. `proposed` set means
show the founder the thread and ask before deleting. A hold with no
matching page falls back to the same evidence check before asking — that
hold has no page to write back to, so the record stays untouched. For a
hold matched to a pipeline page, verify
each delete from the API's own response, then merge `holds` on that page so it
lists only what survives — empty if nothing does — and re-read the window to
confirm the rest remain.

## Repurpose

Moving held times to another investor renames the events (title and
description), through `founder-calendar`/`external-action`, and appends
them to the destination page's existing `holds` — read first, `; `-joined
with what is already there, never overwritten — setting its `status` to
`held` unless it is already further along (e.g. `confirmed`), then clears
them from the source page's `holds` in the same turn — remaining entries
kept (`; `-joined), the field emptied when nothing is
left, the same write-back Sweep uses; attendees stay empty and
notifications stay off. Before moving a blank-`proposed` hold, check
email, texts (Messages through Latch), and the agent's own Plow
conversations (`session_search`) for that investor at those exact times
— evidence found means ask the founder first, same as when `proposed` is
set; no evidence means it moves freely. When `proposed` is set, the
times were sent to the first investor: ask the founder before taking
them, and on a yes, set the source page's `status` to `withdrawn` and
leave `proposed` standing as the record of what was offered.
