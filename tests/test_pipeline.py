from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "skills/investor-pipeline/scripts/pipeline.py"
LEGACY = (
    "﻿Investor,Contact info,Firm,Status\n"
    'Ada Example,ada@example.com,"Example Ventures, LP","Awaiting reply"\n'
    "Cy Placeholder,cy@example.com,Sample Capital,Times sent\n"
)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.csv = Path(self.temporary.name) / "pipeline.csv"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_helper(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HELPER), *arguments],
                              text=True, capture_output=True, check=False)

    def rows(self) -> list[dict]:
        return list(csv.DictReader(io.StringIO(self.csv.read_text(encoding="utf-8"))))

    def test_set_changes_only_the_named_fields_and_upgrades_the_header(self) -> None:
        self.csv.write_text(LEGACY, encoding="utf-8")
        hostile_contact = "O'Brien \"Fund\"; $(echo hi)\nsecond line"
        result = self.run_helper("set", str(self.csv), "--investor", "Cy Placeholder",
                                 "--contact", hostile_contact,
                                 "--holds", "Fri 9/18 12:00–13:00 PT", "--status", "held")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows()
        self.assertEqual(list(rows[0]), ["Investor", "Contact info", "Firm", "Status", "Holds", "Proposed"])
        self.assertEqual(rows[0], {"Investor": "Ada Example", "Contact info": "ada@example.com",
                                   "Firm": "Example Ventures, LP", "Status": "Awaiting reply",
                                   "Holds": "", "Proposed": ""})
        self.assertEqual(rows[1]["Contact info"], hostile_contact)
        self.assertEqual(rows[1]["Holds"], "Fri 9/18 12:00–13:00 PT")
        self.assertEqual(rows[1]["Status"], "held")
        self.assertEqual(rows[1]["Firm"], "Sample Capital")
        self.assertEqual(json.loads(result.stdout)["Holds"], "Fri 9/18 12:00–13:00 PT")

    def test_set_appends_a_new_investor_and_creates_a_missing_file(self) -> None:
        for existing in (LEGACY, None):
            with self.subTest(existing=existing is not None):
                if existing is None:
                    self.csv.unlink(missing_ok=True)
                else:
                    self.csv.write_text(existing, encoding="utf-8")
                result = self.run_helper("set", str(self.csv),
                                         "--investor", "Bo Sample", "--firm", "Placeholder Capital")
                self.assertEqual(result.returncode, 0, result.stderr)
                last = self.rows()[-1]
                self.assertEqual((last["Investor"], last["Firm"], last["Status"]),
                                 ("Bo Sample", "Placeholder Capital", ""))
                self.assertEqual(len(self.rows()), 3 if existing else 1)

    def test_unknown_columns_and_quoted_values_survive(self) -> None:
        self.csv.write_text('Investor,Notes,Status\nAda,"met at YC, 2024\nsecond line",Warm\n', encoding="utf-8")
        result = self.run_helper("set", str(self.csv), "--investor", "Ada",
                                 "--proposed", "email 9/10 (Scheduling thread)")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["Notes"], "met at YC, 2024\nsecond line")
        self.assertEqual(row["Proposed"], "email 9/10 (Scheduling thread)")
        self.assertEqual(list(row)[:3], ["Investor", "Notes", "Status"])

    def test_set_refuses_and_leaves_the_file_untouched(self) -> None:
        cases = {
            "duplicate investor": (LEGACY + "Cy Placeholder,other@example.com,Other Fund,\n",
                                    ["--investor", "Cy Placeholder", "--status", "x"], "Cy Placeholder"),
            "no Investor column": ("Name,Email,Fund,Stage\nJane Doe,jane@example.com,Acme Fund,Series A\n",
                                    ["--investor", "Jane Doe"], "Investor"),
            "repeated header column": ("Investor,Notes,Status,Notes\nAda,foo,Warm,bar\n",
                                        ["--investor", "Ada", "--status", "x"], None),
            "short row": ("Investor,Contact info,Firm,Status\nJane Doe,jane@example.com\n",
                          ["--investor", "Jane Doe", "--status", "x"], "row 2"),
            "formula-leading status": (LEGACY, ["--investor", "Cy Placeholder", "--status", "=cmd"], "Status"),
        }
        for name, (content, flags, message) in cases.items():
            with self.subTest(case=name):
                self.csv.write_text(content, encoding="utf-8")
                result = self.run_helper("set", str(self.csv), *flags)
                self.assertNotEqual(result.returncode, 0)
                if message:
                    self.assertIn(message, result.stderr)
                self.assertEqual(self.csv.read_text(encoding="utf-8"), content)

    def test_show_returns_one_investor_or_all(self) -> None:
        self.csv.write_text(LEGACY, encoding="utf-8")
        one = json.loads(self.run_helper("show", str(self.csv), "--investor", "Cy Placeholder").stdout)
        every = json.loads(self.run_helper("show", str(self.csv)).stdout)
        self.assertEqual((one["count"], one["rows"][0]["Firm"]), (1, "Sample Capital"))
        self.assertEqual(every["count"], 2)
        self.assertEqual(every["columns"][-2:], ["Holds", "Proposed"])


if __name__ == "__main__":
    unittest.main()
