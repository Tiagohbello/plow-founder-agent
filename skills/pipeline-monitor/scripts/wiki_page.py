#!/usr/bin/env python3
"""One wiki page's frontmatter: read it, change the fields you name, keep the rest.

Stdlib only, like every helper here. The parser is deliberately narrow -- flat
`key: value` scalars, which is all a pipeline page's frontmatter holds -- so a page
using a YAML feature it does not cover fails loudly instead of being silently
rewritten into something else.
"""
from __future__ import annotations

import json
import re

FENCE = "---"
# Values reach here from email. A newline forges a sibling field, `---` ends the
# block, and a quote or backslash escapes the scalar we emit. Refuse rather than
# escape: nothing a founder would legitimately put in these fields needs them.
# A key forges a field, so it stays a strict identifier. `fullmatch`, not `match`:
# `$` also matches before a trailing newline, which `match` would let through.
SAFE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


def decode(raw: str) -> str:
    """A double-quoted scalar's real value; anything else verbatim."""
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def encode(value: str) -> str:
    """A JSON string literal, which is also a valid YAML double-quoted scalar.

    Hand-written escaping kept missing things -- first a terminal newline, then
    U+0085 and U+2028, which `splitlines` breaks on and which would have turned
    model-written advice into a forged frontmatter field. `json.dumps` escapes
    every control character and every non-ASCII codepoint by construction, so the
    set cannot drift out of date the way a table maintained by hand does."""
    return json.dumps(value)


def read(text: str) -> tuple[dict, str]:
    """`(frontmatter, body)`. A page without a frontmatter block is not a page."""
    if not text.startswith(FENCE + "\n"):
        raise ValueError("page has no frontmatter block")
    closing = text.find("\n" + FENCE + "\n", len(FENCE))
    if closing == -1:
        raise ValueError("page frontmatter block is not closed")
    front = {}
    for number, line in enumerate(text[len(FENCE) + 1:closing].splitlines(), start=2):
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"frontmatter line {number} is not `key: value`")
        front[key.strip()] = decode(value.strip())
    return front, text[closing + len(FENCE) + 2:]


def merge(text: str, changes: dict) -> str:
    """The page with `changes` applied.

    Lines this does not change are copied through byte for byte, so a field's
    type, spacing and quoting survive it -- `generated: true` stays a boolean
    rather than becoming the string "true" because some unrelated field moved.
    It also means a value the page already held cannot be corrupted here, and an
    odd one somewhere else cannot block a legitimate update."""
    read(text)  # a page whose block does not parse is not one to edit
    for key, value in changes.items():
        if not SAFE_KEY.fullmatch(key) or not isinstance(value, str):
            raise ValueError(f"{key!r}: cannot be written to frontmatter safely")
    closing = text.find("\n" + FENCE + "\n", len(FENCE))
    written, lines = set(), []
    for line in text[len(FENCE) + 1:closing].splitlines():
        key = line.partition(":")[0].strip()
        if key in changes:
            lines.append(f"{key}: {encode(changes[key])}")
            written.add(key)
        else:
            lines.append(line)
    lines += [f"{key}: {encode(value)}" for key, value in changes.items() if key not in written]
    return FENCE + "\n" + "\n".join(lines) + "\n" + FENCE + "\n" + text[closing + len(FENCE) + 2:]
