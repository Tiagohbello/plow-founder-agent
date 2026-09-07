#!/usr/bin/env python3
"""Persistent, deliberately small Founder Queue store."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


STATUSES = ("watching", "ready", "needs_founder", "working", "done")
PRIORITIES = ("low", "medium", "high", "urgent")
PRIORITY_ORDER = {"urgent": 4, "high": 3, "medium": 2, "low": 1}
ACTIVE_STATUSES = ("watching", "ready", "needs_founder", "working")
ACTION_KINDS = ("implement", "communicate", "investigate", "review", "other")


def default_database_path() -> Path:
    configured = os.environ.get("FOUNDER_QUEUE_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "founder-queue" / "queue.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def required_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def validate_status(value: str) -> str:
    if value not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    return value


def validate_priority(value: str) -> str:
    if value not in PRIORITIES:
        raise ValueError(f"priority must be one of: {', '.join(PRIORITIES)}")
    return value


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
        CREATE TABLE IF NOT EXISTS queue_item (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN
                ('low', 'medium', 'high', 'urgent')),
            status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN
                ('watching', 'ready', 'needs_founder', 'working', 'done')),
            can_agent_handle INTEGER NOT NULL DEFAULT 0 CHECK (can_agent_handle IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS queue_status_idx ON queue_item(status);
        CREATE INDEX IF NOT EXISTS queue_priority_idx ON queue_item(priority);
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(queue_item)")}
    additions = {
        "source_kind": "TEXT NOT NULL DEFAULT 'legacy'",
        "source_ref": "TEXT NOT NULL DEFAULT ''",
        "memory_id": "INTEGER",
        "evidence": "TEXT NOT NULL DEFAULT ''",
        "artifact_kind": "TEXT NOT NULL DEFAULT ''",
        "artifact_ref": "TEXT NOT NULL DEFAULT ''",
        "action_kind": "TEXT NOT NULL DEFAULT 'other'",
        "estimated_minutes": "INTEGER",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE queue_item ADD COLUMN {name} {declaration}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS queue_source_ref_idx "
        "ON queue_item(source_kind, source_ref) WHERE source_ref != ''"
    )
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def as_dict(row: sqlite3.Row) -> dict[str, object]:
    item = {key: row[key] for key in row.keys()}
    item["can_agent_handle"] = bool(item["can_agent_handle"])
    return item


def resolve_one(
    connection: sqlite3.Connection,
    *,
    item_id: int | None,
    title: str | None,
) -> sqlite3.Row:
    if item_id is None and title is None:
        raise ValueError("provide --id or --lookup-title")
    if item_id is not None:
        row = connection.execute("SELECT * FROM queue_item WHERE id = ?", (item_id,)).fetchone()
    else:
        matches = list(connection.execute("SELECT * FROM queue_item ORDER BY id"))
        matches = [row for row in matches if normalized(row["title"]) == normalized(title or "")]
        if len(matches) > 1:
            raise ValueError("queue item is ambiguous; use --id")
        row = matches[0] if matches else None
    if row is None:
        raise ValueError("queue item not found")
    return row


def add_record(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    title = required_text(args.title, "title")
    context = (args.context or "").strip()
    priority = validate_priority(args.priority)
    status = validate_status(args.status)
    can_agent_handle = bool(args.can_agent_handle)
    source_kind = args.source_kind
    source_ref = (args.source_ref or "").strip()
    if source_ref:
        row = connection.execute(
            "SELECT * FROM queue_item WHERE source_kind = ? AND source_ref = ?",
            (source_kind, source_ref),
        ).fetchone()
        if row is not None:
            return {"created": False, "duplicate": True, "item": as_dict(row)}

    # Same normalized title is an obvious duplicate. Updating the existing item
    # is an explicit operation, so repeated observations do not grow the queue.
    existing = list(connection.execute("SELECT * FROM queue_item ORDER BY id"))
    for row in existing:
        if normalized(row["title"]) == normalized(title):
            return {"created": False, "duplicate": True, "item": as_dict(row)}

    timestamp = now()
    cursor = connection.execute(
        """
        INSERT INTO queue_item(title, context, priority, status, can_agent_handle,
                               created_at, updated_at, source_kind, source_ref,
                               memory_id, evidence, artifact_kind, artifact_ref,
                               action_kind, estimated_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (title, context, priority, status, int(can_agent_handle), timestamp, timestamp,
         source_kind, source_ref, args.memory_id, (args.evidence or "").strip(),
         (args.artifact_kind or "").strip(), (args.artifact_ref or "").strip(),
         args.action_kind, args.estimated_minutes),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM queue_item WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"created": True, "duplicate": False, "item": as_dict(row)}


