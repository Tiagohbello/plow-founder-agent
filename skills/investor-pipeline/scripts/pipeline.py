#!/usr/bin/env python3
"""The founder's investor pipeline CSV: show it, or change one row and keep the rest."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

COLUMNS = ("Investor", "Contact info", "Firm", "Status", "Holds", "Proposed")
FIELDS = {"contact": "Contact info", "firm": "Firm", "status": "Status", "holds": "Holds", "proposed": "Proposed"}
MAPPING_FIELDS = ("name", *FIELDS, "email", "phone", "type", "next_step")


def validate_mapping(mapping: dict) -> dict:
    if not isinstance(mapping, dict) or set(mapping) - set(MAPPING_FIELDS):
        raise ValueError("mapping must use " + "/".join(MAPPING_FIELDS))
    if not mapping.get("name") or not any(mapping.get(k) for k in ("contact", "email", "phone")):
        raise ValueError("mapping needs name and at least one contact/email/phone column")
    if any(not isinstance(v, str) or not v.strip() for v in mapping.values()):
        raise ValueError("mapped columns must be nonblank strings")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("each mapped field needs a distinct column")
    return mapping


def load(path: Path, mapping: dict | None = None) -> tuple[list[str], list[dict]]:
    """Rows as read, and the header with any missing canonical column appended."""
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    header = list(reader.fieldnames or [])
    if mapping is not None:
        validate_mapping(mapping)
        if not header or set(mapping.values()) - set(header):
            raise ValueError("CSV is missing mapped columns")
    elif header and "Investor" not in header:
        raise ValueError(f"{path}: no 'Investor' column; map the founder's headers before writing")
    if len(header) != len(set(header)):
        raise ValueError(f"{path}: header has a repeated column name")
    for number, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"{path}: row {number} has more cells than the header")
        if any(row[column] is None for column in header):
            raise ValueError(f"{path}: row {number} has fewer cells than the header")
    return (header if mapping is not None else header + [column for column in COLUMNS if column not in header]), rows


def record(header: list[str], row: dict) -> dict:
    return {column: row.get(column) or "" for column in header}


def show(args: argparse.Namespace) -> dict:
    mapping = json.loads(args.mapping) if args.mapping else None
    header, rows = load(args.csv, mapping)
    if args.investor:
        rows = [row for row in rows if (row.get(mapping["name"] if mapping else "Investor") or "").strip() == args.investor.strip()]
    return {"columns": header, "count": len(rows), "rows": [record(header, row) for row in rows]}


def set_row(args: argparse.Namespace) -> dict:
    mapping = json.loads(args.mapping) if args.mapping else None
    header, rows = load(args.csv, mapping)
    investor = args.investor.strip()
    if not investor:
        raise ValueError("--investor must not be blank")
    name_column = mapping["name"] if mapping else "Investor"
    matches = [row for row in rows if (row.get(name_column) or "").strip() == investor]
    if len(matches) > 1:
        raise ValueError(f"{len(matches)} rows are named {investor!r}; rename one before editing")
    fields = mapping if mapping is not None else FIELDS
    requested = {name: getattr(args, name, None) for name in MAPPING_FIELDS if name != "name"}
    if any(value is not None and name not in fields for name, value in requested.items()):
        raise ValueError("cannot write an unmapped field; configure its column first")
    changes = {fields[name]: value for name, value in requested.items() if value is not None}
    for column, value in {name_column: investor, **changes}.items():
        # A literal international phone number is data, not a formula.
        phone_column = fields.get("phone")
        phone = column == phone_column and re.fullmatch(r"\+[0-9 ()-]{7,25}", value)
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") and not phone:
            raise ValueError(f"{column}: {value!r} starts with a character spreadsheet software reads as a formula")
    if matches:
        row = matches[0]
    else:
        row = {name_column: investor}
        rows.append(row)
    row.update(changes)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    writer.writerows(record(header, each) for each in rows)
    args.csv.write_text(buffer.getvalue(), encoding="utf-8")
    return record(header, row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("show")
    listing.add_argument("csv", type=Path)
    listing.add_argument("--investor")
    listing.add_argument("--mapping", help="JSON field-to-column mapping; omit for legacy format")
    change = commands.add_parser("set")
    change.add_argument("csv", type=Path)
    change.add_argument("--investor", required=True)
    change.add_argument("--mapping")
    for name in MAPPING_FIELDS:
        if name == "name":
            continue
        change.add_argument(f"--{name.replace('_', '-')}")
    args = parser.parse_args(argv)
    try:
        result = show(args) if args.command == "show" else set_row(args)
    except (OSError, ValueError, csv.Error) as error:
        print(f"pipeline: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
