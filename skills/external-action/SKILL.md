---
name: external-action
description: "Prepare, approve, claim, and verify communication, calendar, and product writes without repeating ambiguous effects."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, approval, idempotency, gmail, text, plow, calendar, product]
    related_skills: [founder-context, gmail, founder-calendar, product-access]
---

# External Action

Use before every communication preparation or send, calendar write, or product
mutation. A request to “prepare”, “draft”, or “send” a message is an action:
it must create or reuse a ledger record before the agent reports that anything
is prepared. A natural-language preview is not evidence of preparation.
Reads do not require a ledger. Merge, deploy, money movement, critical
credential changes, destructive production deletion, and destructive
operations are always forbidden.

All action records share `$HERMES_HOME/founder-agent/founder-agent.db`.

For a `pipeline-monitor` suggestion, read `founder-scheduling` for lifecycle
policy and follow the monitor's evidence protocol. Use the suggestion's existing
draft id; calendar
`operations.py prepare` calls must include `--suggestion-id <id>`. Linked
calendar operations must exactly match one persisted, displayed plan entry
(`target`, `operation`, `intent`); preparation, approval and claim enforce it.
Use the plan's exact parameters for the provider call. Changed parameters need
a new suggestion and founder approval. Linked product writes are not permitted.
While a suggestion is pending, only an exact `effect: hold` operation on a
`new_options` plan may be claimed; the guard still rejects changed parameters,
non-default calendar destinations, obsolete work, unlinked contacts at claim,
guests, notifications, non-busy visibility, malformed times, and forbidden
calendar policy. Every other
linked operation requires the suggestion's specific foreground approval, even
with autonomous calendar policy. During a scheduled check, the only permitted
mailbox write is saving a founder-owned Gmail draft under the general
`save_gmail_drafts=true` preference or for a required `new_options` proposal,
following Gmail's draft reuse and read-back protocol. An automatic Gmail hold
claim is rejected until that provider draft is recorded as verified. Saving it
does not require approving the pending suggestion and never authorizes sending.
Superseding a suggestion cancels its unexecuted
linked drafts/operations without retrying in-flight or uncertain effects.
Cancelled Gmail drafts remain queued for provider reconciliation. Follow Gmail's
cleanup protocol; save permission never grants deletion permission. Obtain
specific founder approval and claim the exact unchanged draft before deleting,
then verify absence. Provider failure never restores the cancelled approval.

For Gmail, text, or Plow, follow this protocol in the same turn whenever
possible:

1. Resolve the exact existing conversation and participants. For text and
   Plow, use the agent's Plow conversation and `plow_list_chats`; do not use the
   founder's Mac Messages identity. If the conversation or stable thread id is
   missing, stop and explain why it cannot be prepared.
2. Run
   `python3 "$HERMES_HOME/skills/external-action/scripts/drafts.py" prepare ...`
   with channel `gmail`, `text`, or `plow`, the stable conversation id as
   `--thread-id`, and canonical external participant identifiers in
   deterministic order as `--recipient`. Omit `--subject` for text and Plow.
3. Inspect the command result. Only a successful result containing the draft
   id/key and status may be described as “prepared”. If the command fails,
   returns no record, or is unavailable, report “not prepared” and do not call
   any remote send tool.
   For Gmail, follow the Gmail skill's saved-draft preference and reuse protocol
   before presenting the preview; an existing provider draft must not be duplicated.
4. Ask for approval of that exact record. Editing any field creates a new
   unapproved draft. Keep the technical draft id, idempotency key, raw
   `thread_id`, and `approval_ref` internal by default; use them for the next
   ledger commands without making them part of the normal user-facing preview.
   The channel, participant display, conversation context, subject (if any),
   and body must still be exact.
5. After the founder explicitly approves, run `approve`. For text and Plow,
   immediately run a fresh `plow_list_chats` lookup before claiming or sending.
   Canonicalize its live external participant handles exactly as in the draft
   and compare them with the approved `recipient`. A missing conversation or
   any added, removed, changed, or reordered handle makes the approval stale:
   do not claim or send; prepare the changed record and request approval again.
   Only an exact match permits `claim-send`. A claim that returns
   `verification_required`, `already_sent`, or any error is a stop condition;
   never send or retry around it.
6. Send exactly once through the selected channel, then perform a separate
   read-back of the same conversation and verify the exact body. A send receipt
   or `message_id` alone is not verification. Retain the native stable message
   id and run `mark-sent` only after that read-back succeeds. When the send,
   receipt id, or read-back is unavailable or ambiguous — including a warning
   that the message was not mirrored or no live session owns the chat — run
   `mark-uncertain`, report no success, and never retry blindly.

WhatsApp is historical and read-only: it may be listed, but never prepared,
approved, revised, claimed, or marked sent/uncertain. Never silently substitute
another channel or create a new Plow conversation in this flow.

## User-facing draft format

After a successful `prepare`, use the concise preview below. This is only a
presentation format: the ledger command must already have succeeded, and the
technical record remains available for `approve` and `claim-send`.

For text:

```text
Text message prepared:

Channel: SMS / iMessage
Recipient: <display name> (<masked/canonical contact>)
Message: “<body>”
Status: Ready to send (not sent)

Confirm sending this message?
```

For Plow, use the same shape with `Message prepared in Plow`, `Channel: Plow
Chat`, and the existing conversation as the recipient context. For Gmail,
retain the existing Gmail preview and state whether it was saved as a verified
real draft in the founder's inbox or remains ledger-only. Do not expose raw ids
or hashes unless the founder asks for audit details.

For calendar and product writes,
`python3 "$HERMES_HOME/skills/external-action/scripts/operations.py" prepare ...`
resolves policy from Founder Profile; never pass or invent a policy.
Unconfigured operations require approval. A concrete founder request approves
only that exact prepared action.

The protocol is intentionally evidence-driven: do not claim that a message is
prepared, approved, sent, or verified based only on an intended tool call or a
plausible reply. The ledger output and the remote read-back are the source of
truth.
