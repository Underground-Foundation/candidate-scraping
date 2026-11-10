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

    def test_every_row_is_in_the_assembly(self):
        self.assertEqual({r["House"] for r in self.records}, {"Legislative Assembly"})


class ParseCouncilTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        soup = BeautifulSoup(SAMPLE_PAGE.read_text(encoding="utf-8"), "html.parser")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cls.records = parse_candidates.parse_council_tables(soup)
        cls.warnings = stderr.getvalue()

    def candidates(self, electorate):
        return [(r["Candidate"], r["Party"]) for r in self.records if r["Electorate"] == electorate]

    def test_totals_per_region(self):
        self.assertEqual(Counter(r["Electorate"] for r in self.records), {
            "Eastern Victoria": 10,
            "North Eastern Metropolitan": 11,
            "Northern Metropolitan": 13,
            "Northern Victoria": 12,
            "South Eastern Metropolitan": 11,
            "Southern Metropolitan": 11,
            "Western Metropolitan": 13,
            "Western Victoria": 15,
        })

    def test_no_warnings(self):
        self.assertEqual(self.warnings, "")

    def test_every_candidate_has_a_name_and_party(self):
        for r in self.records:
            self.assertTrue(r["Candidate"], r)
            self.assertTrue(r["Party"], r)
            self.assertNotIn("[", r["Candidate"], r)  # footnote markers removed

    def test_each_candidate_row_uses_the_headers_above_it(self):
        self.assertEqual(self.candidates("Eastern Victoria"), [
            ("Renee Heath", "Coalition"),
            ("Melina Bath", "Coalition"),
            ("Matt Green", "Coalition"),
            ("Mat Morgan", "Greens"),
            ("Danielle Burridge", "Legalise Cannabis"),
            ("Neil Davison", "One Nation"),
            ("Helen Jaeges", "Animal Justice"),
            ("Max Forward", "Socialists"),
            ("Reade Smith", "Sustainable"),
            ("Antoinette Pitt", "Independent"),
        ])

    def test_singular_header_after_short_swatch_row(self):
        # Northern Victoria's last swatch row has two cells under three headers.
        self.assertIn(("Kate White", "Independent"), self.candidates("Northern Victoria"))

    def test_party_names_match_assembly(self):
        self.assertIn(("Joe Garra", "The West Party"), self.candidates("Western Metropolitan"))

    def test_mismatched_row_warns(self):
        table = BeautifulSoup(
            "<table><tr><th>Labor candidates</th><th>Greens candidates</th></tr>"
            "<tr><td><ol><li>Only Cell</li></ol></td></tr></table>", "html.parser")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            records = parse_candidates.parse_council_table(table, "Somewhere")
        self.assertEqual(records, [{"Electorate": "Somewhere", "Candidate": "Only Cell",
                                    "Party": "Labor", "House": "Legislative Council",
                                    "URL": ""}])
        self.assertIn("1 candidate cells under 2 party headers", stderr.getvalue())

    def test_every_row_is_in_the_council(self):
        self.assertEqual({r["House"] for r in self.records}, {"Legislative Council"})


class AsteriskTest(unittest.TestCase):
    def test_council_names_and_party_headers(self):
        table = BeautifulSoup(
            "<table><tr><th>Labor*<br/>candidates</th></tr>"
            "<tr><td><ol><li>Jane Doe*</li><li>John Doe</li><li>*</li></ol></td></tr></table>",
            "html.parser")
        records = parse_candidates.parse_council_table(table, "Somewhere")
        self.assertEqual([(r["Candidate"], r["Party"]) for r in records],
                         [("Jane Doe", "Labor"), ("John Doe", "Labor")])

    def test_assembly_names_and_bracketed_parties(self):
        table = BeautifulSoup(
            "<table><tr><th>Electorate</th><th>Held by</th><th>Labor* candidate</th>"
            "<th>Other candidates</th></tr>"
            "<tr><td>Kew</td><td>Liberal</td><td>Jane Doe*</td>"
            "<td>Ann Lee* (Ind)<br/>Bob Ray (L)*<br/>Cy Young (FF*)</td></tr></table>",
            "html.parser")
        records = parse_candidates.parse_table(table)
        self.assertEqual([(r["Candidate"], r["Party"]) for r in records], [
            ("Jane Doe", "Labor"),
            ("Ann Lee", "Independent"),
            ("Bob Ray", "Liberal"),
            ("Cy Young", "Family First"),
        ])


