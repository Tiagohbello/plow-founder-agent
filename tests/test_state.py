from __future__ import annotations

import hashlib
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

    def video_preference(self, *arguments: str, ok: bool = True):
        result = self.run_helper(
            "skills/founder-context/scripts/profile.py", *arguments, ok=ok
        )
        return json.loads(result.stdout) if ok else result

    def configure_product_access(self) -> None:
        self.run_helper(
            "skills/founder-context/scripts/profile.py", "set-access",
            "--name", "CRM", "--kind", "app", "--url", "https://crm.example.test",
            "--environment", "staging", "--status", "available",
        )
        self.run_helper(
            "skills/founder-context/scripts/profile.py", "set-access-policy",
            "--name", "CRM", "--access-operation", "update_record",
            "--policy", "autonomous",
        )

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

    def test_product_operation_persists_and_claims_the_selected_access(self) -> None:
        self.configure_product_access()
        prepared = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "prepare",
            "--scope", "product", "--target", "contact:1", "--operation", "update_record",
            "--intent", "update-contact", "--access-name", "CRM",
        ).stdout)
        operation = prepared["operation"]
        self.assertEqual("CRM", operation["access_name"])
        self.assertEqual("autonomous", operation["policy"])

        self.run_helper(
            "skills/founder-context/scripts/profile.py", "set-access",
            "--name", "Billing", "--kind", "app", "--url", "https://billing.example.test",
            "--environment", "production", "--status", "available",
        )
        self.run_helper(
            "skills/founder-context/scripts/profile.py", "set-access-policy",
            "--name", "Billing", "--access-operation", "update_record",
            "--policy", "autonomous",
        )
        duplicate_refused = self.run_helper(
            "skills/external-action/scripts/operations.py", "prepare",
            "--scope", "product", "--target", "contact:1", "--operation", "update_record",
            "--intent", "update-contact", "--access-name", "Billing", ok=False,
        )
        self.assertEqual(2, duplicate_refused.returncode)
        self.assertIn("error:", duplicate_refused.stderr)

        claimed = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "claim", "--id", "1"
        ).stdout)
        self.assertTrue(claimed["claimed"])

    def test_product_claim_rejects_access_that_became_unusable(self) -> None:
        self.configure_product_access()
        changes = ("inactive", "blocked", "forbidden", "approval")
        for index, change in enumerate(changes, start=1):
            with self.subTest(change=change):
                self.run_helper(
                    "skills/founder-context/scripts/profile.py", "set-access",
                    "--name", "CRM", "--kind", "app", "--url", "https://crm.example.test",
                    "--environment", "staging", "--status", "available",
                )
                self.run_helper(
                    "skills/founder-context/scripts/profile.py", "set-access-policy",
                    "--name", "CRM", "--access-operation", "update_record",
                    "--policy", "autonomous",
                )
                self.run_helper(
                    "skills/external-action/scripts/operations.py", "prepare",
                    "--scope", "product", "--target", f"contact:{index}",
                    "--operation", "update_record", "--intent", f"change-{index}",
                    "--access-name", "CRM",
                )

                if change == "inactive":
                    self.run_helper(
                        "skills/founder-context/scripts/profile.py", "deactivate-access",
                        "--name", "CRM",
                    )
                elif change == "blocked":
                    self.run_helper(
                        "skills/founder-context/scripts/profile.py", "set-access",
                        "--name", "CRM", "--kind", "app", "--url", "https://crm.example.test",
                        "--environment", "staging", "--status", "blocked",
                    )
                else:
                    policy = "forbidden" if change == "forbidden" else "approval"
                    self.run_helper(
                        "skills/founder-context/scripts/profile.py", "set-access-policy",
                        "--name", "CRM", "--access-operation", "update_record",
                        "--policy", policy,
                    )

                refused = self.run_helper(
                    "skills/external-action/scripts/operations.py", "claim",
                    "--id", str(index), ok=False,
                )
                self.assertEqual(2, refused.returncode)
                self.assertIn("error:", refused.stderr)
                if change == "approval":
                    approved = json.loads(self.run_helper(
                        "skills/external-action/scripts/operations.py", "approve",
                        "--id", str(index),
                    ).stdout)
                    self.assertEqual("approval", approved["operation"]["policy"])
                    self.assertEqual("approved", approved["operation"]["status"])
                    claimed = json.loads(self.run_helper(
                        "skills/external-action/scripts/operations.py", "claim",
                        "--id", str(index),
                    ).stdout)
                    self.assertTrue(claimed["claimed"])

    def test_product_operations_require_a_configured_access_name(self) -> None:
        refused = self.run_helper(
            "skills/external-action/scripts/operations.py", "prepare",
            "--scope", "product", "--target", "contact:1", "--operation", "update_record",
            "--intent", "update-contact", ok=False,
        )
        self.assertEqual(2, refused.returncode)

    def test_operations_schema_adds_access_name_without_losing_existing_rows(self) -> None:
        database = self.home / "founder-agent" / "founder-agent.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE external_operation (
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL,
                target TEXT NOT NULL,
                operation TEXT NOT NULL,
                intent TEXT NOT NULL,
                policy TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                external_ref TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE founder_agent_migration (
                component TEXT PRIMARY KEY,
                migrated_at TEXT NOT NULL
            );
            INSERT INTO founder_agent_migration VALUES ('operations', '2026-09-01T00:00:00+00:00');
            INSERT INTO external_operation VALUES
                (1, 'product', 'contact:legacy', 'update_record', 'legacy-update',
                 'approval', 'pending', 'legacy-key', '', '', '2026-09-01', '2026-09-01'),
                (2, 'product', 'contact:legacy-approved', 'update_record', 'legacy-approved',
                 'approval', 'approved', 'legacy-approved-key', '', '', '2026-09-01', '2026-09-01'),
                (3, 'product', 'contact:legacy-completed', 'update_record', 'legacy-completed',
                 'approval', 'completed', 'legacy-completed-key', '', '', '2026-09-01', '2026-09-01'),
                (4, 'calendar', 'primary/new', 'create_event', 'legacy-calendar',
                 'approval', 'pending', 'legacy-calendar-key', '', '', '2026-09-01', '2026-09-01');
            PRAGMA user_version = 1;
            """
        )
        connection.commit()
        connection.close()

        result = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "list"
        ).stdout)
        self.assertEqual(4, result["count"])
        operations = {operation["id"]: operation for operation in result["operations"]}
        self.assertIsNone(operations[1]["access_name"])
        self.assertIsNone(operations[2]["access_name"])
        self.assertEqual("cancelled", operations[1]["status"])
        self.assertEqual("cancelled", operations[2]["status"])
        self.assertTrue(
            operations[1]["idempotency_key"].startswith("cancelled:legacy-no-access:")
        )
        self.assertTrue(
            operations[2]["idempotency_key"].startswith("cancelled:legacy-no-access:")
        )
        self.assertEqual("completed", operations[3]["status"])
        self.assertEqual("pending", operations[4]["status"])
        connection = sqlite3.connect(database)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(external_operation)")}
        marker = connection.execute(
            "SELECT 1 FROM founder_agent_migration WHERE component=?",
            ("operations-access-name-v3",),
        ).fetchone()
        connection.close()
        self.assertIn("access_name", columns)
        self.assertIsNotNone(marker)

        self.configure_product_access()
        self.run_helper(
            "skills/founder-context/scripts/profile.py", "set-access-policy",
            "--name", "CRM", "--access-operation", "update_record", "--policy", "approval",
        )
        prepared = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "prepare",
            "--scope", "product", "--target", "contact:legacy", "--operation", "update_record",
            "--intent", "legacy-update", "--access-name", "CRM", "--idempotency-key", "legacy-key",
        ).stdout)
        self.assertTrue(prepared["created"])
        self.assertEqual("CRM", prepared["operation"]["access_name"])
        self.assertEqual("pending", prepared["operation"]["status"])
        approved = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "approve",
            "--id", str(prepared["operation"]["id"]),
        ).stdout)
        self.assertEqual("approved", approved["operation"]["status"])

    def test_video_preference_is_one_typed_json_value(self) -> None:
        preferences = self.video_preference("show")["preferences"]
        self.assertNotIn("video", preferences)

        self.video_preference(
            "set-video-preference", "--provider", "zoom", "--zoom-link-mode", "personal_room",
            "--zoom-personal-room-url", "https://us02web.zoom.us/j/123456789",
        )
        preferences = self.video_preference(
            "set-video-preference", "--provider", "google_meet"
        )["preferences"]
        self.assertEqual({"video": {"provider": "google_meet"}}, preferences)
        self.assertEqual(preferences, self.video_preference("show")["preferences"])

    def test_video_preference_zoom_modes_replace_complete_json_value(self) -> None:
        room = "https://zoom.us/my/founder"
        preferences = self.video_preference(
            "set-video-preference", "--provider", "zoom", "--zoom-link-mode", "personal_room",
            "--zoom-personal-room-url", room,
        )["preferences"]
        self.assertEqual(
            {"video": {"provider": "zoom", "link_mode": "personal_room",
                        "personal_room_url": room}},
            preferences,
        )
        preferences = self.video_preference(
            "set-video-preference", "--provider", "zoom", "--zoom-link-mode", "per_meeting"
        )["preferences"]
        self.assertEqual(
            {"video": {"provider": "zoom", "link_mode": "per_meeting"}}, preferences
        )
        self.assertEqual(preferences, self.video_preference("show")["preferences"])

    def test_invalid_video_settings_preserve_prior_configuration(self) -> None:
        self.video_preference(
            "set-video-preference", "--provider", "zoom", "--zoom-link-mode", "personal_room",
            "--zoom-personal-room-url", "https://zoom.us/my/founder",
        )
        original = self.video_preference("show")["preferences"]
        invalid = [
            ("--provider", "unknown"),
            ("--provider", "zoom"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "http://zoom.us/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us.evil.test/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://user:***@zoom.us/my/founder"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/not-a-room"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?pwd=secret"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?token=***"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?utm_source=mail"),
            ("--provider", "zoom", "--zoom-link-mode", "personal_room",
             "--zoom-personal-room-url", "https://zoom.us/my/founder?"),
            ("--provider", "zoom", "--zoom-link-mode", "per_meeting",
             "--zoom-personal-room-url", "https://zoom.us/my/founder"),
            ("--provider", "google_meet", "--zoom-link-mode", "per_meeting"),
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                result = self.video_preference(
                    "set-video-preference", *arguments, ok=False
                )
                self.assertEqual(2, result.returncode)
                self.assertEqual(original, self.video_preference("show")["preferences"])

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

    def test_gmail_provider_draft_reference_is_durable_and_idempotent(self) -> None:
        self.run_helper(
            "skills/external-action/scripts/drafts.py", "prepare", "--channel", "gmail",
            "--thread-id", "thread-1", "--recipient", "founder@example.com", "--body", "Hello",
        )
        saved = json.loads(self.run_helper(
            "skills/external-action/scripts/drafts.py", "mark-draft-saved", "--id", "1",
            "--draft-id", "gmail-draft-123", "--account", "owner@example.com",
        ).stdout)
        self.assertTrue(saved["draft_saved"])
        self.assertEqual(saved["draft"]["external_draft_id"], "gmail-draft-123")
        repeated = json.loads(self.run_helper(
            "skills/external-action/scripts/drafts.py", "mark-draft-saved", "--id", "1",
            "--draft-id", "gmail-draft-123", "--account", "owner@example.com",
        ).stdout)
        self.assertEqual(repeated["draft"]["external_draft_id"], "gmail-draft-123")

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
        connection = sqlite3.connect(database)
        connection.execute("UPDATE draft SET status='sending' WHERE id=8")
        connection.commit()
        connection.close()
        refused = self.run_helper(
            "skills/external-action/scripts/drafts.py", "mark-sent", "--id", "8",
            "--message-id", "must-not-send", ok=False,
        )
        self.assertEqual(2, refused.returncode)
        refused = self.run_helper(
            "skills/external-action/scripts/drafts.py", "mark-uncertain", "--id", "8",
            "--note", "must-remain-read-only", ok=False,
        )
        self.assertEqual(2, refused.returncode)
        connection = sqlite3.connect(database)
        self.assertEqual(
            "sending",
            connection.execute("SELECT status FROM draft WHERE id=8").fetchone()[0],
        )
        connection.close()

    def test_draft_migration_runs_after_a_sibling_sets_the_shared_version(self) -> None:
        database = self.home / "founder-agent" / "founder-agent.db"
        expected = self.create_v1_draft_database(database)
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA user_version = 0")
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
            ("drafts-schema-v2",),
        ).fetchone()
        self.assertEqual(1, connection.execute("PRAGMA user_version").fetchone()[0])
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
                    self.assertEqual(1, connection.execute("PRAGMA user_version").fetchone()[0])
                    markers = {
                        row[0] for row in connection.execute(
                            "SELECT component FROM founder_agent_migration"
                        )
                    }
                    self.assertTrue({"drafts", "drafts-schema-v2"}.issubset(markers))
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

    def test_clean_legacy_idempotency_keys_deduplicate_after_contact_refresh(self) -> None:
        legacy_drafts = self.home / "communication" / "drafts.db"
        legacy_operations = self.home / "external-operations" / "operations.db"
        draft_args = (
            "prepare", "--channel", "gmail", "--thread-id", "legacy-pipeline-thread",
            "--recipient", "alex@example.test", "--body", "Legacy pipeline draft",
        )
        operation_args = (
            "prepare", "--scope", "calendar", "--target", "primary/new",
            "--operation", "create_event", "--intent", "Legacy pipeline event",
        )
        legacy_draft = json.loads(self.run_helper(
            "skills/external-action/scripts/drafts.py", "--db", str(legacy_drafts), *draft_args
        ).stdout)["draft"]
        legacy_operation = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", "--db", str(legacy_operations), *operation_args
        ).stdout)["operation"]
        self.assertFalse(legacy_draft["idempotency_key"].startswith("pipeline:"))
        self.assertFalse(legacy_operation["idempotency_key"].startswith("pipeline:"))

        database = self.home / "founder-agent" / "founder-agent.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE monitor_contact_guard (contact_key TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO monitor_contact_guard VALUES (?,?)",
            ("alex", json.dumps({
                "contact_key": "alex", "name": "Alex", "handles": ["alex@example.test"],
                "fields": {"status": "sent", "holds": "", "proposed": ""},
                "mapped_status": "sent",
            })),
        )
        connection.commit()
        connection.close()

        migrated_draft = json.loads(self.run_helper(
            "skills/external-action/scripts/drafts.py", *draft_args, "--contact-key", "alex"
        ).stdout)
        migrated_operation = json.loads(self.run_helper(
            "skills/external-action/scripts/operations.py", *operation_args, "--contact-key", "alex"
        ).stdout)
        self.assertTrue(migrated_draft["duplicate"])
        self.assertEqual(migrated_draft["draft"]["id"], legacy_draft["id"])
        self.assertEqual(migrated_draft["draft"]["idempotency_key"], legacy_draft["idempotency_key"])
        self.assertEqual(migrated_draft["draft"]["pipeline_contact_key"], "alex")
        self.assertTrue(migrated_operation["duplicate"])
        self.assertEqual(migrated_operation["operation"]["id"], legacy_operation["id"])
        self.assertEqual(migrated_operation["operation"]["idempotency_key"], legacy_operation["idempotency_key"])
        self.assertEqual(migrated_operation["operation"]["pipeline_contact_key"], "alex")

        connection = sqlite3.connect(database)
        self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM draft").fetchone()[0])
        self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM external_operation").fetchone()[0])
        connection.close()

        revised_draft = json.loads(self.run_helper(
            "skills/external-action/scripts/drafts.py", "revise",
            "--id", str(legacy_draft["id"]), "--body", "Revised pipeline draft",
        ).stdout)["draft"]
        expected_revised_key = hashlib.sha256(
            "\x1f".join(("gmail", "legacy-pipeline-thread", "alex@example.test", "",
                         "Revised pipeline draft")).encode()
        ).hexdigest()
        self.assertEqual(revised_draft["idempotency_key"], expected_revised_key)
        self.assertEqual(revised_draft["pipeline_contact_key"], "alex")


if __name__ == "__main__":
    unittest.main()
