#!/usr/bin/env python3
"""Read-only Founder Agent installation diagnostic; never prints secrets."""
from __future__ import annotations
import hashlib, json, os, sqlite3
from pathlib import Path

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    home=Path(os.environ.get("HERMES_HOME","/var/lib/hermes")); root=Path("/opt/founder-agent")
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8")); checks=[]
    for relative,wanted in manifest["files"].items():
        target=home/relative
        checks.append({"path":relative,"present":target.is_file(),"valid":target.is_file() and digest(target)==wanted})
    stores={}
    for name,relative in {"profile":"founder-profile/profile.db","memory":"founder-memory/memory.db","queue":"founder-queue/queue.db","drafts":"communication/drafts.db","shift":"founder-shift/shift.db","operations":"external-operations/operations.db"}.items():
        path=home/relative
        try:
            if path.exists():
                db=sqlite3.connect(f"file:{path}?mode=ro",uri=True); db.execute("PRAGMA schema_version").fetchone(); db.close(); stores[name]="readable"
            else: stores[name]="not_created"
        except sqlite3.Error: stores[name]="unreadable"
    result={"version":manifest["version"],"installation_ok":all(c["valid"] for c in checks),"files":checks,"stores":stores,"external_access":"verify interactively through Latch"}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0 if result["installation_ok"] else 1

if __name__=="__main__": raise SystemExit(main())
