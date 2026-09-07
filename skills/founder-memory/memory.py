#!/usr/bin/env python3
"""Small, dependency-free persistent store for Founder Agent company memory."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


MEMORY_TYPES = (
    "customer",
    "feature",
    "decision",
    "goal",
    "commitment",
    "risk",
    "note",
)
STATUSES = ("active", "deferred", "completed", "archived")
PRIORITIES = ("low", "medium", "high", "urgent")
SOURCE_KINDS = ("founder", "gmail", "github", "sentry", "whatsapp", "repo", "legacy")
CONFIDENCE_LEVELS = ("fact", "inference")


def default_database_path() -> Path:
    configured = os.environ.get("FOUNDER_MEMORY_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "founder-memory" / "memory.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


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
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN
                ('customer', 'feature', 'decision', 'goal', 'commitment', 'risk', 'note')),
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN
                ('low', 'medium', 'high', 'urgent')),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                ('active', 'deferred', 'completed', 'archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS memory_subject_idx ON memory(subject);
        CREATE INDEX IF NOT EXISTS memory_status_idx ON memory(status);
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(memory)")}
    additions = {
        "source_kind": "TEXT NOT NULL DEFAULT 'legacy'",
        "source_ref": "TEXT NOT NULL DEFAULT ''",
        "observed_at": "TEXT NOT NULL DEFAULT ''",
        "evidence": "TEXT NOT NULL DEFAULT ''",
        "confidence": "TEXT NOT NULL DEFAULT 'fact'",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE memory ADD COLUMN {name} {declaration}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS memory_source_ref_idx "
        "ON memory(source_kind, source_ref) WHERE source_ref != ''"
    )
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def as_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def validate_type(value: str) -> str:
    if value not in MEMORY_TYPES:
        raise ValueError(f"type must be one of: {', '.join(MEMORY_TYPES)}")
    return value


def validate_status(value: str) -> str:
    if value not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    return value


def validate_priority(value: str) -> str:
    if value not in PRIORITIES:
        raise ValueError(f"priority must be one of: {', '.join(PRIORITIES)}")
    return value


def matching_rows(
    connection: sqlite3.Connection,
    *,
    record_id: int | None = None,
    subject: str | None = None,
    record_type: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    values: list[object] = []
    if record_id is not None:
        clauses.append("id = ?")
        values.append(record_id)
    if record_type is not None:
        clauses.append("type = ?")
        values.append(record_type)
    query = "SELECT * FROM memory"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"
    rows = list(connection.execute(query, values))
    if subject is not None:
        subject_key = normalized(subject)
        rows = [row for row in rows if normalized(row["subject"]) == subject_key]
    return rows


def resolve_one(
    connection: sqlite3.Connection,
    *,
    record_id: int | None,
    subject: str | None,
    record_type: str | None,
) -> sqlite3.Row:
    if record_id is None and subject is None:
        raise ValueError("provide --id or --lookup-subject")
    rows = matching_rows(
        connection, record_id=record_id, subject=subject, record_type=record_type
    )
    if not rows:
        raise ValueError("memory item not found")
    if len(rows) > 1:
        raise ValueError("memory item is ambiguous; use --id")
    return rows[0]


def add_record(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    record_type = validate_type(args.type)
    subject = required_text(args.subject, "subject")
    content = required_text(args.content, "content")
    priority = validate_priority(args.priority)
    status = validate_status(args.status)
    source_kind = args.source_kind
    source_ref = (args.source_ref or "").strip()
    observed_at = (args.observed_at or now()).strip()
    evidence = (args.evidence or "").strip()
    confidence = args.confidence

    if source_ref:
        existing = connection.execute(
            "SELECT * FROM memory WHERE source_kind = ? AND source_ref = ?",
            (source_kind, source_ref),
        ).fetchone()
        if existing is not None:
            return {"created": False, "duplicate": True, "record": as_dict(existing)}

    candidates = connection.execute(
        "SELECT * FROM memory WHERE type = ? ORDER BY id", (record_type,)
    )
    for row in candidates:
        if normalized(row["subject"]) == normalized(subject) and normalized(
            row["content"]
        ) == normalized(content):
            return {"created": False, "duplicate": True, "record": as_dict(row)}

    timestamp = now()
    cursor = connection.execute(
        """
        INSERT INTO memory(type, subject, content, priority, status, created_at, updated_at,
                           source_kind, source_ref, observed_at, evidence, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_type, subject, content, priority, status, timestamp, timestamp,
         source_kind, source_ref, observed_at, evidence, confidence),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM memory WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return {"created": True, "duplicate": False, "record": as_dict(row)}


