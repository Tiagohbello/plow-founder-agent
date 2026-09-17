"""Narrow approval guard shared by both external-action ledgers."""


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
    if approved and (row["status"] not in ("approved", "executing") or not row["approval_ref"] or not row["validation_ref"]):
        raise ValueError("monitor action requires specific founder approval and fresh source/calendar validation")
