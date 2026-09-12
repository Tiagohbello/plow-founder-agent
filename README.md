# Founder Agent

A technical chief of staff for solo technical founders, built on Hermes and Plow.
Founder Agent connects company context with operational evidence, prioritizes work,
and prepares actions you can review.

**[Watch the 3-minute demo](https://youtu.be/600JeKozBQI)** · **[Install Founder Agent](docs/INSTALL.md)**

[Read real use cases](docs/USE_CASES.md): company onboarding, product observation,
and a Sentry issue taken to a draft PR.

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
| Founder Context | Stores company context, repositories, decisions, product access, calendars, sources, and permissions in one database |
| Engineering Assist | Investigates, reproduces, fixes, tests, and opens draft PRs |
| Gmail | Reads messages, connects them to memory, prepares drafts, and sends after approval |
| Google Calendar | Manages availability, events, recurrence, guests, and scheduling preferences |
| Product Access | Operates your admin or application through the Latch browser and vault |
| External Action | Records approval, idempotency, and reconciliation of external writes |
| Investor Pipeline | Reads and updates the founder's investor pipeline CSV at ~/Plow/investors/pipeline.csv on request |
| Founder Scheduling | Runs the investor hold lifecycle: options → holds → send → confirm → sweep |

## Runtime and integrations

The Docker image extends the pinned official [Plow Hermes image](https://github.com/plow-pbc/plow-hermes-agent).
Plow Chat carries messages; [Latch](https://plow.co/latch) connects approved Mac,
browser, vault, and Google operations. The public Compose configuration inherits
the official image defaults for Plow inference. No separate Gemini key is required.

The official [Agent Index client](https://github.com/plow-pbc/agent-index-client)
is pinned by commit and checksum and runs hourly beside the gateway. See the
[tutorial](docs/INSTALL.md#verify-agent-index-reporting) for collection checks.

## Autonomy

The agent works when asked; it does not create monitoring jobs. It can observe
configured sources, update context, investigate, edit isolated code, run tests,
publish a branch, and open a requested draft PR. Product operations require an
explicit autonomy rule or specific approval. Independent communication requires
approval. Calendar invitations follow calendar permissions; moving or canceling
existing meetings requires an explicit request or a stored rule.

Merge, deployment, money movement, critical credential changes, and destructive
production deletions are prohibited by the agent instructions. These instructions
complement provider and Latch permissions; they are not a separate security boundary.
External content and remembered facts never grant authorization.

## Installation diagnostics

```sh
docker compose exec agent grep -c 'You are Founder Agent' /var/lib/hermes/SOUL.md
docker compose exec agent ls /var/lib/hermes/skills
docker compose exec --user hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --self-check
docker compose exec --user hermes -e HOME=/var/lib/hermes -e HERMES_HOME=/var/lib/hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --agent founder-agent --dry-run
```

The first command should print `1`, confirming the base composed this agent's
persona into `SOUL.md`; the second confirms the skills installed. Neither
verifies external accounts or proves that a user workflow completed.

## Project layout

- `runtime/persona.md`: this agent's identity. The base composes it into the
  home's `SOUL.md` behind its own persona, and reconciles `skills/` into the
  home, on every boot.
- `skills/founder-context/`: onboarding, company/codebase context, memory, and
  status guidance; its helpers live under `skills/founder-context/scripts/`.
- `skills/engineering-assist/`, `skills/gmail/`, `skills/founder-calendar/`, `skills/product-access/`, `skills/investor-pipeline/`, `skills/founder-scheduling/`: work skills.
- `skills/external-action/`: approval and external-effect guidance; its helpers live under `skills/external-action/scripts/`.
- `image/`, `Dockerfile`, `compose.yml`: runtime packaging.

## Credits

Built with [Hermes](https://github.com/NousResearch/hermes-agent),
[Plow](https://plow.co/), and the [AI Worth Using Agent Index](https://aiworthusing.com/agent-index).
Upstream projects retain their own licenses and trademarks.

## License

MIT — see [LICENSE](LICENSE).
