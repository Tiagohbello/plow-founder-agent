#!/usr/bin/env python3
"""Durable Founder Shift lifecycle, cycle lock, and action ledger."""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION_STATES = ("handled", "prepared", "needs_founder", "watching", "uncertain")

def default_database_path():
    value = os.environ.get("FOUNDER_SHIFT_DB")
    return Path(value).expanduser() if value else Path(os.environ.get("HERMES_HOME", "/var/lib/hermes")) / "founder-shift" / "shift.db"

def parse_time(value=None):
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)

def iso(value): return value.astimezone(timezone.utc).isoformat(timespec="seconds")
def required(value, name):
    if not value or not value.strip(): raise ValueError(f"{name} must not be blank")
    return value.strip()
def as_dict(row): return dict(row)

def connect(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000"); db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS shift_run (
        id TEXT PRIMARY KEY, duration_minutes INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','completed','failed')),
        started_at TEXT NOT NULL, finished_at TEXT);
      CREATE TABLE IF NOT EXISTS shift_action (
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES shift_run(id),
        action_key TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN
        ('handled','prepared','needs_founder','watching','uncertain')),
        summary TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(run_id,action_key));
      CREATE TABLE IF NOT EXISTS shift_cycle (
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES shift_run(id),
        cycle_key TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
        started_at TEXT NOT NULL, finished_at TEXT, evidence TEXT NOT NULL DEFAULT '',
        UNIQUE(run_id,cycle_key));
      CREATE TABLE IF NOT EXISTS shift_effect (
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES shift_run(id),
        action_key TEXT NOT NULL, kind TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('claimed','completed','uncertain')),
        evidence TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(run_id,action_key));
      CREATE INDEX IF NOT EXISTS shift_action_run_idx ON shift_action(run_id);
      CREATE INDEX IF NOT EXISTS shift_cycle_run_idx ON shift_cycle(run_id);
      CREATE INDEX IF NOT EXISTS shift_effect_run_idx ON shift_effect(run_id);
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(shift_run)")}
    for name, declaration in {
        "expires_at":"TEXT NOT NULL DEFAULT ''", "interval_minutes":"INTEGER NOT NULL DEFAULT 10",
        "cycle_job_id":"TEXT NOT NULL DEFAULT ''", "finalizer_job_id":"TEXT NOT NULL DEFAULT ''",
        "origin":"TEXT NOT NULL DEFAULT ''", "completion_reason":"TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in columns: db.execute(f"ALTER TABLE shift_run ADD COLUMN {name} {declaration}")
    for row in db.execute("SELECT id,started_at,duration_minutes FROM shift_run WHERE expires_at='' "):
        db.execute("UPDATE shift_run SET expires_at=? WHERE id=?", (iso(parse_time(row["started_at"])+timedelta(minutes=row["duration_minutes"])),row["id"]))
    db.commit()
    try: path.chmod(0o600)
    except OSError: pass
    return db

def get_run(db, run_id):
    row=db.execute("SELECT * FROM shift_run WHERE id=?",(required(run_id,"run_id"),)).fetchone()
    if row is None: raise ValueError("shift run not found")
    return row

def reconcile_expiry(db, current):
    expired=[]
    for row in db.execute("SELECT * FROM shift_run WHERE status='active'"):
        if parse_time(row["expires_at"]) <= current:
            db.execute("UPDATE shift_run SET status='completed',finished_at=?,completion_reason='expired' WHERE id=?",(iso(current),row["id"]))
            db.execute("UPDATE shift_cycle SET status='failed',finished_at=?,evidence='shift expired during cycle' WHERE run_id=? AND status='running'",(iso(current),row["id"]))
            expired.append(row["id"])
    db.commit(); return expired

def begin_run(db, duration, interval, origin, current):
    if duration<=0 or interval<=0: raise ValueError("duration and interval must be positive")
    reconcile_expiry(db,current); db.execute("BEGIN IMMEDIATE")
    try:
        active=db.execute("SELECT * FROM shift_run WHERE status='active' ORDER BY started_at DESC LIMIT 1").fetchone()
        if active: db.rollback(); return {"created":False,"already_active":True,"run":as_dict(active)}
        run_id=uuid.uuid4().hex
        db.execute("INSERT INTO shift_run(id,duration_minutes,status,started_at,expires_at,interval_minutes,origin) VALUES (?,?,'active',?,?,?,?)",(run_id,duration,iso(current),iso(current+timedelta(minutes=duration)),interval,origin.strip()))
        db.commit(); return {"created":True,"already_active":False,"run":as_dict(get_run(db,run_id))}
    except BaseException:
        if db.in_transaction: db.rollback()
        raise

def set_jobs(db,run_id,cycle_job,final_job):
    run=get_run(db,run_id)
    if run["status"]!="active": raise ValueError("cannot attach jobs to a finished shift")
    db.execute("UPDATE shift_run SET cycle_job_id=?,finalizer_job_id=? WHERE id=?",(required(cycle_job,"cycle_job_id"),required(final_job,"finalizer_job_id"),run_id)); db.commit()
    return {"updated":True,"run":as_dict(get_run(db,run_id))}

def claim_cycle(db,run_id,key,current):
    reconcile_expiry(db,current); db.execute("BEGIN IMMEDIATE")
    try:
        run=get_run(db,run_id)
        if run["status"]!="active": db.rollback(); return {"claimed":False,"reason":run["completion_reason"] or run["status"],"run":as_dict(run)}
        running=db.execute("SELECT * FROM shift_cycle WHERE run_id=? AND status='running' LIMIT 1",(run_id,)).fetchone()
        if running: db.rollback(); return {"claimed":False,"reason":"cycle_already_running","cycle":as_dict(running)}
        old=db.execute("SELECT * FROM shift_cycle WHERE run_id=? AND cycle_key=?",(run_id,required(key,"cycle_key"))).fetchone()
        if old: db.rollback(); return {"claimed":False,"reason":"duplicate_cycle","cycle":as_dict(old)}
        cursor=db.execute("INSERT INTO shift_cycle(run_id,cycle_key,status,started_at) VALUES (?,?,'running',?)",(run_id,key,iso(current))); db.commit()
        row=db.execute("SELECT * FROM shift_cycle WHERE id=?",(cursor.lastrowid,)).fetchone()
        return {"claimed":True,"cycle":as_dict(row),"run":as_dict(get_run(db,run_id))}
    except BaseException:
        if db.in_transaction: db.rollback()
        raise

def finish_cycle(db,run_id,key,status,evidence,current):
    if status not in ("completed","failed"): raise ValueError("cycle status must be completed or failed")
    row=db.execute("SELECT * FROM shift_cycle WHERE run_id=? AND cycle_key=?",(run_id,key)).fetchone()
    if row is None: raise ValueError("cycle not found")
    if row["status"]!="running": return {"finished":False,"already_finished":True,"cycle":as_dict(row)}
    db.execute("UPDATE shift_cycle SET status=?,finished_at=?,evidence=? WHERE id=?",(status,iso(current),evidence.strip(),row["id"])); db.commit()
    return {"finished":True,"already_finished":False,"cycle":as_dict(db.execute("SELECT * FROM shift_cycle WHERE id=?",(row["id"],)).fetchone())}

def record_action(db,run_id,key,state,summary,evidence,current):
    reconcile_expiry(db,current)
    if state not in ACTION_STATES: raise ValueError("invalid action state")
    if get_run(db,run_id)["status"]!="active": raise ValueError("cannot record action on a finished shift")
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("SELECT * FROM shift_action WHERE run_id=? AND action_key=?",(run_id,required(key,"action_key"))).fetchone()
        if old: db.rollback(); return {"recorded":False,"duplicate":True,"action":as_dict(old)}
        stamp=iso(current); cursor=db.execute("INSERT INTO shift_action(run_id,action_key,state,summary,evidence,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",(run_id,key,state,required(summary,"summary"),evidence.strip(),stamp,stamp)); db.commit()
        return {"recorded":True,"duplicate":False,"action":as_dict(db.execute("SELECT * FROM shift_action WHERE id=?",(cursor.lastrowid,)).fetchone())}
    except BaseException:
        if db.in_transaction: db.rollback()
        raise

def claim_effect(db,run_id,key,kind,current):
    reconcile_expiry(db,current)
    if get_run(db,run_id)["status"]!="active": return {"claimed":False,"reason":"shift_not_active"}
    db.execute("BEGIN IMMEDIATE")
    try:
        old=db.execute("SELECT * FROM shift_effect WHERE run_id=? AND action_key=?",(run_id,required(key,"action_key"))).fetchone()
        if old:
            db.rollback(); return {"claimed":False,"verification_required":True,"effect":as_dict(old)}
        stamp=iso(current); cursor=db.execute("INSERT INTO shift_effect(run_id,action_key,kind,status,created_at,updated_at) VALUES (?,?,?,'claimed',?,?)",(run_id,key,required(kind,"kind"),stamp,stamp)); db.commit()
        return {"claimed":True,"effect":as_dict(db.execute("SELECT * FROM shift_effect WHERE id=?",(cursor.lastrowid,)).fetchone())}
    except BaseException:
        if db.in_transaction: db.rollback()
        raise

def finish_effect(db,run_id,key,status,evidence,current):
    if status not in ("completed","uncertain"): raise ValueError("effect status must be completed or uncertain")
    row=db.execute("SELECT * FROM shift_effect WHERE run_id=? AND action_key=?",(run_id,key)).fetchone()
    if row is None: raise ValueError("effect must be claimed before completion")
    if row["status"]!="claimed": return {"finished":False,"verification_required":True,"effect":as_dict(row)}
    db.execute("UPDATE shift_effect SET status=?,evidence=?,updated_at=? WHERE id=?",(status,required(evidence,"evidence"),iso(current),row["id"])); db.commit()
    return {"finished":True,"effect":as_dict(db.execute("SELECT * FROM shift_effect WHERE id=?",(row["id"],)).fetchone())}

def finish_run(db,run_id,status,reason,current):
    if status not in ("completed","failed"): raise ValueError("invalid finish status")
    run=get_run(db,run_id)
    if run["status"]!="active": return {"finished":False,"already_finished":True,"run":as_dict(run)}
    db.execute("UPDATE shift_run SET status=?,finished_at=?,completion_reason=? WHERE id=?",(status,iso(current),reason.strip() or status,run_id))
    db.execute("UPDATE shift_cycle SET status='failed',finished_at=?,evidence='shift finished during cycle' WHERE run_id=? AND status='running'",(iso(current),run_id)); db.commit()
    return {"finished":True,"already_finished":False,"run":as_dict(get_run(db,run_id))}

def summary(db,run_id,current):
    reconcile_expiry(db,current)
    return {"run":as_dict(get_run(db,run_id)),"actions":[as_dict(r) for r in db.execute("SELECT * FROM shift_action WHERE run_id=? ORDER BY id",(run_id,))],"cycles":[as_dict(r) for r in db.execute("SELECT * FROM shift_cycle WHERE run_id=? ORDER BY id",(run_id,))],"effects":[as_dict(r) for r in db.execute("SELECT * FROM shift_effect WHERE run_id=? ORDER BY id",(run_id,))]}

def format_summary(value):
    actions=value["actions"]; groups=(("Handled",("handled",)),("Prepared",("prepared",)),("Needs you",("needs_founder",)),("Watching",("watching","uncertain")))
    lines=["FOUNDER SHIFT",""]
    if not actions: return "\n".join(lines+["Handled","- No work was recorded."])
    for title,states in groups:
        items=[a for a in actions if a["state"] in states]; lines += [title,""]
        if not items: lines.append("- None.")
        for index,item in enumerate(items,1):
            prefix=f"{index}." if title=="Needs you" else "-"; evidence=f" ({item['evidence']})" if item["evidence"] else ""
            lines.append(f"{prefix} {item['summary']}{evidence}")
        lines.append("")
    return "\n".join(lines).rstrip()

def build_parser():
    root=argparse.ArgumentParser(); root.add_argument("--db"); root.add_argument("--now")
    commands=root.add_subparsers(dest="operation",required=True)
    begin=commands.add_parser("begin"); begin.add_argument("--minutes",type=int,required=True); begin.add_argument("--interval-minutes",type=int,default=10); begin.add_argument("--origin",default="")
    jobs=commands.add_parser("set-jobs"); jobs.add_argument("--run-id",required=True); jobs.add_argument("--cycle-job-id",required=True); jobs.add_argument("--finalizer-job-id",required=True)
    claim=commands.add_parser("claim-cycle"); claim.add_argument("--run-id",required=True); claim.add_argument("--cycle-key",required=True)
    cycle=commands.add_parser("finish-cycle"); cycle.add_argument("--run-id",required=True); cycle.add_argument("--cycle-key",required=True); cycle.add_argument("--status",required=True,choices=("completed","failed")); cycle.add_argument("--evidence",default="")
    action=commands.add_parser("record-action"); action.add_argument("--run-id",required=True); action.add_argument("--action-key",required=True); action.add_argument("--state",required=True,choices=ACTION_STATES); action.add_argument("--summary",required=True); action.add_argument("--evidence",default="")
    effect=commands.add_parser("claim-effect"); effect.add_argument("--run-id",required=True); effect.add_argument("--action-key",required=True); effect.add_argument("--kind",required=True)
    effect_finish=commands.add_parser("finish-effect"); effect_finish.add_argument("--run-id",required=True); effect_finish.add_argument("--action-key",required=True); effect_finish.add_argument("--status",required=True,choices=("completed","uncertain")); effect_finish.add_argument("--evidence",required=True)
    for name in ("finish","cancel"):
        ending=commands.add_parser(name); ending.add_argument("--run-id",required=True); ending.add_argument("--status",default="completed",choices=("completed","failed")); ending.add_argument("--reason",default="cancelled" if name=="cancel" else "completed")
    status=commands.add_parser("status"); status.add_argument("--run-id")
    report=commands.add_parser("summary"); report.add_argument("--run-id",required=True); report.add_argument("--json",action="store_true")
    return root

def run(args):
    if args.db: os.environ["FOUNDER_SHIFT_DB"]=args.db
    current=parse_time(args.now); db=connect(default_database_path())
    try:
        if args.operation=="begin": return begin_run(db,args.minutes,args.interval_minutes,args.origin,current)
        if args.operation=="set-jobs": return set_jobs(db,args.run_id,args.cycle_job_id,args.finalizer_job_id)
        if args.operation=="claim-cycle": return claim_cycle(db,args.run_id,args.cycle_key,current)
        if args.operation=="finish-cycle": return finish_cycle(db,args.run_id,args.cycle_key,args.status,args.evidence,current)
        if args.operation=="record-action": return record_action(db,args.run_id,args.action_key,args.state,args.summary,args.evidence,current)
        if args.operation=="claim-effect": return claim_effect(db,args.run_id,args.action_key,args.kind,current)
        if args.operation=="finish-effect": return finish_effect(db,args.run_id,args.action_key,args.status,args.evidence,current)
        if args.operation in ("finish","cancel"): return finish_run(db,args.run_id,args.status,args.reason,current)
        if args.operation=="status":
            reconcile_expiry(db,current); row=get_run(db,args.run_id) if args.run_id else db.execute("SELECT * FROM shift_run ORDER BY started_at DESC LIMIT 1").fetchone(); return {"run":as_dict(row) if row else None}
        value=summary(db,args.run_id,current); return value if args.json else format_summary(value)
    finally: db.close()

def main(argv=None):
    try: result=run(build_parser().parse_args(argv))
    except (OSError,sqlite3.Error,ValueError) as error: print(f"error: {error}",file=sys.stderr); return 2
    print(result if isinstance(result,str) else json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
