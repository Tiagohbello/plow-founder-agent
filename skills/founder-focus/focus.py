#!/usr/bin/env python3
"""Choose one small founder task using priority and available time."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUEUE_SCRIPT = ROOT / "founder-queue" / "queue.py"
PRIORITY_ORDER = {"urgent": 4, "high": 3, "medium": 2, "low": 1}
FOCUS_STATUSES = {"ready", "needs_founder", "working"}


def load_queue_module():
    spec = importlib.util.spec_from_file_location("founder_queue_store", QUEUE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Founder Queue helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_minutes(value: str | int | float) -> int:
    if isinstance(value, (int, float)):
        minutes = int(value)
    else:
        text = value.strip().casefold()
        match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours)?", text)
        if not match:
            raise ValueError("time must look like 30m, 30 minutes, 3h, or 180")
        amount = int(match.group(1))
        minutes = amount * 60 if match.group(2) in {"h", "hr", "hour", "hours"} else amount
    if minutes <= 0:
        raise ValueError("time must be positive")
    return minutes


def estimate_minutes(item: dict[str, Any]) -> int | None:
    explicit = item.get("estimated_minutes")
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            pass
    text = f"{item.get('title', '')} {item.get('context', '')}".casefold()
    match = re.search(r"(?:about\s+|est(?:imate)?\s*[:=]?\s*)?(\d+)\s*"
                      r"(m|min|mins|minute|minutes|h|hr|hour|hours)\b", text)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 60 if match.group(2) in {"h", "hr", "hour", "hours"} else amount


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def deferred_related(item: dict[str, Any], memories: list[dict[str, Any]]) -> bool:
    if item.get("action_kind", "implement") != "implement":
        return False
    text = _normalized(f"{item.get('title', '')} {item.get('context', '')}")
    if "deferred" in text:
        return True
    for record in memories:
        if record.get("status") != "deferred":
            continue
        subject = _normalized(str(record.get("subject", "")))
        if subject and subject in text:
            return True
    return False


def _sort_key(item: dict[str, Any], available_minutes: int) -> tuple[int, int, int, int, int, int]:
    duration = estimate_minutes(item)
    if duration is None:
        fit = 1
        duration_score = 0
    elif duration <= available_minutes:
        fit = 3
        duration_score = -duration
    elif duration <= available_minutes * 2:
        fit = 0
        duration_score = -duration
    else:
        fit = -3
        duration_score = -duration
    status_bonus = {"needs_founder": 2, "working": 1, "ready": 0}.get(item.get("status"), 0)
    evidence_bonus = 1 if str(item.get("evidence", "")).strip() else 0
    return (
        fit,
        PRIORITY_ORDER.get(str(item.get("priority")), 0),
        status_bonus,
        evidence_bonus,
        duration_score,
        int(item.get("id", 0)),
    )


def explanation(item: dict[str, Any], available_minutes: int) -> str:
    priority = str(item.get("priority", "medium"))
    duration = estimate_minutes(item)
    fit = (
        f"fits the {available_minutes}-minute window"
        if duration is not None and duration <= available_minutes
        else f"is the strongest available priority for a {available_minutes}-minute window"
    )
    estimate = f" Estimated effort: {duration} minutes." if duration is not None else ""
    return f"{item.get('title')} is {priority} priority and {fit}.{estimate}"


def recommend_focus(
    queue_items: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    available_minutes: int | str,
) -> dict[str, Any]:
    minutes = parse_minutes(available_minutes)
    candidates = [
        item for item in queue_items
        if item.get("status") in FOCUS_STATUSES and not deferred_related(item, memories)
    ]
    candidates.sort(key=lambda item: _sort_key(item, minutes), reverse=True)
    recommendation = candidates[0] if candidates else None
    alternative = candidates[1] if len(candidates) > 1 else None
    return {
        "minutes": minutes,
        "recommendation": recommendation,
        "alternative": alternative,
        "why": explanation(recommendation, minutes) if recommendation else "No supported work fits this window.",
    }


def load_memories(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM memory WHERE status != 'archived'")]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Founder Focus")
    parser.add_argument("minutes", help="available time, for example 30m or 3h")
    parser.add_argument("--queue-db")
    parser.add_argument("--memory-db")
    args = parser.parse_args(argv)
    try:
        queue = load_queue_module()
        queue_path = Path(args.queue_db).expanduser() if args.queue_db else queue.default_database_path()
        connection = queue.connect(queue_path)
        try:
            rows = list(connection.execute("SELECT * FROM queue_item WHERE status != 'done'"))
            items = [queue.as_dict(row) for row in rows]
        finally:
            connection.close()
        memory_path = Path(args.memory_db).expanduser() if args.memory_db else Path(
            os.environ.get("FOUNDER_MEMORY_DB", Path(os.environ.get("HERMES_HOME", "/var/lib/hermes"))
            / "founder-memory" / "memory.db")
        )
        result = recommend_focus(items, load_memories(memory_path), args.minutes)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