def update_record(
    connection: sqlite3.Connection, args: argparse.Namespace, operation: str
) -> dict:
    record = resolve_one(
        connection,
        record_id=args.id,
        subject=args.lookup_subject,
        record_type=args.lookup_type,
    )
    changes: dict[str, str] = {}
    if args.type is not None:
        changes["type"] = validate_type(args.type)
    if args.subject is not None:
        changes["subject"] = required_text(args.subject, "subject")
    if args.content is not None:
        changes["content"] = required_text(args.content, "content")
    if args.priority is not None:
        changes["priority"] = validate_priority(args.priority)
    if args.status is not None:
        changes["status"] = validate_status(args.status)
    if getattr(args, "source_kind", None) is not None:
        changes["source_kind"] = args.source_kind
    if getattr(args, "source_ref", None) is not None:
        changes["source_ref"] = args.source_ref.strip()
    if getattr(args, "observed_at", None) is not None:
        changes["observed_at"] = args.observed_at.strip()
    if getattr(args, "evidence", None) is not None:
        changes["evidence"] = args.evidence.strip()
    if getattr(args, "confidence", None) is not None:
        changes["confidence"] = args.confidence
    if not changes:
        raise ValueError("provide at least one field to change")

    new_type = changes.get("type", record["type"])
    new_subject = changes.get("subject", record["subject"])
    new_content = changes.get("content", record["content"])
    duplicate = connection.execute(
        "SELECT * FROM memory WHERE type = ? AND id != ? ORDER BY id",
        (new_type, record["id"]),
    )
    for candidate in duplicate:
        if normalized(candidate["subject"]) == normalized(new_subject) and normalized(
            candidate["content"]
        ) == normalized(new_content):
            raise ValueError("update would create a duplicate memory item")

    changes["updated_at"] = now()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = list(changes.values()) + [record["id"]]
    connection.execute(f"UPDATE memory SET {assignments} WHERE id = ?", values)
    connection.commit()
    updated = connection.execute(
        "SELECT * FROM memory WHERE id = ?", (record["id"],)
    ).fetchone()
    return {"updated": True, "operation": operation, "record": as_dict(updated)}


