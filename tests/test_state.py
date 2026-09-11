from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FounderAgentStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = {**os.environ, "HERMES_HOME": str(self.home)}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_helper(self, relative: str, *arguments: str, ok: bool = True):
        result = subprocess.run(
            [sys.executable, str(ROOT / relative), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if ok and result.returncode != 0:
            self.fail(f"{relative} failed: {result.stderr}")
        return result

    def test_helpers_share_one_database(self) -> None:
        self.run_helper("skills/founder-profile/profile.py", "show")
        self.run_helper(
            "skills/founder-memory/memory.py",
            "add", "--type", "goal", "--subject", "Launch", "--content", "Ship v1",
        )
        self.run_helper(
            "skills/communication/drafts.py",
            "prepare", "--channel", "gmail", "--thread-id", "thread-1",
            "--recipient", "founder@example.com", "--body", "Hello",
        )
        database = self.home / "founder-agent" / "founder-agent.db"
        self.assertTrue(database.is_file())
        connection = sqlite3.connect(database)
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        connection.close()
        self.assertTrue({"company", "memory", "draft"}.issubset(tables))

    def test_calendar_write_requires_approval_by_default(self) -> None:
        self.run_helper("skills/founder-profile/profile.py", "show")
        result = self.run_helper(
            "skills/external-operations/operations.py",
            "prepare", "--scope", "calendar", "--target", "primary/new",
            "--operation", "create_event", "--intent", "demo-event",
        )
        operation = json.loads(result.stdout)["operation"]
        self.assertEqual("approval", operation["policy"])
        self.assertEqual("pending", operation["status"])

    def test_permanent_prohibitions_cannot_be_overridden(self) -> None:
        result = self.run_helper(
            "skills/founder-profile/profile.py",
            "set-permission", "--capability", "deploy", "--policy", "autonomous",
            ok=False,
        )
        self.assertEqual(2, result.returncode)
        result = self.run_helper(
            "skills/external-operations/operations.py",
            "prepare", "--scope", "product", "--target", "production",
            "--operation", "deploy", "--intent", "release-v1",
            ok=False,
        )
        self.assertEqual(2, result.returncode)

    def test_gmail_approval_requires_a_source_reference(self) -> None:
        self.run_helper(
            "skills/communication/drafts.py",
            "prepare", "--channel", "gmail", "--thread-id", "thread-1",
            "--recipient", "founder@example.com", "--body", "Hello",
        )
        missing = self.run_helper(
            "skills/communication/drafts.py", "approve", "--id", "1", ok=False
        )
        self.assertNotEqual(0, missing.returncode)
        self.run_helper(
            "skills/communication/drafts.py", "approve", "--id", "1",
            "--approval-ref", "conversation:message-42",
        )
        claimed = self.run_helper(
            "skills/communication/drafts.py", "claim-send", "--id", "1"
        )
        self.assertTrue(json.loads(claimed.stdout)["claimed"])

    def test_legacy_memory_is_imported_once(self) -> None:
        legacy = self.home / "founder-memory" / "memory.db"
        self.run_helper(
            "skills/founder-memory/memory.py", "--db", str(legacy),
            "add", "--type", "decision", "--subject", "Pricing",
            "--content", "Keep current plan",
        )
        result = self.run_helper("skills/founder-memory/memory.py", "list")
        self.assertEqual(1, json.loads(result.stdout)["count"])

    def test_other_legacy_stores_are_imported(self) -> None:
        profile = self.home / "founder-profile" / "profile.db"
        drafts = self.home / "communication" / "drafts.db"
        operations = self.home / "external-operations" / "operations.db"
        self.run_helper(
            "skills/founder-profile/profile.py", "--db", str(profile),
            "set-company", "--name", "Acme", "--product", "App",
        )
        self.run_helper(
            "skills/communication/drafts.py", "--db", str(drafts),
            "prepare", "--channel", "gmail", "--thread-id", "legacy-thread",
            "--recipient", "founder@example.com", "--body", "Legacy draft",
        )
        self.run_helper(
            "skills/external-operations/operations.py", "--db", str(operations),
            "prepare", "--scope", "calendar", "--target", "primary/new",
            "--operation", "create_event", "--intent", "legacy-event",
        )

        profile_result = self.run_helper("skills/founder-profile/profile.py", "show")
        draft_result = self.run_helper("skills/communication/drafts.py", "list")
        operation_result = self.run_helper("skills/external-operations/operations.py", "list")
        self.assertEqual("Acme", json.loads(profile_result.stdout)["company"]["name"])
        self.assertEqual(1, json.loads(draft_result.stdout)["count"])
        self.assertEqual(1, json.loads(operation_result.stdout)["count"])


if __name__ == "__main__":
    unittest.main()
