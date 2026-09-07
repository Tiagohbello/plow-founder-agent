#!/usr/bin/env python3
"""Idempotent ledger for calendar and product operations through Latch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


SCOPES = ("calendar", "product")
POLICIES = ("autonomous", "approval", "forbidden")
STATUSES = ("pending", "approved", "executing", "completed", "uncertain", "cancelled")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def required(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def database_path() -> Path:
    configured = os.environ.get("FOUNDER_OPERATIONS_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "external-operations" / "operations.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS external_operation (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL CHECK (scope IN ('calendar','product')),
            target TEXT NOT NULL,
            operation TEXT NOT NULL,
            intent TEXT NOT NULL,
            policy TEXT NOT NULL CHECK (policy IN ('autonomous','approval','forbidden')),
            status TEXT NOT NULL CHECK (status IN
                ('pending','approved','executing','completed','uncertain','cancelled')),
            idempotency_key TEXT NOT NULL UNIQUE,
            external_ref TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS external_operation_status_idx
            ON external_operation(status, updated_at);
        """
    )
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def as_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def resolve(connection: sqlite3.Connection, operation_id: int) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM external_operation WHERE id=?", (operation_id,)).fetchone()
    if row is None:
        raise ValueError("operation not found")
    return row


def derive_key(scope: str, target: str, operation: str, intent: str) -> str:
    value = "\x1f".join((scope, target, operation, intent))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.policy == "forbidden":
        raise ValueError("operation is forbidden by Founder Profile")
    target = required(args.target, "target")
    operation = required(args.external_operation, "external_operation")
    intent = required(args.intent, "intent")
    key = args.idempotency_key or derive_key(args.scope, target, operation, intent)
    existing = connection.execute("SELECT * FROM external_operation WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        return {"created": False, "duplicate": True, "operation": as_dict(existing)}
    status = "approved" if args.policy == "autonomous" else "pending"
    timestamp = now()
    cursor = connection.execute(
        """INSERT INTO external_operation(scope,target,operation,intent,policy,status,idempotency_key,
                                            created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (args.scope, target, operation, intent, args.policy, status, key, timestamp, timestamp),
    )
    connection.commit()
    return {"created": True, "duplicate": False, "approval_required": status == "pending",
            "operation": as_dict(resolve(connection, cursor.lastrowid))}


def approve(connection: sqlite3.Connection, operation_id: int) -> dict:
    row = resolve(connection, operation_id)
    if row["status"] == "approved":
        return {"approved": True, "already_approved": True, "operation": as_dict(row)}
    if row["status"] != "pending":
        raise ValueError(f"operation cannot be approved from status {row['status']}")
    connection.execute("UPDATE external_operation SET status='approved',updated_at=? WHERE id=?", (now(), operation_id))
    connection.commit()
    return {"approved": True, "already_approved": False, "operation": as_dict(resolve(connection, operation_id))}


def claim(connection: sqlite3.Connection, operation_id: int) -> dict:
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = resolve(connection, operation_id)
        if row["status"] == "completed":
            connection.rollback()
            return {"claimed": False, "already_completed": True, "operation": as_dict(row)}
        if row["status"] in {"executing", "uncertain"}:
            connection.rollback()
            return {"claimed": False, "reconciliation_required": True, "operation": as_dict(row)}
        if row["status"] != "approved":
            connection.rollback()
            raise ValueError("operation must be approved before execution")
        connection.execute("UPDATE external_operation SET status='executing',updated_at=? WHERE id=?", (now(), operation_id))
        connection.commit()
        return {"claimed": True, "operation": as_dict(resolve(connection, operation_id))}
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def finish(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    row = resolve(connection, args.id)
    if row["status"] != "executing":
        raise ValueError("only an executing operation can be finished")
    connection.execute(
        "UPDATE external_operation SET status=?,external_ref=?,evidence=?,updated_at=? WHERE id=?",
        (args.outcome, (args.external_ref or "").strip(), required(args.evidence, "evidence"), now(), args.id),
    )
    connection.commit()
    return {"finished": True, "operation": as_dict(resolve(connection, args.id))}


def reconcile(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    row = resolve(connection, args.id)
    if row["status"] != "uncertain":
        raise ValueError("only an uncertain operation can be reconciled")
    connection.execute(
        "UPDATE external_operation SET status=?,external_ref=?,evidence=?,updated_at=? WHERE id=?",
        (args.outcome, (args.external_ref or "").strip(), required(args.evidence, "evidence"), now(), args.id),
    )
    connection.commit()
    return {"reconciled": True, "operation": as_dict(resolve(connection, args.id))}


def listing(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    query = "SELECT * FROM external_operation"
    values: list[str] = []
    if args.status:
        query += " WHERE status=?"; values.append(args.status)
    query += " ORDER BY updated_at DESC,id DESC"
    items = [as_dict(row) for row in connection.execute(query, values)]
    return {"count": len(items), "operations": items}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Founder Agent external operation ledger")
    root.add_argument("--db")
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--scope", required=True, choices=SCOPES); create.add_argument("--target", required=True)
    create.add_argument("--operation", dest="external_operation", required=True); create.add_argument("--intent", required=True)
    create.add_argument("--policy", required=True, choices=POLICIES); create.add_argument("--idempotency-key")
    approval = commands.add_parser("approve"); approval.add_argument("--id", required=True, type=int)
    execution = commands.add_parser("claim"); execution.add_argument("--id", required=True, type=int)
    done = commands.add_parser("finish"); done.add_argument("--id", required=True, type=int)
    done.add_argument("--outcome", required=True, choices=("completed", "uncertain")); done.add_argument("--external-ref"); done.add_argument("--evidence", required=True)
    repaired = commands.add_parser("reconcile"); repaired.add_argument("--id", required=True, type=int)
    repaired.add_argument("--outcome", required=True, choices=("completed", "cancelled")); repaired.add_argument("--external-ref"); repaired.add_argument("--evidence", required=True)
    items = commands.add_parser("list"); items.add_argument("--status", choices=STATUSES)
    return root


def run(args: argparse.Namespace) -> dict:
    connection = connect(Path(args.db).expanduser() if args.db else database_path())
    try:
        if args.command == "prepare": return prepare(connection, args)
        if args.command == "approve": return approve(connection, args.id)
        if args.command == "claim": return claim(connection, args.id)
        if args.command == "finish": return finish(connection, args)
        if args.command == "reconcile": return reconcile(connection, args)
        if args.command == "list": return listing(connection, args)
        raise ValueError(f"unknown command: {args.command}")
    finally:
        connection.close()


def main(argv=None) -> int:
    try:
        result = run(parser().parse_args(argv))
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
