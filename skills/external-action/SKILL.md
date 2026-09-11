---
name: external-action
description: "Prepare, approve, claim, and verify email, calendar, and product writes without repeating ambiguous effects."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, approval, idempotency, gmail, calendar, product]
    related_skills: [founder-context, gmail, founder-calendar, product-access]
---

# External Action

Use before every communication send, calendar write, or product mutation. Reads
do not require a ledger. Merge, deploy, money movement, critical credential
changes, destructive production deletion, and destructive operations are always
forbidden.

All action records share `$HERMES_HOME/founder-agent/founder-agent.db`.

For Gmail, prepare a draft first. Only the founder's explicit approval of its
exact recipient, thread, subject, and body permits recording approval and
claiming one send. Record a stable conversation/message reference as
`--approval-ref`. Editing any field creates a new unapproved draft.

For calendar and product writes, `operations.py prepare` resolves policy from
Founder Profile; never pass or invent a policy. Unconfigured operations require
approval. A concrete founder request approves only that exact prepared action.

Claim before touching the external system. After observable verification, mark
the action completed with its external id and evidence. After timeout or an
ambiguous response, mark it uncertain, inspect remote state, and never retry
blindly.
