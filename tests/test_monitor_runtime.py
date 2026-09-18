"""Opt-in contract test inside the pinned Hermes image, without credentials/network.

The real native job store, scheduling claim, runner, output and result persistence
are exercised. LLM reasoning and remote Plow delivery are test doubles: this test
must never contact a founder or an investor.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("FOUNDER_TEST_HERMES") == "1", "run in pinned Hermes image explicitly")
class NativeRuntimeTests(unittest.TestCase):
    def test_native_cron_lifecycle_silence_delivery_and_restart(self):
        sys.path.insert(0, "/opt/hermes")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "HERMES_HOME": temporary, "PLOW_HOME_CHANNEL": "cht_test_owner"
        }):
            # The normal plow-init boot enables this shipped platform plugin.
            # Reproduce only that non-secret config in our isolated home.
            (Path(temporary) / "config.yaml").write_text("plugins:\n  enabled:\n    - plow-chat-platform\n")
            from cron import jobs, scheduler, scheduler_preflight
            root = Path(__file__).resolve().parents[1]
            shutil.copytree(root / "skills", Path(temporary) / "skills", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
            spec = importlib.util.spec_from_file_location("monitor_native", root / "skills/pipeline-monitor/scripts/monitor.py")
            monitor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(monitor)
            path = Path(temporary) / "founder-agent/founder-agent.db"
            db = monitor.connect(path)
            self.addCleanup(db.close)
            native = monitor.Hermes()
            config = {
                "csv_path": "~/Plow/example.csv", "csv_verified_ref": "fixture:csv",
                "mapping": {"name": "Name", "email": "Email"},
                "timezone": "America/Los_Angeles", "interval_minutes": 30,
                "sources": {"gmail": {"status": "available", "evidence": "fixture:mail"}},
            }
            monitor.configure(db, config, native)
            state = monitor.sync_job(db, native, True)
            job_id = state["job_id"]
            job = jobs.get_job(job_id)
            self.assertEqual(job["schedule"]["minutes"], 30)
            self.assertEqual(job["deliver"], "plow_chat:cht_test_owner")
            self.assertEqual(job["skills"], ["pipeline-monitor"])
            self.assertTrue(job["attach_to_session"])
            self.assertIsNone(scheduler_preflight._preflight_check_skills(job))
            target = scheduler._resolve_delivery_targets(job)
            self.assertEqual(target[0]["platform"], "plow_chat")
            self.assertEqual(target[0]["chat_id"], "cht_test_owner")
            monitor.configure(db, {**config, "interval_minutes": 45}, native)
            self.assertEqual(len([j for j in jobs.list_jobs(True) if j["name"] == monitor.JOB_NAME]), 1)
            self.assertEqual(jobs.get_job(job_id)["schedule"]["minutes"], 45)
            self.assertTrue(jobs.get_job(job_id)["attach_to_session"])
            self.assertIn("private holds", jobs.get_job(job_id)["prompt"])

            def fire(response, error=None):
                claimed = jobs.claim_job_for_fire(job_id, return_job=True)
                self.assertIsInstance(claimed, dict)
                # A parallel scheduler/manual run cannot claim this occurrence.
                self.assertFalse(jobs.claim_job_for_fire(job_id, return_job=True))
                # The pinned runtime can dispatch a detached process. Keep the
                # real runner/store in this process so LLM and delivery mocks
                # cannot be bypassed by that subprocess boundary.
                with patch.object(scheduler, "_launch_external_cron_worker", return_value=False), \
                     patch.object(scheduler, "run_job", return_value=(True, response, response, None)), \
                     patch.object(scheduler, "_deliver_result", return_value=error) as delivery:
                    self.assertTrue(scheduler.run_one_job(claimed))
                    if response == "[SILENT]":
                        delivery.assert_not_called()
                    else:
                        self.assertEqual(delivery.call_count, 1)
                        self.assertEqual(delivery.call_args.args[0]["deliver"], "plow_chat:cht_test_owner")
                        self.assertEqual(delivery.call_args.args[1], response)
                return jobs.get_job(job_id)

            successful = fire("Alex accepted Tuesday. Create invite and release sibling holds? Approve?")
            self.assertEqual(successful["last_status"], "ok")
            self.assertIsNone(successful["last_delivery_error"])
            self.assertEqual(fire("[SILENT]")["last_status"], "ok")
            self.assertEqual(fire("New suggestion", "simulated Plow unavailable")["last_delivery_error"], "simulated Plow unavailable")
            monitor.sync_job(db, native, False)
            self.assertFalse(jobs.get_job(job_id)["enabled"])
            monitor.refresh_job(db, native)
            self.assertFalse(jobs.get_job(job_id)["enabled"])
            self.assertEqual(monitor.show(db)["job_id"], job_id)
            self.assertIn("private holds", jobs.get_job(job_id)["prompt"])
            db.close()
            reopened = monitor.connect(path)
            try:
                self.assertFalse(monitor.show(reopened)["enabled"])
                self.assertTrue(monitor.gate(reopened, manual=True)["run"])
                self.assertFalse(jobs.get_job(job_id)["enabled"])
                monitor.sync_job(reopened, native, True)
                self.assertEqual(monitor.show(reopened)["job_id"], job_id)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
