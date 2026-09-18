#!/usr/bin/env python3
"""One wiki page's frontmatter: read it, change the fields you name, keep the rest.

Stdlib only, like every helper here. The parser is deliberately narrow -- flat
`key: value` scalars, which is all a pipeline page's frontmatter holds -- so a page
using a YAML feature it does not cover fails loudly instead of being silently
rewritten into something else.
"""
from __future__ import annotations

import re

FENCE = "---"
# Values reach here from email. A newline forges a sibling field, `---` ends the
# block, and a quote or backslash escapes the scalar we emit. Refuse rather than
# escape: nothing a founder would legitimately put in these fields needs them.
SAFE_VALUE = re.compile(r"^[^\n\r\t\"\\]*$")
# A key forges a field just as well as a value does, and a page may already hold
# one written before this module existed -- so the check belongs where the block
# is built, not on the way in.
SAFE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


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
        front[key.strip()] = value.strip().strip('"')
    return front, text[closing + len(FENCE) + 2:]


def merge(text: str, changes: dict) -> str:
    """The page with `changes` applied and everything else -- order, other keys,
    body -- exactly as it was.

    Every field is checked as the block is built, not just the ones changed: a
    value carrying a quote from before this guard existed would otherwise be
    re-emitted inside a fresh pair of them and silently break the page the next
    time any unrelated field was touched."""
    front, body = read(text)
    front.update(changes)
    lines = []
    for key, value in front.items():
        if not SAFE_KEY.match(key) or not isinstance(value, str) or not SAFE_VALUE.match(value):
            raise ValueError(f"{key!r}: cannot be written to frontmatter safely")
        lines.append(f'{key}: "{value}"')
    return f"{FENCE}\n" + "\n".join(lines) + f"\n{FENCE}\n{body}"
