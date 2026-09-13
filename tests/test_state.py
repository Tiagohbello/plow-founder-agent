from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DRAFTS_PATH = ROOT / "skills/external-action/scripts/drafts.py"
DRAFTS_SPEC = importlib.util.spec_from_file_location("founder_agent_drafts", DRAFTS_PATH)
assert DRAFTS_SPEC and DRAFTS_SPEC.loader
DRAFTS = importlib.util.module_from_spec(DRAFTS_SPEC)
DRAFTS_SPEC.loader.exec_module(DRAFTS)


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

    def create_v1_draft_database(self, database: Path) -> list[tuple]:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE draft (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL CHECK (channel IN ('gmail', 'whatsapp')),
                thread_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
                    ('draft', 'approved', 'sending', 'sent', 'uncertain', 'cancelled')),
                approval_token TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                external_message_id TEXT,
                verification_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approval_ref TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX draft_thread_idx ON draft(channel, thread_id);
            CREATE INDEX draft_status_idx ON draft(status);
            CREATE TABLE founder_agent_migration (
                component TEXT PRIMARY KEY,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO founder_agent_migration VALUES ('drafts', '2026-09-01T00:00:00+00:00');
            PRAGMA user_version = 1;
            """
        )
        rows = [
            (
                7, "gmail", "gmail-thread", "founder@example.test", "Times",
                "Tuesday at 11:30?", "sent", "approval-token", "gmail-key",
                "gmail-message", "verified", "2026-09-01T00:00:00+00:00",
                "2026-09-01T00:01:00+00:00", "conversation:approval-1",
            ),
            (
                8, "whatsapp", "retired-thread", "+15550100999", "",
                "Historical message", "uncertain", "retired-token", "retired-key",
                None, "legacy verification required", "2026-09-02T00:00:00+00:00",
                "2026-09-02T00:01:00+00:00", "conversation:approval-2",
            ),
        ]
        connection.executemany(
            """INSERT INTO draft(
                   id,channel,thread_id,recipient,subject,body,status,approval_token,
                   idempotency_key,external_message_id,verification_note,created_at,
                   updated_at,approval_ref
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        connection.commit()
        connection.close()
        return rows

    def test_helpers_share_one_database(self) -> None:
        self.run_helper("skills/founder-context/scripts/profile.py", "show")
        self.run_helper(
            "skills/founder-context/scripts/memory.py",
            "add", "--type", "goal", "--subject", "Launch", "--content", "Ship v1",
        )
        self.run_helper(
            "skills/external-action/scripts/drafts.py",
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
        self.run_helper("skills/founder-context/scripts/profile.py", "show")
        result = self.run_helper(
            "skills/external-action/scripts/operations.py",
            "prepare", "--scope", "calendar", "--target", "primary/new",
            "--operation", "create_event", "--intent", "demo-event",
        )
        operation = json.loads(result.stdout)["operation"]
        self.assertEqual("approval", operation["policy"])
        self.assertEqual("pending", operation["status"])

    def test_permanent_prohibitions_cannot_be_overridden(self) -> None:
        result = self.run_helper(
            "skills/founder-context/scripts/profile.py",
            "set-permission", "--capability", "deploy", "--policy", "autonomous",
            ok=False,
        )
        self.assertEqual(2, result.returncode)
        result = self.run_helper(
            "skills/external-action/scripts/operations.py",
            "prepare", "--scope", "product", "--target", "production",
            "--operation", "deploy", "--intent", "release-v1",
            ok=False,
        )
        self.assertEqual(2, result.returncode)

    def test_gmail_approval_requires_a_source_reference(self) -> None:
        self.run_helper(
            "skills/external-action/scripts/drafts.py",
            "prepare", "--channel", "gmail", "--thread-id", "thread-1",
            "--recipient", "founder@example.com", "--body", "Hello",
        )
        missing = self.run_helper(
            "skills/external-action/scripts/drafts.py", "approve", "--id", "1", ok=False
        )
        self.assertNotEqual(0, missing.returncode)
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "approve", "--id", "1",
            "--approval-ref", "conversation:message-42",
        )
        claimed = self.run_helper(
            "skills/external-action/scripts/drafts.py", "claim-send", "--id", "1"
        )
        self.assertTrue(json.loads(claimed.stdout)["claimed"])

    def test_active_channels_complete_the_same_durable_send_lifecycle(self) -> None:
        for draft_id, channel in enumerate(("gmail", "text", "plow"), start=1):
            with self.subTest(channel=channel):
                arguments = (
                    "prepare", "--channel", channel, "--thread-id", f"{channel}-thread",
                    "--recipient", f"{channel}-recipient", "--body", "Tuesday at 11:30?",
                )
                prepared = json.loads(
                    self.run_helper("skills/external-action/scripts/drafts.py", *arguments).stdout
                )
                duplicate = json.loads(
                    self.run_helper("skills/external-action/scripts/drafts.py", *arguments).stdout
                )
                self.assertTrue(prepared["created"])
                self.assertTrue(duplicate["duplicate"])
                self.assertEqual(draft_id, duplicate["draft"]["id"])

                self.run_helper(
                    "skills/external-action/scripts/drafts.py", "approve", "--id", str(draft_id),
                    "--approval-ref", f"conversation:approval-{draft_id}",
                )
                claimed = json.loads(
                    self.run_helper(
                        "skills/external-action/scripts/drafts.py", "claim-send", "--id", str(draft_id)
                    ).stdout
                )
                repeated_claim = json.loads(
                    self.run_helper(
                        "skills/external-action/scripts/drafts.py", "claim-send", "--id", str(draft_id)
                    ).stdout
                )
                self.assertTrue(claimed["claimed"])
                self.assertTrue(repeated_claim["verification_required"])

                self.run_helper(
                    "skills/external-action/scripts/drafts.py", "mark-sent", "--id", str(draft_id),
                    "--message-id", f"{channel}-message",
                )
                sent_claim = json.loads(
                    self.run_helper(
                        "skills/external-action/scripts/drafts.py", "claim-send", "--id", str(draft_id)
                    ).stdout
                )
                self.assertTrue(sent_claim["already_sent"])

    def test_uncertain_send_is_not_claimed_again(self) -> None:
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "prepare", "--channel", "text",
            "--thread-id", "plow-text-thread-42", "--recipient", "investor-id",
            "--body", "Tuesday at 11:30?",
        )
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "approve", "--id", "1",
            "--approval-ref", "conversation:approval-1",
        )
        self.run_helper("skills/external-action/scripts/drafts.py", "claim-send", "--id", "1")
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "mark-uncertain", "--id", "1",
            "--note", "Plow read-back unavailable",
        )
        repeated = json.loads(
            self.run_helper(
                "skills/external-action/scripts/drafts.py", "claim-send", "--id", "1"
            ).stdout
        )
        self.assertTrue(repeated["verification_required"])

    def test_revision_cannot_cancel_a_draft_claimed_during_its_state_check(self) -> None:
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "prepare", "--channel", "text",
            "--thread-id", "text-thread", "--recipient", "investor-id",
            "--body", "Tuesday at 11:30?",
        )
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "approve", "--id", "1",
            "--approval-ref", "conversation:approval-1",
        )
        database = self.home / "founder-agent" / "founder-agent.db"
        revision_connection = DRAFTS.connect(database)
        claim_connection = DRAFTS.connect(database)
        original_resolve = DRAFTS.resolve
        claim_succeeded = False
        claim_attempted = False

        def resolve_with_interleaved_claim(connection, draft_id):
            nonlocal claim_attempted, claim_succeeded
            row = original_resolve(connection, draft_id)
            if (
                connection is revision_connection
                and not connection.in_transaction
                and not claim_attempted
            ):
                claim_attempted = True
                claim_succeeded = DRAFTS.claim_send(claim_connection, draft_id)["claimed"]
            return row

        arguments = argparse.Namespace(
            id=1, thread_id=None, recipient=None, subject=None,
            body="Wednesday at 14:00?", idempotency_key=None,
        )
        try:
            with mock.patch.object(DRAFTS, "resolve", side_effect=resolve_with_interleaved_claim):
                DRAFTS.revise_draft(revision_connection, arguments)
            if not claim_succeeded:
                with self.assertRaises(ValueError):
                    DRAFTS.claim_send(claim_connection, 1)
            self.assertFalse(claim_succeeded)
            self.assertEqual("cancelled", original_resolve(revision_connection, 1)["status"])
        finally:
            revision_connection.close()
            claim_connection.close()

    def test_approval_cannot_resurrect_a_draft_revised_during_its_state_check(self) -> None:
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "prepare", "--channel", "plow",
            "--thread-id", "plow-thread", "--recipient", "investor-id",
            "--body", "Tuesday at 11:30?",
        )
        database = self.home / "founder-agent" / "founder-agent.db"
        approval_connection = DRAFTS.connect(database)
        revision_connection = DRAFTS.connect(database)
        original_resolve = DRAFTS.resolve
        revision_ran = False
        revision_attempted = False
        arguments = argparse.Namespace(
            id=1, thread_id=None, recipient=None, subject=None,
            body="Wednesday at 14:00?", idempotency_key=None,
        )

        def resolve_with_interleaved_revision(connection, draft_id):
            nonlocal revision_attempted, revision_ran
            row = original_resolve(connection, draft_id)
            if (
                connection is approval_connection
                and not connection.in_transaction
                and not revision_attempted
            ):
                revision_attempted = True
                DRAFTS.revise_draft(revision_connection, arguments)
                revision_ran = True
            return row

        try:
            with mock.patch.object(DRAFTS, "resolve", side_effect=resolve_with_interleaved_revision):
                DRAFTS.approve_draft(approval_connection, 1, "conversation:approval-1")
            if not revision_ran:
                DRAFTS.revise_draft(revision_connection, arguments)
            self.assertEqual("cancelled", original_resolve(approval_connection, 1)["status"])
            self.assertEqual("draft", original_resolve(approval_connection, 2)["status"])
        finally:
            approval_connection.close()
            revision_connection.close()

    def test_v1_draft_schema_is_migrated_without_losing_rows(self) -> None:
        database = self.home / "founder-agent" / "founder-agent.db"
        expected = self.create_v1_draft_database(database)

        result = json.loads(
            self.run_helper("skills/external-action/scripts/drafts.py", "list").stdout
        )
        actual = {
            row["id"]: tuple(row[name] for name in (
                "id", "channel", "thread_id", "recipient", "subject", "body", "status",
                "approval_token", "idempotency_key", "external_message_id",
                "verification_note", "created_at", "updated_at", "approval_ref",
            ))
            for row in result["drafts"]
        }
        self.assertEqual({row[0]: row for row in expected}, actual)

        migrated = json.loads(
            self.run_helper(
                "skills/external-action/scripts/drafts.py", "prepare", "--channel", "text",
                "--thread-id", "text-thread", "--recipient", "investor-id",
                "--body", "Wednesday at 14:00?",
            ).stdout
        )
        self.assertTrue(migrated["created"])

        historical = json.loads(
            self.run_helper(
                "skills/external-action/scripts/drafts.py", "list", "--channel", "whatsapp"
            ).stdout
        )
        self.assertEqual([8], [row["id"] for row in historical["drafts"]])
        refused = self.run_helper(
            "skills/external-action/scripts/drafts.py", "approve", "--id", "8", ok=False
        )
        self.assertEqual(2, refused.returncode)
        refused = self.run_helper(
            "skills/external-action/scripts/drafts.py", "prepare", "--channel", "whatsapp",
            "--thread-id", "new-retired-thread", "--recipient", "+15550100888",
            "--body", "This must remain historical", ok=False,
        )
        self.assertEqual(2, refused.returncode)

    def test_draft_migration_runs_when_another_helper_already_set_version_two(self) -> None:
        database = self.home / "founder-agent" / "founder-agent.db"
        expected = self.create_v1_draft_database(database)
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()

        # A sibling helper may touch the shared version before drafts.py gets
        # a chance to run its component-specific migration.
        self.run_helper("skills/founder-context/scripts/profile.py", "show")
        result = json.loads(
            self.run_helper("skills/external-action/scripts/drafts.py", "list").stdout
        )
        self.assertEqual({row[0] for row in expected}, {row["id"] for row in result["drafts"]})
        connection = sqlite3.connect(database)
        draft_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='draft'"
        ).fetchone()[0]
        marker = connection.execute(
            "SELECT 1 FROM founder_agent_migration WHERE component=?",
            (DRAFTS.DRAFT_SCHEMA_MIGRATION,),
        ).fetchone()
        self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
        self.assertIn("'text'", draft_sql)
        self.assertIn("'plow'", draft_sql)
        self.assertIsNotNone(marker)
        connection.close()

    def test_shared_helpers_initialize_in_different_orders(self) -> None:
        helper_commands = {
            "profile": ("skills/founder-context/scripts/profile.py", "show"),
            "memory": ("skills/founder-context/scripts/memory.py", "list"),
            "operations": ("skills/external-action/scripts/operations.py", "list"),
            "drafts": ("skills/external-action/scripts/drafts.py", "list"),
        }
        for order in (
            ("profile", "memory", "operations", "drafts"),
            ("drafts", "operations", "memory", "profile"),
        ):
            with self.subTest(order=order):
                with tempfile.TemporaryDirectory() as directory:
                    environment = {**os.environ, "HERMES_HOME": directory}
                    for name in order:
                        helper, *arguments = helper_commands[name]
                        result = subprocess.run(
                            [sys.executable, str(ROOT / helper), *arguments],
                            cwd=ROOT,
                            env=environment,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(0, result.returncode, result.stderr)
                    database = Path(directory) / "founder-agent" / "founder-agent.db"
                    connection = sqlite3.connect(database)
                    self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
                    tables = {
                        row[0] for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    self.assertTrue({"company", "memory", "draft", "external_operation"}.issubset(tables))
                    connection.close()
    def test_legacy_memory_is_imported_once(self) -> None:
        legacy = self.home / "founder-memory" / "memory.db"
        self.run_helper(
            "skills/founder-context/scripts/memory.py", "--db", str(legacy),
            "add", "--type", "decision", "--subject", "Pricing",
            "--content", "Keep current plan",
        )
        result = self.run_helper("skills/founder-context/scripts/memory.py", "list")
        self.assertEqual(1, json.loads(result.stdout)["count"])

    def test_other_legacy_stores_are_imported(self) -> None:
        profile = self.home / "founder-profile" / "profile.db"
        drafts = self.home / "communication" / "drafts.db"
        operations = self.home / "external-operations" / "operations.db"
        self.run_helper(
            "skills/founder-context/scripts/profile.py", "--db", str(profile),
            "set-company", "--name", "Acme", "--product", "App",
        )
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "--db", str(drafts),
            "prepare", "--channel", "gmail", "--thread-id", "legacy-thread",
            "--recipient", "founder@example.com", "--body", "Legacy draft",
        )
        self.run_helper(
            "skills/external-action/scripts/operations.py", "--db", str(operations),
            "prepare", "--scope", "calendar", "--target", "primary/new",
            "--operation", "create_event", "--intent", "legacy-event",
        )

        profile_result = self.run_helper("skills/founder-context/scripts/profile.py", "show")
        draft_result = self.run_helper("skills/external-action/scripts/drafts.py", "list")
        operation_result = self.run_helper("skills/external-action/scripts/operations.py", "list")
        self.assertEqual("Acme", json.loads(profile_result.stdout)["company"]["name"])
        self.assertEqual(1, json.loads(draft_result.stdout)["count"])
        self.assertEqual(1, json.loads(operation_result.stdout)["count"])


if __name__ == "__main__":
    unittest.main()
