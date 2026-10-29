#!/usr/bin/env python3
"""Parse the Legislative Assembly candidates table from a saved Wikipedia page into a CSV.

Output has one row per candidate, with columns Electorate, Candidate, Party.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

DEFAULT_INPUT = "Candidates of the 2026 Victorian state election - Wikipedia.html"
DEFAULT_OUTPUT = "legislative_assembly_candidates.csv"

# Abbreviations used in brackets after a candidate's name, e.g. "Andrew Cook (L)".
PARTY_ABBREVIATIONS = {
    "AJP": "Animal Justice",
    "FF": "Family First",
    "Ind": "Independent",
    "L": "Liberal",
    "LBT": "Libertarian",
    "N": "National",
    "SA": "Socialist Alliance",
    "West": "The West Party",
}

# Matches "Name (Party)" with an optional trailing bracketed party.
CANDIDATE_RE = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<party>[^()]*)\))?$")


def find_assembly_table(soup: BeautifulSoup) -> Tag:
    heading = soup.find(id="Legislative_Assembly")
    if heading is None:
        sys.exit("Could not find the 'Legislative Assembly' heading")
    # Newer Wikipedia markup wraps the <h2> in a <div class="mw-heading">, older doesn't.
    if heading.parent and "mw-heading" in (heading.parent.get("class") or []):
        heading = heading.parent
    table = heading.find_next("table", class_="wikitable")
    if table is None:
        sys.exit("Could not find a table after the 'Legislative Assembly' heading")
    return table


def column_party(header: Tag) -> str:
    """Party for a column header like "Labor candidate"; returns "" for mixed columns."""
    text = header.get_text(" ", strip=True)
    return re.sub(r"\s*candidates?$", "", text, flags=re.IGNORECASE)


def cell_lines(cell: Tag) -> list[str]:
    """Text of a cell split on <br>, with footnote markers removed."""
    for sup in cell.find_all("sup"):
        sup.decompose()
    for br in cell.find_all("br"):
        br.replace_with("\n")
    text = cell.get_text()
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


def resolve_party(abbreviation: str | None, default: str, electorate: str, line: str) -> str:
    if not abbreviation:
        return default
    if abbreviation in PARTY_ABBREVIATIONS:
        return PARTY_ABBREVIATIONS[abbreviation]
    print(f"Warning: unknown party abbreviation {abbreviation!r} in {electorate}: {line!r}",
          file=sys.stderr)
    return abbreviation


def parse_table(table: Tag) -> list[dict]:
    rows = table.find_all("tr")
    headers = rows[0].find_all(["th", "td"], recursive=False)
    # Columns: Electorate, Held by, <party> candidate..., Other candidates
    candidate_columns = range(2, len(headers))
    other_column = len(headers) - 1
    parties = {i: column_party(headers[i]) for i in candidate_columns}
    parties[other_column] = ""

    records = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) != len(headers):
            continue
        electorate = cells[0].get_text(" ", strip=True)
        if not electorate:  # e.g. the row of party colour swatches
            continue
        for i in candidate_columns:
            for line in cell_lines(cells[i]):
                match = CANDIDATE_RE.match(line)
                name = match["name"]
                party = resolve_party(match["party"], parties[i], electorate, line)
                records.append({"Electorate": electorate, "Candidate": name, "Party": party})
    return drop_partyless_duplicates(records)


def drop_partyless_duplicates(records: list[dict]) -> list[dict]:
    """Drop a party-less entry when the same person is also listed with a party in that
    electorate (e.g. Mornington lists "Adrian Maher" and "Adrian Maher (Ind)")."""
    with_party = {(r["Electorate"], r["Candidate"]) for r in records if r["Party"]}
    return [r for r in records
            if r["Party"] or (r["Electorate"], r["Candidate"]) not in with_party]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path(DEFAULT_INPUT),
                        help="Saved HTML page (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help="CSV file to write (default: %(default)s)")
    args = parser.parse_args()

    soup = BeautifulSoup(args.input.read_text(encoding="utf-8"), "html.parser")
    records = parse_table(find_assembly_table(soup))

    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Electorate", "Candidate", "Party"])
        writer.writeheader()
        writer.writerows(records)

    electorates = len({r["Electorate"] for r in records})
    print(f"Wrote {len(records)} candidates across {electorates} electorates to {args.output}")


if __name__ == "__main__":
    main()
