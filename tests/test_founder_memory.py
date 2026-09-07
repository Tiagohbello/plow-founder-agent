import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "founder-memory" / "memory.py"


class FounderMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "memory.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_memory(self, *arguments, check=True):
        environment = os.environ.copy()
        environment["FOUNDER_MEMORY_DB"] = str(self.db)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"memory command failed: {result.stderr}")
        if result.returncode == 0:
            return json.loads(result.stdout)
        return result

    def test_add_search_and_reopen_persist_data(self):
        created = self.run_memory(
            "add",
            "--type",
            "feature",
            "--subject",
            "SSO",
            "--content",
            "Acme and Beta requested SSO.",
        )
        self.assertTrue(created["created"])
        record_id = created["record"]["id"]

        reopened = self.run_memory("search", "SSO")
        self.assertEqual(reopened["count"], 1)
        self.assertEqual(reopened["items"][0]["id"], record_id)

    def test_update_preserves_deferred_decision(self):
        created = self.run_memory(
            "add",
            "--type",
            "feature",
            "--subject",
            "SSO",
            "--content",
            "Acme requested SSO.",
        )
        updated = self.run_memory(
            "update",
            "--id",
            str(created["record"]["id"]),
            "--priority",
            "low",
            "--status",
            "deferred",
            "--content",
            "Acme requested SSO. The founder decided not to prioritize it for now.",
        )
        self.assertEqual(updated["record"]["status"], "deferred")
        self.assertEqual(updated["record"]["priority"], "low")
        listed = self.run_memory("list", "--status", "deferred")
        self.assertEqual(listed["count"], 1)

    def test_correction_replaces_incorrect_fact(self):
        created = self.run_memory(
            "add",
            "--type",
            "feature",
            "--subject",
            "SSO",
            "--content",
            "Acme requested SSO.",
        )
        corrected = self.run_memory(
            "correct",
            "--id",
            str(created["record"]["id"]),
            "--subject",
            "SCIM",
            "--content",
            "Acme requested SCIM, not SSO.",
        )
        self.assertEqual(corrected["record"]["subject"], "SCIM")
        old_term = self.run_memory("search", "SSO")
        self.assertEqual(old_term["count"], 1)
        self.assertIn("not SSO", old_term["items"][0]["content"])
        self.assertEqual(self.run_memory("search", "SCIM")["count"], 1)

    def test_identical_add_is_deduplicated(self):
        arguments = (
            "add",
            "--type",
            "customer",
            "--subject",
            "Acme",
            "--content",
            "Requested export.",
        )
        first = self.run_memory(*arguments)
        second = self.run_memory(*arguments)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["record"]["id"], first["record"]["id"])
        self.assertEqual(self.run_memory("list")["count"], 1)

    def test_stable_source_reference_deduplicates_observation(self):
        arguments = ("add", "--type", "feature", "--subject", "SSO", "--content",
                     "Delta requested SSO.", "--source-kind", "gmail", "--source-ref", "message-44",
                     "--evidence", "Gmail thread Acme SSO")
        first = self.run_memory(*arguments)
        second = self.run_memory("add", "--type", "feature", "--subject", "Different title",
                                 "--content", "Repeated observation", "--source-kind", "gmail",
                                 "--source-ref", "message-44")
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["record"]["id"], second["record"]["id"])
        self.assertEqual(second["record"]["source_kind"], "gmail")

    def test_delete_removes_explicit_record(self):
        created = self.run_memory(
            "add",
            "--type",
            "note",
            "--subject",
            "Temporary",
            "--content",
            "Forget this note.",
        )
        deleted = self.run_memory("delete", "--id", str(created["record"]["id"]))
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.run_memory("list")["count"], 0)

    def test_additive_migration_preserves_legacy_id(self):
        db = sqlite3.connect(self.db)
        db.executescript("""CREATE TABLE memory(id INTEGER PRIMARY KEY,type TEXT NOT NULL,subject TEXT NOT NULL,
          content TEXT NOT NULL,priority TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          INSERT INTO memory VALUES(41,'note','Legacy','kept','medium','active','old','old');""")
        db.commit(); db.close()
        listed = self.run_memory("list")
        self.assertEqual(listed["items"][0]["id"], 41)
        self.assertEqual(listed["items"][0]["source_kind"], "legacy")


if __name__ == "__main__":
    unittest.main()
