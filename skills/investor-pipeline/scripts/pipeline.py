#!/usr/bin/env python3
"""The founder's investor pipeline CSV: show it, or change one row and keep the rest."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

COLUMNS = ("Investor", "Contact info", "Firm", "Status", "Holds", "Proposed")
FIELDS = {"contact": "Contact info", "firm": "Firm", "status": "Status", "holds": "Holds", "proposed": "Proposed"}


def load(path: Path) -> tuple[list[str], list[dict]]:
    """Rows as read, and the header with any missing canonical column appended."""
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    header = list(reader.fieldnames or [])
    if header and "Investor" not in header:
        raise ValueError(f"{path}: no 'Investor' column; map the founder's headers before writing")
    if len(header) != len(set(header)):
        raise ValueError(f"{path}: header has a repeated column name")
    for number, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"{path}: row {number} has more cells than the header")
    return header + [column for column in COLUMNS if column not in header], rows


def record(header: list[str], row: dict) -> dict:
    return {column: row.get(column) or "" for column in header}


def show(args: argparse.Namespace) -> dict:
    header, rows = load(args.csv)
    if args.investor:
        rows = [row for row in rows if (row.get("Investor") or "").strip() == args.investor.strip()]
    return {"columns": header, "count": len(rows), "rows": [record(header, row) for row in rows]}


def set_row(args: argparse.Namespace) -> dict:
    header, rows = load(args.csv)
    investor = args.investor.strip()
    if not investor:
        raise ValueError("--investor must not be blank")
    matches = [row for row in rows if (row.get("Investor") or "").strip() == investor]
    if len(matches) > 1:
        raise ValueError(f"{len(matches)} rows are named {investor!r}; rename one before editing")
    changes = {column: getattr(args, name) for name, column in FIELDS.items() if getattr(args, name) is not None}
    if matches:
        row = matches[0]
    else:
        row = {"Investor": investor}
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
    change = commands.add_parser("set")
    change.add_argument("csv", type=Path)
    change.add_argument("--investor", required=True)
    for name in FIELDS:
        change.add_argument(f"--{name}")
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
