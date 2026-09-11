# Install Founder Agent

This guide runs Founder Agent locally in Docker and connects it to your Plow
assistant line. Run terminal commands from the repository root unless noted.

## 1. Prepare your accounts and machine

You need:

- A Mac with [Latch](https://plow.co/latch) installed, connected to your Plow account,
  and permitted to access the apps and browser you want the agent to use.
- Docker Desktop running, with Docker Compose available.
- Git and Python 3 on the host.
- A Plow account and a free assistant line. The login flow uses your phone.
- A product repository you can safely use for the first task.

Check the local tools:

```sh
git --version
python3 --version
docker info
docker compose version
```

`docker info` must connect successfully before continuing. Inference follows your Plow account access and billing.
Never put credentials in chat or commit them.

## 2. Download the agent and official runner

```sh
git clone https://github.com/Tiagohbello/plow-founder-agent.git
cd plow-founder-agent
git clone --depth 1 https://github.com/plow-pbc/plow-agents.git tools/plow-agents
```

The `bin/plow-agents` wrapper delegates account and line setup to that official
runner. The runner checkout is ignored by this repository.

## 3. Connect a free Plow line

```sh
./bin/plow-agents login
./bin/plow-agents lines
```

Follow the login instruction to text the activation phrase from your phone.
If your account needs an assistant line, use `./bin/plow-agents login --new-line`
and follow the service prompts. Choose a line marked `free`, then replace the
placeholder below with its actual line ID:

```sh
./bin/plow-agents mint <line-uid>
```

Do not type the angle brackets literally. Minting writes `plow-credentials` in
this directory. Keep it private: it identifies the agent and gives it scoped Plow
access. Every installer uses their own account and credential. Do not share yours.

Mint before starting Docker. A line already held by another agent cannot be used
by a second agent at the same time.

## 4. Agent identity and inference defaults

No `.env` file is required for the standard installation. Compose defaults to
`AGENT_ID=founder-agent`, so the reporter targets the Founder Agent listing.
Each installer still needs their own Plow credential from step 3; selecting an
agent ID alone does not authenticate or confirm a successful report.

The public Compose file inherits the official image defaults for Plow inference.
No separate Gemini API key or model configuration is needed.

For a fork with its own Index identity, copy `.env.example` to `.env` and change
`AGENT_ID`. Both `.env` and `plow-credentials` are excluded from Git and the Docker
build context.

### Optional local inference override

To use your own inference provider, create `compose.override.yml` beside
`compose.yml`. Docker Compose loads this file automatically. For example:

```yaml
services:
  agent:
    environment:
      HERMES_PROVIDER: gemini
      HERMES_MODEL: gemini-3.8-flash
      GEMINI_API_KEY: ${GEMINI_API_KEY:?set GEMINI_API_KEY in .env}
```

For this override, add your own `GEMINI_API_KEY` to `.env` and confirm the model is
available to your provider account. The override is excluded from Git and the
Docker build context, so local settings do not change the public defaults.
Plow continues to carry messages. To return to Plow inference, remove or rename
the override and recreate the service with `docker compose up -d`.

## 5. Build and start

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 -f agent
```

The first build downloads the base image and the pinned Agent Index client.
Wait for the gateway to start; `plow-init: configured ... as cht_...` indicates
line configuration. Press Ctrl-C to stop following logs; the agent keeps running.
Text your selected Plow assistant line from your phone and confirm it replies.

No inbound ports are published. Docker stores agent state in the Compose-managed
`agent-home` volume mounted at `/var/lib/hermes`. Preserve this volume and use the
same checkout/project name across updates to retain state and install identity.

The volume is the installation's persistent data. Founder Agent creates one
SQLite store there as it is first used:

```text
/var/lib/hermes/founder-agent/founder-agent.db
```

The Hermes-owned `/var/lib/hermes/state.db` is separate and must also be
preserved. The Founder Agent store records its schema version in SQLite
`user_version`; image updates apply compatible migrations when it is opened.
Existing split stores are imported once into the shared database and retained
as rollback copies. Do not delete the volume during a normal update.

## 6. Onboard your company

Send this message to the agent:

> Onboard the project. Ask one question at a time. Start with my company and goal,
> then connect the sources needed for one useful task.

Be ready to identify:

1. Your company, product, and current goal.
2. Your product repository's actual local path on the connected Mac.
3. Admin and/or application URLs, environment, and related repositories.
4. Google account, calendars, timezone, working hours, and scheduling preferences.
5. Gmail, GitHub, and Sentry sources you want to connect.
6. Operations it can perform autonomously and operations requiring approval.

The Founder Agent checkout is infrastructure, not automatically your product.
Keep product credentials in the Latch vault and give the agent an item reference,
not a password. Approve access through Latch/provider prompts when applicable.

Each connection is recorded as `available`, `blocked`, or `unconfigured`.
One blocked connection should not stop work with sources already available.

## 7. Complete your first real task

Start with:

> What's going on? Read my available sources and give me a short brief with
> evidence, the most important priorities, and what needs my decision.

Check that the answer refers to actual company evidence. Then pick one bounded
engineering issue in a repository you authorized:

> Investigate this issue, reproduce it, prepare a minimal fix, run the relevant
> tests, and open a draft PR for my review. Do not merge or deploy.

Success means a verified result: a reproduction, relevant test results, and a
real draft PR URL, or an explicit blocker with a prepared patch. A summary of the
README is not an end-to-end real-world success.

For a restart test, use `docker compose restart agent`, ask what it remembers,
and confirm the company and repository context survived.

## Verify installation

```sh
docker compose exec agent grep -c 'You are Founder Agent' /var/lib/hermes/SOUL.md
docker compose exec agent ls /var/lib/hermes/skills
```

The first command should print `1`, confirming the base composed this agent's
persona into `SOUL.md`; the second should list Founder Agent's skills. Both are
composed and installed by the base image on every boot, so they confirm the
packaging rather than any Founder Agent-specific state. Verify browser and
external account access interactively through Latch; neither command checks
those connections.

## Verify Agent Index reporting

The supervised reporter attempts registration and reports usage hourly. It uses
the official client pinned in `vendor/client.pin`. After a real conversation:

```sh
docker compose exec --user hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --self-check
docker compose exec --user hermes -e HOME=/var/lib/hermes -e HERMES_HOME=/var/lib/hermes agent /opt/hermes/.venv/bin/python3 /opt/plow/agent-index-client.py --agent founder-agent --dry-run
```

`--self-check` validates client behavior. `--dry-run` previews collected usage
without sending it. Neither proves that the server accepted a report. Check
service logs for registration/report errors and verify the results in the
[Agent Index](https://aiworthusing.com/agent-index) after a reporting cycle.
Do not repeatedly register or discard the persistent volume to create installs.

The upstream client documents token-count reporting plus public registration
metadata and explicitly submitted stories. Never include private company data
in public descriptions or stories. See the
[client documentation](https://github.com/plow-pbc/agent-index-client) for its
current payload and install identity contract.

## Update and retain your data

```sh
git pull --ff-only
docker compose up --build -d
docker compose exec agent grep -c 'You are Founder Agent' /var/lib/hermes/SOUL.md
```

The base image recomposes `SOUL.md` from its own persona plus `runtime/persona.md`
on every boot, and reconciles `skills/` into the home when the gateway starts:
new skills are copied, untouched ones are updated, and any skill edited or
deleted in the home (by you or the agent) stays as you left it. Databases,
credentials, and session history in the persistent volume are untouched by
this reconciliation.

Before significant changes, back up the persistent volume with the agent stopped.
For rollback, run the prior image/version against the same volume.
Do not remove the volume as part of a normal update.

## Stop or uninstall

Temporarily stop the agent without revoking its line:

```sh
docker compose stop
```

Resume with `docker compose start`. To disconnect permanently:

```sh
./bin/plow-agents revoke
docker compose down
```

This leaves the named volume intact. Only delete retained state separately when
you intend to permanently discard company memory, session history, and install identity.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop and retry `docker info` |
| Local Gemini override requires `GEMINI_API_KEY` | Add your key to `.env`, or remove the optional override to use Plow inference |
| Official runner missing | Complete the runner clone in step 2 |
| Line is already occupied | Choose a free line; do not revoke an unrelated running agent |
| `plow-credentials` is a directory | Stop with `docker compose down`; remove it with `rmdir plow-credentials` only if empty, then mint before starting |
| No reply on the selected line | Check gateway logs, line configuration, and provider authentication/model errors |
| TLS certificate error during login | Check your host Python certificate setup; the wrapper uses `certifi` if installed |
| Latch source blocked or a 403 | Reconnect the correct account and grant the required scope; ask the agent to retry that source |
| Draft PR cannot be published | Check GitHub write access; preserve the prepared local patch |
| Index registration/report error | Check the credential, client output, and `/var/lib/hermes/state.db`; do not delete identity files to retry |
| `SOUL.md` or a skill looks wrong after an update | Restart (`docker compose restart agent`) recomposes `SOUL.md`, but keeps a skill edited in the home (by you or the agent) as you left it; restore the shipped copy with `docker compose exec --user hermes -e HOME=/var/lib/hermes -e HERMES_HOME=/var/lib/hermes agent /opt/hermes/.venv/bin/hermes skills reset <name> --restore --yes` |

Logs can contain account or task context. Redact private information before
sharing diagnostics in a public issue.

## For the repository owner: publish the listing

Repository publication and Index registration are separate steps. Use your
legitimate Plow agent credential with the official client to register
`founder-agent` and supply these public fields:

- Name: `Founder Agent`
- Blurb: `A technical chief of staff for solo founders: evidence-backed briefs and tested draft PRs.`
- Runtime: `Hermes`
- Repository: `https://github.com/Tiagohbello/plow-founder-agent`
- Install URL: `https://github.com/Tiagohbello/plow-founder-agent/blob/main/docs/INSTALL.md`

The client exposes `--register`, `--agent`, `--name`, `--blurb`, `--runtime`,
`--repo`, and `--install-url`; inspect its `--help` for the pinned version before
registering. Do not publish the token or run owner metadata updates for someone
else's agent. Confirm the listing and install link in the live Index, collect real
installation feedback, and request organizer verification through the Index.
Publishing this repository alone does not establish eligibility or verification.
