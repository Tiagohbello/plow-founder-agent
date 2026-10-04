"""Narrow approval guard shared by both external-action ledgers."""

from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo


HOLD_FIELDS = ("account", "calendar", "start", "end", "timezone", "title",
               "description", "attendees", "send_updates", "transparency")
TERMINAL_PIPELINE_STATUSES = {"passed", "do_not_contact", "withdrawn"}
PIPELINE_STATUS_SET = {
    "new", "waiting_on_us", "held", "sent", "waiting_on_them", "confirmed",
    *TERMINAL_PIPELINE_STATUSES, "unverified",
}


def contact_fields(connection, contact_key):
    for table in ("monitor_contact", "monitor_contact_guard"):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        row = connection.execute(
            f"SELECT data FROM {table} WHERE contact_key=?", (contact_key,)
        ).fetchone()
        if row:
            return json.loads(row["data"]).get("fields", {})
    return None


def require_contact_not_terminal(fields):
    status = fields.get("status") if fields else None
    normalized = " ".join(str(status or "").casefold().replace("_", " ").replace("-", " ").split())
    terminal_labels = {
        "passed", "declined", "not interested", "do not contact", "do not reach out",
        "no further contact", "withdrawn", "offer withdrawn",
    }
    if status in TERMINAL_PIPELINE_STATUSES or normalized in terminal_labels:
        raise ValueError(f"contact status {status} is terminal; monitor actions are disabled")


def add_monitor_column(connection, table):
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
        if "monitor_suggestion_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN monitor_suggestion_id INTEGER")


def require_current_contact(connection, row):
    if row["contact_key"].startswith("source:"):
        return
    fields = contact_fields(connection, row["contact_key"])
    if fields is None:
        raise ValueError("contact is not in the latest verified pipeline read; re-read it first")
    require_contact_not_terminal(fields)
    if fields.get("status") not in PIPELINE_STATUS_SET:
        raise ValueError("contact pipeline status is noncanonical; reconcile it before monitor actions")


def resolve_direct_contact_key(connection, contact_key=None, identifiers=(), context_text=()):
    """Resolve explicit or handle-linked direct context and enforce current status."""
    matched = set()
    normalized_identifiers = {str(value).strip().casefold() for value in identifiers
                              if isinstance(value, str) and value.strip()}
    normalized_context = [value.casefold() for value in context_text
                          if isinstance(value, str) and value.strip()]
    if normalized_identifiers:
        seen = set()
        for table in ("monitor_contact", "monitor_contact_guard"):
            if not connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                continue
            for row in connection.execute(f"SELECT contact_key,data FROM {table}"):
                if row["contact_key"] in seen:
                    continue
                seen.add(row["contact_key"])
                data = json.loads(row["data"])
                handles = {str(value).strip().casefold() for value in data.get("handles", [])
                           if isinstance(value, str) and value.strip()}
                candidates = handles | {row["contact_key"].casefold()}
                name = data.get("name")
                if isinstance(name, str) and name.strip():
                    candidates.add(name.strip().casefold())
                exact_match = bool(candidates & normalized_identifiers)
                mentioned = any(
                    re.search(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])",
                              text, flags=re.IGNORECASE)
                    for candidate in candidates if len(candidate) >= 3
                    for text in normalized_context
                )
                if exact_match or mentioned:
                    matched.add(row["contact_key"])
    if len(matched) > 1:
        raise ValueError("direct action recipient matches multiple pipeline contacts; provide an exact --contact-key")
    if contact_key is not None:
        if (not isinstance(contact_key, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", contact_key)
                or contact_key in {"index", ".", ".."}):
            raise ValueError("contact_key must be one pipeline page slug")
        if matched and contact_key not in matched:
            raise ValueError("--contact-key differs from the pipeline contact matched by recipient")
        resolved = contact_key
    else:
        resolved = next(iter(matched), None)
    if resolved is not None:
        require_current_contact(connection, {"contact_key": resolved})
    return resolved


def require_direct_contact(connection, contact_key, identifiers=(), context_text=()):
    return resolve_direct_contact_key(connection, contact_key, identifiers, context_text)


def add_pipeline_contact_key_column(connection, table):
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
        if "pipeline_contact_key" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN pipeline_contact_key TEXT")


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


def next_plan_entry(connection, row, plan):
    for entry in plan:
        completed = connection.execute(
            """SELECT external_ref FROM external_operation
               WHERE monitor_suggestion_id=? AND target=? AND operation=? AND intent=?
                 AND status='completed'""",
            (row["id"], entry["target"], entry["operation"], entry["intent"]),
        ).fetchone()
        if completed is None:
            return entry
        if entry["effect"] != "hold":
            continue
        contact = connection.execute(
            "SELECT data FROM monitor_contact WHERE contact_key=?", (row["contact_key"],)
        ).fetchone()
        fields = json.loads(contact["data"]).get("fields", {}) if contact else {}
        recorded = {value.strip() for value in str(fields.get("holds", "")).split(";")
                    if value.strip()}
        provider_target = f"{entry['target'].rsplit('/', 1)[0]}/{completed['external_ref']}"
        if provider_target not in recorded:
            raise ValueError("each verified hold must be recorded on the contact page before the next")
    raise ValueError("monitor calendar plan is already complete")


def monitor_item(connection, suggestion_id, approved=False):
    if suggestion_id is None:
        return
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_suggestion'"
    ).fetchone()
    row = connection.execute("SELECT * FROM monitor_suggestion WHERE id=?", (suggestion_id,)).fetchone() if exists else None
    if row is None or row["status"] not in ("pending", "approved", "executing"):
        raise ValueError("monitor suggestion is missing, obsolete, or requires reconciliation")
    if not row["contact_key"].startswith("source:"):
        fields = contact_fields(connection, row["contact_key"])
        if fields is not None:
            require_contact_not_terminal(fields)
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


def monitor_operation(connection, suggestion_id, scope, target=None, operation=None, intent=None,
                      approved=False):
    row = monitor_item(connection, suggestion_id)
    if row is None:
        return
    require_current_contact(connection, row)
    payload = json.loads(row["payload"])
    plan = payload.get("calendar_plan", [])
    if scope != "calendar" or not isinstance(plan, list):
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
    if any(not isinstance(entry, dict)
           or entry.get("effect") not in ("hold", "invitation", "delete_hold")
           for entry in plan):
        raise ValueError("monitor calendar plan entries require a canonical effect")
    entry = next_plan_entry(connection, row, plan)
    exact = {"target": target, "operation": operation, "intent": intent}
    if target is not None and any(entry[key] != value for key, value in exact.items()):
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
    config = connection.execute("SELECT enabled FROM monitor_config WHERE id=1").fetchone()
    automatic_hold = (payload.get("action") == "new_options" and entry["effect"] == "hold"
                      and config is not None and config["enabled"] == 1)
    if automatic_hold:
        parse_hold_intent(entry["intent"], entry["target"])
        require_proposal_draft(connection, row)
        require_default_calendar(connection, entry["target"])
    if approved:
        if automatic_hold:
            require_current_contact(connection, row)
        else:
            monitor_item(connection, suggestion_id, approved=True)
    return {"entry": entry, "automatic_hold": automatic_hold}
