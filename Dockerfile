# Founder Agent variant built on the official Plow Hermes image.
# Keep the base pinned by immutable tag and digest: it contains the Hermes
# runtime, Plow Chat integration, and Latch configuration.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-6117ddf828a7b565dc9d02814b90c284af4976e3@sha256:0d8f8e3594662eb6e5ccd42faee28161f62e08e0fff2e14c07f7cc34a6c22c94

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
