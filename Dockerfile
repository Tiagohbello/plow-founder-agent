# Founder Agent variant built on the official Plow Hermes image.
# Keep the base pinned by immutable tag and digest: it contains the Hermes
# runtime, Plow Chat integration, and Latch configuration.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-c3aad2bacdcf2787067c5caf27707183dbcc71e5@sha256:6e1eaf43474efe62f860ecf1298f8602ea452591298aab52ab40a5fa2dc54ebb

# Variant-owned files live outside the persistent home. variant-init verifies
# and reconciles them into /var/lib/hermes before the gateway starts.
COPY --chown=0:0 --chmod=0644 runtime/SOUL.md /opt/founder-agent/payload/SOUL.md
COPY --chown=0:0 skills/ /opt/founder-agent/payload/skills/
COPY --chown=0:0 --chmod=0755 runtime/variant_init.py /opt/founder-agent/variant_init.py
COPY --chown=0:0 --chmod=0755 runtime/doctor.py /opt/founder-agent/doctor.py
COPY --chown=0:0 --chmod=0644 variant/manifest.json /opt/founder-agent/manifest.json

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
