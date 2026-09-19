# Canonical Scheduling Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the existing founder scheduling lifecycle so every proposal has exactly three held options and every accepted slot plans an invitation followed by complete sibling-hold cleanup.

**Architecture:** Keep `founder-scheduling` as the sole operational contract. Extend the existing monitor plan with one `effect` discriminator, validate action-specific invariants in one pure helper, and let the existing external-action guard authorize only planned `hold` effects before founder approval. No new service, database table, or workflow framework is introduced.

**Tech Stack:** Python 3 standard library, SQLite, `unittest`, Markdown skills and runtime prompts.

**Spec:** `docs/superpowers/specs/2026-09-18-canonical-scheduling-contract-design.md`

## Global Constraints

- Exactly three options and three attendee-free tentative holds are required when the founder owes times.
- The monitor may autonomously create only a planned `hold` effect for a pending `new_options` suggestion.
- Sending proposals, creating invitations, and deleting holds retain specific founder approval.
- SQLite ledgers remain operational truth; wiki pages remain verified projections.
- `skills/founder-scheduling/SKILL.md` is the sole operational behavior contract.
- Do not add a service, state table, generalized state machine, or configurable option count.

---

### Task 1: Validate scheduling transitions at observation time

**Files:**
- Modify: `tests/test_monitor.py`
- Modify: `skills/pipeline-monitor/scripts/monitor.py`

**Interfaces:**
- Consumes: the existing observation payload and current `monitor_contact.data` snapshot.
- Produces: `normalize_calendar_plan(action: str, plan: list, draft: dict | None, contact: dict | None) -> list[dict]`, with each entry containing exactly `effect`, `target`, `operation`, and `intent`.

- [ ] **Step 1: Make the shared accepted fixture truthful**

Update `write_contact` to accept a `holds` string and include it in frontmatter. Give the default Alex page two holds. Change `observation()` to use this literal invitation-first plan:

```python
"calendar_plan": [
    {"effect": "invitation", "target": "work/calendar/new", "operation": "create",
     "intent": "Alex; Tuesday 14:00; guest alex@example.com; video; send invitation"},
    {"effect": "delete_hold", "target": "work/calendar/hold-1", "operation": "delete",
     "intent": "Delete verified sibling hold 1 after invitation verification"},
    {"effect": "delete_hold", "target": "work/calendar/hold-2", "operation": "delete",
     "intent": "Delete verified sibling hold 2 after invitation verification"},
]
```

Add `new_options_observation(**changes)` as a test-fixture method that starts
from `observation()`, replaces the action, summary, next step, and plan with the
literal three hold entries below, then applies `changes`:

```python
[
    {"effect": "hold", "target": "work/calendar/hold-1", "operation": "create",
     "intent": "Busy attendee-free tentative hold 1; notifications off"},
    {"effect": "hold", "target": "work/calendar/hold-2", "operation": "create",
     "intent": "Busy attendee-free tentative hold 2; notifications off"},
    {"effect": "hold", "target": "work/calendar/hold-3", "operation": "create",
     "intent": "Busy attendee-free tentative hold 3; notifications off"},
]
```

- [ ] **Step 2: Add failing invariant tests**

Add tests that call the real `monitor.observe` boundary with literal payloads:

```python
def test_new_options_requires_three_holds_and_a_draft(self):
    valid = self.new_options_observation()
    self.assertEqual(len(monitor.observe(self.db, valid)["suggestion"]["payload"]["calendar_plan"]), 3)
    for broken, message in (
        ({**valid, "calendar_plan": valid["calendar_plan"][:2]}, "exactly three"),
        ({**valid, "draft": None}, "prepared draft"),
    ):
        with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
            monitor.observe(self.db, broken)

def test_accepted_requires_invitation_then_every_sibling_hold_delete(self):
    for plan, message in (
        ([], "invitation first"),
        (self.observation()["calendar_plan"][:2], "every live sibling hold"),
        (list(reversed(self.observation()["calendar_plan"])), "invitation first"),
    ):
        with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
            monitor.observe(self.db, self.observation(calendar_plan=plan))
```

