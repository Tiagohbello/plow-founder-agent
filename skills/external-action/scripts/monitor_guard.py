"""Narrow approval guard shared by both external-action ledgers."""

from datetime import datetime
import json
from zoneinfo import ZoneInfo


HOLD_FIELDS = ("account", "calendar", "start", "end", "timezone", "title",
               "description", "attendees", "send_updates", "transparency")


def add_monitor_column(connection, table):
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
        if "monitor_suggestion_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN monitor_suggestion_id INTEGER")


def require_current_contact(connection, row):
    if not row["contact_key"].startswith("source:") and not connection.execute(
            "SELECT 1 FROM monitor_contact WHERE contact_key=?", (row["contact_key"],)).fetchone():
        raise ValueError("contact is not in the latest verified pipeline read; re-read it first")


def require_proposal_draft(connection, row):
    draft = connection.execute("SELECT * FROM draft WHERE id=?", (row["draft_id"],)).fetchone()
    if draft is None:
        raise ValueError("automatic holds require the suggestion's prepared draft")
    if draft["channel"] == "gmail" and (not draft["external_draft_id"]
                                           or not draft["external_draft_account"].strip()):
        raise ValueError("automatic holds require a verified saved Gmail draft")


def parse_hold_intent(intent, target):
    try:
        hold = json.loads(intent)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("automatic hold intent must be structured JSON") from error
    if not isinstance(hold, dict) or set(hold) != set(HOLD_FIELDS):
        raise ValueError("automatic hold requires exact structured calendar parameters")
    if hold["attendees"] != [] or hold["send_updates"] != "none" or hold["transparency"] != "opaque":
        raise ValueError("automatic holds must be busy, attendee-free, with notifications off")
    if hold["description"] != "Tentative — no invitation sent":
        raise ValueError("automatic hold description must be Tentative — no invitation sent")
    if any(not isinstance(hold[key], str) or not hold[key].strip()
           for key in HOLD_FIELDS if key != "attendees"):
        raise ValueError("automatic hold fields must be nonblank strings")
    try:
        zone = ZoneInfo(hold["timezone"])
        start = datetime.fromisoformat(hold["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(hold["end"].replace("Z", "+00:00"))
    except (KeyError, ValueError) as error:
        raise ValueError("automatic hold times must use valid ISO timestamps and timezone") from error
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("automatic hold times must include a timezone")
    if start >= end or any(moment.utcoffset() != moment.astimezone(zone).utcoffset()
                           for moment in (start, end)):
        raise ValueError("automatic hold times must be ordered and match their timezone")
    if not hold["title"].startswith("HOLD — "):
        raise ValueError("automatic hold title must identify a HOLD")
    if target != f"{hold['account']}/{hold['calendar']}/new":
        raise ValueError("automatic hold target must match its account and calendar")
    return {key: hold[key] for key in HOLD_FIELDS}


def require_default_calendar(connection, target):
    rows = connection.execute(
        """SELECT account,default_calendar FROM calendar_account
           WHERE active=1 AND status='available' AND is_default=1"""
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("automatic holds require one available configured default calendar")
    expected = f"{rows[0]['account']}/{rows[0]['default_calendar']}/new"
    if target != expected:
        raise ValueError("automatic holds must use the configured default calendar")


def require_prior_operations_completed(connection, row, plan, entry):
    for prior in plan[:plan.index(entry)]:
        completed = connection.execute(
            """SELECT external_ref FROM external_operation
               WHERE monitor_suggestion_id=? AND target=? AND operation=? AND intent=?
                 AND status='completed'""",
            (row["id"], prior["target"], prior["operation"], prior["intent"]),
        ).fetchone()
        if completed is None:
            raise ValueError("calendar operations must execute in plan order; reconcile the prior operation first")
        if prior["effect"] != "hold":
            continue
        contact = connection.execute(
            "SELECT data FROM monitor_contact WHERE contact_key=?", (row["contact_key"],)
        ).fetchone()
        fields = json.loads(contact["data"]).get("fields", {}) if contact else {}
        recorded = {value.strip() for value in str(fields.get("holds", "")).split(";")
                    if value.strip()}
        provider_target = f"{prior['target'].rsplit('/', 1)[0]}/{completed['external_ref']}"
        if provider_target not in recorded:
            raise ValueError("each verified hold must be recorded on the contact page before the next")


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
        require_current_contact(connection, row)
    return row


def monitor_operation(connection, suggestion_id, scope, target, operation, intent, approved=False):
    row = monitor_item(connection, suggestion_id)
    if row is None:
        return
    payload = json.loads(row["payload"])
    plan = payload.get("calendar_plan", [])
    exact = {"target": target, "operation": operation, "intent": intent}
    if scope != "calendar" or not isinstance(plan, list):
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
    if any(not isinstance(entry, dict)
           or entry.get("effect") not in ("hold", "invitation", "delete_hold")
           for entry in plan):
        raise ValueError("monitor calendar plan entries require a canonical effect")
    matches = [entry for entry in plan if isinstance(entry, dict)
               and {key: entry.get(key) for key in exact} == exact]
    if len(matches) != 1:
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
    entry = matches[0]
    require_prior_operations_completed(connection, row, plan, entry)
    config = connection.execute("SELECT enabled FROM monitor_config WHERE id=1").fetchone()
    automatic_hold = (payload.get("action") == "new_options" and entry["effect"] == "hold"
                      and config is not None and config["enabled"] == 1)
    if automatic_hold:
        parse_hold_intent(intent, target)
        require_proposal_draft(connection, row)
        require_default_calendar(connection, target)
    if approved:
        if automatic_hold:
            require_current_contact(connection, row)
        else:
            monitor_item(connection, suggestion_id, approved=True)
    return {"entry": entry, "automatic_hold": automatic_hold}