class UrlTest(unittest.TestCase):
    PAGE = """
        <table>
          <tr><th>Electorate</th><th>Held by</th><th>Labor candidate</th>
              <th>Other candidates</th></tr>
          <tr><td>Kew</td><td>Liberal</td>
            <td><b><a href="./Jane_Doe">Jane Doe</a></b>*<sup class="reference"><a
                href="#cite_note-1">[1]</a></sup></td>
            <td>Ann Lee (<a href="./Independent_politician">Ind</a>)<sup class="reference"><a
                href="#cite_note-1">[1]</a></sup><sup class="reference"><a
                href="#cite_note-2">[2]</a></sup><br/>
              Bob Ray (L)<br/>
              Cy Young (FF)<sup class="reference"><a href="#cite_note-3">[3]</a></sup></td>
          </tr>
        </table>
        <ol class="references">
          <li id="cite_note-1"><span class="mw-cite-backlink"><a href="#cite_ref-1">^</a></span>
            <span class="reference-text">A note with no link.</span></li>
          <li id="cite_note-2"><span class="mw-cite-backlink"><a href="#cite_ref-2">^</a></span>
            <span class="reference-text"><a class="external text"
              href="https://example.com/ann">Ann Lee for Kew</a></span></li>
          <li id="cite_note-3"><span class="reference-text"><a class="external text"
              href="//example.com/cy">Cy</a></span></li>
        </ol>"""

    def setUp(self):
        soup = BeautifulSoup(self.PAGE, "html.parser")
        records = parse_candidates.parse_table(soup.find("table"))
        self.urls = {r["Candidate"]: r["URL"] for r in records}

    def test_linked_name_beats_reference(self):
        self.assertEqual(self.urls["Jane Doe"], "https://en.wikipedia.org/wiki/Jane_Doe")

    def test_reference_used_when_name_not_linked_and_party_link_ignored(self):
        # The first footnote has no link, so the second is used.
        self.assertEqual(self.urls["Ann Lee"], "https://example.com/ann")

    def test_protocol_relative_reference(self):
        self.assertEqual(self.urls["Cy Young"], "https://example.com/cy")

    def test_no_link_or_reference(self):
        self.assertEqual(self.urls["Bob Ray"], "")

    def test_sample_page_reference_url(self):
        soup = BeautifulSoup(SAMPLE_PAGE.read_text(encoding="utf-8"), "html.parser")
        records = parse_candidates.parse_table(parse_candidates.find_assembly_table(soup))
        urls = {r["Candidate"]: r["URL"] for r in records if r["Electorate"] == "Albert Park"}
        self.assertEqual(urls["Sonya Semmens"], "https://greens.org.au/vic/person/sonya-semmens")


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
            self.assertEqual(reader.fieldnames,
                             ["Electorate", "Candidate", "Party", "House", "URL"])
            self.assertEqual(len(rows), 543 + 96)
            self.assertEqual(rows[0], {"Electorate": "Albert Park", "Candidate": "Nina Taylor",
                                       "Party": "Labor", "House": "Legislative Assembly",
                                       "URL": "https://en.wikipedia.org/wiki/Nina_Taylor"})
            self.assertEqual(rows[543], {"Electorate": "Eastern Victoria",
                                         "Candidate": "Renee Heath", "Party": "Coalition",
                                         "House": "Legislative Council",
                                         "URL": "https://en.wikipedia.org/wiki/Renee_Heath"})


if __name__ == "__main__":
    unittest.main()


