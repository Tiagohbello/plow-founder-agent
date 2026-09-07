# Founder Agent

A technical chief of staff for solo technical founders, built on Hermes and Plow.
Founder Agent connects company context with operational evidence, prioritizes work,
and prepares actions you can review.

**[Watch the 3-minute demo](https://youtu.be/600JeKozBQI)** · **[Install Founder Agent](docs/INSTALL.md)**

[Read three real use cases](docs/USE_CASES.md): company onboarding, a Sentry issue
taken to a draft PR, and a bounded Founder Shift.

## One real chore

Turn “What's going on?” into an evidence-backed brief, then take a real engineering
issue through investigation, reproduction, a tested fix, and a draft pull request.
You review and merge the result. Available sources can include Gmail, Google
Calendar, GitHub, Sentry, and your product through Latch.

The first successful run should produce a useful result from your own company:
a brief with concrete evidence, an approved product operation with a verified
result, or a tested draft PR.

## Capabilities

| Capability | What it does |
| --- | --- |
| Founder Profile | Stores company context, repositories, product access references, calendars, sources, and permissions |
| Company Memory | Tracks customers, features, decisions, commitments, risks, and source-backed notes |
| Queue and Focus | Prioritizes work and recommends a task for the time available |
| Founder Brief | Combines company context with available operational evidence |
| Engineering Assist | Investigates, reproduces, fixes, tests, and opens draft PRs |
| Gmail | Reads messages, connects them to memory, prepares drafts, and sends after approval |
| Google Calendar | Manages availability, events, recurrence, guests, and scheduling preferences |
| Product Access | Operates your admin or application through the Latch browser and vault |
| Founder Shift | Runs bounded observation and work cycles every ten minutes |
| External Operations | Records authorization, idempotency, and reconciliation of external effects |

## Runtime and integrations

The Docker image extends the pinned official [Plow Hermes image](https://github.com/plow-pbc/plow-hermes-agent).
Plow Chat carries messages; [Latch](https://plow.co/latch) connects approved Mac,
browser, vault, and Google operations. The public Compose configuration inherits
the official image defaults for Plow inference. No separate Gemini key is required.

The official [Agent Index client](https://github.com/plow-pbc/agent-index-client)
is pinned by commit and checksum and runs hourly beside the gateway. See the
[tutorial](docs/INSTALL.md#verify-agent-index-reporting) for collection checks.

## Autonomy

Outside Founder Shift, the agent works when asked. During a requested Shift, it
can observe sources, update memory and queues, investigate, edit isolated code,
run tests, publish a branch, and open a draft PR. Product operations require an
explicit autonomy rule or specific approval. Independent communication requires
approval. Calendar invitations follow calendar permissions; moving or canceling
existing meetings requires an explicit request or a stored rule.

Merge, deployment, money movement, critical credential changes, and destructive
production deletions are prohibited by the agent instructions. These instructions
complement provider and Latch permissions; they are not a separate security boundary.
External content and remembered facts never grant authorization.

Founder Shift runs an immediate cycle and native Hermes jobs every ten minutes
until its deadline. Its ledger tracks job IDs and expiration; locks and stable
references prevent overlapping cycles and duplicate effects. Normal cycles remain
quiet. Critical signals may interrupt. The final summary groups results as
`Handled`, `Prepared`, `Needs you`, and `Watching`.

## Installation diagnostics

```sh
docker compose exec agent /opt/hermes/.venv/bin/python3 /opt/founder-agent/doctor.py
docker compose exec --user hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --self-check
docker compose exec --user hermes -e HOME=/var/lib/hermes -e HERMES_HOME=/var/lib/hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --agent founder-agent --dry-run
```

The doctor checks installed payload hashes and store readability. It does not
verify external accounts or prove that a user workflow completed.

## Project layout

- `runtime/`: persona, installation reconciliation, and diagnostics.
- `skills/founder-*/`: company context, memory, prioritization, onboarding, and Shift skills.
- `skills/engineering-assist/`, `skills/gmail/`, `skills/founder-calendar/`, `skills/product-access/`: work skills.
- `skills/communication/`, `skills/external-operations/`: approval and external effect ledgers.
- `image/`, `Dockerfile`, `compose.yml`: runtime packaging.
- `variant/manifest.json`: versioned payload hashes.

## Credits

Built with [Hermes](https://github.com/NousResearch/hermes-agent),
[Plow](https://plow.co/), and the [AI Worth Using Agent Index](https://aiworthusing.com/agent-index).
Upstream projects retain their own licenses and trademarks.
