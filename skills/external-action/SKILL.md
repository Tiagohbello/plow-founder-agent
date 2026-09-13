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

Use before every communication send, calendar write, or product mutation. Reads
do not require a ledger. Merge, deploy, money movement, critical credential
changes, destructive production deletion, and destructive operations are always
forbidden.

All action records share `$HERMES_HOME/founder-agent/founder-agent.db`.

For Gmail, text, or Plow, resolve the exact existing conversation and its
participants, then prepare a draft first with
`python3 "$HERMES_HOME/skills/external-action/scripts/drafts.py" prepare ...`.
Use channel `gmail`, `text`, or `plow`, the stable conversation id as
`--thread-id`, and canonical external participant identifiers in deterministic
order as `--recipient`; omit subject for text and Plow. Only the founder's
explicit approval of that exact channel, recipient set, thread, subject, and
body permits recording approval and claiming one send. Record a stable founder
conversation/message reference as `--approval-ref`. Editing any field creates a
new unapproved draft. WhatsApp drafts are historical and read-only.

For calendar and product writes,
`python3 "$HERMES_HOME/skills/external-action/scripts/operations.py" prepare ...`
resolves policy from Founder Profile; never pass or invent a policy.
Unconfigured operations require approval. A concrete founder request approves
only that exact prepared action.

Claim before touching the external system. For text and Plow, use the agent's
Plow line: resolve an existing conversation with `plow_list_chats` and send with
`plow_send_message`; never use the founder's Mac Messages identity, substitute
another channel, or create a new Plow conversation in this flow. Retain the
successful send receipt's `message_id`, read the exact conversation back to
verify the body, then pass the retained id to `mark-sent`. When sending,
read-back, or the receipt id is unavailable or ambiguous, mark it uncertain,
inspect remote state, and never retry blindly.
