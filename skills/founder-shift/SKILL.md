---
name: founder-shift
description: "Run a finite, proactive company-operations shift every ten minutes using Hermes native scheduling."
version: 2.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, shift, operations, autonomy, cron]
    related_skills: [founder-profile, founder-observe, founder-memory, founder-queue, founder-brief, founder-focus, engineering-assist, gmail, founder-calendar, product-access, external-operations]
---

# Founder Shift

Start only when the founder explicitly asks the agent to keep the company moving
for a duration. Outside an active Shift, never schedule proactive observation.

## Start

1. Create the durable run with `shift.py begin --minutes <n>
   --interval-minutes 10 --origin '<conversation route>'`.
2. Run the first cycle immediately using the cycle protocol below.
3. Use Hermes `cronjob` to create a recurring job every `10m`, with `repeat`
   equal to `ceil(duration/10)`. Load `founder-shift`. Its prompt must name the
   run id, claim a scheduled-time cycle key, execute one cycle, and return exactly
   `[SILENT]` unless a critical issue requires interruption.
4. Create a one-shot finalizer `in <duration>`. It reconciles expiry, lists and
   removes/pauses the verified recurring job, emits `summary`, and delivers to
   the captured origin.
5. Persist both returned job ids with `shift.py set-jobs`. Never guess job ids.

If either job creation fails, remove the successful counterpart, finish the run
as failed, and report evidence. Native cron is the only scheduler.

## Cycle protocol

Each scheduled session reloads Founder Profile, Memory, and Queue. Claim a cycle
before reading sources or causing effects:

```sh
python3 "$HERMES_HOME/skills/founder-shift/shift.py" claim-cycle \
  --run-id <id> --cycle-key '<scheduled ISO time>'
```

If refused, do no work. Observe configured calendars, product surfaces, Gmail,
GitHub, and Sentry through `founder-observe`; reconcile stores; prioritize;
investigate; prepare; and act within Founder Profile permissions. Use the Shift
`claim-effect` guard for every external effect. Calendar and product mutations
also use `external-operations`, whose key represents the business operation
rather than the cycle. After observable verification finish both claims as
`completed`; after a timeout or ambiguous result mark them `uncertain`. A
repeated claim requires inspecting remote state and never blindly repeating the
effect. Communication requires approval. Calendar management and explicitly
autonomous product operations may run during Shift. Draft PR creation is
autonomous. Merge, deploy, money movement, critical credential changes, and
destructive production deletion are forbidden.

Finish the cycle with `finish-cycle`. Expired/cancelled runs refuse new claims.
On restart native cron resumes, while ledger expiry remains authoritative.

Critical signals may interrupt the founder. Important signals update Queue.
Informational signals update memory or `watching`. Stay silent for routine
cycles. The finalizer reports Handled, Prepared, Needs you, and Watching once.

For status, read the ledger and list both stored jobs. For cancellation, list
and remove/pause those exact ids, run `cancel`, and return the summary. Never
stop unrelated jobs.