def update_record(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    row = resolve_one(connection, item_id=args.id, title=args.lookup_title)
    changes: dict[str, object] = {}
    if args.title is not None:
        changes["title"] = required_text(args.title, "title")
    if args.context is not None:
        changes["context"] = args.context.strip()
    if args.priority is not None:
        changes["priority"] = validate_priority(args.priority)
    if args.status is not None:
        changes["status"] = validate_status(args.status)
    if args.can_agent_handle is not None:
        changes["can_agent_handle"] = int(args.can_agent_handle)
    for name in ("source_kind", "action_kind"):
        value = getattr(args, name, None)
        if value is not None:
            changes[name] = value
    for name in ("source_ref", "evidence", "artifact_kind", "artifact_ref"):
        value = getattr(args, name, None)
        if value is not None:
            changes[name] = value.strip()
    for name in ("memory_id", "estimated_minutes"):
        value = getattr(args, name, None)
        if value is not None:
            changes[name] = value
    if not changes:
        raise ValueError("provide at least one field to change")

    new_title = str(changes.get("title", row["title"]))
    duplicate = list(connection.execute("SELECT * FROM queue_item WHERE id != ?", (row["id"],)))
    if any(normalized(candidate["title"]) == normalized(new_title) for candidate in duplicate):
        raise ValueError("update would create a duplicate queue item")

    changes["updated_at"] = now()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = list(changes.values()) + [row["id"]]
    connection.execute(f"UPDATE queue_item SET {assignments} WHERE id = ?", values)
    connection.commit()
    updated = connection.execute("SELECT * FROM queue_item WHERE id = ?", (row["id"],)).fetchone()
    return {"updated": True, "item": as_dict(updated)}


def ordered_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    status_order = {"needs_founder": 2, "working": 1, "ready": 0, "watching": -1, "done": -2}
    return sorted(
        rows,
        key=lambda row: (
            PRIORITY_ORDER[row["priority"]],
            status_order[row["status"]],
            row["updated_at"],
            row["id"],
        ),
        reverse=True,
    )


def list_records(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    clauses: list[str] = []
    values: list[object] = []
    if args.status is not None:
        clauses.append("status = ?")
        values.append(validate_status(args.status))
    elif not args.include_done:
        clauses.append("status != 'done'")
    if args.priority is not None:
        clauses.append("priority = ?")
        values.append(validate_priority(args.priority))
    sql = "SELECT * FROM queue_item"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = ordered_rows(list(connection.execute(sql, values)))
    return {"count": len(rows), "items": [as_dict(row) for row in rows]}


def search_records(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, object]:
    query = required_text(args.query, "query")
    terms = normalized(query).split()
    rows = list(connection.execute("SELECT * FROM queue_item WHERE status != 'done' ORDER BY id"))
    items = []
    for row in rows:
        haystack = normalized(f"{row['title']} {row['context']}")
        if all(term in haystack for term in terms):
            items.append(as_dict(row))
    return {"query": query, "count": len(items), "items": items}


def add_selector(parser: argparse.ArgumentParser) -> None:
    selector = parser.add_argument_group("item selector")
    selector.add_argument("--id", type=int)
    selector.add_argument("--lookup-title")


def add_mutation_fields(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--title", required=required)
    parser.add_argument("--context", default=None if not required else "")
    parser.add_argument("--priority", default="medium" if required else None, choices=PRIORITIES)
    parser.add_argument("--status", default="ready" if required else None, choices=STATUSES)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--can-agent-handle", dest="can_agent_handle", action="store_true")
    group.add_argument("--cannot-agent-handle", dest="can_agent_handle", action="store_false")
    parser.set_defaults(can_agent_handle=False if required else None)
    parser.add_argument("--source-kind", default="founder" if required else None)
    parser.add_argument("--source-ref")
    parser.add_argument("--memory-id", type=int)
    parser.add_argument("--evidence")
    parser.add_argument("--artifact-kind")
    parser.add_argument("--artifact-ref")
    parser.add_argument("--action-kind", default="other" if required else None, choices=ACTION_KINDS)
    parser.add_argument("--estimated-minutes", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Queue")
    parser.add_argument("--db", help="SQLite path; defaults to FOUNDER_QUEUE_DB or HERMES_HOME")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    add_parser = subparsers.add_parser("add", help="create a queue item")
    add_mutation_fields(add_parser, required=True)

    update_parser = subparsers.add_parser("update", help="change a queue item")
    add_selector(update_parser)
    add_mutation_fields(update_parser, required=False)

    list_parser = subparsers.add_parser("list", help="list queue items")
    list_parser.add_argument("--status", choices=STATUSES)
    list_parser.add_argument("--priority", choices=PRIORITIES)
    list_parser.add_argument("--include-done", action="store_true")

    search_parser = subparsers.add_parser("search", help="search active queue items")
    search_parser.add_argument("query")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.db:
        os.environ["FOUNDER_QUEUE_DB"] = args.db
    connection = connect(default_database_path())
    try:
        if args.operation == "add":
            return add_record(connection, args)
        if args.operation == "update":
            return update_record(connection, args)
        if args.operation == "list":
            return list_records(connection, args)
        if args.operation == "search":
            return search_records(connection, args)
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
