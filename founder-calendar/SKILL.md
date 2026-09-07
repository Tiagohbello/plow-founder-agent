---
name: founder-calendar
description: "Read and manage the founder's configured Google calendars through Latch."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, calendar, google, meetings, latch]
    related_skills: [founder-profile, external-operations]
---

# Founder Calendar

Use for calendar setup, availability, meetings, events, reminders, focus time,
out of office, working location, invitations, and calendar preferences. Read
Founder Profile first. Use only active configured accounts and calendars.

Call `plow_list_skills` and read `google-workspace` before using `plow-gog`.
Reads may fan out across accounts. Every write must pass the configured
`--account` and explicit calendar id. An edit, response, or cancellation stays
on the account that owns the event. Use the configured default only when the
founder did not identify an account, and say that the default was used without
revealing its address in a shared conversation.

## Read and plan

Keep results bounded. Use `calendar events`, `freebusy`, or `conflicts` with an
explicit time window and selected fields. Normalize times in the configured
timezone and retain the source timezone for writes. Before creating or moving a
timed event, check conflicts across active accounts.

Preserve existing meetings by default. Find another free time or move a focus
block. Move or cancel an existing meeting only when the founder requested that
specific change or Founder Profile contains an autonomous rule for it. A
conflict is not permission to override a booking.

For a recurring event, establish whether the request targets one occurrence,
this and following occurrences, or the complete series. If the request does
not determine the scope, ask one short question before preparing the operation.

## Mutations

Use `external-operations` for every create, update, move, response, settings
change, or deletion. Resolve the `calendar_manage` policy from Founder Profile;
the default is autonomous. The stable target is `<account>/<calendar>/<event>`
or `<account>/<calendar>/new` and the intent includes times, recurrence scope,
attendees, notification choice, and requested change.

Run the matching `plow-gog calendar` command only after claiming the ledger
item. Timed creates are conflict-gated by Latch. Do not add
`--confirm-conflict` unless the founder explicitly selected the conflicting
slot or a configured rule authorizes it. Verify by fetching the returned event
id; then mark the operation completed. Mark ambiguous outcomes uncertain and
reconcile before retrying.

Use the browser through Latch for settings or sharing capabilities unavailable
to the CLI. Read `camoufox-browsing`, open only the Google Calendar origins,
screenshot before actions, and apply the same ledger protocol. A Google 403
means the capability is unavailable; do not work around missing scopes.

Calendar-generated invitations and update notices are part of the authorized
calendar operation. A separate email still uses the Gmail approval flow.
Latch and Google permissions remain authoritative even when Founder Profile
marks an operation autonomous.
