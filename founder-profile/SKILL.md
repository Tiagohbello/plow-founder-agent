---
name: founder-profile
description: "Persist company identity, repositories, product access, calendars, sources, and autonomy policies."
version: 2.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, company, profile, onboarding, permissions]
    related_skills: [founder-onboarding, founder-memory, founder-calendar, product-access]
---

# Founder Profile

Use this skill to establish which company the agent serves, where its product
and operational signals live, and what it may do. This store is configuration,
not Company Memory.

```sh
python3 "$HERMES_HOME/skills/founder-profile/profile.py" show
```

During onboarding, set the company only from confirmed founder input and add
each explicit repository. Never infer that the Founder Agent checkout or
`plow-agents` runner is a product repository.

Register admin and application surfaces independently with `set-access`; a
company may configure either or both. Store name, kind, URL, environment,
status, evidence, and the Latch vault item reference. Link only repositories
already added with `link-access-repo`. Store the vault item reference, never
credentials or secret values. Use `set-access-policy` for durable operation
rules and `deactivate-access` without deleting history.

Register each Google account with `set-calendar`, explicit selected calendar
ids, default calendar, timezone, working-hours JSON, preferences JSON, access
status, and evidence. Only one active account should be marked default. Use
`deactivate-calendar` without deleting prior configuration.

Record Gmail, GitHub, and Sentry as `available`, `blocked`, or `unconfigured`
after checking them. A blocked source or access does not block others. WhatsApp
is retired and cannot be configured.

Default permissions are: investigation, code preparation, draft PR creation,
and calendar management `autonomous`; communication sending `approval`; merge,
deploy, generic production mutation, and destructive operations `forbidden`.
Product-access policies may explicitly allow a narrowly named production
operation, but cannot override hard prohibitions on merge, deploy, money,
critical credentials, or destructive production deletion. An unconfigured
product operation defaults to `approval`.

All commands emit JSON. Use mutation commands only with verified values.
