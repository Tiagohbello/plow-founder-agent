#!/usr/bin/env python3
"""Resolve scheduling facts by explicit evidence precedence; never guess silently."""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DETAIL_FIELDS = frozenset({"duration_minutes", "format", "location", "participants", "timezone", "city"})
MEETING_FORMATS = ("video", "phone", "in_person")
FORMATS = frozenset(MEETING_FORMATS)
BASE_REQUIRED = ("duration_minutes", "format", "participants", "timezone")
MEETING_DETAIL_REQUIRED = frozenset(
    {"duration_minutes", "format", "location", "participants", "timezone", "evidence_refs"}
)


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
        if not isinstance(value, str) or value not in FORMATS:
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


def normalize_meeting_fields(values, *, required_fields=(), allowed_fields=None,
                             allow_null_fields=()):
    """Validate and normalize a partial set of shared meeting fields."""
    if not isinstance(values, dict):
        raise ValueError("meeting fields must be a JSON object")
    allowed = DETAIL_FIELDS if allowed_fields is None else frozenset(allowed_fields)
    if set(values) - allowed:
        raise ValueError("unsupported meeting detail")
    missing = set(required_fields) - set(values)
    if missing:
        raise ValueError(f"meeting fields missing required values: {', '.join(sorted(missing))}")
    result = {}
    for field, value in values.items():
        if value is None and field in allow_null_fields:
            result[field] = None
            continue
        normalized = value
        if field in {"location", "city", "timezone"} and isinstance(value, str):
            normalized = value.strip()
        elif field == "participants" and isinstance(value, list):
            normalized = [item.strip() if isinstance(item, str) else item for item in value]
        _validate(field, normalized)
        result[field] = normalized
    return result


def normalize_meeting_preferences(values):
    """Normalize the founder's optionally partial meeting preferences."""
    result = normalize_meeting_fields(values)
    if not result:
        raise ValueError("provide at least one meeting preference")
    return result


def normalize_meeting_details(value):
    """Validate and normalize a complete meeting contract plus its evidence."""
    allowed = MEETING_DETAIL_REQUIRED | {"city"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("meeting_details needs duration_minutes, format, location, participants and timezone")
    if MEETING_DETAIL_REQUIRED - set(value):
        raise ValueError("meeting_details needs duration_minutes, format, location, participants and timezone")
    fields = {key: item for key, item in value.items() if key != "evidence_refs"}
    result = normalize_meeting_fields(
        fields,
        required_fields={"duration_minutes", "format", "location", "participants", "timezone"},
        allow_null_fields={"location"},
    )
    if result["format"] == "in_person" and not result["location"]:
        raise ValueError("in-person meetings require a verified location")
    refs = value["evidence_refs"]
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(ref, str) or not ref.strip() for ref in refs)):
        raise ValueError("meeting_details requires source evidence_refs")
    result["evidence_refs"] = list(dict.fromkeys(ref.strip() for ref in refs))
    return result


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
            details[field] = normalize_meeting_fields({field: value})[field]
            continue
        value = profile.get(field)
        if value is not None:
            details[field] = normalize_meeting_fields({field: value})[field]
            continue
        candidates = []
        for record in history:
            if (isinstance(record, dict) and record.get("identity_verified") is True
                    and isinstance(record.get("details"), dict)):
                refs = record.get("evidence_refs", [])
                if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                    raise ValueError("verified history requires valid evidence_refs")
                candidate = record["details"].get(field)
                if candidate is not None:
                    # Context-level refs cannot establish provenance for this fact.
                    # Ignore history facts without their own source citations.
                    if not refs:
                        continue
                    candidate = normalize_meeting_fields({field: candidate})[field]
                    candidates.append((candidate, [ref.strip() for ref in refs]))
        unique = {_key(candidate) for candidate, _ in candidates}
        if len(unique) > 1:
            ambiguous.append(field)
            unresolved.append(field)
            continue
        if candidates:
            details[field] = candidates[0][0]
            for _, refs in candidates:
                evidence_refs.extend(refs)
            continue
        candidate = inference.get(field)
        if candidate is not None:
            if (not isinstance(candidate, dict) or set(candidate) != {"value", "evidence_refs"}
                    or not isinstance(candidate["evidence_refs"], list)
                    or not candidate["evidence_refs"]
                    or any(not isinstance(ref, str) or not ref.strip() for ref in candidate["evidence_refs"])):
                raise ValueError(f"{field} inference requires source evidence_refs")
            value = candidate["value"]
            value = normalize_meeting_fields({field: value})[field]
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
