#!/usr/bin/env python3
"""Draft and send-intent ledger for approved external communication.

The browser/Latch action remains outside this module. This ledger makes the
approval boundary and one-send claim durable across a restart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_CHANNELS = ("gmail",)
HISTORICAL_CHANNELS = ("gmail", "whatsapp")
STATUSES = ("draft", "approved", "sending", "sent", "uncertain", "cancelled")


def default_database_path() -> Path:
    configured = os.environ.get("FOUNDER_DRAFTS_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "communication" / "drafts.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def required_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS draft (
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
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS draft_thread_idx ON draft(channel, thread_id);
        CREATE INDEX IF NOT EXISTS draft_status_idx ON draft(status);
        """
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def as_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def derive_idempotency_key(channel: str, thread_id: str, recipient: str, subject: str, body: str) -> str:
    value = "\x1f".join((channel, thread_id, recipient, subject, body))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare_draft(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    if args.channel not in ACTIVE_CHANNELS:
        raise ValueError(f"new drafts are supported only for: {', '.join(ACTIVE_CHANNELS)}")
    channel = args.channel
    thread_id = required_text(args.thread_id, "thread_id")
    recipient = required_text(args.recipient, "recipient")
    subject = (args.subject or "").strip()
    body = required_text(args.body, "body")
    key = args.idempotency_key or derive_idempotency_key(channel, thread_id, recipient, subject, body)
    existing = connection.execute("SELECT * FROM draft WHERE idempotency_key = ?", (key,)).fetchone()
    if existing is not None:
        return {"created": False, "duplicate": True, "draft": as_dict(existing)}
    timestamp = now()
    cursor = connection.execute(
        """
        INSERT INTO draft(channel, thread_id, recipient, subject, body, idempotency_key,
                          created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (channel, thread_id, recipient, subject, body, key, timestamp, timestamp),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM draft WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"created": True, "duplicate": False, "draft": as_dict(row)}


def revise_draft(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    """Create a new unapproved draft and cancel the superseded one."""
    old = resolve(connection, args.id)
    if old["channel"] not in ACTIVE_CHANNELS:
        raise ValueError("historical WhatsApp drafts are read-only")
    if old["status"] in {"sending", "sent", "uncertain", "cancelled"}:
        raise ValueError(f"draft cannot be revised from status {old['status']}")
    thread_id = required_text(args.thread_id if args.thread_id is not None else old["thread_id"], "thread_id")
    recipient = required_text(args.recipient if args.recipient is not None else old["recipient"], "recipient")
    subject = (args.subject if args.subject is not None else old["subject"]).strip()
    body = required_text(args.body if args.body is not None else old["body"], "body")
    if all(value == old[name] for name, value in (("thread_id", thread_id), ("recipient", recipient),
                                                   ("subject", subject), ("body", body))):
        return {"revised": False, "unchanged": True, "draft": as_dict(old)}
    base_key = args.idempotency_key or derive_idempotency_key(old["channel"], thread_id, recipient, subject, body)
    key = base_key
    existing = connection.execute("SELECT * FROM draft WHERE idempotency_key=?", (key,)).fetchone()
    if existing is not None and existing["status"] != "draft":
        key = hashlib.sha256(f"{base_key}\x1f{secrets.token_urlsafe(12)}".encode()).hexdigest()
        existing = None
    connection.execute("BEGIN IMMEDIATE")
    try:
        timestamp = now()
        if existing is None:
            cursor = connection.execute(
                """INSERT INTO draft(channel,thread_id,recipient,subject,body,idempotency_key,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (old["channel"], thread_id, recipient, subject, body, key, timestamp, timestamp),
            )
            new_id = cursor.lastrowid
        else:
            new_id = existing["id"]
        connection.execute(
            "UPDATE draft SET status='cancelled',approval_token=NULL,verification_note=?,updated_at=? WHERE id=?",
            (f"superseded by draft {new_id}", timestamp, old["id"]),
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {"revised": True, "approval_required": True, "old_draft": as_dict(resolve(connection, old["id"])),
            "draft": as_dict(resolve(connection, new_id))}


def resolve(connection: sqlite3.Connection, draft_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM draft WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise ValueError("draft not found")
    return row


def approve_draft(connection: sqlite3.Connection, draft_id: int) -> dict[str, object]:
    row = resolve(connection, draft_id)
    if row["channel"] not in ACTIVE_CHANNELS:
        raise ValueError("historical WhatsApp drafts cannot be approved")
    if row["status"] == "approved":
        return {"approved": True, "already_approved": True, "draft": as_dict(row)}
    if row["status"] != "draft":
        raise ValueError(f"draft cannot be approved from status {row['status']}")
    token = secrets.token_urlsafe(18)
    connection.execute(
        "UPDATE draft SET status = 'approved', approval_token = ?, updated_at = ? WHERE id = ?",
        (token, now(), draft_id),
    )
    connection.commit()
    return {"approved": True, "already_approved": False, "draft": as_dict(resolve(connection, draft_id))}


def claim_send(connection: sqlite3.Connection, draft_id: int) -> dict[str, object]:
    """Atomically claim the one browser send after approval.

    `sending` and `uncertain` are deliberately not auto-retried. The caller
    must verify the external thread before any recovery decision.
    """
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = resolve(connection, draft_id)
        if row["channel"] not in ACTIVE_CHANNELS:
            connection.rollback()
            raise ValueError("WhatsApp sending is retired")
        if row["status"] == "sent":
            connection.rollback()
            return {"claimed": False, "already_sent": True, "draft": as_dict(row)}
        if row["status"] in {"sending", "uncertain"}:
            connection.rollback()
            return {"claimed": False, "verification_required": True, "draft": as_dict(row)}
        if row["status"] != "approved":
            connection.rollback()
            raise ValueError("explicit founder approval is required before sending")
        connection.execute(
            "UPDATE draft SET status = 'sending', updated_at = ? WHERE id = ?",
            (now(), draft_id),
        )
        connection.commit()
        return {"claimed": True, "already_sent": False, "draft": as_dict(resolve(connection, draft_id))}
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def mark_sent(connection: sqlite3.Connection, draft_id: int, message_id: str) -> dict[str, object]:
    message_id = required_text(message_id, "message_id")
    row = resolve(connection, draft_id)
    if row["status"] == "sent":
        if row["external_message_id"] == message_id:
            return {"sent": True, "already_sent": True, "draft": as_dict(row)}
        raise ValueError("draft is already sent with a different message id")
    if row["status"] != "sending":
        raise ValueError("draft must be claimed before it can be marked sent")
    connection.execute(
        "UPDATE draft SET status = 'sent', external_message_id = ?, updated_at = ? WHERE id = ?",
        (message_id, now(), draft_id),
    )
    connection.commit()
    return {"sent": True, "already_sent": False, "draft": as_dict(resolve(connection, draft_id))}


def mark_uncertain(connection: sqlite3.Connection, draft_id: int, note: str) -> dict[str, object]:
    row = resolve(connection, draft_id)
    if row["status"] not in {"sending", "uncertain"}:
        raise ValueError("only a sending draft can become uncertain")
    connection.execute(
        "UPDATE draft SET status = 'uncertain', verification_note = ?, updated_at = ? WHERE id = ?",
        (required_text(note, "note"), now(), draft_id),
    )
    connection.commit()
    return {"uncertain": True, "draft": as_dict(resolve(connection, draft_id))}


def list_drafts(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    clauses: list[str] = []
    values: list[object] = []
    if args.channel:
        if args.channel not in HISTORICAL_CHANNELS:
            raise ValueError(f"channel must be one of: {', '.join(HISTORICAL_CHANNELS)}")
        clauses.append("channel = ?")
        values.append(args.channel)
    if args.status:
        if args.status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
        clauses.append("status = ?")
        values.append(args.status)
    query = "SELECT * FROM draft"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC, id DESC"
    items = [as_dict(row) for row in connection.execute(query, values)]
    return {"count": len(items), "drafts": items}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Agent communication draft ledger")
    parser.add_argument("--db", help="SQLite path; defaults to FOUNDER_DRAFTS_DB or HERMES_HOME")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--channel", required=True, choices=HISTORICAL_CHANNELS)
    prepare.add_argument("--thread-id", required=True)
    prepare.add_argument("--recipient", required=True)
    prepare.add_argument("--subject")
    prepare.add_argument("--body", required=True)
    prepare.add_argument("--idempotency-key")

    approve = subparsers.add_parser("approve")
    approve.add_argument("--id", required=True, type=int)

    revise = subparsers.add_parser("revise")
    revise.add_argument("--id", required=True, type=int)
    revise.add_argument("--thread-id")
    revise.add_argument("--recipient")
    revise.add_argument("--subject")
    revise.add_argument("--body")
    revise.add_argument("--idempotency-key")

    claim = subparsers.add_parser("claim-send")
    claim.add_argument("--id", required=True, type=int)

    sent = subparsers.add_parser("mark-sent")
    sent.add_argument("--id", required=True, type=int)
    sent.add_argument("--message-id", required=True)

    uncertain = subparsers.add_parser("mark-uncertain")
    uncertain.add_argument("--id", required=True, type=int)
    uncertain.add_argument("--note", required=True)

    listing = subparsers.add_parser("list")
    listing.add_argument("--channel", choices=HISTORICAL_CHANNELS)
    listing.add_argument("--status", choices=STATUSES)
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.db:
        os.environ["FOUNDER_DRAFTS_DB"] = args.db
    connection = connect(default_database_path())
    try:
        if args.operation == "prepare":
            return prepare_draft(connection, args)
        if args.operation == "approve":
            return approve_draft(connection, args.id)
        if args.operation == "revise":
            return revise_draft(connection, args)
        if args.operation == "claim-send":
            return claim_send(connection, args.id)
        if args.operation == "mark-sent":
            return mark_sent(connection, args.id, args.message_id)
        if args.operation == "mark-uncertain":
            return mark_uncertain(connection, args.id, args.note)
        if args.operation == "list":
            return list_drafts(connection, args)
        raise ValueError(f"unknown operation: {args.operation}")
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