def search_records(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    query = required_text(args.query, "query")
    clauses: list[str] = []
    values: list[object] = []
    if args.type is not None:
        clauses.append("type = ?")
        values.append(validate_type(args.type))
    if args.status is not None:
        clauses.append("status = ?")
        values.append(validate_status(args.status))
    if not args.include_archived:
        clauses.append("status != 'archived'")
    sql = "SELECT * FROM memory"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC, id DESC"
    terms = normalized(query).split()
    items = []
    for row in connection.execute(sql, values):
        haystack = normalized(f"{row['subject']} {row['content']} {row['evidence']}")
        if all(term in haystack for term in terms):
            items.append(as_dict(row))
    return {"query": query, "count": len(items), "items": items}


def list_records(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    clauses: list[str] = []
    values: list[object] = []
    if args.type is not None:
        clauses.append("type = ?")
        values.append(validate_type(args.type))
    if args.status is not None:
        clauses.append("status = ?")
        values.append(validate_status(args.status))
    if args.priority is not None:
        clauses.append("priority = ?")
        values.append(validate_priority(args.priority))
    if not args.include_archived:
        clauses.append("status != 'archived'")
    query = "SELECT * FROM memory"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC, id DESC"
    items = [as_dict(row) for row in connection.execute(query, values)]
    return {"count": len(items), "items": items}


def delete_record(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    record = resolve_one(
        connection,
        record_id=args.id,
        subject=args.lookup_subject,
        record_type=args.lookup_type,
    )
    connection.execute("DELETE FROM memory WHERE id = ?", (record["id"],))
    connection.commit()
    return {"deleted": True, "record": as_dict(record)}


def add_common_update_arguments(parser: argparse.ArgumentParser) -> None:
    selector = parser.add_argument_group("record selector")
    selector.add_argument("--id", type=int)
    selector.add_argument("--lookup-subject")
    selector.add_argument("--lookup-type", choices=MEMORY_TYPES)
    parser.add_argument("--type", choices=MEMORY_TYPES)
    parser.add_argument("--subject")
    parser.add_argument("--content")
    parser.add_argument("--priority", choices=PRIORITIES)
    parser.add_argument("--status", choices=STATUSES)
    parser.add_argument("--source-kind", choices=SOURCE_KINDS)
    parser.add_argument("--source-ref")
    parser.add_argument("--observed-at")
    parser.add_argument("--evidence")
    parser.add_argument("--confidence", choices=CONFIDENCE_LEVELS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Agent company memory")
    parser.add_argument(
        "--db", help="SQLite path; defaults to FOUNDER_MEMORY_DB or HERMES_HOME"
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    add_parser = subparsers.add_parser("add", help="create a memory item")
    add_parser.add_argument("--type", required=True, choices=MEMORY_TYPES)
    add_parser.add_argument("--subject", required=True)
    add_parser.add_argument("--content", required=True)
    add_parser.add_argument("--priority", default="medium", choices=PRIORITIES)
    add_parser.add_argument("--status", default="active", choices=STATUSES)
    add_parser.add_argument("--source-kind", default="founder", choices=SOURCE_KINDS)
    add_parser.add_argument("--source-ref")
    add_parser.add_argument("--observed-at")
    add_parser.add_argument("--evidence")
    add_parser.add_argument("--confidence", default="fact", choices=CONFIDENCE_LEVELS)

    for name, help_text in (
        ("update", "change a memory item"),
        ("correct", "correct remembered data"),
    ):
        update_parser = subparsers.add_parser(name, help=help_text)
        add_common_update_arguments(update_parser)

    search_parser = subparsers.add_parser("search", help="search subject and content")
    search_parser.add_argument("query")
    search_parser.add_argument("--type", choices=MEMORY_TYPES)
    search_parser.add_argument("--status", choices=STATUSES)
    search_parser.add_argument("--include-archived", action="store_true")

    list_parser = subparsers.add_parser("list", help="list memory items")
    list_parser.add_argument("--type", choices=MEMORY_TYPES)
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--priority", choices=PRIORITIES)
    list_parser.add_argument("--include-archived", action="store_true")

    delete_parser = subparsers.add_parser("delete", help="delete a memory item")
    delete_parser.add_argument("--id", type=int)
    delete_parser.add_argument("--lookup-subject")
    delete_parser.add_argument("--lookup-type", choices=MEMORY_TYPES)
    return parser


def run(args: argparse.Namespace) -> dict:
    if args.db:
        os.environ["FOUNDER_MEMORY_DB"] = args.db
    connection = connect(default_database_path())
    try:
        if args.operation == "add":
            return add_record(connection, args)
        if args.operation == "update":
            return update_record(connection, args, "update")
        if args.operation == "correct":
            return update_record(connection, args, "correct")
        if args.operation == "search":
            return search_records(connection, args)
        if args.operation == "list":
            return list_records(connection, args)
        if args.operation == "delete":
            return delete_record(connection, args)
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
