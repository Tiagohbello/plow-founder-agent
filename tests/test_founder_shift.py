import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "founder-shift" / "shift.py"


class FounderShiftTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "shift.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_shift(self, *arguments, check=True):
        environment = os.environ.copy()
        environment["FOUNDER_SHIFT_DB"] = str(self.db)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(result.stderr)
        return json.loads(result.stdout) if result.returncode == 0 and arguments[0] != "summary" else result

    def test_empty_shift_does_not_invent_work(self):
        started = self.run_shift("begin", "--minutes", "240")
        run_id = started["run"]["id"]
        summary = self.run_shift("summary", "--run-id", run_id)
        self.assertIn("No work was recorded", summary.stdout)

    def test_action_key_is_idempotent_and_summary_distinguishes_states(self):
        started = self.run_shift("begin", "--minutes", "60")
        run_id = started["run"]["id"]
        first = self.run_shift(
            "record-action", "--run-id", run_id, "--action-key", "reply-1",
            "--state", "prepared", "--summary", "Prepared customer reply",
        )
        second = self.run_shift(
            "record-action", "--run-id", run_id, "--action-key", "reply-1",
            "--state", "handled", "--summary", "Must not duplicate",
        )
        self.assertTrue(first["recorded"])
        self.assertTrue(second["duplicate"])
        self.run_shift(
            "record-action", "--run-id", run_id, "--action-key", "approval-1",
            "--state", "needs_founder", "--summary", "Approve reply",
        )
        summary = self.run_shift("summary", "--run-id", run_id)
        self.assertIn("Prepared customer reply", summary.stdout)
        self.assertIn("1. Approve reply", summary.stdout)

    def test_cycles_do_not_overlap_or_repeat(self):
        started = self.run_shift("--now", "2026-09-06T10:00:00Z", "begin", "--minutes", "60")
        run_id = started["run"]["id"]
        first = self.run_shift("--now", "2026-09-06T10:00:01Z", "claim-cycle",
                               "--run-id", run_id, "--cycle-key", "initial")
        overlap = self.run_shift("--now", "2026-09-06T10:00:02Z", "claim-cycle",
                                 "--run-id", run_id, "--cycle-key", "scheduled-1")
        self.assertTrue(first["claimed"])
        self.assertEqual(overlap["reason"], "cycle_already_running")
        self.run_shift("--now", "2026-09-06T10:01:00Z", "finish-cycle", "--run-id", run_id,
                       "--cycle-key", "initial", "--status", "completed")
        duplicate = self.run_shift("--now", "2026-09-06T10:02:00Z", "claim-cycle",
                                   "--run-id", run_id, "--cycle-key", "initial")
        self.assertEqual(duplicate["reason"], "duplicate_cycle")

    def test_expiry_and_cancel_refuse_new_work(self):
        started = self.run_shift("--now", "2026-09-06T10:00:00Z", "begin", "--minutes", "20")
        run_id = started["run"]["id"]
        expired = self.run_shift("--now", "2026-09-06T10:21:00Z", "claim-cycle",
                                 "--run-id", run_id, "--cycle-key", "late")
        self.assertFalse(expired["claimed"])
        self.assertEqual(expired["reason"], "expired")
        second = self.run_shift("--now", "2026-09-06T11:00:00Z", "begin", "--minutes", "20")
        second_id = second["run"]["id"]
        self.run_shift("--now", "2026-09-06T11:01:00Z", "cancel", "--run-id", second_id)
        cancelled = self.run_shift("--now", "2026-09-06T11:02:00Z", "claim-cycle",
                                   "--run-id", second_id, "--cycle-key", "after-cancel")
        self.assertEqual(cancelled["reason"], "cancelled")

    def test_job_ids_survive_reopen(self):
        started = self.run_shift("begin", "--minutes", "30")
        run_id = started["run"]["id"]
        self.run_shift("set-jobs", "--run-id", run_id, "--cycle-job-id", "cron-cycle",
                       "--finalizer-job-id", "cron-final")
        status = self.run_shift("status", "--run-id", run_id)
        self.assertEqual(status["run"]["cycle_job_id"], "cron-cycle")

    def test_external_effect_is_claimed_once_and_requires_verification(self):
        started = self.run_shift("begin", "--minutes", "30")
        run_id = started["run"]["id"]
        first = self.run_shift("claim-effect", "--run-id", run_id, "--action-key", "pr:issue-31",
                               "--kind", "draft_pr")
        repeat = self.run_shift("claim-effect", "--run-id", run_id, "--action-key", "pr:issue-31",
                                "--kind", "draft_pr")
        self.assertTrue(first["claimed"]); self.assertTrue(repeat["verification_required"])
        finished = self.run_shift("finish-effect", "--run-id", run_id, "--action-key", "pr:issue-31",
                                  "--status", "completed", "--evidence", "https://github.test/pr/31")
        self.assertTrue(finished["finished"])


if __name__ == "__main__":
    unittest.main()
