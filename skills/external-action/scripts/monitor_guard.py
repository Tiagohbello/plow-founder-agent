"""Narrow approval guard shared by both external-action ledgers."""

from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo


HOLD_CREATE = "create_private_hold"
HOLD_DELETE = "delete_private_hold"
HOLD_FIELDS = ("account", "calendar", "start", "end", "timezone", "title",
               "attendees", "send_updates", "transparency")


def add_monitor_column(connection, table):
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
        if "monitor_suggestion_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN monitor_suggestion_id INTEGER")


def validate_hold(hold):
    if not isinstance(hold, dict) or set(hold) != set(HOLD_FIELDS):
        raise ValueError("private hold requires exact structured calendar parameters")
    if hold["attendees"] != [] or hold["send_updates"] != "none" or hold["transparency"] != "opaque":
        raise ValueError("private holds must be busy, attendee-free, with notifications off")
    if any(not isinstance(hold[key], str) or not hold[key].strip() for key in HOLD_FIELDS if key != "attendees"):
        raise ValueError("hold fields must be nonblank strings")
    zone = ZoneInfo(hold["timezone"])
    start = datetime.fromisoformat(hold["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(hold["end"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("hold times must include a timezone")
    if start >= end or any(moment.utcoffset() != moment.astimezone(zone).utcoffset() for moment in (start, end)):
        raise ValueError("hold times must be ordered and match their timezone")
    if not hold["title"].startswith("HOLD — "):
        raise ValueError("private hold title must identify a HOLD")
    return {key: hold[key] for key in HOLD_FIELDS}


def hold_key(contact_key, hold):
    start = datetime.fromisoformat(hold["start"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    end = datetime.fromisoformat(hold["end"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    identity = json.dumps([contact_key, hold["account"], hold["calendar"], start, end], separators=(",", ":"))
    return "monitor-hold:" + hashlib.sha256(identity.encode()).hexdigest()


def parse_hold_intent(intent):
    try:
        payload = json.loads(intent) if isinstance(intent, str) else intent
    except json.JSONDecodeError as error:
        raise ValueError("private hold intent must be structured JSON") from error
    return validate_hold(payload)


def monitor_item(connection, suggestion_id, approved=False):
    if suggestion_id is None:
        return
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_suggestion'"
    ).fetchone()
    row = connection.execute("SELECT * FROM monitor_suggestion WHERE id=?", (suggestion_id,)).fetchone() if exists else None
    if row is None or row["status"] not in ("pending", "approved", "executing"):
        raise ValueError("monitor suggestion is missing, obsolete, or requires reconciliation")
    if approved:
        if row["status"] not in ("approved", "executing") or not row["approval_ref"] or not row["validation_ref"]:
            raise ValueError("monitor action requires specific founder approval and fresh source/calendar validation")
        # Approval does not expire on its own: a later pipeline read can unlink the
        # contact while the suggestion stays `approved`, so status alone cannot answer
        # whether this identity is still placeable. Asked here, where the external
        # effect happens -- staging a local draft is not an effect and stays allowed,
        # so reconciling one for a contact that has since unlinked still works.
        if not row["contact_key"].startswith("source:") and not connection.execute(
                "SELECT 1 FROM monitor_contact WHERE contact_key=?", (row["contact_key"],)).fetchone():
            raise ValueError("contact is not in the latest verified pipeline read; re-read it first")
    return row


def authorize_private_hold(connection, suggestion_id, scope, target, operation, intent):
    row = monitor_item(connection, suggestion_id, approved=False)
    if row is None or scope != "calendar":
        raise ValueError("private hold requires a monitor suggestion and calendar scope")
    hold = parse_hold_intent(intent)
    expected_new = f"{hold['account']}/{hold['calendar']}/new"
    if operation == HOLD_CREATE:
        if not row["draft_id"]:
            raise ValueError("private hold creation requires a linked draft")
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "calendar_account" in tables:
            cal = connection.execute(
                "SELECT * FROM calendar_account WHERE active=1 AND is_default=1 LIMIT 1"
            ).fetchone()
            if cal and (hold["account"] != cal["account"] or hold["calendar"] != cal["default_calendar"]):
                raise ValueError("private hold creation must target the active configured default calendar")
        plan = json.loads(row["payload"]).get("hold_plan", [])
        if not isinstance(plan, list) or hold not in plan:
            raise ValueError("hold differs from the persisted plan")
        if target != expected_new:
            raise ValueError("hold destination is not authorized")
        return hold, row
    event_id = target.rsplit("/", 1)[-1]
    if not event_id or event_id == "new" or target != f"{hold['account']}/{hold['calendar']}/{event_id}":
        raise ValueError("hold deletion target is not authorized")
    plan = json.loads(row["payload"]).get("hold_plan", [])
    if isinstance(plan, list) and hold in plan:
        raise ValueError("cannot delete hold that is still present in current hold plan")
    existing = connection.execute(
        "SELECT * FROM external_operation WHERE idempotency_key=? AND status='completed'",
        (hold_key(row["contact_key"], hold),),
    ).fetchone()
    if existing is None or existing["external_ref"] != event_id:
        raise ValueError("hold deletion requires a verified event for this contact")
    return hold, row


def monitor_operation(connection, suggestion_id, scope, target, operation, intent, approved=False):
    if operation in (HOLD_CREATE, HOLD_DELETE):
        return authorize_private_hold(connection, suggestion_id, scope, target, operation, intent)
    row = monitor_item(connection, suggestion_id, approved=approved)
    if row is None:
        return
    plan = json.loads(row["payload"]).get("calendar_plan", [])
    exact = {"target": target, "operation": operation, "intent": intent}
    if scope != "calendar" or not isinstance(plan, list) or exact not in plan:
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
