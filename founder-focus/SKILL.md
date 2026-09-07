---
name: founder-focus
description: "Recommend one queue item that fits the founder's available time."
version: 1.0.0
author: Founder Agent
metadata:
  hermes:
    tags: [founder, focus, timebox, prioritization]
    related_skills: [founder-memory, founder-queue]
---

# Founder Focus

Use for `I have X minutes. What should I work on?` Parse the time, read the
company profile, goals in Company Memory, and Founder Queue. Ignore `done` and
`watching`. A deferred decision excludes implementation of that feature, while
communication, investigation, or review that respects the decision remains a
candidate. Then run:

```sh
python3 "$HERMES_HOME/skills/founder-focus/focus.py" "30 minutes"
```

Return one main recommendation and at most one alternative. Use impact on the
current goal, evidence, risk, priority, founder dependency, and time fit. The
helper filters and orders supported candidates; apply model reasoning to the
final choice. If no estimate exists, say so; do not invent one.

`Why?` must name the selected queue item, the evidence used, and the time-fit
or priority reason. This is a recommendation only: do not mark work `working`,
execute it, or treat a recommendation as authorization.
