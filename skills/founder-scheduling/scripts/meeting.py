#!/usr/bin/env python3
"""Resolve scheduling facts by explicit evidence precedence; never guess silently."""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DETAIL_FIELDS = frozenset({"duration_minutes", "format", "location", "participants", "timezone", "city"})
FORMATS = frozenset({"video", "phone", "in_person"})
BASE_REQUIRED = ("duration_minutes", "format", "participants", "timezone")


def _key(value):
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            value = sorted((item.strip().casefold() for item in value))
        else:
            value = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    elif isinstance(value, str):
        value = value.strip().casefold()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate(field, value):
    if field == "duration_minutes":
        if type(value) is not int or not 1 <= value <= 1440:
            raise ValueError("duration_minutes must be an integer from 1 to 1440")
    elif field == "format":
        if value not in FORMATS:
            raise ValueError("format must be video, phone or in_person")
    elif field == "participants":
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("participants must be a nonempty list of verified identities")
        if len({item.strip().casefold() for item in value}) != len(value):
            raise ValueError("participants must be unique")
    elif field in {"location", "city", "timezone"}:
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{field} must be nonblank text when provided")
        if field == "timezone" and value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError("timezone must be an IANA timezone") from error


def resolve_meeting_details(*, request=None, profile=None, history=None, inference=None, context_refs=None):
    """Return highest-precedence facts and unresolved/ambiguous fields.

    `request` and `profile` map field names to exact values. `history` contains
    records with `identity_verified: true` and a `details` map. `inference`
    maps fields to `{value, evidence_refs}`; an inference without source refs is
    rejected. Conflicting verified history blocks lower-precedence inference.
    """
    request = {} if request is None else request
    profile = {} if profile is None else profile
    history = [] if history is None else history
    inference = {} if inference is None else inference
    if not isinstance(request, dict) or not isinstance(profile, dict) or not isinstance(inference, dict):
        raise ValueError("request, profile and inference must be objects")
    if any(set(source) - DETAIL_FIELDS for source in (request, profile, inference)):
        raise ValueError("unsupported meeting detail")
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    if context_refs is None:
        context_refs = []
    if (not isinstance(context_refs, list)
            or any(not isinstance(ref, str) or not ref.strip() for ref in context_refs)):
        raise ValueError("context_refs must be a list of source references")
    details, unresolved, ambiguous = {}, [], []
    evidence_refs = list(dict.fromkeys(ref.strip() for ref in context_refs))
    for field in sorted(DETAIL_FIELDS):
        value = request.get(field)
        if value is not None:
            _validate(field, value)
            details[field] = value
            continue
        value = profile.get(field)
        if value is not None:
            _validate(field, value)
            details[field] = value
            continue
        candidates = []
        for record in history:
            if (isinstance(record, dict) and record.get("identity_verified") is True
                    and isinstance(record.get("details"), dict)):
                refs = record.get("evidence_refs", [])
                if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                    raise ValueError("verified history requires valid evidence_refs")
                evidence_refs.extend(ref.strip() for ref in refs)
                candidate = record["details"].get(field)
                if candidate is not None:
                    _validate(field, candidate)
                    candidates.append(candidate)
        unique = {_key(candidate) for candidate in candidates}
        if len(unique) > 1:
            ambiguous.append(field)
            unresolved.append(field)
            continue
        if candidates:
            details[field] = candidates[0]
            continue
        candidate = inference.get(field)
        if candidate is not None:
            if (not isinstance(candidate, dict) or set(candidate) != {"value", "evidence_refs"}
                    or not isinstance(candidate["evidence_refs"], list)
                    or not candidate["evidence_refs"]
                    or any(not isinstance(ref, str) or not ref.strip() for ref in candidate["evidence_refs"])):
                raise ValueError(f"{field} inference requires source evidence_refs")
            value = candidate["value"]
            _validate(field, value)
            details[field] = value
            evidence_refs.extend(ref.strip() for ref in candidate["evidence_refs"])
    for field in BASE_REQUIRED:
        if details.get(field) is None and field not in unresolved:
            unresolved.append(field)
    if details.get("format") == "in_person" and not details.get("location"):
        if "location" not in unresolved:
            unresolved.append("location")
    return {"details": details, "unresolved": sorted(set(unresolved)),
            "ambiguous": sorted(set(ambiguous)), "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "ready": not unresolved}


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON file with request/profile/history/inference")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text())
    print(json.dumps(resolve_meeting_details(**data), ensure_ascii=False, sort_keys=True))
