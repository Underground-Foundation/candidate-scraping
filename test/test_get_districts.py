"""Tests for get_districts.py against the saved VEC state districts page."""

import contextlib
import io
import re
import unittest
from pathlib import Path

from get_districts import get_nomination_url_for_district, parse_districts, parse_nominations

SAMPLE_PAGE = Path(__file__).parent / "State districts _ Victorian Electoral Commission.html"
BASE_URL = "https://www.vec.vic.gov.au/electoral-boundaries/state-districts"


class ParseDistrictsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.districts = parse_districts(SAMPLE_PAGE.read_text(encoding="utf-8"), BASE_URL)
        cls.names = [d["name"] for d in cls.districts]

    def test_total(self):
        # Victoria has 88 Legislative Assembly districts.
        self.assertEqual(len(self.districts), 88)

    def test_first_and_last(self):
        self.assertEqual(self.districts[0], {
            "url": f"{BASE_URL}/albert-park-district",
            "name": "Albert Park",
        })
        self.assertEqual(self.districts[-1], {
            "url": f"{BASE_URL}/yan-yean-district",
            "name": "Yan Yean",
        })

    def test_names_have_district_stripped(self):
        for name in self.names:
            self.assertNotRegex(name, r"(?i)district")
            self.assertEqual(name, name.strip())

    def test_multi_word_names(self):
        for name in ("Bendigo East", "Box Hill", "Narre Warren North"):
            self.assertIn(name, self.names)

    def test_no_navigation_links(self):
        for name in ("Listen", "Find region candidates", "Find voting centres", "A", "Z"):
            self.assertNotIn(name, self.names)

    def test_names_and_urls_are_unique(self):
        self.assertEqual(len(set(self.names)), len(self.names))
        self.assertEqual(len({d["url"] for d in self.districts}), len(self.districts))

    def test_urls_are_absolute_and_match_names(self):
        for d in self.districts:
            slug = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")
            self.assertEqual(d["url"], f"{BASE_URL}/{slug}-district")

    def test_no_main_element(self):
        with self.assertRaises(ValueError):
            parse_districts("<html><body><a href='/x'>X District</a></body></html>", BASE_URL)


# The structure of a VEC nominations page, e.g. .../albert-park-district/nominations: a desktop and
# a mobile header row, then one row per candidate with the name as text and the party in a <p>.
NOMINATIONS_PAGE = """
<html><body>
<header><table><tr><td>Not this table</td></tr></table></header>
<main>
<table class="js-responsive-table">
 <thead>
  <tr class="candidate-row desktop"><th scope="col">Candidates</th><th scope="col">Contact details</th></tr>
  <tr class="candidate-row mobile"><th scope="col">Candidates</th></tr>
 </thead>
 <tbody>
  <tr class="candidate-row">
   <td>
    DRAGWIDGE, Georgie
   </td>
   <td><span>Contact Person</span><br/><span>Mob: 0400 000 000</span></td>
  </tr>
  <tr class="candidate-row">
   <td>
    SEMMENS, Sonya
    <p>The Greens</p>
   </td>
   <td><span>Contact Person</span></td>
  </tr>
  <tr class="candidate-row">
   <td>TAYLOR, Nina<p>Australian Labor Party</p></td>
   <td><span>Contact Person</span></td>
  </tr>
  <tr class="candidate-row">
   <td>McKEEMAN, Adrian William<p>Libertarian (formerly Liberal Democrats)</p></td>
   <td><span>Contact Person</span></td>
  </tr>
 </tbody>
</table>
</main>
</body></html>
"""


class NominationUrlTest(unittest.TestCase):
    def test_appends_nominations(self):
        self.assertEqual(
            get_nomination_url_for_district(f"{BASE_URL}/albert-park-district"),
            f"{BASE_URL}/albert-park-district/nominations")

    def test_trailing_slash(self):
        self.assertEqual(
            get_nomination_url_for_district(f"{BASE_URL}/albert-park-district/"),
            f"{BASE_URL}/albert-park-district/nominations")


class ParseNominationsTest(unittest.TestCase):
    def parse(self, html):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            records = parse_nominations(html, "Albert Park")
        return records, stderr.getvalue()

    def test_candidates(self):
        records, warnings = self.parse(NOMINATIONS_PAGE)
        self.assertEqual(warnings, "")
        self.assertEqual([(r["Candidate"], r["Party"]) for r in records], [
            ("Georgie Dragwidge", "Independent"),
            ("Sonya Semmens", "Greens"),
            ("Nina Taylor", "Labor"),
            ("Adrian William McKeeman", "Libertarian"),
        ])

    def test_same_format_as_parse_candidates(self):
        records, _ = self.parse(NOMINATIONS_PAGE)
        for r in records:
            self.assertEqual(list(r), ["Electorate", "Candidate", "Party", "House", "URL"])
            self.assertEqual(r["Electorate"], "Albert Park")
            self.assertEqual(r["House"], "Legislative Assembly")
            self.assertEqual(r["URL"], "")

    def test_finds_candidates_column_when_not_first(self):
        html = NOMINATIONS_PAGE.replace(
            '<th scope="col">Candidates</th><th scope="col">Contact details</th>',
            '<th scope="col">Ballot position</th><th scope="col">Candidate</th>',
        ).replace('<tr class="candidate-row">\n   <td', '<tr class="candidate-row">\n   <td>1</td><td')
        records, _ = self.parse(html)
        self.assertEqual([r["Candidate"] for r in records][:2], ["Georgie Dragwidge", "Sonya Semmens"])

    def test_unknown_party_is_kept_with_a_warning(self):
        records, warnings = self.parse(NOMINATIONS_PAGE.replace("The Greens", "New Party"))
        self.assertEqual(records[1]["Party"], "New Party")
        self.assertIn("New Party", warnings)

    def test_no_table(self):
        with self.assertRaises(ValueError):
            parse_nominations("<html><body><main><p>No nominations yet</p></main></body></html>",
                              "Albert Park")


if __name__ == "__main__":
    unittest.main()