class VecNameTest(unittest.TestCase):
    def test_names(self):
        cases = {
            "SEMMENS, Sonya": "Sonya Semmens",
            "KING, Adrian William": "Adrian William King",
            "MCRAE, Ross": "Ross McRae",
            "McKEEMAN, Lachie": "Lachie McKeeman",
            "de VIETRI, Gabrielle": "Gabrielle de Vietri",
            "O'BRIEN, Danny": "Danny O'Brien",
            "D'ARCY, Catherine": "Catherine D'Arcy",
            "MATTHEWS-WARD, Kathleen": "Kathleen Matthews-Ward",
            "DE SILVA, Roshan": "Roshan De Silva",
            "ISLAM, SM Zaberul": "SM Zaberul Islam",
        }
        for vec, expected in cases.items():
            self.assertEqual(parse_candidates.vec_candidate_name(vec), expected)


class ParseVecSheetTest(unittest.TestCase):
    ROWS = [
        ["Candidate Contact Persons' Details Summary Report", "", "", "", ""],
        ["Total Candidates for ALL Electorates", 3.0, "", "", ""],
        ["", "", "", "", ""],
        ["Albert Park District", "", "", "", ""],
        ["(1 vacancy, 2 candidates) ", "", "", "", ""],
        ["Candidates", "Contact Person Name", "Phone Contact", "Email Address", "RPP Name"],
        ["SEMMENS, Sonya", "Jess Wheelock", "", "x@example.org", "Australian Greens Victoria"],
        ["KING, Adrian William", "Adrian King", "", "y@example.org", ""],
        ["", "", "", "", ""],
        ["Eastern Victoria Region", "", "", "", ""],
        ["(5 vacancies, 1 candidates) ", "", "", "", ""],
        ["Candidates", "Contact Person Name", "Phone Contact", "Email Address", "RPP Name"],
        ["BATH, Melina", "Someone", "", "z@example.org", "National Party of Australia - Victoria"],
    ]

    def test_parse(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            records = parse_candidates.parse_vec_sheet(self.ROWS)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual([(r["Electorate"], r["Candidate"], r["Party"], r["House"]) for r in records], [
            ("Albert Park", "Sonya Semmens", "Greens", "Legislative Assembly"),
            ("Albert Park", "Adrian William King", "Independent", "Legislative Assembly"),
            ("Eastern Victoria", "Melina Bath", "National", "Legislative Council"),
        ])

    def test_coalition_and_electorate_names(self):
        rows = [
            ["North-Eastern Metropolitan Region", "", "", "", ""],
            ["(5 vacancies, 1 candidates) ", "", "", "", ""],
            ["WELCH, Richard", "", "", "", "Liberal Party of Australia - Victorian Division"],
            ["Northern Victoria Region", "", "", "", ""],
            ["(5 vacancies, 2 candidates) ", "", "", "", ""],
            ["BROAD, Gaelle", "", "", "", "National Party of Australia - Victoria"],
            ["BROOKS, Steve", "", "", "", "Liberal Party of Australia - Victorian Division"],
        ]
        records = parse_candidates.parse_vec_sheet(rows)
        self.assertEqual([(r["Electorate"], r["Party"]) for r in records], [
            ("North Eastern Metropolitan", "Liberal"),
            ("Northern Victoria", "Coalition"),
            ("Northern Victoria", "Coalition"),
        ])

    def test_warns_on_unknown_party(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            records = parse_candidates.parse_vec_sheet(
                self.ROWS[3:6] + [["SMITH, Jo", "", "", "", "New Party"], self.ROWS[7]])
        self.assertEqual(records[0]["Party"], "New Party")
        self.assertIn("unknown VEC party 'New Party'", stderr.getvalue())

    def test_warns_on_count_mismatch(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            parse_candidates.parse_vec_sheet(self.ROWS[:7])
        self.assertIn("Albert Park lists 2 candidates but 1 were found", stderr.getvalue())
