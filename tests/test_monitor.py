from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
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
            "csv_path": "~/Plow/pipeline.csv", "csv_verified_ref": "read:file:1",
            "mapping": {"name": "Name", "email": "Email", "phone": "Phone", "status": "Stage", "type": "Type"},
            "timezone": "America/Los_Angeles", "interval_minutes": 30,
            "sources": {"gmail": {"status": "available", "evidence": "read:mail:1"},
                        "messages": {"status": "blocked", "evidence": "permission denied"}},
        }
        monitor.configure(self.db, self.config, self.scheduler)
        self.csv = self.home / "snapshot.csv"
        self.csv.write_text("Name,Email,Phone,Stage,Type,Notes\nAlex,alex@example.com,+1 415 555 0100,Times sent,customer,Keep me\n")
        self.contact = monitor.contacts(self.db, self.csv)["contacts"][0]

    def observation(self, **changes):
        value = {
            "contact_key": self.contact["contact_key"], "conversation_ref": "gmail:thread-1",
            "evidence_refs": ["gmail:message-1"], "evidence_at": "2026-09-17T14:00:00Z",
            "evidence_summary": "Alex replied in Scheduling at 07:00 PT.",
            "action": "accepted", "summary": "Alex accepted Tuesday at 14:00 PT.",
            "next_step": "Create a video invite and release the two sibling holds. Approve?",
            "draft": {"channel": "gmail", "thread_id": "thread-1", "recipient": "alex@example.com",
                      "subject": "Re: Scheduling", "body": "Tuesday at 14:00 PT works."},
        }
        value.update(changes)
        return value

    def helper(self, skill, filename, *args, ok=True):
        result = subprocess.run([sys.executable, str(ROOT / "skills" / skill / "scripts" / filename),
                                 "--db", str(self.path), *args], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr + result.stdout)
        return json.loads(result.stdout) if ok else result.stderr

    def approve(self, item):
        return monitor.decide(self.db, item["id"], {"evidence_refs": item["payload"]["evidence_refs"],
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
                       {"start": "18:00", "end": "09:00"}, {"csv_verified_ref": ""},
                       {"sources": {"gmail": {"status": "blocked", "evidence": "403"}}},
                       {"csv_path": "relative.csv"}):
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                monitor.configure(self.db, {**self.config, **change}, self.scheduler)
        result = monitor.configure(self.db, {**self.config, "deliver": "plow_chat:group",
                                   "owner_chat_verified_ref": "untrusted assertion"}, self.scheduler)
        self.assertEqual(result["config"]["deliver"], "plow_chat:cht_test_owner")
        self.assertNotIn("owner_chat_verified_ref", result["config"])
        with patch.dict(os.environ, {"PLOW_HOME_CHANNEL": ""}):
            with self.assertRaisesRegex(ValueError, "PLOW_HOME_CHANNEL"):
                monitor.configure(self.db, self.config, self.scheduler)

    def test_contacts_phones_duplicates_and_no_csv_mutation(self):
        original = self.csv.read_bytes()
        self.assertEqual(self.contact["handles"], ["+14155550100", "alex@example.com"])
        monitor.observe(self.db, self.observation())
        self.assertEqual(self.csv.read_bytes(), original)
        self.csv.write_text(original.decode() + "Another,alex@example.com,,Interested,investor,\nLocal,,4155550101,New,customer,\n")
        found = monitor.contacts(self.db, self.csv)
        self.assertEqual(found["contacts"], [])
        self.assertEqual(len(found["ambiguous"]), 3)
        self.assertEqual(monitor.suggestion(self.db, 1)["status"], "superseded")

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
        operation = self.helper("external-action", "operations.py", "prepare", "--scope", "calendar", "--target", "work/calendar/new",
                                "--operation", "create", "--intent", "Tuesday 14:00", "--suggestion-id", str(item["id"]))["operation"]
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

    def test_autonomous_calendar_policy_never_auto_approves_monitor_work(self):
        self.helper("founder-context", "profile.py", "set-permission", "--capability", "calendar_manage", "--policy", "autonomous")
        item = monitor.observe(self.db, self.observation())["suggestion"]
        result = self.helper("external-action", "operations.py", "prepare", "--scope", "calendar", "--target", "work/calendar/new",
                             "--operation", "create", "--intent", "Tuesday 14:00", "--suggestion-id", str(item["id"]))
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

    def test_changed_facts_cannot_reuse_approval(self):
        item = monitor.observe(self.db, self.observation())["suggestion"]
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            monitor.decide(self.db, item["id"], {"evidence_refs": ["calendar:new-conflict"], "approval_ref": "founder:1", "validation_ref": "calendar:2"})
        self.assertEqual(monitor.suggestion(self.db, item["id"])["status"], "pending")

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
        monitor.receipt(self.db, retry["notice_id"], "delivered", "plow:verified-message-1")
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")

    def test_sam_scenarios_produce_consolidated_suggestions_without_external_writes(self):
        accepted = self.observation(draft=None)
        modality = self.observation(conversation_ref="gmail:other-thread", evidence_refs=["gmail:phone-offer"],
            action="modality", summary="Alex offered a phone call; you prefer video.",
            next_step="Reply with two verified video options. Approve?",
            draft={"channel": "gmail", "thread_id": "other-thread", "recipient": "alex@example.com",
                   "body": "Could we meet by video Tuesday at 14:00 or Wednesday at 10:00 PT?"})
        monitor.observe(self.db, accepted)
        monitor.observe(self.db, modality)
        result = monitor.notice(self.db)
        self.assertIn("two sibling holds", result["body"])
        self.assertIn("prefer video", result["body"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM draft WHERE status='draft'").fetchone()[0], 1)
        self.assertFalse(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='external_operation'").fetchone())

    def test_profile_and_additive_schema_compatibility(self):
        monitor.observe(self.db, self.observation())
        for script in ("drafts.py", "operations.py"):
            self.helper("external-action", script, "list")
        profile = self.helper("founder-context", "profile.py", "show")
        self.assertEqual(profile["pipeline_monitor"]["config"]["csv_path"], self.config["csv_path"])
        self.assertFalse(profile["pipeline_monitor"]["enabled"])
        self.assertEqual(profile["preferences"], {})
        updated = self.helper("founder-context", "profile.py", "set-preference",
                              "--key", "save_gmail_drafts", "--value", "true")
        self.assertTrue(updated["preferences"]["save_gmail_drafts"])
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
