#!/usr/bin/env python3
"""Install the immutable Founder Agent payload into a persistent Hermes home."""
from __future__ import annotations
import hashlib, json, os, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

VARIANT_ROOT = Path(os.environ.get("FOUNDER_AGENT_ROOT", "/opt/founder-agent"))
PAYLOAD = VARIANT_ROOT / "payload"
MANIFEST = VARIANT_ROOT / "manifest.json"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))

def digest(path):
    value=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""): value.update(chunk)
    return value.hexdigest()

def safe_target(relative):
    path=Path(relative)
    if path.is_absolute() or ".." in path.parts: raise ValueError(f"unsafe manifest path: {relative}")
    target=(HERMES_HOME/path).resolve(); home=HERMES_HOME.resolve()
    if home not in target.parents and target != home: raise ValueError(f"path escapes Hermes home: {relative}")
    return target

def atomic_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(f".{target.name}.founder-agent-new")
    shutil.copyfile(source,temporary); os.chmod(temporary,0o644); os.replace(temporary,target)

def retire_file(relative,wanted,backup_root):
    target=safe_target(relative)
    if not target.exists(): return False
    if not target.is_file() or digest(target)!=wanted: return False
    backup=backup_root/relative; backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(target,backup)
    target.unlink(); return True

def set_owner(path, owner, group):
    try: os.chown(path,owner,group)
    except PermissionError:
        if os.geteuid()==0: raise

def main():
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8")); files=manifest.get("files",{})
    retired_files=manifest.get("retired_files",{})
    if not manifest.get("version") or not files: raise ValueError("invalid Founder Agent manifest")
    owner=int(os.environ.get("HERMES_UID","10000")); group=int(os.environ.get("HERMES_GID","10000"))
    # plow-init owns the home as root while Hermes runs as its group. Reassert
    # traversal after a Docker restart; a 0700 home makes every CLI/cron turn fail.
    set_owner(HERMES_HOME,0 if os.geteuid()==0 else owner,group); os.chmod(HERMES_HOME,0o3770)
    skills_root=HERMES_HOME/"skills"; skills_root.mkdir(parents=True,exist_ok=True)
    set_owner(skills_root,0 if os.geteuid()==0 else owner,group); os.chmod(skills_root,0o3770)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root=HERMES_HOME/"backups"/"founder-agent"/f"{manifest['version']}-{stamp}"
    changed=[]; retired=[]
    for relative,wanted in sorted(files.items()):
        source=PAYLOAD/relative; target=safe_target(relative)
        if not source.is_file() or digest(source)!=wanted: raise ValueError(f"payload hash mismatch: {relative}")
        if target.is_file() and digest(target)==wanted: continue
        if target.exists():
            backup=backup_root/relative; backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(target,backup)
        atomic_copy(source,target); changed.append(relative)
    for relative,wanted in sorted(retired_files.items()):
        if retire_file(relative,wanted,backup_root): retired.append(relative)
    for relative,wanted in files.items():
        target=safe_target(relative)
        if not target.is_file() or digest(target)!=wanted: raise ValueError(f"installed hash mismatch: {relative}")
    for relative in files:
        target=safe_target(relative)
        if relative=="SOUL.md": set_owner(target,0 if os.geteuid()==0 else owner,0 if os.geteuid()==0 else group)
        else: set_owner(target,owner,group)
    state=HERMES_HOME/"founder-agent-version.json"
    state.write_text(json.dumps({"version":manifest["version"],"installed_at":stamp,"changed":changed,"retired":retired},sort_keys=True)+"\n",encoding="utf-8")
    set_owner(state,owner,group); os.chmod(state,0o600)
    print(f"founder-agent variant {manifest['version']}: {len(changed)} file(s) reconciled, {len(retired)} retired")
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except (OSError,ValueError,json.JSONDecodeError) as error:
        print(f"founder-agent variant init failed: {error}",file=sys.stderr); raise SystemExit(1)
