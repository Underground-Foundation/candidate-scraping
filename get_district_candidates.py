#!/usr/bin/env python3
"""Scrape the Legislative Assembly candidates for every district from the VEC website into a CSV.

Fetches the districts page (e.g. https://www.vec.vic.gov.au/electoral-boundaries/state-districts)
and collects the <a> elements inside its <main> whose text ends in "District" (<main> also
contains navigation links such as "Listen", "Find voting centres" and the A-Z jump links). The
district's name is the link text with the trailing "District" removed, e.g. "Albert Park".

Then for each district it visits the nominations page (the district's URL plus "/nominations")
and reads the candidates from the table in its <main>. In the candidates column each cell holds
the candidate's name as text, followed by their party in a <p>; a cell with no <p> is an
Independent candidate.

The CSV is in the same format as parse_candidates.py writes: Electorate, Candidate, Party, House,
URL, with names and parties converted to the ones the Wikipedia page uses.
"""

import argparse
import csv
import difflib
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from parse_candidates import (ASSEMBLY, FIELDNAMES, VEC_COLUMN_HEADER, clean_text,
                              vec_candidate_name, vec_party)
from user_agent import add_browser_arguments, browser_from_args

DEFAULT_URL = "https://www.vec.vic.gov.au/electoral-boundaries/state-districts"
DEFAULT_OUTPUT = "candidates_vec_web.csv"

DISTRICT_SUFFIX = re.compile(r"\s+District$", re.IGNORECASE)


def parse_districts(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main is None:
        raise ValueError("No <main> element found on the page")

    districts = []
    seen = set()
    for link in main.find_all("a", href=True):
        text = " ".join(link.get_text().split())
        if not DISTRICT_SUFFIX.search(text):
            # Ignore links to other things
            continue
        url = urljoin(base_url, link["href"])
        if url in seen:
            continue
        seen.add(url)
        districts.append({"url": url, "name": DISTRICT_SUFFIX.sub("", text)})
    return districts


def get_nomination_url_for_district(district_url: str) -> str:
    """The page listing a district's nominated candidates, e.g.
    .../state-districts/albert-park-district -> .../state-districts/albert-park-district/nominations"""
    return district_url.rstrip("/") + "/nominations"


def find_column(table: Tag, wanted: str) -> int:
    """The index of the table's column whose header most closely resembles `wanted`."""
    header_row = table.find("tr")
    headers = [clean_text(th.get_text()) for th in header_row.find_all(["th", "td"])]
    by_similarity = sorted(range(len(headers)), reverse=True, key=lambda i: difflib.SequenceMatcher(
        None, headers[i].lower(), wanted.lower()).ratio())
    if not by_similarity:
        raise ValueError(f"The table has no column headers: {table}")
    return by_similarity[0]


def split_candidate_cell(cell: Tag) -> tuple[str, str]:
    """A candidates cell holds the name as text, then the party (if any) in a <p>:
    "SEMMENS, Sonya<p>The Greens</p>" -> ("SEMMENS, Sonya", "The Greens")."""
    party_tag = cell.find("p")
    name_parts = []
    for node in cell.children:
        if node is party_tag:
            break
        name_parts.append(str(node) if isinstance(node, NavigableString) else node.get_text())
    party = clean_text(party_tag.get_text()) if party_tag else ""
    return clean_text("".join(name_parts)), party


def parse_nominations(html: str, electorate: str) -> list[dict]:
    """Parse a district's nominations page into candidate records."""
    main = BeautifulSoup(html, "html.parser").find("main")
    if main is None:
        raise ValueError(f"No <main> element found on the nominations page for {electorate}")
    table = main.find("table")
    if table is None:
        raise ValueError(f"No <table> found on the nominations page for {electorate}")
    column = find_column(table, VEC_COLUMN_HEADER)

    records = []
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) <= column:
            continue  # a header row
        name, party = split_candidate_cell(cells[column])
        if not name:
            continue
        records.append({"Electorate": electorate, "Candidate": vec_candidate_name(name),
                        "Party": vec_party(party, electorate), "House": ASSEMBLY, "URL": ""})
    if not records:
        print(f"Warning: no candidates found for {electorate}", file=sys.stderr)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", nargs="?", default=DEFAULT_URL,
                        help="Page listing the districts (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help="CSV file to write (default: %(default)s)")
    add_browser_arguments(parser)
    args = parser.parse_args()

    records = []
    with browser_from_args(args) as browser:
        districts = parse_districts(browser.get(args.url), args.url)
        if not districts:
            print("No district links found", file=sys.stderr)
            return 1
        for i, district in enumerate(districts, 1):
            print(f"[{i}/{len(districts)}] {district['name']}", file=sys.stderr)
            html = browser.get(get_nomination_url_for_district(district["url"]))
            records += parse_nominations(html, district["name"])

    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records)} candidates across {len(districts)} districts to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
