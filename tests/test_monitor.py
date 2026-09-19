from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pipeline_monitor", ROOT / "skills/pipeline-monitor/scripts/monitor.py")
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class Scheduler:
    """Only the native cron boundary is fake; state and ledgers are real."""
    def __init__(self):
        self.jobs = []
        self.calls = []
        self.fail = None

    def call(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == self.fail:
            raise ValueError("native scheduler unavailable")
        if action == "list": return {"jobs": deepcopy(self.jobs)}
        if action == "create":
            job = {**kwargs, "job_id": f"job-{len(self.jobs) + 1}", "enabled": True}
            self.jobs.append(job)
            return job
        job = next(j for j in self.jobs if j["job_id"] == kwargs["job_id"])
        if action == "update": job.update(kwargs)
        if action in ("pause", "resume"): job["enabled"] = action == "resume"
        return {"job": job}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.environment = patch.dict(os.environ, {"HERMES_HOME": str(self.home), "PLOW_HOME_CHANNEL": "cht_test_owner"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.path = self.home / "founder-agent/founder-agent.db"
        self.db = monitor.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        self.scheduler = Scheduler()
        self.config = {
            "wiki_verified_ref": "read:wiki:1",
            "timezone": "America/Los_Angeles", "interval_minutes": 30,
            "sources": {"gmail": {"status": "available", "evidence": "read:mail:1"},
                        "messages": {"status": "blocked", "evidence": "permission denied"}},
        }
        monitor.configure(self.db, self.config, self.scheduler)
        self.helper("founder-context", "profile.py", "set-calendar",
                    "--account", "work@example.com", "--calendar-id", "primary",
                    "--default-calendar", "primary", "--timezone", "America/Los_Angeles",
                    "--status", "available", "--evidence", "calendar:verified", "--is-default")
        self.vault = self.path.parent / "wiki"
        self.write_contact("alex", email="alex@example.com", phone="+1 415 555 0100",
                           holds=("work@example.com/primary/hold-1; "
                                  "work@example.com/primary/hold-2"))
        self.contact = self.contacts()["contacts"][0]

    def write_contact(self, slug, *, email="", phone="", person=True, status="Times sent", holds=""):
        """One pipeline entry and, unless suppressed, the person page it points at."""
        entry = self.vault / monitor.PIPELINE_ROOT / f"{slug}.md"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(f'---\ntype: "PipelineEntry"\nperson: "{slug}"\nstatus: "{status}"\n'
                         f'holds: "{holds}"\nnext_step: ""\n---\n\nNotes about {slug}.\n')
        if person:
            page = self.vault / monitor.PEOPLE_ROOT / f"{slug}.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(f'---\ntype: "Person"\ntitle: "{slug.title()}"\n'
                            f'email: "{email}"\nphone: "{phone}"\n---\n\nWho {slug} is.\n')
        return entry

    def wiki(self):
        return {str(p.relative_to(self.vault)): p.read_bytes() for p in self.vault.rglob("*.md")}

    def shasum(self, pages, count=None):
        """What `shasum -a 256` on the Mac prints for these pages."""
        pipeline = sum(1 for rel in pages if rel.startswith(monitor.PIPELINE_ROOT + "/"))
        total = pipeline if count is None else count
        body = "".join(f"{hashlib.sha256(body).hexdigest()}  {rel}\n" for rel, body in sorted(pages.items()))
        return f"{body}entries {total}\n"

    def contacts(self, listing=None):
        """One `contacts` run; by default against a Mac that matches the mirror."""
        path = self.home / "listing.txt"
        path.write_text(self.shasum(self.wiki()) if listing is None else listing)
        return monitor.contacts(self.db, self.vault, monitor.listing(path))

    def observation(self, **changes):
        value = {
            "contact_key": self.contact["contact_key"], "conversation_ref": "gmail:thread-1",
            "conversation_context": "Gmail · Alex · Scheduling",
            "calendar_plan": [
                {"effect": "invitation", "target": "work@example.com/primary/new",
                 "intent": "Alex; Tuesday 14:00; guest alex@example.com; video; send invitation"},
                {"effect": "delete_hold", "target": "work@example.com/primary/hold-1",
                 "intent": "Delete verified sibling hold 1 after invitation verification"},
                {"effect": "delete_hold", "target": "work@example.com/primary/hold-2",
                 "intent": "Delete verified sibling hold 2 after invitation verification"},
            ],
            "evidence_refs": ["gmail:message-1"], "evidence_at": "2026-09-17T14:00:00Z",
            "evidence_summary": "Alex replied in Scheduling at 07:00 PT.",
            "action": "accepted", "summary": "Alex accepted Tuesday at 14:00 PT.",
            "next_step": "Create a video invite and release the two sibling holds. Approve?",
            "draft": {"channel": "gmail", "thread_id": "thread-1", "recipient": "alex@example.com",
                      "subject": "Re: Scheduling", "body": "Tuesday at 14:00 PT works."},
        }
        value.update(changes)
        return value

    def new_options_observation(self, **changes):
        value = self.observation(
            action="new_options",
            summary="You owe Alex times.",
            next_step="Three held options are drafted. Review and send?",
            calendar_plan=[
                {"effect": "hold", "target": "work@example.com/primary/new",
                 "intent": json.dumps(self.hold())},
                {"effect": "hold", "target": "work@example.com/primary/new",
                 "intent": json.dumps(self.hold(start="2026-09-23T12:00:00-07:00",
                                                 end="2026-09-23T12:30:00-07:00"))},
                {"effect": "hold", "target": "work@example.com/primary/new",
                 "intent": json.dumps(self.hold(start="2026-09-24T12:00:00-07:00",
                                                 end="2026-09-24T12:30:00-07:00"))},
            ],
        )
        value.update(changes)
        return value

    def hold(self, **changes):
        value = {
            "account": "work@example.com", "calendar": "primary",
            "start": "2026-09-22T12:00:00-07:00", "end": "2026-09-22T12:30:00-07:00",
            "timezone": "America/Los_Angeles", "title": "HOLD — Alex / Example",
            "attendees": [], "send_updates": "none", "transparency": "opaque",
        }
        value.update(changes)
        return value

    def helper(self, skill, filename, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / "skills" / skill / "scripts" / filename),
                                 "--db", str(self.path), *args], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr + result.stdout)
        return json.loads(result.stdout) if ok else result.stderr

    def approve(self, item):
        notice = monitor.notice(self.db)
        monitor.receipt(self.db, notice["notice_id"], "delivered", "plow:verified-preview", notice["body"])
        return monitor.decide(self.db, item["id"], {"evidence_refs": item["payload"]["evidence_refs"],
            "notice_id": notice["notice_id"],
            "approval_ref": "founder:approve:1", "validation_ref": "fresh:thread-and-calendars:1"})

    def test_opt_in_reconfigure_pause_restart_and_recover_creation(self):
        self.assertFalse(monitor.show(self.db)["enabled"])
        self.assertEqual(self.scheduler.jobs, [])
        first = monitor.sync_job(self.db, self.scheduler, True)
        self.assertTrue(self.scheduler.jobs[0]["attach_to_session"])
        changed = {**self.config, "interval_minutes": 45}
        monitor.configure(self.db, changed, self.scheduler)
        self.assertEqual(len(self.scheduler.jobs), 1)
        self.assertEqual(self.scheduler.jobs[0]["schedule"], "45m")
        self.assertTrue(self.scheduler.jobs[0]["attach_to_session"])
        self.db.close()
        self.db = monitor.connect(self.path)
        self.assertEqual(monitor.show(self.db)["job_id"], first["job_id"])
        monitor.sync_job(self.db, self.scheduler, False)
        self.assertFalse(monitor.show(self.db)["enabled"])
        self.assertFalse(self.scheduler.jobs[0]["enabled"])
        # Simulate process death after native create but before saving its id.
        with self.db: self.db.execute("UPDATE monitor_config SET job_id=NULL")
        monitor.sync_job(self.db, self.scheduler, True)
        self.assertEqual(len(self.scheduler.jobs), 1)
        self.assertEqual(monitor.show(self.db)["job_id"], first["job_id"])

    def test_native_failure_leaves_monitor_closed(self):
        monitor.sync_job(self.db, self.scheduler, True)
        self.scheduler.fail = "update"
        with self.assertRaisesRegex(ValueError, "unavailable"):
            monitor.configure(self.db, {**self.config, "interval_minutes": 15}, self.scheduler)
        self.assertFalse(monitor.show(self.db)["enabled"])
        self.assertFalse(self.scheduler.jobs[0]["enabled"])

    def test_supported_schedule_options(self):
        monitor.sync_job(self.db, self.scheduler, True)
        for interval in (15, 30, 45):
            with self.subTest(interval=interval):
                monitor.configure(self.db, {**self.config, "interval_minutes": interval}, self.scheduler)
                self.assertEqual(self.scheduler.jobs[0]["schedule"], f"{interval}m")

    def test_onboarding_must_choose_frequency(self):
        without_frequency = {key: value for key, value in self.config.items() if key != "interval_minutes"}
        with self.assertRaisesRegex(ValueError, "choose interval_minutes"):
            monitor.configure(self.db, without_frequency, self.scheduler)

    def test_removed_interval_requires_explicit_reconfiguration_on_resume(self):
        monitor.sync_job(self.db, self.scheduler, True)
        with self.db:
            self.db.execute(
                "UPDATE monitor_config SET config=?,enabled=1",
                (monitor.canonical({**self.config, "interval_minutes": 5}),),
            )
        state = monitor.show(self.db)
        self.assertTrue(state["schedule_requires_choice"])
        self.assertEqual(state["available_intervals"], [15, 30, 45])
        with self.assertRaisesRegex(ValueError, "15, 30 or 45"):
            monitor.sync_job(self.db, self.scheduler, True)
        self.assertFalse(monitor.show(self.db)["enabled"])
        self.assertFalse(self.scheduler.jobs[0]["enabled"])

    def test_cron_output_cleanup_service_is_packaged_before_gateway(self):
        root = ROOT / "image/s6-overlay/s6-rc.d"
        self.assertEqual((root / "cron-config/type").read_text().strip(), "oneshot")
        self.assertIn("cron.wrap_response false", (root / "cron-config/run").read_text())
        self.assertTrue((root / "hermes-gateway/dependencies.d/cron-config").exists())

    def test_working_hours_dst_and_manual_check(self):
        monitor.sync_job(self.db, self.scheduler, True)
        cases = [("2026-03-06T16:59:00Z", False), ("2026-03-06T17:00:00Z", True),
                 ("2026-03-07T17:00:00Z", False), ("2026-03-09T16:00:00Z", True),
                 ("2026-03-10T01:00:00Z", False), ("2026-11-02T17:00:00Z", True)]
        for instant, expected in cases:
            with self.subTest(instant=instant):
                self.assertEqual(monitor.gate(self.db, monitor.parse_time(instant))["run"], expected)
        monitor.sync_job(self.db, self.scheduler, False)
        self.assertFalse(monitor.gate(self.db, monitor.parse_time(cases[1][0]))["run"])
        self.assertTrue(monitor.gate(self.db, monitor.parse_time(cases[1][0]), manual=True)["run"])
        self.assertFalse(monitor.show(self.db)["enabled"])

    def test_invalid_configuration_and_private_destination(self):
        for change in ({"timezone": "Invalid/Zone"}, {"interval_minutes": 1}, {"interval_minutes": 5},
                       {"interval_minutes": 60}, {"weekdays": []},
                       {"start": "18:00", "end": "09:00"}, {"wiki_verified_ref": ""},
                       {"sources": {"gmail": {"status": "blocked", "evidence": "403"}}}):
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                monitor.configure(self.db, {**self.config, **change}, self.scheduler)
        result = monitor.configure(self.db, {**self.config, "deliver": "plow_chat:group",
                                   "owner_chat_verified_ref": "untrusted assertion"}, self.scheduler)
        self.assertEqual(result["config"]["deliver"], "plow_chat:cht_test_owner")
        self.assertNotIn("owner_chat_verified_ref", result["config"])
        with patch.dict(os.environ, {"PLOW_HOME_CHANNEL": ""}):
            with self.assertRaisesRegex(ValueError, "PLOW_HOME_CHANNEL"):
                monitor.configure(self.db, self.config, self.scheduler)

    def test_an_entry_is_reachable_only_through_a_person_the_wiki_knows(self):
        self.assertEqual(self.contact["handles"], ["+1 415 555 0100", "alex@example.com"])
        self.assertEqual(self.contact["contact_key"], "alex")
        vault_before = sorted((p, p.read_bytes()) for p in self.vault.rglob("*.md"))
        monitor.observe(self.db, self.observation())
        self.assertEqual(sorted((p, p.read_bytes()) for p in self.vault.rglob("*.md")), vault_before,
                         "reading the pipeline must not write to the vault")

        self.write_contact("dana", person=False)                      # entry with no person page
        self.write_contact("robin", email="", phone="")               # person page with no handles
        # entities/people is shared and edited in Obsidian, so a half-written page is
        # ordinary. It must cost that one contact, never the whole check.
        self.write_contact("sam", email="sam@example.com")
        (self.vault / monitor.PEOPLE_ROOT / "sam.md").write_text("# no frontmatter yet\n")
        self.write_contact("kit", email="kit@example.com")
        (self.vault / monitor.PIPELINE_ROOT / "kit.md").write_text("---\nunclosed: block\n")

        found = self.contacts()
        self.assertEqual([c["contact_key"] for c in found["contacts"]], ["alex"])
        # A page cannot claim the namespace the database uses for feed blockers.
        self.write_contact("source:gmail", email="spoof@example.com")
        found = self.contacts()
        self.assertEqual(sorted(u["contact_key"] for u in found["unlinked"]),
                         ["dana", "kit", "robin", "sam", "source:gmail"])
        self.assertIn("reserved", next(u for u in found["unlinked"]
                                       if u["contact_key"] == "source:gmail")["reason"])
        self.assertIn("cannot be read", next(u for u in found["unlinked"] if u["contact_key"] == "sam")["reason"])

    def test_reconfiguring_keeps_the_work_already_prepared(self):
        # The root is fixed, so no reconfigure changes which pipeline this is.
        # Re-proving the read must not throw away pending suggestions or cursors.
        item = monitor.observe(self.db, self.observation())["suggestion"]
        monitor.configure(self.db, {**self.config, "wiki_verified_ref": "read:wiki:2"}, self.scheduler)
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "pending")
        self.assertTrue(self.db.execute("SELECT 1 FROM monitor_contact").fetchone())

    def test_an_unlinked_contact_can_recover_but_cannot_execute(self):
        # The two halves of the same rule: its suggestion survives an unreadable
        # page, and cannot be approved while the pipeline cannot place the contact.
        item = monitor.observe(self.db, self.observation())["suggestion"]
        entry = self.vault / monitor.PIPELINE_ROOT / "alex.md"
        good = entry.read_text()
        notice = monitor.notice(self.db)
        monitor.receipt(self.db, notice["notice_id"], "delivered", "plow:verified-preview", notice["body"])
        decision = {"evidence_refs": item["payload"]["evidence_refs"], "notice_id": notice["notice_id"],
                    "approval_ref": "founder:approve:1", "validation_ref": "fresh:thread-and-calendars:1"}

        entry.write_text("---\nunclosed: block\n")
        self.contacts()
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "pending")
        with self.assertRaisesRegex(ValueError, "not in the latest verified pipeline read"):
            monitor.decide(self.db, item["id"], decision)

        entry.write_text(good)
        self.contacts()
        self.assertEqual(monitor.decide(self.db, item["id"], decision)["status"], "approved")

        # Approval does not expire on its own. If a later read unlinks the contact,
        # the already-approved suggestion must not still authorize an external effect.
        guard = monitor.sibling("external-action", "monitor_guard.py")
        self.assertTrue(guard.monitor_item(self.db, item["id"], approved=True))
        entry.write_text("---\nunclosed: block\n")
        self.contacts()
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "approved")
        with self.assertRaisesRegex(ValueError, "not in the latest verified pipeline read"):
            guard.monitor_item(self.db, item["id"], approved=True)
        # Staging and reconciling a local record is not an external effect, so it
        # must not be blocked by the same gate.
        self.assertTrue(guard.monitor_item(self.db, item["id"]))


    def test_an_entry_that_leaves_the_pipeline_supersedes_its_suggestion(self):
        monitor.observe(self.db, self.observation())
        # Another entry keeps the root listed: an empty listing is refused, never
        # read as everyone leaving.
        self.write_contact("dana", email="dana@example.com")
        entry = f"{monitor.PIPELINE_ROOT}/alex.md"
        found = self.contacts(self.shasum({rel: body for rel, body in self.wiki().items() if rel != entry}))
        self.assertEqual([c["contact_key"] for c in found["contacts"]], ["dana"])
        self.assertFalse((self.vault / entry).exists(), "the mirror keeps only what the wiki still has")
        self.assertEqual(monitor.suggestion(self.db, 1)["status"], "superseded")

    def test_a_person_page_deleted_on_the_mac_stops_supplying_handles(self):
        person = f"{monitor.PEOPLE_ROOT}/alex.md"
        found = self.contacts(self.shasum({rel: body for rel, body in self.wiki().items() if rel != person}))
        self.assertEqual(found["unlinked"], [{"contact_key": "alex", "reason": f"no {monitor.PEOPLE_ROOT} page"}])

    def test_a_page_not_yet_copied_is_still_in_the_pipeline(self):
        # The listing is the pipeline; the mirror only caches it. A page it lacks or
        # holds stale is present and unlinked until copied, so a first run or a
        # partial copy never supersedes live work.
        item = monitor.observe(self.db, self.observation())["suggestion"]
        mirrored = self.wiki()
        # A page no entry reads is never copied: the index is generated, and
        # `entities/people` is shared.
        mac = {**mirrored, f"{monitor.PIPELINE_ROOT}/index.md": b"| alex |\n",
               f"{monitor.PEOPLE_ROOT}/jane-doe.md": b"Not in the pipeline.\n"}
        entry = f"{monitor.PIPELINE_ROOT}/alex.md"
        edited = {**mac, entry: mac[entry].replace(b"Notes", b"Newer notes")}
        for case, pages, stale in (("fresh", mac, []), ("changed on the Mac", edited, [entry]),
                                   ("first run", mac, sorted(mirrored))):
            with self.subTest(case=case):
                if case == "first run":
                    shutil.rmtree(self.vault)
                found = self.contacts(self.shasum(pages))
                self.assertEqual([c["page"] for c in found["copy"]], stale)
                self.assertEqual(found["unlinked"], [{"contact_key": "alex", "reason": "not yet copied from the wiki"}]
                                 if stale else [])
                self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "pending")
                # Write each page where it says, as the check does; the next run reads it whole.
                for copy in found["copy"]:
                    Path(copy["to"]).write_bytes(pages[copy["page"]])
                found = self.contacts(self.shasum(pages))
                self.assertEqual((found["copy"], [c["contact_key"] for c in found["contacts"]]), ([], ["alex"]))

    def test_a_dropped_listing_line_is_refused_rather_than_superseding(self):
        monitor.observe(self.db, self.observation())
        # Another entry keeps the root listed.
        self.write_contact("dana", email="dana@example.com")
        entry = f"{monitor.PIPELINE_ROOT}/alex.md"
        # The Mac had 2 pipeline entries, but the relay dropped alex.md while keeping the count.
        listing = self.shasum({rel: body for rel, body in self.wiki().items() if rel != entry}, count=2)
        with self.assertRaisesRegex(ValueError, r"^the listing has 1 pipeline entries, expected 2$"):
            self.contacts(listing)
        self.assertEqual(monitor.suggestion(self.db, 1)["status"], "pending",
                         "a dropped line must not supersede live work")

    def test_a_listing_names_pages_in_the_two_roots_or_is_refused(self):
        # The check writes each page it is sent to, so a path outside the roots is
        # refused rather than mirrored. So is a listing with no entries, or a line it
        # cannot read: a failed `cd` lists nothing and a mangled line drops an entry,
        # and reading either as entries leaving would supersede their work.
        listed, digest = self.shasum(self.wiki()), "0" * 64
        for listing, error in (("", "no entries count"),
                               (f"{digest}  {monitor.PEOPLE_ROOT}/alex.md\n", "no entries count"),
                               ("entries 0\n", "not in the wiki"),
                               (f"{digest}  {monitor.PEOPLE_ROOT}/alex.md\nentries 0\n", "not in the wiki"),
                               (f"{digest}  {monitor.PIPELINE_ROOT}/index.md\nentries 1\n", "not in the wiki"),
                               (listed.replace("  ", " ", 1), "cannot be read"),
                               # Any readable file can be passed, so the refusal names the line, never its text.
                               ("KEY=held-in-some-other-file\n", r"^the listing cannot be read at line 1; save the command's output verbatim$"),
                               (f"{listed}shasum: {monitor.PIPELINE_ROOT}/kit.md: Permission denied\n", "cannot be read"),
                               (f"{listed}{digest}  projects/founder-agent/notes.md\n", "outside"),
                               (f"{listed}{digest}  {monitor.PIPELINE_ROOT}/../escape.md\n", "outside"),
                               (f"{listed}{digest}  {monitor.PIPELINE_ROOT}/alex.txt\n", "outside"),
                               (f"{listed}entries 1\n", "cannot be read"),
                               (self.shasum(self.wiki(), count=0), r"^the listing has 1 pipeline entries, expected 0$"),
                               (self.shasum(self.wiki(), count=2), r"^the listing has 1 pipeline entries, expected 2$")):
            with self.subTest(listing=listing[-50:]), self.assertRaisesRegex(ValueError, error):
                self.contacts(listing)
        # A blank line names no page. Through the CLI, which keeps the mirror
        # beside the database.
        path = self.home / "listing.txt"
        path.write_text(listed + "\n\n")
        found = self.helper("pipeline-monitor", "monitor.py", "contacts", "--listing", str(path))
        self.assertEqual((found["copy"], [c["contact_key"] for c in found["contacts"]]), ([], ["alex"]))

    def test_a_check_may_write_the_advice_and_nothing_else(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        update = monitor.page_update(self.db, item["id"])
        self.assertEqual(update["path"], f"{monitor.PIPELINE_ROOT}/alex.md")
        # The payload carries a calendar plan and a draft; none of that is a fact
        # about the world an unattended check gets to assert in the founder's wiki.
        self.assertEqual(list(update["changes"]), ["next_step"])
        self.assertEqual(update["changes"]["next_step"], self.observation()["next_step"])
        # Once it is resolved the answer is what is left standing, which here is
        # nothing — the field never widens and the page never keeps stale advice.
        monitor.supersede(self.db, item["id"])
        self.assertEqual(monitor.page_update(self.db, item["id"])["changes"], {"next_step": ""})

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

    def test_accepted_rejects_legacy_hold_labels_until_resolved_to_event_targets(self):
        legacy = "Tuesday 14:00 PT; Wednesday 10:00 PT"
        self.write_contact("alex", email="alex@example.com", phone="+1 415 555 0100",
                           holds=legacy)
        self.contact = self.contacts()["contacts"][0]
        plan = self.observation()["calendar_plan"]
        plan[1]["target"], plan[2]["target"] = legacy.split("; ")
        with self.assertRaisesRegex(ValueError, "canonical provider event target"):
            monitor.observe(self.db, self.observation(calendar_plan=plan))

    def test_calendar_plan_rejects_unknown_effects(self):
        plan = self.observation()["calendar_plan"]
        plan[0] = {**plan[0], "effect": "maybe_invitation"}
        with self.assertRaisesRegex(ValueError, "unsupported calendar effect"):
            monitor.observe(self.db, self.observation(calendar_plan=plan))

    def test_calendar_effects_derive_operations_and_require_exact_hold_deletes(self):
        proposal = self.new_options_observation()
        duplicate_hold = [proposal["calendar_plan"][0], proposal["calendar_plan"][0],
                          proposal["calendar_plan"][2]]
        accepted = self.observation()["calendar_plan"]
        repeated_delete = [accepted[0], accepted[1], {**accepted[2], "target": accepted[1]["target"]}]
        unrelated_deletes = [accepted[0],
                             {**accepted[1], "target": "work@example.com/primary/other-1"},
                             {**accepted[2], "target": "work@example.com/primary/other-2"}]
        for observation, message in (
            (self.new_options_observation(calendar_plan=duplicate_hold), "duplicate calendar operation"),
            (self.observation(calendar_plan=repeated_delete), "unique target"),
            (self.observation(calendar_plan=unrelated_deletes), "match every live sibling hold"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                monitor.observe(self.db, observation)
        item = monitor.observe(self.db, proposal)["suggestion"]
        self.assertEqual([step["operation"] for step in item["payload"]["calendar_plan"]],
                         ["create", "create", "create"])

    def test_automatic_holds_require_structured_private_calendar_parameters(self):
        for changed_hold, message in (
            (self.hold(attendees=["alex@example.com"]), "attendee-free"),
            (self.hold(send_updates="all"), "notifications off"),
            (self.hold(transparency="transparent"), "busy"),
            (self.hold(account="other@example.com"), "target must match"),
            (self.hold(timezone="Not/A_Zone"), "valid ISO timestamps and timezone"),
        ):
            proposal = self.new_options_observation()
            proposal["calendar_plan"][0] = {
                **proposal["calendar_plan"][0], "intent": json.dumps(changed_hold)
            }
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                monitor.observe(self.db, proposal)

        proposal = self.new_options_observation()
        duplicate_slot = json.loads(proposal["calendar_plan"][0]["intent"])
        duplicate_slot["title"] = "HOLD — Alex / Different title"
        proposal["calendar_plan"][1]["intent"] = json.dumps(duplicate_slot)
        with self.assertRaisesRegex(ValueError, "distinct start and end"):
            monitor.observe(self.db, proposal)

    def test_current_advice_follows_evidence_and_empties_when_nothing_is_left(self):
        # One lifecycle: an old thread read after a new one does not outrank it,
        # resolving the stale one leaves the recent advice standing, and resolving
        # that one empties the page.
        recent = monitor.observe(self.db, self.observation(
            evidence_at="2026-09-17T18:00:00Z", evidence_refs=["gmail:recent"],
            next_step="Confirm Thursday. Approve?"))["suggestion"]
        stale = monitor.observe(self.db, self.new_options_observation(
            conversation_ref="gmail:old-thread", evidence_refs=["gmail:from-last-week"],
            evidence_at="2026-09-10T09:00:00Z", summary="An older thread offered times.",
            next_step="Reply to the old thread. Approve?"))["suggestion"]
        self.assertGreater(stale["id"], recent["id"])

        # Naming either suggestion answers for the contact, so an older thread's id
        # cannot put older advice on the page.
        for named in (stale, recent):
            with self.subTest(named=named["id"]):
                self.assertEqual(monitor.page_update(self.db, named["id"])["changes"]["next_step"],
                                 "Confirm Thursday. Approve?")

        for resolved, remaining in ((stale, "Confirm Thursday. Approve?"), (recent, "")):
            with self.subTest(resolved=resolved["id"]):
                monitor.supersede(self.db, resolved["id"])
                self.assertEqual(monitor.current_advice(self.db, "alex")["changes"]["next_step"], remaining)

    def test_a_resolved_suggestion_still_answers_for_its_contact(self):
        # Asked after `finish`, which is when the caller asks: the answer is what is
        # left standing, not an error and not the advice just completed.
        item = monitor.observe(self.db, self.observation())["suggestion"]
        self.approve(item)
        self.helper("pipeline-monitor", "monitor.py", "finish", "--id", str(item["id"]),
                    "--outcome", "completed", "--ref", "calendar:invite-1")
        update = monitor.page_update(self.db, item["id"])
        self.assertEqual(update["path"], f"{monitor.PIPELINE_ROOT}/alex.md")
        self.assertEqual(update["changes"]["next_step"], "")

    def test_a_source_blocker_yields_no_page_update(self):
        blocked = self.observation(contact_key="source:gmail", action="blocked", draft=None,
                                   calendar_plan=[], conversation_ref="source:gmail",
                                   evidence_refs=["gmail:auth-failure"],
                                   summary="Gmail access is blocked.", next_step="Reconnect Gmail. Approve?")
        item = monitor.observe(self.db, blocked)["suggestion"]
        # No page rather than an error, so both workflows can ask unconditionally
        # and neither needs its own eligibility rule.
        self.assertIsNone(monitor.page_update(self.db, item["id"]))

    def test_window_overlap_failure_and_source_isolation(self):
        key = self.contact["contact_key"]
        now = datetime(2026, 1, 31, tzinfo=timezone.utc)
        first = monitor.window(self.db, key, "gmail", now)
        self.assertTrue(first["since"].startswith("2026-01-01T00:00:00"))
        monitor.checkpoint(self.db, {"contact_key": key, "source": "gmail", "through": "2026-01-30T10:00:00Z", "success": True})
        with self.assertRaises(ValueError):
            monitor.checkpoint(self.db, {"contact_key": key, "source": "gmail", "through": "2026-01-30T11:00:00Z", "success": False})
        second = monitor.window(self.db, key, "gmail", now)
        self.assertTrue(second["since"].startswith("2026-01-30T09:00:00"))
        self.assertEqual(monitor.window(self.db, key, "messages", now)["since"], first["since"])

    def test_same_evidence_deduplicates_wording_and_draft_after_restart(self):
        first = monitor.observe(self.db, self.observation())["suggestion"]
        self.db.close()
        self.db = monitor.connect(self.path)
        changed = self.observation(summary="Different generated wording", draft={**self.observation()["draft"], "body": "Different wording"})
        result = monitor.observe(self.db, changed)
        self.assertFalse(result["created"])
        self.assertEqual(result["suggestion"]["id"], first["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM draft").fetchone()[0], 1)

    def test_new_evidence_cancels_draft_approval_and_pending_calendar_actions(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        self.approve(item)
        self.helper("external-action", "drafts.py", "approve", "--id", str(item["draft_id"]), "--approval-ref", "founder:approve:1")
        planned = item["payload"]["calendar_plan"][0]
        operation = self.helper("external-action", "operations.py", "prepare", "--scope", "calendar",
                                "--target", planned["target"], "--operation", planned["operation"],
                                "--intent", planned["intent"], "--suggestion-id", str(item["id"]))["operation"]
        newer = self.observation(evidence_refs=["gmail:message-2"], evidence_at="2026-09-17T15:00:00Z", action="modality")
        replacement = monitor.observe(self.db, newer)["suggestion"]
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "superseded")
        self.assertEqual(replacement["status"], "pending")
        self.assertEqual(self.db.execute("SELECT status FROM draft WHERE id=?", (item["draft_id"],)).fetchone()[0], "cancelled")
        self.assertEqual(self.db.execute("SELECT status FROM external_operation WHERE id=?", (operation["id"],)).fetchone()[0], "cancelled")
        self.helper("external-action", "drafts.py", "claim-send", "--id", str(item["draft_id"]), ok=False)
        self.helper("external-action", "operations.py", "claim", "--id", str(operation["id"]), ok=False)
        # Historical evidence from overlap must not replace the newer suggestion.
        monitor.observe(self.db, self.observation(evidence_refs=["older:0"], evidence_at="2026-09-16T14:00:00Z"))
        self.assertEqual(monitor.suggestion(self.db, replacement["id"])["status"], "pending")

    def test_monitor_invitation_requires_specific_approval_even_with_autonomous_calendar_policy(self):
        self.helper("founder-context", "profile.py", "set-permission", "--capability", "calendar_manage", "--policy", "autonomous")
        item = monitor.observe(self.db, self.observation())["suggestion"]
        planned = item["payload"]["calendar_plan"][0]
        result = self.helper("external-action", "operations.py", "prepare", "--scope", "calendar",
                             "--target", planned["target"], "--operation", planned["operation"],
                             "--intent", planned["intent"], "--suggestion-id", str(item["id"]))
        oid = str(result["operation"]["id"])
        self.assertTrue(result["approval_required"])
        self.helper("external-action", "operations.py", "approve", "--id", oid, ok=False)
        self.helper("external-action", "operations.py", "claim", "--id", oid, ok=False)
        self.helper("external-action", "drafts.py", "approve", "--id", str(item["draft_id"]), "--approval-ref", "fake", ok=False)
        self.approve(item)
        self.helper("external-action", "operations.py", "approve", "--id", oid)
        self.assertTrue(self.helper("external-action", "operations.py", "claim", "--id", oid)["claimed"])
        self.helper("external-action", "operations.py", "finish", "--id", oid, "--outcome", "uncertain", "--evidence", "request timed out")
        self.assertFalse(self.helper("external-action", "operations.py", "claim", "--id", oid)["claimed"])

    def test_only_validated_monitor_holds_inherit_automatic_calendar_policy(self):
        self.helper("founder-context", "profile.py", "set-permission",
                    "--capability", "calendar_manage", "--policy", "autonomous")
        direct = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", "work@example.com/primary/new",
            "--operation", "create", "--intent", "unlinked event",
        )
        self.assertTrue(direct["approval_required"])

        item = monitor.observe(self.db, self.new_options_observation(draft={
            "channel": "text", "thread_id": "sms-thread-1", "recipient": "+14155550100",
            "body": "Could you meet Tuesday, Wednesday, or Thursday?",
        }))["suggestion"]
        hold = item["payload"]["calendar_plan"][0]
        prepared = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", hold["target"],
            "--operation", hold["operation"], "--intent", hold["intent"],
            "--suggestion-id", str(item["id"]),
        )
        self.assertFalse(prepared["approval_required"])
        self.helper("founder-context", "profile.py", "set-permission",
                    "--capability", "calendar_manage", "--policy", "forbidden")
        error = self.helper("external-action", "operations.py", "claim",
                            "--id", str(prepared["operation"]["id"]), ok=False)
        self.assertIn("forbidden", error)

    def test_pending_new_options_may_claim_only_its_exact_hold_operations(self):
        item = monitor.observe(self.db, self.new_options_observation())["suggestion"]
        hold = item["payload"]["calendar_plan"][0]
        command = (
            "--scope", "calendar", "--target", hold["target"],
            "--operation", hold["operation"], "--intent", hold["intent"],
            "--suggestion-id", str(item["id"]),
        )
        error = self.helper("external-action", "operations.py", "prepare", *command, ok=False)
        self.assertIn("saved Gmail draft", error)
        self.helper("external-action", "drafts.py", "mark-draft-saved", "--id", str(item["draft_id"]),
                    "--draft-id", "gmail-draft-1", "--account", "owner@example.com")
        wrong_target = list(command)
        wrong_target[3] = "other@example.com/primary/new"
        error = self.helper("external-action", "operations.py", "prepare", *wrong_target, ok=False)
        self.assertIn("differs from", error)
        result = self.helper(
            "external-action", "operations.py", "prepare",
            *command,
        )
        self.assertFalse(result["approval_required"])
        self.assertTrue(self.helper("external-action", "operations.py", "claim",
                                    "--id", str(result["operation"]["id"]))["claimed"])

    def test_automatic_hold_plan_must_use_configured_default_calendar(self):
        proposal = self.new_options_observation()
        proposal["calendar_plan"] = [
            {**step, "target": "other@example.com/primary/new",
             "intent": json.dumps({**json.loads(step["intent"]), "account": "other@example.com"})}
            for step in proposal["calendar_plan"]
        ]
        item = monitor.observe(self.db, proposal)["suggestion"]
        self.helper("external-action", "drafts.py", "mark-draft-saved", "--id", str(item["draft_id"]),
                    "--draft-id", "gmail-draft-1", "--account", "owner@example.com")
        hold = item["payload"]["calendar_plan"][0]
        error = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", hold["target"],
            "--operation", hold["operation"], "--intent", hold["intent"],
            "--suggestion-id", str(item["id"]), ok=False,
        )
        self.assertIn("configured default calendar", error)

    def test_automatic_holds_execute_in_plan_order(self):
        item = monitor.observe(self.db, self.new_options_observation())["suggestion"]
        self.helper("external-action", "drafts.py", "mark-draft-saved", "--id", str(item["draft_id"]),
                    "--draft-id", "gmail-draft-1", "--account", "owner@example.com")
        first, second = item["payload"]["calendar_plan"][:2]

        error = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", second["target"],
            "--operation", second["operation"], "--intent", second["intent"],
            "--suggestion-id", str(item["id"]), ok=False,
        )
        self.assertIn("plan order", error)

        prepared = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", first["target"],
            "--operation", first["operation"], "--intent", first["intent"],
            "--suggestion-id", str(item["id"]),
        )["operation"]
        oid = str(prepared["id"])
        self.helper("external-action", "operations.py", "claim", "--id", oid)
        error = self.helper("external-action", "operations.py", "finish", "--id", oid,
                            "--outcome", "completed", "--evidence", "calendar:verified-hold-1",
                            ok=False)
        self.assertIn("provider event id", error)
        self.helper("external-action", "operations.py", "finish", "--id", oid,
                    "--outcome", "completed", "--external-ref", "hold-event-1",
                    "--evidence", "calendar:verified-hold-1")
        error = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", second["target"],
            "--operation", second["operation"], "--intent", second["intent"],
            "--suggestion-id", str(item["id"]), ok=False,
        )
        self.assertIn("recorded on the contact page", error)
        self.write_contact(
            "alex", email="alex@example.com", phone="+1 415 555 0100",
            holds=("work@example.com/primary/hold-1; work@example.com/primary/hold-2; "
                   "work@example.com/primary/hold-event-1"),
        )
        self.contact = self.contacts()["contacts"][0]
        second_result = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", second["target"],
            "--operation", second["operation"], "--intent", second["intent"],
            "--suggestion-id", str(item["id"]),
        )
        self.assertFalse(second_result["approval_required"])

    def test_automatic_hold_reconciliation_requires_provider_event_id(self):
        item = monitor.observe(self.db, self.new_options_observation(draft={
            "channel": "text", "thread_id": "sms-thread-1", "recipient": "+14155550100",
            "body": "Could you meet Tuesday, Wednesday, or Thursday?",
        }))["suggestion"]
        hold = item["payload"]["calendar_plan"][0]
        prepared = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", hold["target"],
            "--operation", hold["operation"], "--intent", hold["intent"],
            "--suggestion-id", str(item["id"]),
        )["operation"]
        oid = str(prepared["id"])
        self.helper("external-action", "operations.py", "claim", "--id", oid)
        self.helper("external-action", "operations.py", "finish", "--id", oid,
                    "--outcome", "uncertain", "--evidence", "provider timeout")
        error = self.helper("external-action", "operations.py", "reconcile", "--id", oid,
                            "--outcome", "completed", "--evidence", "provider read-back",
                            ok=False)
        self.assertIn("provider event id", error)
        result = self.helper("external-action", "operations.py", "reconcile", "--id", oid,
                             "--outcome", "completed", "--external-ref", "hold-event-1",
                             "--evidence", "provider read-back")
        self.assertEqual(result["operation"]["external_ref"], "hold-event-1")

    def test_text_proposal_needs_no_provider_draft_before_automatic_holds(self):
        draft = {"channel": "text", "thread_id": "sms-thread-1", "recipient": "+14155550100",
                 "body": "Could you meet Tuesday, Wednesday, or Thursday?"}
        item = monitor.observe(self.db, self.new_options_observation(draft=draft))["suggestion"]
        hold = item["payload"]["calendar_plan"][0]
        result = self.helper(
            "external-action", "operations.py", "prepare",
            "--scope", "calendar", "--target", hold["target"],
            "--operation", hold["operation"], "--intent", hold["intent"],
            "--suggestion-id", str(item["id"]),
        )
        self.assertFalse(result["approval_required"])

    def test_obsolete_gmail_draft_cleanup_survives_restart_and_uncertainty(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        did = str(item["draft_id"])
        saved = self.helper("external-action", "drafts.py", "mark-draft-saved", "--id", did,
                            "--draft-id", "gmail-draft-1", "--account", "owner@example.com")["draft"]
        self.approve(item)
        monitor.observe(self.db, self.observation(evidence_refs=["gmail:message-2"],
                        evidence_at="2026-09-17T15:00:00Z", action="modality"))
        self.db.close()
        self.db = monitor.connect(self.path)
        self.assertEqual(monitor.gmail_cleanup(self.db)[0]["id"], item["draft_id"])
        self.helper("external-action", "drafts.py", "claim-send", "--id", did, ok=False)
        snapshot = {key: saved[key] for key in (
            "external_draft_id", "external_draft_account", "thread_id", "recipient", "subject", "body")}
        file = self.home / "provider-readback.json"
        file.write_text(json.dumps({**snapshot, "body": "Founder edited this"}))
        claim = ("reconcile-draft", "--id", did, "--outcome", "deleting", "--file", str(file),
                 "--ref", "gmail:readback:1")
        self.helper("external-action", "drafts.py", *claim, ok=False)
        self.helper("external-action", "drafts.py", *claim, "--approval-ref", "founder:cleanup:1", ok=False)
        file.write_text(json.dumps(snapshot))
        self.assertEqual(self.helper("external-action", "drafts.py", *claim,
                         "--approval-ref", "founder:cleanup:1")["cleanup_status"], "deleting")
        self.helper("external-action", "drafts.py", "reconcile-draft", "--id", did,
                    "--outcome", "blocked", "--ref", "provider timeout")
        self.helper("external-action", "drafts.py", *claim, "--approval-ref", "founder:cleanup:1", ok=False)
        self.assertEqual(monitor.gmail_cleanup(self.db)[0]["cleanup_status"], "deleting")
        self.helper("external-action", "drafts.py", "reconcile-draft", "--id", did,
                    "--outcome", "removed", "--ref", "gmail:verified-absence:2")
        self.assertEqual(monitor.gmail_cleanup(self.db), [])

    def test_changed_facts_cannot_reuse_approval(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            monitor.decide(self.db, item["id"], {"evidence_refs": ["calendar:new-conflict"], "approval_ref": "founder:1", "validation_ref": "calendar:2"})
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "pending")

    def test_calendar_operation_must_match_displayed_plan(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        with self.assertRaisesRegex(ValueError, "verified delivered notice"):
            monitor.decide(self.db, item["id"], {"evidence_refs": item["payload"]["evidence_refs"],
                           "approval_ref": "founder:1", "validation_ref": "fresh:1"})
        self.approve(item)
        for change in ({"target": "other/calendar/event"}, {"operation": "delete"},
                       {"intent": "Wednesday 16:00"}, {"scope": "product"}):
            args = {"scope": "calendar", **item["payload"]["calendar_plan"][0], **change}
            error = self.helper("external-action", "operations.py", "prepare",
                "--scope", args["scope"], "--target", args["target"], "--operation", args["operation"],
                "--intent", args["intent"], "--suggestion-id", str(item["id"]), ok=False)
            self.assertIn("differs from", error)

    def test_notices_require_readback_and_failed_delivery_can_be_retried(self):
        monitor.observe(self.db, self.observation())
        first = monitor.notice(self.db)
        self.assertEqual(first["status"], "staged")
        self.assertNotIn("gmail:message-1", first["body"])
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")
        monitor.receipt(self.db, first["notice_id"], "uncertain", "read-back unavailable")
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")
        monitor.receipt(self.db, first["notice_id"], "failed", "cron rejected delivery; verified absent")
        retry = monitor.notice(self.db)
        self.assertEqual(first["body"], retry["body"])
        monitor.receipt(self.db, retry["notice_id"], "delivered", "plow:verified-message-1", retry["body"])
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")

    def test_receipt_exact_body_reconciliation(self):
        monitor.observe(self.db, self.observation())
        notice = monitor.notice(self.db)
        nid = notice["notice_id"]

        # Delivered requires verified read-back
        with self.assertRaisesRegex(ValueError, "requires verified read-back"):
            monitor.receipt(self.db, nid, "delivered", "plow:msg-1")

        # CLI helper rejects delivered read-back with narration prefix ahead of body
        narration = f"Cleaned up temp files. The notice text is the final output:\n{notice['body']}"
        bad_file = self.home / "bad-readback.txt"
        bad_file.write_text(narration)
        err = self.helper("pipeline-monitor", "monitor.py", "receipt", "--id", str(nid),
                          "--outcome", "delivered", "--ref", "plow:msg-1", "--file", str(bad_file), ok=False)
        self.assertIn("delivered body does not match staged notice body", err)

        # Uncertain or failed does not require read-back
        monitor.receipt(self.db, nid, "uncertain", "plow:msg-1-narration-mismatch")
        self.assertEqual(self.db.execute("SELECT status FROM monitor_notice WHERE id=?", (nid,)).fetchone()[0], "uncertain")

        # Exact match via file succeeds and marks delivered
        good_file = self.home / "good-readback.txt"
        good_file.write_text(notice["body"])
        res = self.helper("pipeline-monitor", "monitor.py", "receipt", "--id", str(nid),
                          "--outcome", "delivered", "--ref", "plow:msg-1-clean", "--file", str(good_file))
        self.assertEqual(res["status"], "delivered")
        self.assertEqual(self.db.execute("SELECT status FROM monitor_notice WHERE id=?", (nid,)).fetchone()[0], "delivered")

        # CLI rejects deleted --body argument
        err_body = self.helper("pipeline-monitor", "monitor.py", "receipt", "--id", str(nid),
                               "--outcome", "delivered", "--ref", "plow:msg-1", "--body", notice["body"], ok=False)
        self.assertIn("unrecognized arguments: --body", err_body)

    def test_stage_notice_normalizes_outer_whitespace(self):
        obs = self.observation(
            evidence_summary="Alex replied in Scheduling at 07:00 PT.  \n",
            draft={"channel": "gmail", "thread_id": "thread-1", "recipient": "alex@example.com",
                   "subject": "Re: Scheduling", "body": "Tuesday at 14:00 PT works.  \n\n"}
        )
        monitor.observe(self.db, obs)
        notice = monitor.notice(self.db)
        self.assertEqual(notice["body"], notice["body"].strip())
        self.assertFalse(notice["body"].endswith("\n"))
        # Delivery adapter strips outer whitespace; reconciliation must succeed
        readback_file = self.home / "readback-whitespace.txt"
        readback_file.write_text(notice["body"])
        res = self.helper("pipeline-monitor", "monitor.py", "receipt", "--id", str(notice["notice_id"]),
                          "--outcome", "delivered", "--ref", "plow:msg-ws", "--file", str(readback_file))
        self.assertEqual(res["status"], "delivered")

    def test_receipt_serializes_with_begin_immediate(self):
        monitor.observe(self.db, self.observation())
        notice = monitor.notice(self.db)
        nid = notice["notice_id"]
        executed_stmts = []
        self.db.set_trace_callback(executed_stmts.append)
        try:
            monitor.receipt(self.db, nid, "delivered", "plow:msg-1", notice["body"])
        finally:
            self.db.set_trace_callback(None)

        self.assertIn("BEGIN IMMEDIATE", [s.strip() for s in executed_stmts])
        normalized = [s.strip() for s in executed_stmts]
        sel_idx = next(i for i, s in enumerate(normalized) if s.startswith("SELECT * FROM monitor_notice WHERE id="))
        self.assertLess(normalized.index("BEGIN IMMEDIATE"), sel_idx)
        # Overlapping reconciliation cannot overwrite delivered
        with self.assertRaisesRegex(ValueError, "notice is not awaiting reconciliation"):
            monitor.receipt(self.db, nid, "uncertain", "plow:msg-overwrite")

    def test_a_notice_carries_the_most_urgent_few_and_holds_the_rest_without_external_writes(self):
        accepted = self.observation(draft=None)
        modality = self.observation(conversation_ref="gmail:other-thread", evidence_refs=["gmail:phone-offer"],
            action="modality", summary="Alex offered a phone call; you prefer video.",
            next_step="Reply with two verified video options. Approve?",
            draft={"channel": "gmail", "thread_id": "other-thread", "recipient": "alex@example.com",
                   "body": "Could we meet by video Tuesday at 14:00 or Wednesday at 10:00 PT?"})
        clarification = self.observation(conversation_ref="gmail:third-thread", evidence_refs=["gmail:ambiguous"],
            action="clarification", draft=None, summary="Alex named a day with no time.",
            next_step="Ask which hour they meant. Approve?")
        for item in (clarification, modality, accepted):   # least urgent observed first
            monitor.observe(self.db, item)
        result = monitor.notice(self.db)
        self.assertIn("two sibling holds", result["body"])
        self.assertIn("prefer video", result["body"])
        self.assertLess(result["body"].index("two sibling holds"), result["body"].index("prefer video"))
        self.assertNotIn("named a day with no time", result["body"])
        monitor.receipt(self.db, result["notice_id"], "delivered", "plow:verified-message-1", result["body"])
        self.assertIn("named a day with no time", monitor.notice(self.db)["body"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM draft WHERE status='draft'").fetchone()[0], 1)
        self.assertFalse(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='external_operation'").fetchone())

    def test_profile_and_additive_schema_compatibility(self):
        monitor.observe(self.db, self.observation())
        for script in ("drafts.py", "operations.py"):
            self.helper("external-action", script, "list")
        profile = self.helper("founder-context", "profile.py", "show")
        self.assertEqual(profile["pipeline_monitor"]["config"]["wiki_verified_ref"], self.config["wiki_verified_ref"])
        self.assertFalse(profile["pipeline_monitor"]["enabled"])
        self.assertEqual(profile["preferences"], {})
        updated = self.helper("founder-context", "profile.py", "set-preference",
                              "--key", "save_gmail_drafts", "--value", "true")
        self.assertTrue(updated["preferences"]["save_gmail_drafts"])
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
