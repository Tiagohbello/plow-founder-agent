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
    store_path=home/"founder-agent"/"founder-agent.db"; store="not_created"
    try:
        if store_path.exists():
            db=sqlite3.connect(f"file:{store_path}?mode=ro",uri=True)
            integrity=db.execute("PRAGMA quick_check").fetchone()[0]
            db.close(); store="readable" if integrity=="ok" else "unreadable"
    except sqlite3.Error: store="unreadable"
    result={"version":manifest["version"],"installation_ok":all(c["valid"] for c in checks),"files":checks,"store":store,"external_access":"verify interactively through Latch"}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return 0 if result["installation_ok"] else 1

if __name__=="__main__": raise SystemExit(main())
