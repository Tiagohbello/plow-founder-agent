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

Use for the contact scheduling lifecycle (investors, customers, and other
contacts): track who owes the next action, propose times, hold them, prepare and
send the proposal, confirm a pick, and sweep stale holds. This skill is the
canonical behavior contract. Other skills own mechanics and must not redefine
this lifecycle. It delegates
availability reads to Latch's `google-workspace`, calendar writes to
`founder-calendar`/`external-action`, email to `gmail`, and the record to the
contact's page in the pipeline root, through `pipeline-monitor`'s write-back
protocol — one destination, so an approved action cannot leave the page stale.
It never sends anything on its own. Only `pipeline-monitor` may configure the
explicitly opted-in background check. That check may prepare drafts and create
the exact three attendee-free tentative holds in a persisted `new_options`
plan; it may not send, create an invitation, or delete a hold without specific
founder approval. Every monitor-originated calendar operation uses
`external-action` with `--suggestion-id`. Use the suggestion's existing linked
draft for a send.
Every step leaves each contact's page it touches true of
the calendar by the end of the same turn: `holds` lists exactly the events
that still exist, `proposed` describes what was actually sent, and `status`
is exactly one value from the closed enum below. A blank `proposed` is never
proof that nothing went out — verify before acting on it. Every step
records what actually happened, never what was intended. `holds` contains only
provider events confirmed to exist now; `confirmed` requires an empty `holds`
after all sibling holds are cleaned up.

## Canonical page status

Use exactly one of these values in the pipeline page's `status` field. No
sentences, names, dates, second-person text, or evidence references belong there.
Put narrative, notes, and evidence references in a dated log in the page body.

| Status | Meaning |
| --- | --- |
| `new` | Contact is in the pipeline; no scheduling exchange or next action is established yet. |
| `waiting_on_us` | The next scheduling action belongs to the founder/assistant. |
| `held` | One or more tentative calendar events currently exist and every live target is recorded in `holds`. |
| `sent` | An outbound scheduling proposal/request was verified sent; use as the send state when no explicit reply/decision is currently owed by the contact. |
| `waiting_on_them` | A verified outbound request or proposal leaves a specific reply, choice, or information due from the contact. |
| `confirmed` | Meeting time and details are agreed, invitation is verified, and all sibling holds are deleted; `holds` is empty. |
| `passed` | Contact declined or scheduling is closed without a do-not-contact instruction. |
| `do_not_contact` | Contact explicitly asked not to be contacted; do not initiate further outreach. |
| `unverified` | A send or calendar effect is ambiguous or cannot be verified; reconcile it and never retry blindly. |
| `withdrawn` | Founder withdrew the outstanding scheduling offer; retain `proposed` as the record of what was offered. |


## Find times

Call `plow_list_skills` and read `google-workspace`, then read availability
across every calendar the founder shows, not just the configured ones.
Classify each conflict: hard (anything in Founder Profile `preferences`,
travel, medical, school logistics, or otherwise marked do-not-overbook) or
soft (internal standups, household services, optional blocks). Apply the
request's own rules — blackout days, deadlines, duration — and offer exactly
three options, each a specific time slot in the counterparty's timezone, none overlapping another contact's
live holds in the pipeline root. Read the contact's page for them. Explain any overlap
(hard or soft) to the founder privately; never expose the reason in outgoing text.

## Outgoing scheduling messages

- **Voice:** Write external messages strictly as the founder's assistant (for
  example, “Hi, I'm <Founder>'s assistant”). Never impersonate the founder or
  write in first person as the founder.
- **Proposals:** Offer exactly three options, each a specific time slot in the
  contact's timezone. Never ask open-ended questions such as “What days work for you?”.
- **Context check:** Before asking the contact for any information, always search
  existing conversations in Gmail, Plow, and Messages through Latch for email
  addresses and phone numbers. Confirm known details rather than asking from scratch.
- **Privacy and questions:** Never disclose the personal reason for the founder's
  unavailability (medical, family, or otherwise); simply state that the founder is
  unavailable. Route internal ambiguity that cannot be inferred from context
  (for example, virtual versus in-person) privately to the founder in
  `PLOW_HOME_CHANNEL`; never ask the external contact.

## Hold

When it is on the founder to propose times, hold all three options. This is
authorized either by the founder's direct request or by an enabled
`pipeline-monitor` suggestion whose persisted `new_options` plan contains
exactly three distinct `effect: hold` entries targeting
the available configured default calendar's `/new` destination, plus a prepared
draft. Through `founder-calendar`/`external-action`, create one busy,
attendee-free event per option on the account and calendar the founder named,
or the configured work default
when the founder did not identify one, titled `HOLD — <Investor> / <Firm>`
(drop ` / <Firm>` when `Firm` is blank), description `Tentative — no
invitation sent`, notifications off. Read the page's existing `holds`, then
fetch each created hold and append its exact
`<account>/<calendar>/<event-id>` target immediately after verification, before
creating the next. Pass the complete live target list as a JSON `holds` array to
`page-update`, merge only its validated output, then immediately read the page
back and confirm the target persisted before creating the next hold. If the
write or read-back fails, stop; reconcile the existing event and page before any
further calendar operation, and never retry creation blindly. Keep `holds` as
the complete `; `-joined set of live event targets, so a later action cannot
delete an unrelated event or lose a partial success. Set `status` to `held` only
after all three persisted targets have been read back. An uncertain hold stops
the remaining operations and is reconciled rather than retried. Holding is
never sending.

