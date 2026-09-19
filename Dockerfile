# Founder Agent variant built on the official Plow Hermes image.
# Keep the base pinned by immutable tag and digest: it contains the Hermes
# runtime, Plow Chat integration, and Latch configuration.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-ef0019372ff8bca593611b31ebd2e08f9f1458ff@sha256:a8a2f97ad78b8192d80a984dce81d3bf5a9a883d18cb7b677704913a09b56aee

# Link the GHCR package to the public source repository.
LABEL org.opencontainers.image.source="https://github.com/Tiagohbello/plow-founder-agent"

# plow-init composes the home's SOUL.md from the base persona plus this file
# on every boot; nothing is COPYed to $HERMES_HOME/SOUL.md directly.
COPY --chmod=0644 runtime/persona.md /opt/hermes/plow-seed/persona.md

# The gateway's sync_skills() reconciles this into the home at startup: new
# skills are copied, untouched ones are updated, owner edits/deletes are kept.
# /opt/hermes/skills already holds the base's own bundled skills; leave their
# modes alone -- our checkout's own modes are already readable and our
# helpers run as `python3 <path>`, so nothing here needs the exec bit.
COPY --chown=0:0 skills/ /opt/hermes/skills/

# Variant s6 configuration (such as cron-config).
COPY image/s6-overlay/ /etc/s6-overlay/
