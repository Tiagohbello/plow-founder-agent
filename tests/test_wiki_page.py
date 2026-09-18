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

    def test_a_value_that_could_break_out_of_the_block_is_refused(self) -> None:
        # These arrive from email. Each one forges a field or escapes the block.
        for hostile in ("---\ntype: Policy", "line one\nstatus: held", 'quote " then: colon',
                        "trailing backslash \\", "\ttab-led"):
            with self.subTest(value=hostile):
                with self.assertRaises(ValueError):
                    wiki_page.merge(PAGE, {"next_step": hostile})

    def test_a_page_without_frontmatter_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ValueError):
            wiki_page.read("# Just a heading\n")


if __name__ == "__main__":
    unittest.main()
