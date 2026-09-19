from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/pipeline-monitor/scripts"))
import wiki_page

PAGE = """---
title: Ada Example
type: PipelineEntry
status: Awaiting reply
next_step: ""
---

## Notes

- Met at the conference. ^[inferred]
"""


class WikiPageTests(unittest.TestCase):
    def test_merge_changes_only_named_fields_and_keeps_the_body(self) -> None:
        out = wiki_page.merge(PAGE, {"next_step": "Reply with two slots Thu/Fri"})
        front, body = wiki_page.read(out)
        self.assertEqual(front["next_step"], "Reply with two slots Thu/Fri")
        self.assertEqual(front["status"], "Awaiting reply")
        self.assertEqual(front["title"], "Ada Example")
        self.assertEqual(list(front), ["title", "type", "status", "next_step"])
        self.assertIn("- Met at the conference. ^[inferred]", body)

    def test_merge_adds_a_field_the_page_does_not_have_yet(self) -> None:
        front, _ = wiki_page.read(wiki_page.merge(PAGE, {"holds": "Fri 9/18 12:00-13:00 PT"}))
        self.assertEqual(front["holds"], "Fri 9/18 12:00-13:00 PT")
        self.assertEqual(front["status"], "Awaiting reply")

    def test_generated_prose_round_trips_instead_of_being_refused(self) -> None:
        # next_step is written by a model. Quotes, em dashes, line breaks and
        # backslashes are ordinary content; refusing them strands the advice.
        for value in ('Ask if "video" works.', "Two slots \u2014 Thu 2pm or Fri 10am",
                      "line one\nline two", "the \\ deck", "tab\there", 'ends with a quote "'):
            with self.subTest(value=value):
                out = wiki_page.merge(PAGE, {"next_step": value})
                self.assertEqual(wiki_page.read(out)[0]["next_step"], value)
                self.assertEqual(wiki_page.read(out)[0]["status"], "Awaiting reply")

    def test_an_escaped_value_cannot_forge_a_field(self) -> None:
        # The encoded form stays on one line, so nothing it contains starts a
        # sibling key or closes the block. `splitlines` breaks on more than \n:
        # U+2028, U+2029 and U+0085 are line breaks to it, and a hand-written
        # escape table missed all three.
        for hostile in ("---\ntype: Policy\nstatus: held",
                        "ok\u2028status: held",
                        "ok\u2029status: held",
                        "ok\u0085status: held",
                        "ok\u000bstatus: held"):
            with self.subTest(value=hostile):
                out = wiki_page.merge(PAGE, {"next_step": hostile})
                self.assertEqual(len([l for l in out.splitlines() if l.startswith("next_step:")]), 1)
                self.assertEqual(len([l for l in out.splitlines() if l.startswith("status:")]), 1)
                self.assertEqual(wiki_page.read(out)[0]["status"], "Awaiting reply")
                self.assertEqual(wiki_page.read(out)[0]["next_step"], hostile)

    def test_a_key_is_still_a_strict_identifier(self) -> None:
        for key in ("rogue\nstatus", "rogue: colon", "has space", ""):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    wiki_page.merge(PAGE, {key: "held"})

    def test_a_page_without_frontmatter_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ValueError):
            wiki_page.read("# Just a heading\n")


if __name__ == "__main__":
    unittest.main()
