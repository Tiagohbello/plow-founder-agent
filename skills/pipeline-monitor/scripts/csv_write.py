"""Durable CSV upload claims. The skill performs Latch reads/writes, never this helper."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import monitor


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(db, sid):
    row = db.execute("SELECT * FROM monitor_csv_write WHERE suggestion_id=?", (sid,)).fetchone()
    return dict(row) if row else None


def store(db, sid, status, detail):
    db.execute("UPDATE monitor_csv_write SET status=?,detail=?,updated_at=? WHERE suggestion_id=?",
               (status, detail, monitor.stamp(), sid))


def completed_holds(db, sid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='external_operation'").fetchone():
        return []
    return db.execute("SELECT o.* FROM external_operation o JOIN monitor_hold_link l ON l.operation_id=o.id WHERE l.suggestion_id=? AND o.status='completed' ORDER BY o.id", (sid,)).fetchall()


def run(db, args, validation):
    # Serializes helpers; one executing/uncertain whole-file upload blocks all others.
    # Latch has no conditional write: the agreed no-edit window is still necessary.
    with db:
        db.execute("BEGIN IMMEDIATE")
        existing = record(db, args.id)
        holds = completed_holds(db, args.id)
        hold_revision = monitor.canonical([[h["id"], h["external_ref"]] for h in holds])
        if args.command == "reconcile-csv":
            monitor.required(args.ref, "remote read-back reference")
            if getattr(args, "accept_current", False):
                monitor.required(args.approval_ref, "specific founder reconciliation decision")
            if not existing or existing["status"] not in ("executing", "uncertain"):
                raise ValueError("CSV upload is not awaiting reconciliation")
            actual = file_hash(args.csv)
            if actual == existing["after_hash"]:
                store(db, args.id, "completed", "Next step updated and read back")
            elif actual == existing["before_hash"]:
                store(db, args.id, "pending", "Remote file unchanged; prepare again before retrying")
            elif getattr(args, "accept_current", False):
                store(db, args.id, "pending", "Founder retained current content; prepare a fresh patch")
            else:
                store(db, args.id, "uncertain", "Read-back differs; reconcile edits before another upload")
            ref = args.ref + ("; " + args.approval_ref if getattr(args, "accept_current", False) else "")
            db.execute("UPDATE monitor_csv_write SET evidence_ref=? WHERE suggestion_id=?", (ref, args.id))
            return record(db, args.id)
        if args.command == "defer-csv":
            reason = monitor.required(args.reason, "deferral reason")
            if not existing:
                state = monitor.show(db)
                monitor.suggestion(db, args.id)
                db.execute("INSERT INTO monitor_csv_write (suggestion_id,csv_path,before_hash,after_hash,content,status,detail,config_digest,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (args.id, state["config"]["csv_path"], "", "", "", "pending", reason, state["config_digest"], monitor.stamp()))
            else:
                if existing["status"] == "completed" and existing["hold_revision"] == hold_revision:
                    return existing
                store(db, args.id, "uncertain" if existing["status"] in ("executing", "uncertain") else "pending", reason)
            return record(db, args.id)
        if existing and (existing["status"] in ("executing", "uncertain") or
                         existing["status"] == "completed" and existing["hold_revision"] == hold_revision):
            return {"claimed": False, "write": existing}
        if db.execute("SELECT 1 FROM monitor_csv_write WHERE status IN ('executing','uncertain')").fetchone():
            raise ValueError("another CSV upload needs reconciliation")
        # Refresh identities without committing the enclosing transaction.
        current = monitor.contacts(db, args.csv, manage_transaction=False)
        autonomy = monitor.sibling("external-action", "monitor_autonomy.py")
        config, grant, item, contact = autonomy.authorize(db, args.id, "csv", validation)
        if db.execute("""SELECT 1 FROM monitor_suggestion WHERE contact_key=? AND id!=?
                         AND status IN ('pending','approved','executing') AND evidence_at>?""",
                      (item["contact_key"], args.id, item["evidence_at"])).fetchone():
            raise ValueError("a newer contact suggestion owns Next step; do not overwrite it with older advice")
        if item["contact_key"] not in {c["contact_key"] for c in current["contacts"]}:
            raise ValueError("CSV contact is no longer unambiguous")
        if args.command == "claim-csv":
            if not existing or existing["status"] != "prepared":
                raise ValueError("prepare CSV before claiming upload")
            if existing["config_digest"] != monitor.digest(config) or existing["csv_path"] != config["csv_path"]:
                raise ValueError("CSV configuration changed; prepare again")
            if existing["hold_revision"] != hold_revision:
                store(db, args.id, "pending", "Hold results changed; prepare updated CSV content")
                return {"claimed": False, "write": record(db, args.id)}
            if file_hash(args.csv) != existing["before_hash"]:
                store(db, args.id, "pending", "CSV changed before upload; prepare against the new content")
                return {"claimed": False, "write": record(db, args.id)}
            store(db, args.id, "executing", "Upload awaiting remote read-back")
            db.execute("UPDATE monitor_csv_write SET authorization=? WHERE suggestion_id=?",
                       (json.dumps({"grant": grant, "validation": validation}), args.id))
            return {"claimed": True, "write": record(db, args.id)}
        fields = {"next_step": json.loads(item["payload"])["next_step"]}
        if holds:
            if not validation.get("calendar_ref"):
                raise ValueError("verify the completed holds still exist before CSV write-back")
            times = [s.strip() for s in contact["fields"].get("holds", "").split(";") if s.strip()]
            for operation in holds:
                hold = json.loads(operation["intent"])
                label = f"{hold['start']} – {hold['end']} {hold['timezone']}"
                if label not in times:
                    times.append(label)
            fields["holds"] = "; ".join(times)
            if contact["fields"].get("status") not in ("confirmed", "completed"):
                fields["status"] = "held"
        pipeline = monitor.sibling("investor-pipeline", "pipeline.py")
        before = file_hash(args.csv)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "snapshot.csv"
            temporary.write_bytes(args.csv.read_bytes())
            pipeline.set_row(argparse.Namespace(csv=temporary, mapping=json.dumps(config["mapping"]),
                                               investor=contact["fields"]["name"], existing_only=True, **fields))
            content = temporary.read_text()
            after = file_hash(temporary)
        status = "completed" if before == after else "prepared"
        db.execute("""INSERT INTO monitor_csv_write (suggestion_id,csv_path,before_hash,after_hash,content,status,detail,config_digest,updated_at) VALUES (?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(suggestion_id) DO UPDATE SET csv_path=excluded.csv_path,
                      before_hash=excluded.before_hash,after_hash=excluded.after_hash,content=excluded.content,
                      status=excluded.status,detail=excluded.detail,config_digest=excluded.config_digest,updated_at=excluded.updated_at""",
                   (args.id, config["csv_path"], before, after, content, status,
                    "Next step already matches the remote read" if status == "completed" else "Ready for pre-upload comparison",
                    monitor.digest(config), monitor.stamp()))
        db.execute("UPDATE monitor_csv_write SET authorization=?,hold_revision=? WHERE suggestion_id=?",
                   (json.dumps({"grant": grant, "validation": validation}), hold_revision, args.id))
        return record(db, args.id)
