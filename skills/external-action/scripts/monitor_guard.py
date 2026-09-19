"""Narrow approval guard shared by both external-action ledgers."""

import json


def add_monitor_column(connection, table):
    connection.commit()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {r[1] for r in connection.execute(f"PRAGMA table_info({table})")}
        if "monitor_suggestion_id" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN monitor_suggestion_id INTEGER")


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


def monitor_operation(connection, suggestion_id, scope, target, operation, intent, approved=False):
    row = monitor_item(connection, suggestion_id, approved=approved)
    if row is None:
        return
    plan = json.loads(row["payload"]).get("calendar_plan", [])
    exact = {"target": target, "operation": operation, "intent": intent}
    if scope != "calendar" or not isinstance(plan, list):
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
    matches = [entry for entry in plan if isinstance(entry, dict)
               and {key: entry.get(key) for key in exact} == exact]
    if len(matches) != 1:
        raise ValueError("operation differs from the displayed monitor calendar plan; request fresh approval")
