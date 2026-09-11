#!/usr/bin/env python3
"""Persistent company configuration, kept separate from remembered facts."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SOURCE_KINDS = ("gmail", "github", "sentry")
SOURCE_STATUSES = ("available", "blocked", "unconfigured")
POLICIES = ("autonomous", "approval", "forbidden")
ACCESS_KINDS = ("admin", "app")
DEFAULT_POLICIES = {
    "investigate": "autonomous",
    "prepare_code": "autonomous",
    "open_draft_pr": "autonomous",
    "send_communication": "approval",
    "calendar_manage": "approval",
    "merge": "forbidden",
    "deploy": "forbidden",
    "production_mutation": "forbidden",
    "destructive_operation": "forbidden",
}
PERMANENTLY_FORBIDDEN = {
    "merge",
    "deploy",
    "production_mutation",
    "destructive_operation",
}
SCHEMA_VERSION = 1


def database_path() -> Path:
    configured = os.environ.get("FOUNDER_PROFILE_DB")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
    return home / "founder-agent" / "founder-agent.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def json_object(value: str | None, name: str) -> str:
    if not value:
        return "{}"
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} must be a JSON object")
    return json.dumps(decoded, ensure_ascii=False, sort_keys=True)


def web_url(value: str | None) -> str:
    url = text(value, "url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("url must not contain credentials")
    return url


def migrate_legacy(connection: sqlite3.Connection, path: Path) -> None:
    """Import the former profile database once when the shared store is empty."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS founder_agent_migration "
        "(component TEXT PRIMARY KEY, migrated_at TEXT NOT NULL)"
    )
    if connection.execute(
        "SELECT 1 FROM founder_agent_migration WHERE component='profile'"
    ).fetchone():
        return
    legacy = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes")) / "founder-profile" / "profile.db"
    empty = not connection.execute("SELECT 1 FROM company LIMIT 1").fetchone()
    if legacy.is_file() and legacy.resolve() != path.resolve() and empty:
        connection.execute("ATTACH DATABASE ? AS legacy_profile", (str(legacy),))
        tables = {
            "company": "id,name,product,main_goal,updated_at",
            "repository": "id,local_path,remote_url,is_primary,updated_at",
            "source": "kind,status,locator,evidence,checked_at",
            "permission": "capability,policy,updated_at",
            "product_access": "id,name,kind,url,environment,credential_item_ref,status,evidence,active,checked_at,updated_at",
            "calendar_account": "account,calendar_ids,default_calendar,timezone,working_hours,preferences,status,evidence,is_default,active,checked_at,updated_at",
            "product_access_repository": "access_id,repository_id",
            "product_access_policy": "access_id,operation,policy,updated_at",
        }
        for table, columns in tables.items():
            connection.execute(
                f"INSERT OR IGNORE INTO {table} ({columns}) SELECT {columns} FROM legacy_profile.{table}"
            )
        connection.commit()
        connection.execute("DETACH DATABASE legacy_profile")
    connection.execute(
        "INSERT INTO founder_agent_migration(component,migrated_at) VALUES ('profile',?)",
        (now(),),
    )


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    current_schema = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_schema > SCHEMA_VERSION:
        raise sqlite3.Error(
            f"profile schema {current_schema} is newer than supported {SCHEMA_VERSION}"
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS company (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            product TEXT NOT NULL DEFAULT '',
            main_goal TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS repository (
            id INTEGER PRIMARY KEY,
            local_path TEXT NOT NULL UNIQUE,
            remote_url TEXT NOT NULL DEFAULT '',
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source (
            kind TEXT PRIMARY KEY CHECK (kind IN ('gmail','github','sentry','whatsapp')),
            status TEXT NOT NULL CHECK (status IN ('available','blocked','unconfigured')),
            locator TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            checked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permission (
            capability TEXT PRIMARY KEY,
            policy TEXT NOT NULL CHECK (policy IN ('autonomous','approval','forbidden')),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_access (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('admin','app')),
            url TEXT NOT NULL,
            environment TEXT NOT NULL,
            credential_item_ref TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK (status IN ('available','blocked','unconfigured')),
            evidence TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            checked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_access_repository (
            access_id INTEGER NOT NULL REFERENCES product_access(id),
            repository_id INTEGER NOT NULL REFERENCES repository(id),
            PRIMARY KEY(access_id, repository_id)
        );
        CREATE TABLE IF NOT EXISTS product_access_policy (
            access_id INTEGER NOT NULL REFERENCES product_access(id),
            operation TEXT NOT NULL,
            policy TEXT NOT NULL CHECK (policy IN ('autonomous','approval','forbidden')),
            updated_at TEXT NOT NULL,
            PRIMARY KEY(access_id, operation)
        );
        CREATE TABLE IF NOT EXISTS calendar_account (
            account TEXT PRIMARY KEY,
            calendar_ids TEXT NOT NULL DEFAULT '[]',
            default_calendar TEXT NOT NULL DEFAULT 'primary',
            timezone TEXT NOT NULL,
            working_hours TEXT NOT NULL DEFAULT '{}',
            preferences TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL CHECK (status IN ('available','blocked','unconfigured')),
            evidence TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
            checked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    migrate_legacy(connection, path)
    # Version 1 is the bootstrap schema. Future changes must bump
    # SCHEMA_VERSION, apply a guarded migration, then update user_version.
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    timestamp = now()
    for capability, policy in DEFAULT_POLICIES.items():
        connection.execute(
            "INSERT OR IGNORE INTO permission(capability, policy, updated_at) VALUES (?, ?, ?)",
            (capability, policy, timestamp),
        )
    connection.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return connection


def row_dict(row: sqlite3.Row | None):
    return dict(row) if row else None


def access_items(connection: sqlite3.Connection) -> list[dict]:
    items = []
    for row in connection.execute("SELECT * FROM product_access ORDER BY active DESC, kind, name"):
        item = dict(row)
        item["repositories"] = [
            value["local_path"]
            for value in connection.execute(
                """SELECT r.local_path FROM repository r
                   JOIN product_access_repository ar ON ar.repository_id=r.id
                   WHERE ar.access_id=? ORDER BY r.is_primary DESC, r.id""",
                (row["id"],),
            )
        ]
        item["policies"] = {
            value["operation"]: value["policy"]
            for value in connection.execute(
                "SELECT operation,policy FROM product_access_policy WHERE access_id=? ORDER BY operation",
                (row["id"],),
            )
        }
        items.append(item)
    return items


def calendar_items(connection: sqlite3.Connection) -> list[dict]:
    items = []
    for row in connection.execute("SELECT * FROM calendar_account ORDER BY is_default DESC, account"):
        item = dict(row)
        for field in ("calendar_ids", "working_hours", "preferences"):
            item[field] = json.loads(item[field])
        items.append(item)
    return items


def show(connection: sqlite3.Connection) -> dict:
    company = connection.execute("SELECT * FROM company WHERE id = 1").fetchone()
    repositories = [dict(row) for row in connection.execute("SELECT * FROM repository ORDER BY is_primary DESC, id")]
    sources = [dict(row) for row in connection.execute("SELECT * FROM source WHERE kind != 'whatsapp' ORDER BY kind")]
    permissions = [dict(row) for row in connection.execute("SELECT * FROM permission ORDER BY capability")]
    return {
        "configured": company is not None,
        "company": row_dict(company),
        "repositories": repositories,
        "sources": sources,
        "permissions": permissions,
        "product_accesses": access_items(connection),
        "calendars": calendar_items(connection),
    }


def require_access(connection: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM product_access WHERE name=?", (text(name, "name"),)).fetchone()
    if row is None:
        raise ValueError("product access not found")
    return row


def run(args: argparse.Namespace) -> dict:
    connection = connect(Path(args.db).expanduser() if args.db else database_path())
    try:
        timestamp = now()
        if args.operation == "show":
            return show(connection)
        if args.operation == "set-company":
            name = text(args.name, "name")
            connection.execute(
                """INSERT INTO company(id,name,product,main_goal,updated_at) VALUES (1,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,product=excluded.product,
                   main_goal=excluded.main_goal,updated_at=excluded.updated_at""",
                (name, (args.product or "").strip(), (args.main_goal or "").strip(), timestamp),
            )
        elif args.operation == "add-repo":
            local_path = text(args.local_path, "local_path")
            if args.primary:
                connection.execute("UPDATE repository SET is_primary=0")
            connection.execute(
                """INSERT INTO repository(local_path,remote_url,is_primary,updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(local_path) DO UPDATE SET remote_url=excluded.remote_url,
                   is_primary=excluded.is_primary,updated_at=excluded.updated_at""",
                (local_path, (args.remote_url or "").strip(), int(args.primary), timestamp),
            )
        elif args.operation == "set-source":
            connection.execute(
                """INSERT INTO source(kind,status,locator,evidence,checked_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(kind) DO UPDATE SET status=excluded.status,locator=excluded.locator,
                   evidence=excluded.evidence,checked_at=excluded.checked_at""",
                (args.kind, args.status, (args.locator or "").strip(), (args.evidence or "").strip(), timestamp),
            )
        elif args.operation == "set-permission":
            capability = text(args.capability, "capability")
            if capability in PERMANENTLY_FORBIDDEN and args.policy != "forbidden":
                raise ValueError(f"{capability} is permanently forbidden")
            connection.execute(
                """INSERT INTO permission(capability,policy,updated_at) VALUES (?,?,?)
                   ON CONFLICT(capability) DO UPDATE SET policy=excluded.policy,updated_at=excluded.updated_at""",
                (capability, args.policy, timestamp),
            )
        elif args.operation == "set-access":
            existing = connection.execute(
                "SELECT credential_item_ref FROM product_access WHERE name=?",
                (text(args.name, "name"),),
            ).fetchone()
            if args.credential_item_ref is not None and args.clear_credential_item_ref:
                raise ValueError("choose credential item reference or clear it, not both")
            credential_item_ref = (
                "" if args.clear_credential_item_ref
                else args.credential_item_ref.strip() if args.credential_item_ref is not None
                else existing["credential_item_ref"] if existing else ""
            )
            connection.execute(
                """INSERT INTO product_access(name,kind,url,environment,credential_item_ref,status,evidence,
                                                active,checked_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,url=excluded.url,
                   environment=excluded.environment,credential_item_ref=excluded.credential_item_ref,
                   status=excluded.status,evidence=excluded.evidence,active=1,
                   checked_at=excluded.checked_at,updated_at=excluded.updated_at""",
                (text(args.name, "name"), args.kind, web_url(args.url), text(args.environment, "environment"),
                 credential_item_ref, args.status, (args.evidence or "").strip(),
                 timestamp, timestamp),
            )
        elif args.operation == "deactivate-access":
            row = require_access(connection, args.name)
            connection.execute("UPDATE product_access SET active=0,updated_at=? WHERE id=?", (timestamp, row["id"]))
        elif args.operation == "link-access-repo":
            row = require_access(connection, args.name)
            repo = connection.execute("SELECT id FROM repository WHERE local_path=?", (text(args.local_path, "local_path"),)).fetchone()
            if repo is None:
                raise ValueError("repository not found; add it before linking")
            connection.execute(
                "INSERT OR IGNORE INTO product_access_repository(access_id,repository_id) VALUES (?,?)",
                (row["id"], repo["id"]),
            )
        elif args.operation == "set-access-policy":
            row = require_access(connection, args.name)
            connection.execute(
                """INSERT INTO product_access_policy(access_id,operation,policy,updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(access_id,operation) DO UPDATE SET policy=excluded.policy,updated_at=excluded.updated_at""",
                (row["id"], text(args.access_operation, "access_operation"), args.policy, timestamp),
            )
        elif args.operation == "set-calendar":
            existing = connection.execute("SELECT * FROM calendar_account WHERE account=?", (text(args.account, "account"),)).fetchone()
            default_calendar = args.default_calendar or (existing["default_calendar"] if existing else "primary")
            calendar_ids = args.calendar_id or (json.loads(existing["calendar_ids"]) if existing else [default_calendar])
            working_hours = json_object(args.working_hours, "working_hours") if args.working_hours is not None else (existing["working_hours"] if existing else "{}")
            preferences = json_object(args.preferences, "preferences") if args.preferences is not None else (existing["preferences"] if existing else "{}")
            is_default = int(args.is_default) if args.is_default is not None else (existing["is_default"] if existing else 0)
            if is_default:
                connection.execute("UPDATE calendar_account SET is_default=0")
            connection.execute(
                """INSERT INTO calendar_account(account,calendar_ids,default_calendar,timezone,working_hours,
                                                  preferences,status,evidence,is_default,active,checked_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(account) DO UPDATE SET calendar_ids=excluded.calendar_ids,
                   default_calendar=excluded.default_calendar,timezone=excluded.timezone,
                   working_hours=excluded.working_hours,preferences=excluded.preferences,
                   status=excluded.status,evidence=excluded.evidence,is_default=excluded.is_default,
                   active=1,checked_at=excluded.checked_at,updated_at=excluded.updated_at""",
                (text(args.account, "account"), json.dumps(calendar_ids, ensure_ascii=False),
                 default_calendar, text(args.timezone, "timezone"), working_hours, preferences,
                 args.status, (args.evidence or "").strip(), is_default, timestamp, timestamp),
            )
        elif args.operation == "deactivate-calendar":
            cursor = connection.execute(
                "UPDATE calendar_account SET active=0,is_default=0,updated_at=? WHERE account=?",
                (timestamp, text(args.account, "account")),
            )
            if cursor.rowcount == 0:
                raise ValueError("calendar account not found")
        else:
            raise ValueError(f"unknown operation: {args.operation}")
        connection.commit()
        return show(connection)
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Founder Agent company profile")
    root.add_argument("--db")
    commands = root.add_subparsers(dest="operation", required=True)
    commands.add_parser("show")
    company = commands.add_parser("set-company")
    company.add_argument("--name", required=True); company.add_argument("--product"); company.add_argument("--main-goal")
    repo = commands.add_parser("add-repo")
    repo.add_argument("--local-path", required=True); repo.add_argument("--remote-url"); repo.add_argument("--primary", action="store_true")
    source = commands.add_parser("set-source")
    source.add_argument("--kind", required=True, choices=SOURCE_KINDS); source.add_argument("--status", required=True, choices=SOURCE_STATUSES)
    source.add_argument("--locator"); source.add_argument("--evidence")
    permission = commands.add_parser("set-permission")
    permission.add_argument("--capability", required=True, choices=tuple(DEFAULT_POLICIES)); permission.add_argument("--policy", required=True, choices=POLICIES)
    access = commands.add_parser("set-access")
    access.add_argument("--name", required=True); access.add_argument("--kind", required=True, choices=ACCESS_KINDS)
    access.add_argument("--url", required=True); access.add_argument("--environment", required=True)
    access.add_argument("--credential-item-ref"); access.add_argument("--clear-credential-item-ref", action="store_true")
    access.add_argument("--status", required=True, choices=SOURCE_STATUSES)
    access.add_argument("--evidence")
    deactivate = commands.add_parser("deactivate-access"); deactivate.add_argument("--name", required=True)
    link = commands.add_parser("link-access-repo"); link.add_argument("--name", required=True); link.add_argument("--local-path", required=True)
    access_policy = commands.add_parser("set-access-policy")
    access_policy.add_argument("--name", required=True); access_policy.add_argument("--access-operation", required=True)
    access_policy.add_argument("--policy", required=True, choices=POLICIES)
    calendar = commands.add_parser("set-calendar")
    calendar.add_argument("--account", required=True); calendar.add_argument("--calendar-id", action="append")
    calendar.add_argument("--default-calendar"); calendar.add_argument("--timezone", required=True)
    calendar.add_argument("--working-hours"); calendar.add_argument("--preferences")
    calendar.add_argument("--status", required=True, choices=SOURCE_STATUSES); calendar.add_argument("--evidence")
    default_group=calendar.add_mutually_exclusive_group()
    default_group.add_argument("--is-default", dest="is_default", action="store_true")
    default_group.add_argument("--not-default", dest="is_default", action="store_false")
    calendar.set_defaults(is_default=None)
    deactivate_calendar = commands.add_parser("deactivate-calendar"); deactivate_calendar.add_argument("--account", required=True)
    return root


def main(argv=None) -> int:
    try:
        result = run(parser().parse_args(argv))
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
