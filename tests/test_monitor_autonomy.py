"""Real shared ledgers and CLI commands; remote reads/uploads are synthetic snapshots."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import unittest

import test_monitor as baseline
from test_monitor import monitor, ROOT


class AutonomyTests(unittest.TestCase):
    observation = baseline.MonitorTests.observation
    helper = baseline.MonitorTests.helper
    approve = baseline.MonitorTests.approve

    def setUp(self):
        baseline.MonitorTests.setUp(self)
        self.config["mapping"].update(next_step="Next step", holds="Holds")
        self.config["autonomy"] = {
            "csv": {"enabled": True, "approval_ref": "founder:csv", "no_edit_window_ref": "founder:closed-sheet"},
            "holds": {"enabled": True, "approval_ref": "founder:holds", "account": "owner@example.com", "calendar": "work"},
        }
        self.csv.write_text("Name,Email,Phone,Stage,Type,Notes,Next step,Holds\nAlex,alex@example.com,+1 415 555 0100,Warm,customer,Keep me,,\n")
        monitor.configure(self.db, self.config, self.scheduler)
        self.contact = monitor.contacts(self.db, self.csv)["contacts"][0]
        start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(second=0, microsecond=0)
        self.hold = {"account": "owner@example.com", "calendar": "work", "start": start.isoformat(),
                     "end": (start + timedelta(minutes=30)).isoformat(), "timezone": "UTC",
                     "title": "HOLD — Alex", "attendees": [], "send_updates": "none", "transparency": "opaque"}
        self.item = monitor.observe(self.db, self.observation(calendar_plan=[], hold_plan=[self.hold],
                                   next_step="Review the draft; send it when ready."))["suggestion"]

    def validation(self, **changes):
        return {"config_digest": monitor.show(self.db)["config_digest"], "checked_at": monitor.stamp(),
                "evidence_refs": self.item["payload"]["evidence_refs"], "source_ref": "fresh:thread",
                "calendar_ref": "fresh:all-calendars", "conflict_free": True,
                "csv_ref": "fresh:csv", "manual_request_ref": "founder:check-now", **changes}

    def payload(self, value, name="validation.json"):
        file = self.home / name
        file.write_text(json.dumps(value))
        return str(file)

    def prepare_hold(self, validation=None, hold=None, ok=True):
        h = hold or self.hold
        return self.helper("external-action", "operations.py", "prepare", "--scope", "calendar",
                           "--target", f"{h['account']}/{h['calendar']}/new", "--operation", "create_private_hold",
                           "--intent", monitor.canonical(h), "--suggestion-id", str(self.item["id"]),
                           "--validation-file", self.payload(validation or self.validation()), ok=ok)

    def claim_hold(self, oid, validation=None, ok=True):
        return self.helper("external-action", "operations.py", "claim", "--id", str(oid),
                           "--validation-file", self.payload(validation or self.validation()), ok=ok)

    def csv_command(self, command, ok=True, **changes):
        args = [command, "--id", str(self.item["id"]), "--csv", str(self.csv)]
        if command == "reconcile-csv":
            args += ["--ref", "remote:read-back"]
        else:
            args += ["--file", self.payload(self.validation(**changes))]
        return self.helper("pipeline-monitor", "monitor.py", *args, ok=ok)

    def complete_hold(self):
        op = self.prepare_hold()["operation"]
        self.assertTrue(self.claim_hold(op["id"])["claimed"])
        self.helper("external-action", "operations.py", "finish", "--id", str(op["id"]),
                    "--outcome", "completed", "--external-ref", "event-1", "--evidence", "provider:fetch:event-1")
        return op

    def test_private_hold_does_not_approve_send_or_suggestion(self):
        operation = self.complete_hold()
        authorization = json.loads(self.db.execute("SELECT monitor_authorization FROM external_operation WHERE id=?", (operation["id"],)).fetchone()[0])
        self.assertEqual(authorization["grant"]["approval_ref"], "founder:holds")
        self.assertEqual(monitor.suggestion(self.db, self.item["id"])["status"], "pending")
        self.helper("external-action", "drafts.py", "approve", "--id", str(self.item["draft_id"]),
                    "--approval-ref", "founder:holds", ok=False)
        self.helper("external-action", "drafts.py", "claim-send", "--id", str(self.item["draft_id"]), ok=False)
        self.approve(monitor.suggestion(self.db, self.item["id"]))
        self.helper("external-action", "drafts.py", "approve", "--id", str(self.item["draft_id"]),
                    "--approval-ref", "founder:generic-approve", ok=False)
        self.helper("external-action", "drafts.py", "approve", "--id", str(self.item["draft_id"]),
                    "--approval-ref", "founder:send", "--send-request-ref", "founder:send")
        self.assertTrue(self.helper("external-action", "drafts.py", "claim-send", "--id", str(self.item["draft_id"]))["claimed"])
        self.assertIn("Send outcome unverified", monitor.render_suggestion(monitor.suggestion(self.db, self.item["id"])))
        with self.db:
            self.db.execute("UPDATE draft SET status='sent' WHERE id=?", (self.item["draft_id"],))
        rendered = monitor.render_suggestion(monitor.suggestion(self.db, self.item["id"]))
        self.assertIn("Message sent and verified", rendered)
        self.assertNotIn("Not sent", rendered)

    def test_hold_parameters_and_revocation_are_enforced(self):
        for changes in ({"attendees": ["alex@example.com"]}, {"send_updates": "all"},
                        {"transparency": "transparent"}, {"calendar": "other"}, {"title": "HOLD — Someone else"}):
            with self.subTest(changes=changes):
                self.prepare_hold(hold={**self.hold, **changes}, ok=False)
        op = self.prepare_hold()["operation"]
        old = self.validation()
        self.config["autonomy"]["holds"]["enabled"] = False
        monitor.configure(self.db, self.config, self.scheduler)
        self.claim_hold(op["id"], validation=old, ok=False)
        self.claim_hold(op["id"], ok=False)

    def test_pause_stale_evidence_and_forbidden_calendar_stop_claim(self):
        op = self.prepare_hold()["operation"]
        self.claim_hold(op["id"], validation=self.validation(manual_request_ref=None), ok=False)
        self.claim_hold(op["id"], validation=self.validation(evidence_refs=["new-message"]), ok=False)
        self.claim_hold(op["id"], validation=self.validation(conflict_free=False), ok=False)
        old = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        self.claim_hold(op["id"], validation=self.validation(checked_at=old), ok=False)
        self.helper("founder-context", "profile.py", "set-permission", "--capability", "calendar_manage", "--policy", "forbidden")
        self.claim_hold(op["id"], ok=False)

    def test_hold_reused_after_restart_new_evidence_and_concurrent_claim(self):
        op = self.complete_hold()
        self.db.close()
        self.db = monitor.connect(self.path)
        self.item = monitor.observe(self.db, self.observation(calendar_plan=[], hold_plan=[self.hold],
            evidence_refs=["gmail:new"], evidence_at="2026-09-18T15:00:00Z"))["suggestion"]
        self.assertEqual(self.prepare_hold()["operation"]["id"], op["id"])
        self.assertFalse(self.claim_hold(op["id"])["claimed"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM external_operation").fetchone()[0], 1)

    def test_uncertain_hold_never_duplicates_and_requires_event_reference(self):
        op = self.prepare_hold()["operation"]
        self.claim_hold(op["id"])
        self.assertFalse(self.claim_hold(op["id"])["claimed"])
        self.helper("external-action", "operations.py", "finish", "--id", str(op["id"]),
                    "--outcome", "completed", "--evidence", "receipt only", ok=False)
        self.helper("external-action", "operations.py", "finish", "--id", str(op["id"]),
                    "--outcome", "uncertain", "--evidence", "timeout")
        self.assertEqual(self.prepare_hold()["operation"]["id"], op["id"])
        self.assertTrue(self.claim_hold(op["id"])["reconciliation_required"])

    def test_csv_preserves_other_cells_and_retries_only_upload(self):
        self.complete_hold()
        before = self.csv.read_bytes()
        prepared = self.csv_command("prepare-csv")
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertIn("Keep me", prepared["content"])
        self.assertIn("Review the draft; send it when ready.", prepared["content"])
        claim = self.csv_command("claim-csv")
        self.assertTrue(claim["claimed"])
        self.assertFalse(self.csv_command("claim-csv")["claimed"])
        # Simulate no upload having reached the remote file.
        self.assertEqual(self.csv_command("reconcile-csv")["status"], "pending")
        self.csv_command("prepare-csv")
        claim = self.csv_command("claim-csv")
        self.csv.write_text(claim["write"]["content"])
        self.assertEqual(self.csv_command("reconcile-csv")["status"], "completed")
        self.assertFalse(self.csv_command("prepare-csv")["claimed"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM external_operation").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT status FROM draft").fetchone()[0], "draft")

    def test_csv_conflict_removed_contact_and_revoked_grant(self):
        self.csv_command("prepare-csv")
        self.csv.write_text(self.csv.read_text().replace("Keep me", "Founder edit"))
        self.assertFalse(self.csv_command("claim-csv")["claimed"])
        self.assertIn("Founder edit", self.csv_command("prepare-csv")["content"])
        self.config["autonomy"]["csv"]["enabled"] = False
        monitor.configure(self.db, self.config, self.scheduler)
        self.csv_command("claim-csv", ok=False)
        self.config["autonomy"]["csv"]["enabled"] = True
        monitor.configure(self.db, self.config, self.scheduler)
        self.csv.write_text(self.csv.read_text().splitlines()[0] + "\n")
        self.csv_command("prepare-csv", ok=False)
        self.assertEqual(len(self.csv.read_text().splitlines()), 1)

    def test_uncertain_csv_blocks_other_uploads_and_preserves_edits(self):
        self.csv_command("prepare-csv")
        self.csv_command("claim-csv")
        self.csv.write_text(self.csv.read_text().replace("Keep me", "Concurrent edit"))
        self.assertEqual(self.csv_command("reconcile-csv")["status"], "uncertain")
        self.item = monitor.observe(self.db, self.observation(conversation_ref="other", evidence_refs=["new-thread"]))["suggestion"]
        self.csv_command("prepare-csv", ok=False)
        self.assertIn("Concurrent edit", self.csv.read_text())

    def test_notices_follow_results_not_repeated_checks(self):
        notice = monitor.notice(self.db)
        monitor.receipt(self.db, notice["notice_id"], "delivered", "private:read-back")
        self.complete_hold()
        self.csv_command("prepare-csv")
        self.csv.write_text(self.csv_command("claim-csv")["write"]["content"])
        self.csv_command("reconcile-csv")
        changed = monitor.notice(self.db)
        self.assertIn("CSV: completed", changed["body"])
        self.assertIn("Private hold:", changed["body"])
        self.assertIn("Not sent", changed["body"])
        monitor.receipt(self.db, changed["notice_id"], "delivered", "private:read-back-2")
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")

    def test_sync_refreshes_paused_job_and_never_creates_one(self):
        monitor.refresh_job(self.db, self.scheduler)
        self.assertEqual(self.scheduler.jobs, [])
        monitor.sync_job(self.db, self.scheduler, True)
        monitor.sync_job(self.db, self.scheduler, False)
        self.scheduler.jobs[0]["prompt"] = "retired policy"
        job_id = self.scheduler.jobs[0]["job_id"]
        monitor.refresh_job(self.db, self.scheduler)
        self.assertEqual(self.scheduler.jobs[0]["prompt"], monitor.PROMPT)
        self.assertEqual(self.scheduler.jobs[0]["job_id"], job_id)
        self.assertFalse(self.scheduler.jobs[0]["enabled"])
        self.assertFalse(monitor.show(self.db)["enabled"])

    def test_two_processes_cannot_claim_one_hold(self):
        op = self.prepare_hold()["operation"]
        validation = self.payload(self.validation())
        command = [sys.executable, str(ROOT / "skills/external-action/scripts/operations.py"),
                   "--db", str(self.path), "claim", "--id", str(op["id"]), "--validation-file", validation]
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: subprocess.run(command, capture_output=True, text=True), range(2)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(json.loads(r.stdout)["claimed"] for r in results), 1)

    def test_new_grants_require_consent_and_old_config_stays_disabled(self):
        for grant, field in (("csv", "approval_ref"), ("csv", "no_edit_window_ref"), ("holds", "approval_ref")):
            config = json.loads(json.dumps(self.config))
            config["autonomy"][grant].pop(field)
            with self.assertRaises(ValueError):
                monitor.configure(self.db, config, self.scheduler)
        legacy = {k: v for k, v in self.config.items() if k != "autonomy"}
        with self.db:
            self.db.execute("UPDATE monitor_config SET config=?", (json.dumps(legacy),))
        self.db.close()
        self.db = monitor.connect(self.path)
        self.assertFalse(monitor.show(self.db)["config"]["autonomy"]["csv"]["enabled"])
        self.prepare_hold(ok=False)
        self.csv_command("prepare-csv", ok=False)

    def test_deferred_csv_notification_and_recovery_are_deduplicated(self):
        for _ in range(2):
            self.helper("pipeline-monitor", "monitor.py", "defer-csv", "--id", str(self.item["id"]), "--reason", "Sheet is open")
            notice = monitor.notice(self.db)
            if _ == 0:
                self.assertIn("Sheet is open", notice["body"])
                monitor.receipt(self.db, notice["notice_id"], "delivered", "private:blocked")
            else:
                self.assertEqual(notice["body"], "[SILENT]")
        self.csv_command("prepare-csv")
        self.csv.write_text(self.csv_command("claim-csv")["write"]["content"])
        self.csv_command("reconcile-csv")
        self.assertIn("CSV: completed", monitor.notice(self.db)["body"])

    def test_csv_uncertainty_requires_decision_to_preserve_divergent_content(self):
        self.csv_command("prepare-csv")
        self.csv_command("claim-csv")
        self.csv.write_text(self.csv.read_text().replace("Keep me", "Keep founder edits"))
        self.csv_command("reconcile-csv")
        args = ["reconcile-csv", "--id", str(self.item["id"]), "--csv", str(self.csv),
                "--ref", "readback:changed", "--accept-current"]
        self.helper("pipeline-monitor", "monitor.py", *args, ok=False)
        result = self.helper("pipeline-monitor", "monitor.py", *args, "--approval-ref", "founder:keep-current")
        self.assertEqual(result["status"], "pending")
        self.assertIn("founder:keep-current", result["evidence_ref"])
        self.assertIn("Keep founder edits", self.csv_command("prepare-csv")["content"])

    def test_older_thread_cannot_overwrite_newer_next_step(self):
        monitor.observe(self.db, self.observation(conversation_ref="newer-thread", evidence_refs=["gmail:new"],
                        evidence_at="2026-09-18T15:00:00Z", next_step="Newer advice"))
        self.assertIn("newer contact suggestion", self.csv_command("prepare-csv", ok=False))

    def test_old_deliveries_migrate_without_replaying_history(self):
        notice = monitor.notice(self.db)
        monitor.receipt(self.db, notice["notice_id"], "delivered", "private:old-delivery")
        with self.db:
            self.db.execute("ALTER TABLE monitor_notice DROP COLUMN sections")
        self.db.close()
        self.db = monitor.connect(self.path)
        self.assertEqual(monitor.notice(self.db)["body"], "[SILENT]")
        self.complete_hold()
        self.assertIn("Private hold:", monitor.notice(self.db)["body"])

    def test_hold_completed_later_updates_already_written_csv(self):
        self.csv_command("prepare-csv")
        self.csv.write_text(self.csv_command("claim-csv")["write"]["content"])
        self.csv_command("reconcile-csv")
        self.complete_hold()
        updated = self.csv_command("prepare-csv")
        self.assertEqual(updated["status"], "prepared")
        self.assertIn(self.hold["start"], updated["content"])
        self.csv.write_text(self.csv_command("claim-csv")["write"]["content"])
        self.assertEqual(self.csv_command("reconcile-csv")["status"], "completed")
        self.assertFalse(self.csv_command("prepare-csv")["claimed"])
