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
- A product repository for engineering work, or a `plow-wiki` vault for a pipeline-first setup.

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
preserved. The Founder Agent store records its shared compatibility version in
SQLite `user_version`; component migrations use durable markers in the same
database. Image updates apply compatible migrations when it is opened. Existing
split stores are imported once and retained as rollback copies. Do not delete
the volume during a normal update.

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
7. Optionally, the wiki pipeline root and proactive checks (see below).

The Founder Agent checkout is infrastructure, not automatically your product.
Keep product credentials in the Latch vault and give the agent an item reference,
not a password. Approve access through Latch/provider prompts when applicable.

Each connection is recorded as `available`, `blocked`, or `unconfigured`.
One blocked connection should not stop work with sources already available.

### Optional proactive scheduling

Tell the agent:

> Monitor replies from the contacts in my wiki pipeline. Show me the frequency options
> (15, 30, or 45 minutes) so I can choose during onboarding. Then monitor them
> during my working hours. Prepare next steps and notify me in Plow. Ask for
> approval before sending messages, creating invitations, or removing holds.

The contacts come from `projects/founder-agent/pipeline` in your wiki, one page
per contact, each linking to the `entities/people` page for that person. There is
no path to give and no columns to map: `wiki.toml` says the agent owns that root
and its schema says what a page carries. Investors and customers share the root.
An entry the wiki cannot connect to a person — no person page, no email or phone
on it, or a page that will not parse — is skipped and reported.

Confirm your timezone, working days/window and video/phone preference. The offer
is weekdays 09:00–18:00. The agent must show and ask you to choose one frequency:
15, 30 or 45 minutes; there is no assumed default. During onboarding, it also
asks whether every prepared email should be saved as a real Gmail draft in the
founder's inbox for review. The explicit yes/no answer is persisted as
`save_gmail_drafts`; a real Gmail draft is reported only after provider
read-back verification.
Existing calendar preferences are reused. Available Gmail, Messages through
Latch, and agent Plow conversations can be checked; unavailable sources are
reported rather than treated as empty. Verify the destination is your private
founder chat. The agent creates one native Hermes job only after you opt in.

The first check looks back 30 days and follows referenced scheduling threads.
Subsequent checks use each contact/source's successful-read cursor with a
one-hour overlap. New evidence produces a suggestion and, where useful, a local
ledger draft shown in Plow. With `save_gmail_drafts=true`, a prepared Gmail
response is also saved as a verified real draft in the founder's inbox; it is
never sent automatically. There is no automatic invitation or hold deletion, and
no factual field changes on its own; a check writes the recommended next step to
the contact's page and reports it in the notice. Each notice carries the most urgent one or two suggestions rather than every
outstanding one; the rest arrive in later checks once the current notice is
delivered, whether or not its suggestions have been acted on. There
are no repeated reminders for unchanged pending suggestions. A new reply
invalidates the old suggestion's approval.
The calendar operations must exactly match the plan displayed in that notice.
Obsolete Gmail drafts enter a persistent reconciliation queue: the agent flags
them and asks before removing an unchanged draft. Edited or unverifiable drafts
require clarification; Gmail downtime never keeps the old approval valid.

Use “pause monitoring”, “resume monitoring”, “check now”, “change frequency to
15, 30, or 45 minutes”, or “show configuration”. A manual check
can run outside working hours without changing the recurring schedule. Check
status for the native job's last run/delivery error and any unavailable sources.

Monitor notifications are attached to the private founder conversation. Replying
“approve” refers to the suggestion in that notification; the agent
still rechecks the conversation and calendar before executing it. Technical cron
headers, job ids and management footers are disabled for cron notifications in
this installation.

Docker/Hermes must be running, and Latch and the selected sources must be
reachable on the Mac. The interval job wakes outside working hours too, but its
gate ends the agent turn silently before source reads; this is not a zero-cost
inference change detector. No second daemon or inbox mirror is installed.

Acceptance check, using test contacts you control:

