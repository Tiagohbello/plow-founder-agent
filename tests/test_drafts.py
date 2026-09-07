import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "communication" / "drafts.py"


class DraftLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "drafts.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_drafts(self, *arguments, check=True):
        environment = os.environ.copy()
        environment["FOUNDER_DRAFTS_DB"] = str(self.db)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(result.stderr)
        return json.loads(result.stdout) if result.returncode == 0 else result

    def test_draft_requires_approval_and_send_is_claimed_once(self):
        created = self.run_drafts(
            "prepare", "--channel", "gmail", "--thread-id", "thread-1",
            "--recipient", "acme@example.com", "--subject", "SSO", "--body", "We know about it.",
        )
        draft_id = str(created["draft"]["id"])
        rejected = self.run_drafts("claim-send", "--id", draft_id, check=False)
        self.assertNotEqual(rejected.returncode, 0)

        self.run_drafts("approve", "--id", draft_id)
        claimed = self.run_drafts("claim-send", "--id", draft_id)
        self.assertTrue(claimed["claimed"])
        again = self.run_drafts("claim-send", "--id", draft_id)
        self.assertTrue(again["verification_required"])

        sent = self.run_drafts("mark-sent", "--id", draft_id, "--message-id", "message-1")
        self.assertEqual(sent["draft"]["status"], "sent")
        repeat = self.run_drafts("mark-sent", "--id", draft_id, "--message-id", "message-1")
        self.assertTrue(repeat["already_sent"])

    def test_whatsapp_history_is_readable_but_new_work_is_blocked(self):
        self.run_drafts("list")
        connection=sqlite3.connect(self.db)
        connection.execute(
            """INSERT INTO draft(channel,thread_id,recipient,subject,body,status,idempotency_key,
                                  created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            ("whatsapp","chat-1","historical-recipient","","Historical","draft","legacy-key",
             "2026-01-01T00:00:00Z","2026-01-01T00:00:00Z"),
        )
        connection.commit(); connection.close()
        history=self.run_drafts("list","--channel","whatsapp")
        self.assertEqual(history["count"],1)
        blocked=self.run_drafts("claim-send","--id",str(history["drafts"][0]["id"]),check=False)
        self.assertIn("retired",blocked.stderr)
        new=self.run_drafts("prepare","--channel","whatsapp","--thread-id","chat-2",
                            "--recipient","someone","--body","New",check=False)
        self.assertIn("new drafts",new.stderr)

    def test_material_revision_invalidates_approval(self):
        created = self.run_drafts("prepare", "--channel", "gmail", "--thread-id", "t-1",
                                  "--recipient", "acme@example.com", "--body", "Original")
        draft_id = str(created["draft"]["id"])
        self.run_drafts("approve", "--id", draft_id)
        revised = self.run_drafts("revise", "--id", draft_id, "--body", "Changed")
        self.assertTrue(revised["approval_required"])
        self.assertEqual(revised["old_draft"]["status"], "cancelled")
        self.assertEqual(revised["draft"]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
