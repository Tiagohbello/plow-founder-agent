---
name: external-operations
description: "Durably authorize, claim, and verify calendar and product mutations made through Latch."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, latch, idempotency, calendar, product]
    related_skills: [founder-profile, founder-calendar, product-access]
---

# External Operations

Use this ledger before every calendar or connected-product mutation. Read
Founder Profile and resolve the exact target and operation policy first. A
direct founder request for a concrete operation satisfies an `approval` policy
for that operation only; record it by preparing and approving the item. Latch
may still require its own approval.

Prepare with a stable intent that includes the external object and requested
change. `autonomous` produces an approved item, `approval` produces a pending
item, and `forbidden` is refused. Claim before touching the external system:

```sh
python3 "$HERMES_HOME/skills/external-operations/operations.py" prepare \
  --scope calendar --target '<account>/<calendar>' --operation create_event \
  --intent '<stable normalized intent>' --policy autonomous
python3 "$HERMES_HOME/skills/external-operations/operations.py" claim --id <id>
```

After observable verification, finish as `completed` with the external id and
evidence. After timeout or ambiguous response, finish as `uncertain`. Never
repeat an `executing` or `uncertain` operation. Inspect the external system,
then reconcile it as `completed` or `cancelled` with evidence.

The ledger stores intent and references, never passwords, tokens, session
cookies, MFA codes, or vault field values.
