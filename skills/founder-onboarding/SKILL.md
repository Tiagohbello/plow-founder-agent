---
name: founder-onboarding
description: "Run the resumable conversation that connects company context, product access, calendars, and operational sources."
version: 2.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, onboarding, setup, calendar, product]
    related_skills: [founder-profile, founder-memory, founder-calendar, product-access, founder-observe]
---

# Founder Onboarding

Treat `vamos fazer o onboarding do projeto`, `onboard the project`, and similar
requests as company onboarding. The current directory, Founder Agent checkout,
and `tools/plow-agents` runner are infrastructure unless the founder explicitly
identifies one as the company's product repository.

Read Founder Profile first and reuse confirmed answers. Continue from the first
incomplete stage in this order:

1. company, product, and principal goal;
2. explicit local repositories, including which is primary;
3. admin, application, or both, with URL, environment, repository links, and
   Latch vault item reference;
4. Google accounts, selected calendars, default calendar, timezone, working
   hours, scheduling preferences, and calendar autonomy;
5. Gmail, GitHub, and Sentry usage and access;
6. product operation permissions;
7. first evidence-backed operational read.

Ask one concise question at a time. Stop once answers support first value, and
resume missing optional stages later. Never scan an arbitrary Mac directory.

For product access, use `product-access`. Accept only admin, only app, both, or
a deferred connection. Guide the founder to use the existing Latch vault; never
ask them to paste credentials, passwords, tokens, or MFA codes. Reuse an active
browser session when possible, otherwise use the configured vault item through
`fill_secret`. Test each access separately and record `available`, `blocked`, or
`unconfigured` with evidence.

For calendars, use `founder-calendar` and the Latch `google-workspace` skill.
Discover connected Google accounts, confirm the default without exposing its
address in shared chat, test bounded event access, and persist configuration.
Calendar management defaults to autonomous while preserving existing meetings.

Persist company configuration, repository links, calendar preferences,
sources, and permissions in Founder Profile. Persist durable business facts and
verified repository context in Company Memory. These are separate stores.

After enough context, perform one evidence-backed read across available sources,
calendars, product surfaces, and repositories. A failure in one path does not
block the others. Do not claim onboarding complete after a README summary or
infer that a clean Git tree means nothing needs attention.

Explain that Plow connects the chat line and Latch connects approved Mac,
Google, vault, and browser operations. Founder Profile autonomy never bypasses
Latch or provider approval.