Also add one rejection case for an unsupported `effect` value.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_monitor.MonitorTests.test_new_options_requires_three_holds_and_a_draft tests.test_monitor.MonitorTests.test_accepted_requires_invitation_then_every_sibling_hold_delete -v
```

Expected: failures because the current validator accepts two holds, missing drafts, and empty or incomplete accepted plans.

- [ ] **Step 4: Implement one normalization and invariant function**

Add `PLAN_EFFECTS = ("hold", "invitation", "delete_hold")`, a semicolon-based hold counter, and `normalize_calendar_plan`. It must:

```python
def normalize_calendar_plan(action, plan, draft, contact):
    if not isinstance(plan, list):
        raise ValueError("calendar_plan must be a list of exact operations")
    normalized = []
    for step in plan:
        if not isinstance(step, dict) or set(step) != {"effect", "target", "operation", "intent"}:
            raise ValueError("each calendar operation needs exactly effect, target, operation and intent")
        item = {key: required(step[key], key) for key in ("effect", "target", "operation", "intent")}
        if item["effect"] not in PLAN_EFFECTS:
            raise ValueError("unsupported calendar effect")
        if item in normalized:
            raise ValueError("duplicate calendar operation")
        normalized.append(item)
    if action == "new_options":
        if [item["effect"] for item in normalized] != ["hold", "hold", "hold"]:
            raise ValueError("new_options requires exactly three hold operations")
        if not draft:
            raise ValueError("new_options requires a prepared draft")
    if action == "accepted":
        if not normalized or normalized[0]["effect"] != "invitation" or any(
                item["effect"] != "delete_hold" for item in normalized[1:]):
            raise ValueError("accepted requires the invitation first, followed only by sibling hold deletions")
        fields = (contact or {}).get("fields", {})
        expected = len([item for item in str(fields.get("holds", "")).split(";") if item.strip()])
        if len(normalized) - 1 != expected:
            raise ValueError("accepted must delete every live sibling hold")
    return normalized
```

In `observe`, load the current contact row once, pass its decoded data into this helper, and retain the existing unknown-contact check. Validate the draft fields before invoking the helper so “prepared draft” means a structurally valid draft.

- [ ] **Step 5: Run the focused tests and complete monitor tests**

Run:

```bash
python3 -m unittest tests.test_monitor -v
```

Expected: all monitor tests pass.

- [ ] **Step 6: Commit the transition contract**

```bash
git add tests/test_monitor.py skills/pipeline-monitor/scripts/monitor.py
git commit -m "feat: enforce scheduling transition plans"
```

### Task 2: Authorize only planned automatic holds

**Files:**
- Modify: `tests/test_monitor.py`
- Modify: `skills/external-action/scripts/monitor_guard.py`
- Modify: `skills/external-action/scripts/operations.py`

**Interfaces:**
- Consumes: the persisted monitor suggestion and the exact external operation identity.
- Produces: `monitor_operation(...) -> dict | None`, returning the matched plan entry and `automatic_hold: bool` for linked calendar operations.

- [ ] **Step 1: Add the failing authorization test**

Add a test that observes a valid `new_options` suggestion, prepares its first exact hold operation while `calendar_manage` remains `approval`, and asserts that the resulting operation is already approved and claimable before approving the suggestion:

```python
def test_pending_new_options_may_claim_only_its_exact_hold_operations(self):
    proposal = self.new_options_observation()
    item = monitor.observe(self.db, proposal)["suggestion"]
    hold = item["payload"]["calendar_plan"][0]
    result = self.helper(
        "external-action", "operations.py", "prepare",
        "--scope", "calendar", "--target", hold["target"],
        "--operation", hold["operation"], "--intent", hold["intent"],
        "--suggestion-id", str(item["id"]),
    )
    self.assertFalse(result["approval_required"])
    self.assertTrue(self.helper("external-action", "operations.py", "claim",
                                "--id", str(result["operation"]["id"]))["claimed"])
```

Keep the existing accepted-invitation test and rename it to state the remaining rule: a monitor invitation requires specific approval even under autonomous calendar policy.

- [ ] **Step 2: Run the authorization tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_monitor.MonitorTests.test_pending_new_options_may_claim_only_its_exact_hold_operations tests.test_monitor.MonitorTests.test_monitor_invitation_requires_specific_approval_even_with_autonomous_calendar_policy -v
```

Expected: the hold test fails because every monitor operation is currently forced to approval.

- [ ] **Step 3: Return the matched plan semantics from the guard**

Change `monitor_operation` to compare only `target`, `operation`, and `intent` against each plan entry, then return:

```python
{
    "entry": matched_entry,
    "automatic_hold": (
        payload.get("action") == "new_options"
        and matched_entry.get("effect") == "hold"
    ),
}
```

When `approved=True`, permit a pending suggestion only for `automatic_hold`; still require the contact to exist in the latest verified pipeline read. For every other effect, retain `monitor_item(..., approved=True)` unchanged. Legacy persisted plans without `effect` remain matchable but can never become automatic.

- [ ] **Step 4: Reuse the guard decision in the existing operation ledger**

In `operations.prepare`, use the guard result to choose the existing status:

```python
monitor_plan = monitor_operation(connection, monitor_id, args.scope, target, operation, intent)
if monitor_id is not None:
    policy = "autonomous" if monitor_plan["automatic_hold"] else "approval"
```

