# Founder Agent variant built on the official Plow Hermes image.
# Keep the base pinned by immutable tag and digest: it contains the Hermes
# runtime, Plow Chat integration, and Latch configuration.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-4747960eaa8a44ac24424bf0cc6c22559af61f43@sha256:fe9b0f428f9ed2da1698ecf0b504c79eceb9e016e770291ff6b3418b9f65449d

# plow-init composes the home's SOUL.md from the base persona plus this file
# on every boot; nothing is COPYed to $HERMES_HOME/SOUL.md directly.
COPY --chmod=0644 runtime/persona.md /opt/hermes/plow-seed/persona.md

# The gateway's sync_skills() reconciles this into the home at startup: new
# skills are copied, untouched ones are updated, owner edits/deletes are kept.
# /opt/hermes/skills already holds the base's own bundled skills; leave their
# modes alone -- our checkout's own modes are already readable and our
# helpers run as `python3 <path>`, so nothing here needs the exec bit.
COPY --chown=0:0 skills/ /opt/hermes/skills/

# Agent Index owns its client. Fetch only the reviewed immutable revision and
# verify its checksum before placing it in the root-owned service path.
COPY vendor/client.pin /opt/plow/agent-index-client.pin
RUN set -eu; \
    sha="$(sed -n 's/^sha=//p' /opt/plow/agent-index-client.pin)"; \
    want="$(sed -n 's/^sha256=//p' /opt/plow/agent-index-client.pin)"; \
    path="$(sed -n 's/^path=//p' /opt/plow/agent-index-client.pin)"; \
    curl -fsS --max-time 60 -o /opt/plow/agent-index-client.py \
      "https://raw.githubusercontent.com/plow-pbc/agent-index-client/$sha/$path"; \
    got="$(sha256sum /opt/plow/agent-index-client.py | cut -d' ' -f1)"; \
    [ "$got" = "$want" ] || { echo "agent-index client is $got, pin says $want" >&2; exit 1; }; \
    chmod 0644 /opt/plow/agent-index-client.py

# The reporter is supervised beside the gateway and starts only after the
# credential/identity gate. It stands down when AGENT_ID is absent.
COPY image/s6-overlay/ /etc/s6-overlay/
RUN chmod 0755 /etc/s6-overlay/s6-rc.d/agent-index/run
