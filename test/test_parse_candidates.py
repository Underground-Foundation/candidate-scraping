"""Tests for parse_candidates.py against the saved sample page."""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from bs4 import BeautifulSoup

import parse_candidates

SAMPLE_PAGE = Path(__file__).parent / "sample_page.html"


class ParseSamplePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        soup = BeautifulSoup(SAMPLE_PAGE.read_text(encoding="utf-8"), "html.parser")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cls.records = parse_candidates.parse_table(parse_candidates.find_assembly_table(soup))
        cls.warnings = stderr.getvalue()

    def candidates(self, electorate):
        return [(r["Candidate"], r["Party"]) for r in self.records if r["Electorate"] == electorate]

    def test_totals(self):
        self.assertEqual(len(self.records), 543)
        self.assertEqual(len({r["Electorate"] for r in self.records}), 88)

    def test_no_warnings(self):
        self.assertEqual(self.warnings, "")

    def test_every_candidate_has_a_name_and_party(self):
        for r in self.records:
            self.assertTrue(r["Candidate"], r)
            self.assertTrue(r["Party"], r)
            self.assertNotIn("(", r["Candidate"], r)
            self.assertNotIn("[", r["Candidate"], r)  # footnote markers removed

    def test_party_columns_and_abbreviations(self):
        self.assertEqual(self.candidates("Albert Park")[:5], [
            ("Nina Taylor", "Labor"),
            ("Andrew Cook", "Liberal"),
            ("Sonya Semmens", "Greens"),
            ("Tammy Lindrum", "One Nation"),
            ("Colleen Bolger", "Socialists"),
        ])

    def test_multiple_other_candidates(self):
        self.assertEqual(self.candidates("Kew")[5:], [
            ("Sophie Torney", "Independent"),
            ("Ann Seeley", "Family First"),
        ])

    def test_west_party(self):
        self.assertIn(("Minh Quan Nguyen", "The West Party"), self.candidates("Footscray"))
        self.assertEqual(Counter(r["Party"] for r in self.records)["The West Party"], 10)

    def test_partyless_duplicate_dropped(self):
        maher = [c for c in self.candidates("Mornington") if c[0] == "Adrian Maher"]
        self.assertEqual(maher, [("Adrian Maher", "Independent")])

    def test_colour_swatch_row_skipped(self):
        self.assertNotIn("", {r["Electorate"] for r in self.records})


class MainTest(unittest.TestCase):
    def test_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.csv"
            argv = ["parse_candidates.py", str(SAMPLE_PAGE), "-o", str(output)]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                parse_candidates.main()
            with output.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, ["Electorate", "Candidate", "Party"])
            self.assertEqual(len(rows), 543)
            self.assertEqual(rows[0], {"Electorate": "Albert Park", "Candidate": "Nina Taylor",
                                       "Party": "Labor"})


if __name__ == "__main__":
    unittest.main()
