import importlib.util
import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "founder-queue" / "queue.py"


class FounderQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "queue.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_queue(self, *arguments, check=True):
        environment = os.environ.copy()
        environment["FOUNDER_QUEUE_DB"] = str(self.db)
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

    def test_urgent_first_and_done_hidden(self):
        self.run_queue("add", "--title", "Small task")
        urgent = self.run_queue(
            "add", "--title", "Fix outage", "--priority", "urgent", "--status", "needs_founder"
        )
        self.run_queue(
            "update", "--id", str(urgent["item"]["id"]), "--status", "done"
        )
        visible = self.run_queue("list")
        self.assertEqual(visible["count"], 1)
        self.assertEqual(visible["items"][0]["title"], "Small task")

    def test_duplicate_title_is_not_added(self):
        first = self.run_queue("add", "--title", "Review pricing")
        second = self.run_queue("add", "--title", " review  PRICING ")
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["item"]["id"], second["item"]["id"])

    def test_source_and_draft_pr_are_persisted(self):
        first = self.run_queue("add", "--title", "Review checkout fix", "--status", "needs_founder",
                               "--action-kind", "review", "--source-kind", "github",
                               "--source-ref", "issue:31", "--artifact-kind", "draft_pr",
                               "--artifact-ref", "https://github.test/pr/9", "--evidence", "tests pass")
        second = self.run_queue("add", "--title", "Duplicate", "--source-kind", "github",
                                "--source-ref", "issue:31")
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["item"]["artifact_kind"], "draft_pr")

    def test_additive_migration_preserves_legacy_id(self):
        db = sqlite3.connect(self.db)
        db.executescript("""CREATE TABLE queue_item(id INTEGER PRIMARY KEY,title TEXT NOT NULL,
          context TEXT NOT NULL,priority TEXT NOT NULL,status TEXT NOT NULL,can_agent_handle INTEGER NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          INSERT INTO queue_item VALUES(52,'Legacy task','','medium','ready',0,'old','old');""")
        db.commit(); db.close()
        listed = self.run_queue("list")
        self.assertEqual(listed["items"][0]["id"], 52)
        self.assertEqual(listed["items"][0]["source_kind"], "legacy")


if __name__ == "__main__":
    unittest.main()
