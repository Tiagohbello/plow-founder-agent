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
    'Leah Solivan,leah@example.com,"Fuel, Capital","Awaiting reply"\n'
    "Paul,paul@example.com,Flex Capital,Times sent\n"
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
        result = self.run_helper("set", str(self.csv), "--investor", "Paul",
                                 "--holds", "Fri 9/18 12:00–13:00 PT", "--status", "Holds placed")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows()
        self.assertEqual(list(rows[0]), ["Investor", "Contact info", "Firm", "Status", "Holds", "Proposed"])
        self.assertEqual(rows[0], {"Investor": "Leah Solivan", "Contact info": "leah@example.com",
                                   "Firm": "Fuel, Capital", "Status": "Awaiting reply",
                                   "Holds": "", "Proposed": ""})
        self.assertEqual(rows[1]["Holds"], "Fri 9/18 12:00–13:00 PT")
        self.assertEqual(rows[1]["Status"], "Holds placed")
        self.assertEqual(rows[1]["Firm"], "Flex Capital")
        self.assertEqual(json.loads(result.stdout)["Holds"], "Fri 9/18 12:00–13:00 PT")

    def test_set_appends_a_new_investor_and_creates_a_missing_file(self) -> None:
        for existing in (LEGACY, None):
            with self.subTest(existing=existing is not None):
                if existing is None:
                    self.csv.unlink(missing_ok=True)
                else:
                    self.csv.write_text(existing, encoding="utf-8")
                result = self.run_helper("set", str(self.csv),
                                         "--investor", "Andrew Lee", "--firm", "a16z")
                self.assertEqual(result.returncode, 0, result.stderr)
                last = self.rows()[-1]
                self.assertEqual((last["Investor"], last["Firm"], last["Status"]), ("Andrew Lee", "a16z", ""))
                self.assertEqual(len(self.rows()), 3 if existing else 1)

    def test_unknown_columns_and_quoted_values_survive(self) -> None:
        self.csv.write_text('Investor,Notes,Status\nLeah,"met at YC, 2024\nsecond line",Warm\n', encoding="utf-8")
        result = self.run_helper("set", str(self.csv), "--investor", "Leah",
                                 "--proposed", "email 9/10 (Scheduling thread)")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["Notes"], "met at YC, 2024\nsecond line")
        self.assertEqual(row["Proposed"], "email 9/10 (Scheduling thread)")
        self.assertEqual(list(row)[:3], ["Investor", "Notes", "Status"])

    def test_hostile_values_round_trip_through_argv_untouched(self) -> None:
        investor = "O'Brien \"Fund\"; $(echo hi)\nsecond line"
        status = "held ' \" ; $(whoami) done"
        result = self.run_helper("set", str(self.csv), "--investor", investor, "--status", status)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["Investor"], investor)
        self.assertEqual(row["Status"], status)

    def test_set_refuses_and_leaves_the_file_untouched(self) -> None:
        cases = {
            "duplicate investor": (LEGACY + "Paul,other@example.com,Other Fund,\n",
                                    ["--investor", "Paul", "--status", "x"], "Paul"),
            "no Investor column": ("Name,Email,Fund,Stage\nJane Doe,jane@example.com,Acme Fund,Series A\n",
                                    ["--investor", "Jane Doe"], "Investor"),
            "repeated header column": ("Investor,Notes,Status,Notes\nLeah,foo,Warm,bar\n",
                                        ["--investor", "Leah", "--status", "x"], None),
            "short row": ("Investor,Contact info,Firm,Status\nJane Doe,jane@example.com\n",
                          ["--investor", "Jane Doe", "--status", "x"], "row 2"),
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
        one = json.loads(self.run_helper("show", str(self.csv), "--investor", "Paul").stdout)
        every = json.loads(self.run_helper("show", str(self.csv)).stdout)
        self.assertEqual((one["count"], one["rows"][0]["Firm"]), (1, "Flex Capital"))
        self.assertEqual(every["count"], 2)
        self.assertEqual(every["columns"][-2:], ["Holds", "Proposed"])


if __name__ == "__main__":
    unittest.main()