Do not add a table, policy value, command, or bypass. `approve` and `claim` continue calling the same guard with `approved=True`.

- [ ] **Step 5: Run monitor and state tests**

Run:

```bash
python3 -m unittest tests.test_monitor tests.test_state -v
```

Expected: all tests pass, including exact-operation mismatch and obsolete-suggestion rejection.

- [ ] **Step 6: Commit the narrow authorization**

```bash
git add tests/test_monitor.py skills/external-action/scripts/monitor_guard.py skills/external-action/scripts/operations.py
git commit -m "feat: authorize planned monitor holds"
```

### Task 3: Consolidate the operational contract

**Files:**
- Modify: `skills/founder-scheduling/SKILL.md`
- Modify: `skills/pipeline-monitor/SKILL.md`
- Modify: `skills/external-action/SKILL.md`
- Modify: `runtime/persona.md`
- Modify: `README.md`
- Modify: `docs/INSTALL.md`

**Interfaces:**
- Consumes: the executable invariants from Tasks 1 and 2.
- Produces: one operational contract in `founder-scheduling`; all other prose describes only ownership and authorization boundaries.

- [ ] **Step 1: Rewrite the canonical lifecycle in founder-scheduling**

Replace “offer N options” and “Only on an explicit hold request” with exactly three options and the two authorized hold paths: a direct founder request or the opted-in monitor's persisted `new_options` plan. State that Gmail gets a verified saved draft when enabled, while text/Plow stays ledger-only and requests send permission. Keep invite-first verification and complete sibling-hold deletion in `Pick`.

- [ ] **Step 2: Remove contradictory policy copies**

In `pipeline-monitor`, `external-action`, and `runtime/persona`, reference the `founder-scheduling` contract and retain only these local boundaries:

- the monitor may create the three exact planned tentative holds;
- it never sends communication, creates invitations, or removes holds without specific approval;
- automatic hold effects still use the external-action ledger and provider read-back;
- factual wiki fields change only after verified effects.

Update the scheduled prompt to say the same without reproducing the lifecycle.

- [ ] **Step 3: Make public documentation point to the contract**

Update the README capability row to link to `skills/founder-scheduling/SKILL.md`. Update INSTALL behavior and acceptance checks so the three tentative holds appear during proposal preparation, while invitation creation and deletion remain unchanged until approval.

- [ ] **Step 4: Check prose for the old contradictions**

Run:

```bash
rg -n "offer N|Only on an explicit hold request|never.*creates/removes holds|never.*mutate calendars|calendar is unchanged until you approve" README.md runtime/persona.md docs/INSTALL.md skills
```

Expected: no contradictory lifecycle rule remains. Contextual statements about other calendar mutations may remain only when they explicitly exempt the three planned tentative holds.

- [ ] **Step 5: Run the complete repository gate**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass; only the existing environment-dependent native runtime test may skip.

- [ ] **Step 6: Commit the canonical contract**

```bash
git add README.md docs/INSTALL.md runtime/persona.md skills/founder-scheduling/SKILL.md skills/pipeline-monitor/SKILL.md skills/external-action/SKILL.md
git commit -m "docs: centralize the scheduling lifecycle"
```

### Task 4: Verify the complete change and prepare review

**Files:**
- Modify if needed: `docs/superpowers/specs/2026-09-18-canonical-scheduling-contract-design.md`
- Verify: `docs/superpowers/plans/2026-09-18-canonical-scheduling-contract.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a reviewable branch whose code, canonical contract, and public documentation agree.

- [ ] **Step 1: Self-review the spec and implementation diff**

Run:

```bash
git diff origin/main...HEAD --check
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

Check every changed rule against the spec, confirm there is no second runtime source of lifecycle policy, and remove any unnecessary helper or repeated prose.

- [ ] **Step 2: Run syntax and complete behavior gates freshly**

Run:

```bash
python3 -m py_compile skills/pipeline-monitor/scripts/monitor.py skills/external-action/scripts/monitor_guard.py skills/external-action/scripts/operations.py
python3 -m unittest discover -s tests -v
```

Expected: compilation succeeds and the full suite passes with only documented environment-dependent skips.

- [ ] **Step 3: Commit any final spec simplification**

```bash
git add docs/superpowers/specs/2026-09-18-canonical-scheduling-contract-design.md
git diff --cached --quiet || git commit -m "docs: simplify scheduling design record"
```

- [ ] **Step 4: Push, open the operator-controlled PR, and enter convergence**

Push `feat/canonical-scheduling-contract`, open a PR against `Tiagohbello/plow-founder-agent`, then follow the supplied `babysit-pr` workflow. After every fix push, request exactly one `/srosro-update-review`; require a clean KWR review of the exact current head and green required checks. Do not merge without explicit consent for that exact PR.
