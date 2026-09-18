"""Narrow persisted monitor grants; provider calls remain in the published skills."""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_digest(config):
    return hashlib.sha256(canonical(config).encode()).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return result


def validate_grants(config):
    grants = config.setdefault("autonomy", {})
    if not isinstance(grants, dict) or set(grants) - {"csv", "holds"}:
        raise ValueError("autonomy supports csv and holds only")
    for name in ("csv", "holds"):
        grant = grants.setdefault(name, {"enabled": False})
        if not isinstance(grant, dict) or type(grant.get("enabled")) is not bool:
            raise ValueError("autonomy grants require a boolean enabled flag")
        if not grant["enabled"]:
            continue
        if not isinstance(grant.get("approval_ref"), str) or not grant["approval_ref"].strip():
            raise ValueError("autonomy requires the founder's explicit approval reference")
        if name == "csv":
            if not grant.get("no_edit_window_ref") or not config["mapping"].get("next_step"):
                raise ValueError("CSV autonomy needs a next_step mapping and agreed no-edit window")
        elif not all(isinstance(grant.get(k), str) and grant[k].strip() for k in ("account", "calendar")):
            raise ValueError("hold autonomy needs an explicit account and calendar")


def validate_hold(hold):
    fields = {"account", "calendar", "start", "end", "timezone", "title", "attendees", "send_updates", "transparency"}
    if not isinstance(hold, dict) or set(hold) != fields:
        raise ValueError("private hold requires exact structured calendar parameters")
    if hold["attendees"] != [] or hold["send_updates"] != "none" or hold["transparency"] != "opaque":
        raise ValueError("private holds must be busy, attendee-free, with notifications off")
    if any(not isinstance(hold[k], str) or not hold[k].strip() for k in fields - {"attendees"}):
        raise ValueError("hold fields must be nonblank strings")
    zone = ZoneInfo(hold["timezone"])
    start, end = instant(hold["start"]), instant(hold["end"])
    if start >= end or any(t.utcoffset() != t.astimezone(zone).utcoffset() for t in (start, end)):
        raise ValueError("hold times must be ordered and match their timezone")
    if not hold["title"].startswith("HOLD — "):
        raise ValueError("private hold title must identify a HOLD")
    return hold


def authorize(db, suggestion_id, capability, validation):
    if not isinstance(validation, dict):
        raise ValueError("fresh validation must be a JSON object")
    row = db.execute("SELECT * FROM monitor_config WHERE id=1").fetchone()
    if row is None:
        raise ValueError("monitor is not configured")
    config = json.loads(row["config"])
    validate_grants(config)
    grant = config["autonomy"][capability]
    if not grant["enabled"]:
        raise ValueError("monitor autonomy has not been authorized or was revoked")
    if validation.get("config_digest") != config_digest(config):
        raise ValueError("configuration changed; validate again")
    now = datetime.now(timezone.utc)
    checked = instant(validation.get("checked_at", ""))
    if not 0 <= (now - checked).total_seconds() <= 300:
        raise ValueError("fresh validation (within five minutes) required")
    local = now.astimezone(ZoneInfo(config["timezone"]))
    manual = validation.get("manual_request_ref")
    if manual is not None and (not isinstance(manual, str) or not manual.strip()):
        raise ValueError("manual_request_ref must identify an explicit founder request")
    if not manual and (not row["enabled"] or local.weekday() not in config["weekdays"] or
                       not config["start"] <= local.strftime("%H:%M") < config["end"]):
        raise ValueError("monitor is paused or outside its working window")
    item = db.execute("SELECT * FROM monitor_suggestion WHERE id=?", (suggestion_id,)).fetchone()
    if item is None or item["status"] not in ("pending", "approved", "executing"):
        raise ValueError("suggestion is obsolete or requires reconciliation")
    payload = json.loads(item["payload"])
    if sorted(set(validation.get("evidence_refs", []))) != sorted(set(payload["evidence_refs"])):
        raise ValueError("source evidence changed; observe again")
    contact = db.execute("SELECT data FROM monitor_contact WHERE contact_key=?", (item["contact_key"],)).fetchone()
    if contact is None:
        raise ValueError("contact is missing or ambiguous")
    for key in ("source_ref", "csv_ref") + (("calendar_ref",) if capability == "holds" else ()):
        if not isinstance(validation.get(key), str) or not validation[key].strip():
            raise ValueError("fresh source/CSV/calendar read references are required")
    return config, grant, item, json.loads(contact["data"])


def authorize_hold(db, suggestion_id, target, intent, validation):
    config, grant, item, contact = authorize(db, suggestion_id, "holds", validation)
    if validation.get("conflict_free") is not True:
        raise ValueError("private hold requires a freshly verified conflict-free slot")
    hold = validate_hold(json.loads(intent))
    if hold not in json.loads(item["payload"]).get("hold_plan", []):
        raise ValueError("hold differs from the persisted structured plan")
    if target != f"{hold['account']}/{hold['calendar']}/new" or any(hold[k] != grant[k] for k in ("account", "calendar")):
        raise ValueError("hold destination is not authorized")
    fields = contact["fields"]
    title = "HOLD — " + fields["name"].strip()
    if fields.get("firm", "").strip():
        title += " / " + fields["firm"].strip()
    if hold["title"] != title or instant(hold["start"]) <= datetime.now(timezone.utc):
        raise ValueError("hold must identify this contact and a future slot")
    permission = db.execute("SELECT 1 FROM sqlite_master WHERE name='permission'").fetchone()
    policy = db.execute("SELECT policy FROM permission WHERE capability='calendar_manage'").fetchone() if permission else None
    if policy and policy[0] == "forbidden":
        raise ValueError("calendar operations are forbidden")
    return hold, item, {"grant": grant, "validation": validation}


def hold_key(contact_key, hold):
    # Independent of suggestion/message wording, and stable across timezone representations.
    identity = [contact_key, hold["account"], hold["calendar"],
                instant(hold["start"]).astimezone(timezone.utc).isoformat(),
                instant(hold["end"]).astimezone(timezone.utc).isoformat()]
    return "monitor-hold:" + config_digest(identity)
