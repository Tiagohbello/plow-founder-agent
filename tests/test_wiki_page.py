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

    def test_anything_that_could_break_out_of_the_block_is_refused(self) -> None:
        # Values arrive from email; a key forges a field just as well as a value.
        for field, hostile in [("next_step", "---\ntype: Policy"),
                               ("next_step", "line one\nstatus: held"),
                               ("next_step", 'quote " then: colon'),
                               ("next_step", "trailing backslash \\"),
                               ("next_step", "\ttab-led"),
                               ("rogue\nstatus", "held"),
                               ("rogue: colon", "held")]:
            with self.subTest(field=field, value=hostile):
                with self.assertRaises(ValueError):
                    wiki_page.merge(PAGE, {field: hostile})

    def test_lines_it_does_not_change_come_through_byte_for_byte(self) -> None:
        # A boolean stays a boolean and an awkward pre-existing value survives:
        # re-serializing every field would turn `generated: true` into "true" and
        # wrap the embedded quotes in another pair.
        page = PAGE.replace("title: Ada Example",
                            'title: The "Big" Deal Corp\ngenerated: true\ncount: 3')
        out = wiki_page.merge(page, {"next_step": "Reply Thursday"})
        self.assertIn('title: The "Big" Deal Corp', out)
        self.assertIn("generated: true", out)
        self.assertIn("count: 3", out)
        self.assertIn('next_step: "Reply Thursday"', out)

    def test_a_trailing_newline_cannot_slip_past_the_guard(self) -> None:
        # `$` matches before a final newline, so `match` would accept this and emit
        # frontmatter that read() then refuses.
        with self.assertRaises(ValueError):
            wiki_page.merge(PAGE, {"next_step": "Reply Thursday\n"})

    def test_a_page_without_frontmatter_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ValueError):
            wiki_page.read("# Just a heading\n")


if __name__ == "__main__":
    unittest.main()
