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
from monitor_guard import (
    add_column, add_monitor_column, add_pipeline_contact_key_column,
    bind_pipeline_contact, monitor_operation, require_direct_contact,
    resolve_direct_contact_key, validate_movable_block,
)


SCOPES = ("calendar", "product")
POLICIES = ("autonomous", "approval", "forbidden")
STATUSES = ("pending", "approved", "executing", "completed", "uncertain", "cancelled")
PERMANENTLY_FORBIDDEN = {
    "merge",
    "deploy",
    "move_money",
    "change_critical_credentials",
    "delete_production_data",
    "destructive_operation",
}
SCHEMA_VERSION = 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def required(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def migrate_legacy(connection: sqlite3.Connection, path: Path) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS founder_agent_migration "
        "(component TEXT PRIMARY KEY, migrated_at TEXT NOT NULL)"
    )
    if connection.execute(
        "SELECT 1 FROM founder_agent_migration WHERE component='operations'"
    ).fetchone():
        return
    legacy = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes")) / "external-operations" / "operations.db"
    empty = not connection.execute("SELECT 1 FROM external_operation LIMIT 1").fetchone()
    if legacy.is_file() and legacy.resolve() != path.resolve() and empty:
        columns = (
            "id,scope,target,operation,intent,policy,status,idempotency_key,"
            "external_ref,evidence,created_at,updated_at"
        )
        connection.execute("ATTACH DATABASE ? AS legacy_operations", (str(legacy),))
        connection.execute(
            f"INSERT OR IGNORE INTO external_operation ({columns}) "
            f"SELECT {columns} FROM legacy_operations.external_operation"
        )
        connection.commit()
        connection.execute("DETACH DATABASE legacy_operations")
    connection.execute(
        "INSERT INTO founder_agent_migration(component,migrated_at) VALUES ('operations',?)",
        (now(),),
    )


def add_access_name_column(connection: sqlite3.Connection) -> None:
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS founder_agent_migration "
            "(component TEXT PRIMARY KEY, migrated_at TEXT NOT NULL)"
        )
        add_column(connection, "external_operation", "access_name", "TEXT")
        connection.execute(
            """UPDATE external_operation
               SET status='cancelled',
                   idempotency_key='cancelled:legacy-no-access:' || id || ':' || idempotency_key,
                   updated_at=?
               WHERE scope='product' AND access_name IS NULL
                 AND status IN ('pending','approved')""",
            (now(),),
        )
        connection.execute(
            """INSERT OR IGNORE INTO founder_agent_migration(component,migrated_at)
               VALUES ('operations-access-name-v3',?)""",
            (now(),),
        )