1. Offer three held slots, then reply accepting one. At the next working-hours
   check, expect a proposal to create the invitation and release sibling holds.
   Verify the calendar is unchanged until you approve.
2. Reply proposing a phone call while your preference is video. Expect suitable
   video options and a prepared response in Plow, not a sent message.
3. Run another check without changes: no duplicate alert or draft. Send a newer
   reply: the older suggestion must no longer be executable.
4. Pause, restart Docker, and confirm it stays paused; resume and verify there
   is still only one job. If Plow delivery fails, the notice stays unconfirmed
   until read-back/reconciliation; it is not blindly resent.
5. During onboarding choose “yes” for Gmail drafts, prepare a reply, and verify
   that the same recipient, subject, body, and thread appear as a real draft in
   the founder's inbox. Choosing “no” must leave only the internal ledger
   record; neither path sends the message.

Existing installs remain disabled until configured. Normal updates retain
monitor state in the existing volume. To roll back to an image without this
feature, pause the monitor first; restoring an older image alone does not
remove its persisted Hermes job.

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

The supervised reporter attempts registration and reports usage every 5 minutes. It uses
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

That last rule cuts both ways on an upgrade: a skill **removed** from the image
is not removed from a home that already has it, so an existing install keeps
discovering and running it. `investor-pipeline` was retired when the pipeline
moved into the wiki. Remove its seeded copy once, per install:

```
docker compose exec --user hermes agent sh -c 'd=/var/lib/hermes; s=$d/skills/investor-pipeline; \
  a=$d/.retired/investor-pipeline; \
  if [ ! -d "$s" ]; then echo "already retired"; exit 0; fi; \
  if [ -e "$a" ]; then echo "$a already exists; move it aside first" >&2; exit 1; fi; \
  mkdir -p "$d/.retired" && mv "$s" "$a"'
docker compose exec agent ls /var/lib/hermes/skills/investor-pipeline   # expect: No such file
```

`--user hermes` is load-bearing, not tidiness. `exec` runs as root by default and
`/var/lib/hermes` is writable by the agent, so a compromised agent could leave
`.retired` behind as a symlink into the root-owned `/opt/hermes/skills` and have
root follow it. Running as the agent keeps the move inside the permissions the
agent already has.

Neither `hermes skills uninstall` nor `hermes skills reset --restore` does this,
which is worth stating because both look like they should. `uninstall` refuses —
*"not a hub-installed skill (may be a builtin)"* — and `reset --restore` refuses
too once the bundle no longer carries it: *"not a tracked bundled skill. Nothing
to reset."* The boot log's `1 cleaned from manifest` refers to the manifest
entry, not the directory, which stays until something moves it.

Moving rather than deleting keeps the copy recoverable, which is what the
rollback below needs. The archive has a fixed name, so there is never more than
one, and a missing skill exits early: running this on a fresh install, or twice,
says `already retired` and changes nothing. A `mv` that genuinely fails still
fails, rather than being reported as nothing to do. The archive is refused if it
somehow already exists alongside the skill: `mv` would otherwise nest the skill
*inside* it and exit 0, which is the same silent wrong answer in a new costume.
Refusing rather than overwriting, because an existing archive is someone's copy.

Before significant changes, back up the persistent volume with the agent stopped.
For rollback, run the prior image/version against the same volume.
Do not remove the volume as part of a normal update.

The same rule makes that removal outlive a rollback: the home no longer has the
skill, and reconciliation will not reinstate one it has been told is gone, so
the prior image comes back without the skill its scheduling workflow depends on.
Rolling back past the wiki pipeline therefore takes one more step — move the
archived copy back:

```
docker compose exec --user hermes agent sh -c 'd=/var/lib/hermes; a=$d/.retired/investor-pipeline; \
  s=$d/skills/investor-pipeline; \
  if [ ! -d "$a" ]; then echo "nothing archived to restore"; exit 0; fi; \
  if [ -e "$s" ]; then echo "$s already exists; move it aside first" >&2; exit 1; fi; \
  mv "$a" "$s"'
```

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
| Compose says `plow-credentials` is not found | Mint (step 3) before starting |
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
