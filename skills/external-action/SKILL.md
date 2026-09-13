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
4. Show the exact channel, conversation, participants, subject (if any), body,
   and draft id/key. Ask for approval of that exact record. Editing any field
   creates a new unapproved draft.
5. After the founder explicitly approves, run `approve` and then
   `claim-send`. A claim that returns `verification_required`, `already_sent`,
   or any error is a stop condition; never send or retry around it.
6. Send exactly once through the selected channel, read the same conversation
   back, retain the native stable message id, and finish with `mark-sent`.
   When the send, receipt id, or read-back is unavailable or ambiguous, run
   `mark-uncertain`, inspect remote state, and never retry blindly.

WhatsApp is historical and read-only: it may be listed, but never prepared,
approved, revised, claimed, or marked sent/uncertain. Never silently substitute
another channel or create a new Plow conversation in this flow.

For calendar and product writes,
`python3 "$HERMES_HOME/skills/external-action/scripts/operations.py" prepare ...`
resolves policy from Founder Profile; never pass or invent a policy.
Unconfigured operations require approval. A concrete founder request approves
only that exact prepared action.

The protocol is intentionally evidence-driven: do not claim that a message is
prepared, approved, sent, or verified based only on an intended tool call or a
plausible reply. The ledger output and the remote read-back are the source of
truth.