def database_path() -> Path:
    configured = os.environ.get("FOUNDER_OPERATIONS_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "founder-agent" / "founder-agent.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    current_schema = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_schema > SCHEMA_VERSION:
        raise sqlite3.Error(
            f"operations schema {current_schema} is newer than supported {SCHEMA_VERSION}"
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS external_operation (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL CHECK (scope IN ('calendar','product')),
            target TEXT NOT NULL,
            operation TEXT NOT NULL,
            intent TEXT NOT NULL,
            access_name TEXT,
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
    migrate_legacy(connection, path)
    add_access_name_column(connection)
    add_monitor_column(connection, "external_operation")
    add_pipeline_contact_key_column(connection, "external_operation")
    # Keep the shared compatibility version at 1 so the previous image can use
    # this volume; component changes use founder_agent_migration markers.
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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


def resolve_policy(connection: sqlite3.Connection, scope: str, operation: str,
                   access_name: str | None) -> str:
    normalized_operation = operation.strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized_operation in PERMANENTLY_FORBIDDEN:
        return "forbidden"
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if scope == "calendar" and "permission" in tables:
        row = connection.execute(
            "SELECT policy FROM permission WHERE capability='calendar_manage'"
        ).fetchone()
        return row["policy"] if row else "approval"
    if scope == "product":
        if not access_name:
            raise ValueError("product operations require a configured --access-name")
        if not {"product_access", "product_access_policy"}.issubset(tables):
            raise ValueError("product access profile is not configured")
        access = connection.execute(
            "SELECT active,status FROM product_access WHERE name=?",
            (access_name.strip(),),
        ).fetchone()
        if access is None:
            raise ValueError("configured product access not found")
        if not access["active"]:
            raise ValueError("configured product access is inactive")
        if access["status"] != "available":
            raise ValueError(f"configured product access is {access['status']}")
        row = connection.execute(
            """SELECT p.policy FROM product_access_policy p
               JOIN product_access a ON a.id=p.access_id
               WHERE a.name=? AND a.active=1 AND p.operation=?""",
            (access_name.strip(), operation.strip()),
        ).fetchone()
        return row["policy"] if row else "approval"
    return "approval"


def prepare(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    monitor_id = getattr(args, "suggestion_id", None)
    supplied_contact_key = getattr(args, "contact_key", None)
    if monitor_id is not None and supplied_contact_key is not None:
        raise ValueError("--contact-key cannot be combined with --suggestion-id")
    monitor_plan = monitor_operation(connection, monitor_id, args.scope)
    if monitor_id is not None:
        target, operation, intent = (monitor_plan["entry"][key]
                                     for key in ("target", "operation", "intent"))
        contact_key = None
    else:
        target = required(args.target, "target")
        operation = required(args.external_operation, "external_operation")
        intent = required(args.intent, "intent")
        contact_key = resolve_direct_contact_key(
            connection, supplied_contact_key, (target,), (intent,)
        )
    if monitor_id is None:
        validate_movable_block(connection, args.scope, target, operation, intent)
    access_name = (
        required(args.access_name, "access_name")
        if args.scope == "product"
        else (args.access_name or "").strip() or None
    )
    policy = resolve_policy(connection, args.scope, operation, access_name)
    if policy == "forbidden":
        raise ValueError("operation is forbidden by Founder Profile or global policy")
    if args.scope == "calendar":
        policy = "approval"
    if monitor_id is not None:
        policy = "autonomous" if monitor_plan["automatic_hold"] else "approval"
    key = args.idempotency_key or derive_key(args.scope, target, operation, intent)
    if monitor_id is not None:
        key = f"monitor:{monitor_id}:{derive_key(args.scope, target, operation, intent)}"
    existing = connection.execute("SELECT * FROM external_operation WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        if args.scope == "product" and existing["access_name"] != access_name:
            raise ValueError("product operation already exists with a different access name; reconcile or use a fresh idempotency key")
        existing = bind_pipeline_contact(connection, "external_operation", existing, contact_key)
        connection.commit()
        return {"created": False, "duplicate": True, "operation": as_dict(existing)}
    status = "approved" if policy == "autonomous" else "pending"
    timestamp = now()
    cursor = connection.execute(
        """INSERT INTO external_operation(scope,target,operation,intent,access_name,policy,status,
                                            idempotency_key,created_at,updated_at,monitor_suggestion_id,
                                            pipeline_contact_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (args.scope, target, operation, intent, access_name, policy, status, key, timestamp,
         timestamp, monitor_id, contact_key),
    )
    connection.commit()
    return {"created": True, "duplicate": False, "approval_required": status == "pending",
            "operation": as_dict(resolve(connection, cursor.lastrowid))}


def approve(connection: sqlite3.Connection, operation_id: int) -> dict:
    row = resolve(connection, operation_id)
    if row["monitor_suggestion_id"] is None:
        validate_movable_block(connection, row["scope"], row["target"], row["operation"], row["intent"])
        require_direct_contact(connection, row["pipeline_contact_key"],
                               (row["target"],), (row["intent"],))
    monitor_operation(connection, row["monitor_suggestion_id"], row["scope"], row["target"],
                      row["operation"], row["intent"], approved=True)
    if row["status"] == "approved":
        if row["scope"] == "product" and row["policy"] == "autonomous":
            connection.execute(
                "UPDATE external_operation SET policy='approval',updated_at=? WHERE id=?",
                (now(), operation_id),
            )
            connection.commit()
            return {"approved": True, "already_approved": False, "operation": as_dict(resolve(connection, operation_id))}
        return {"approved": True, "already_approved": True, "operation": as_dict(row)}
    if row["status"] != "pending":
        raise ValueError(f"operation cannot be approved from status {row['status']}")
    connection.execute("UPDATE external_operation SET status='approved',updated_at=? WHERE id=?", (now(), operation_id))
    connection.commit()
    return {"approved": True, "already_approved": False, "operation": as_dict(resolve(connection, operation_id))}


def claim(connection: sqlite3.Connection, operation_id: int, current_event_json: str | None = None) -> dict:
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = resolve(connection, operation_id)
        if row["status"] == "completed":
            connection.rollback()
            return {"claimed": False, "already_completed": True, "operation": as_dict(row)}
        if row["monitor_suggestion_id"] is None:
            validate_movable_block(
                connection, row["scope"], row["target"], row["operation"], row["intent"],
                current_event=current_event_json, require_current=row["status"] == "approved",
            )
            require_direct_contact(connection, row["pipeline_contact_key"],
                                   (row["target"],), (row["intent"],))
        monitor_operation(connection, row["monitor_suggestion_id"], row["scope"], row["target"],
                          row["operation"], row["intent"], approved=True)
        if row["status"] in {"executing", "uncertain"}:
            connection.rollback()
            return {"claimed": False, "reconciliation_required": True, "operation": as_dict(row)}
        current_policy = resolve_policy(
            connection, row["scope"], row["operation"], row["access_name"]
        )
        if current_policy == "forbidden":
            raise ValueError("operation is forbidden by Founder Profile or global policy")
        if row["scope"] == "product" and row["policy"] == "autonomous" \
                and current_policy != "autonomous":
            raise ValueError("product operation now requires founder approval under current policy")
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


def require_completion_ref(row, outcome, external_ref):
    monitor_create = (row["scope"] == "calendar" and row["operation"] == "create"
                      and row["monitor_suggestion_id"] is not None)
    if (outcome == "completed" and monitor_create
            and not (external_ref or "").strip()):
        raise ValueError("completed monitor calendar create requires its verified provider event id")


def finish(connection: sqlite3.Connection, args: argparse.Namespace) -> dict:
    row = resolve(connection, args.id)
    if row["status"] != "executing":
        raise ValueError("only an executing operation can be finished")
    require_completion_ref(row, args.outcome, args.external_ref)
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
    require_completion_ref(row, args.outcome, args.external_ref)
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
    create.add_argument("--scope", required=True, choices=SCOPES); create.add_argument("--target")
    create.add_argument("--operation", dest="external_operation"); create.add_argument("--intent")
    create.add_argument("--access-name"); create.add_argument("--idempotency-key")
    create.add_argument("--suggestion-id", type=int, help="Required for actions originating in a monitor suggestion")
    create.add_argument("--contact-key", help="Pipeline contact context for direct operations")
    approval = commands.add_parser("approve"); approval.add_argument("--id", required=True, type=int)
    execution = commands.add_parser("claim"); execution.add_argument("--id", required=True, type=int)
    execution.add_argument(
        "--current-event-json",
        help="fresh move_block provider snapshot JSON, including checked_at, captured within 30 seconds",
    )
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
        if args.command == "claim": return claim(connection, args.id, args.current_event_json)
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