For an automatic hold, encode the exact provider parameters as JSON in the
plan entry's existing `intent`: `account`, `calendar`, `start`, `end`,
`timezone`, `title`, `description: "Tentative — no invitation sent"`, empty `attendees`, `send_updates: "none"`, and
`transparency: "opaque"`. The validator rejects any other shape before the
suggestion is persisted and rechecks it before claim.

Prepare the proposal in its existing conversation. For Gmail, prepare the
ledger draft, then always save and verify the real Gmail draft before claiming
any automatic hold; this scheduling invariant is narrower than the general
`save_gmail_drafts` preference. For an existing SMS/iMessage or Plow
conversation, prepare the exact text/Plow draft and ask permission to send;
never use the founder's Mac Messages identity or substitute email. The proposal
is not ready when either its draft or any of its three holds is missing.

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

When the contact chooses, the persisted calendar plan starts with the real
invitation (`effect: invitation`) for every format, including Zoom per meeting.
Only `effect: delete_hold` entries follow it. Zoom per-meeting link creation is
a separate, prior product operation in `external-action`, not an effect in the
monitor calendar plan. Every plan contains one unique `effect: delete_hold`
entry for
every semicolon-separated provider event target in the page's `holds` field;
the deletion-target set must match that field exactly. If a legacy entry contains
only a human-readable time, resolve it to one verified provider event target and
replace it before creating the plan; ambiguous or missing matches are blocked,
never guessed. Create the invite from the account and calendar the founder named,
or the configured work default when the
founder did not identify one, with every attendee from the prior thread;
for a video meeting, first honor the format and provider approved for this
specific meeting (for example, “Zoom nesta reunião” or a Zoom link supplied by
the guest). That meeting-specific choice takes immediate precedence over the
global Founder Profile video preference: do not use the default provider for
this invitation. Use an agreed guest-supplied link directly; do not create a
second conference link. Only if no meeting-specific format or link is established,
read Founder Profile `show.preferences` and dispatch by `video_provider` and
`zoom_link_mode` as below. If the format is unknown, the provider preference is
absent, or
Zoom mode/room URL is missing, ask the founder privately and persist reusable
provider settings via `founder-context`; do not silently assume Google Meet or
create an unsupported link. Do not substitute phone for requested video, and
omit a conferencing link for an explicitly approved phone/in-person meeting.

- **Google Meet (`video_provider=google_meet`):** Prepare and claim the calendar
  invitation in `external-action`, then use `plow-gog calendar` to create it
  with `--with-meet`, on the chosen account/calendar with the agreed attendees.
  Read back the event by returned ID and verify its generated Meet URL and
  attendee/time details before marking the ledger operation complete. A missing
  link is an uncertain invitation, not permission to create another.
- **Zoom personal room (`video_provider=zoom`,
  `zoom_link_mode=personal_room`):** Use the persisted HTTPS
  `zoom_personal_room_url` in the Google Calendar event location or description
  (prefer both where supported), with the agreed attendees. Prepare/claim the
  calendar invitation, create it with `plow-gog calendar` **without**
  `--with-meet`, and read it back by ID. Verify the stored Zoom URL, attendees,
  and time; do not create a separate Zoom meeting or generate a Meet link.
- **Zoom per meeting (`video_provider=zoom`,
  `zoom_link_mode=per_meeting`):** Obtain the conference link before finalizing
  the monitor calendar plan. Prepare, approve, and claim a standalone
  `external-action` product operation for the Zoom meeting (`--scope product
  --access-name <configured-Zoom-access> --contact-key <page-slug>`); do not
  pass `--suggestion-id`, because monitor-linked product writes are forbidden.
  Give it a stable target and exact intent tied to the chosen contact, time,
  title, and attendees; retain its ledger ID for the contact page's dated log.
  Use configured Zoom product access through Latch/browser/API to create one meeting with the agreed
  time and title, **without sending Zoom's own invitations or attendee emails**.
  Capture its `join_url`, then read back the Zoom meeting by provider ID and
  verify that URL and meeting details before completing the product ledger
  operation with the provider ID and verification evidence. If this operation
  is uncertain, reconcile it by provider ID; never create another meeting.
  If Zoom access or no-invite creation is unavailable, stop and report the
  blocker; never substitute a provider. Put the verified `join_url` in the
  `effect: invitation` intent of a fresh persisted monitor calendar plan,
  followed only by the sibling `effect: delete_hold` entries. Present that exact
  plan for founder approval, then prepare/claim the linked calendar operation
  using `--suggestion-id`. Put the URL in the calendar event location or
  description (prefer both), then use `plow-gog calendar` **without**
  `--with-meet` to
  create the Google Calendar invitation with attendees. Read the event back by
  returned ID and verify the Zoom URL, time, and attendees before completing
  that ledger operation. If the calendar effect is ambiguous, mark it uncertain
  and reconcile by provider event ID/ledger; never create it again blindly.

Only after the invitation has been fetched and verified may any hold be
deleted. The Zoom meeting alone does not confirm the invitation. Then delete
every matching sibling hold event, including the tentative event at the chosen
time, clear `holds` using an empty JSON array (merge it empty), verify the page
read-back, and set `status` to `confirmed` only after cleanup is confirmed. A
date agreed without a time is not confirmed — say so and
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
