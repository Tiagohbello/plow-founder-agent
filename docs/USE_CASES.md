# Founder Agent in practice

Three real workflows from the founder's recorded session.

## Connected my company and surfaced the first priorities

I introduced my edtech company and asked Founder Agent to help track bugs and operational issues. It walked through onboarding in chat, connected the frontend and backend repositories, and checked the production and staging product surfaces through Latch.

Its first operational read brought together Calendar, Gmail, and Sentry. It surfaced a backend configuration error and a meeting cancellation request, and clearly flagged GitHub authentication as blocked instead of pretending every connection worked. After I restored access, it confirmed GitHub was connected too.

The result was saved company context and a concrete starting list of priorities. I could move straight from setup to choosing real work, without re-explaining the company.

## Turned a Sentry chunk-loading error into a draft PR

A Sentry issue showed that the frontend could fail while loading a JavaScript chunk during navigation. I selected that issue and asked Founder Agent to investigate it and open a pull request.

The agent prepared chunk-error detection, a reload cooldown to prevent loops, and an error boundary with a recovery path. Its completion report recorded passing lint, type checking, and 410 tests across 86 test files.

It opened draft PR #47 with the explanation, code changes, and verification details. The deliverable was a reviewable patch: the PR remained open in draft, with merge and deployment left to me.

## Prepared follow-up work while I was in a meeting

I asked Founder Agent to run a 30-minute Founder Shift while I was on a call. A frontend fix was already prepared, and I had just asked it to remember a high-priority customer request for an SOS doubt-resolution feature.

The shift kept that work in context. Its final summary included a prepared scope for the SOS feature: a ticket model, API endpoints, question-context attachments, student and mentor workflows, and a founder validation checklist. It also identified a missing production configuration key as an action that still needed me.

The handoff separated Handled, Prepared, Needs you, and Watching. I returned to scoped follow-up work and explicit decisions, with the existing draft PR still awaiting my review. The feature was scoped, not implemented, and the production configuration was not changed.
