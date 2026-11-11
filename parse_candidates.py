#!/usr/bin/env python3
"""Parse the Legislative Assembly and Legislative Council candidates into a CSV, from either a
saved Wikipedia page (.html) or the VEC's candidate contact persons report (.xls).

Output has one row per candidate, with columns Electorate, Candidate, Party, House, URL.
For a Wikipedia page, the URL is the candidate's own link (usually their Wikipedia article) if
their name is linked, otherwise the first web link in a footnote attached to their name,
otherwise blank. The VEC report has no URLs, so that column is left blank.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

DEFAULT_INPUT = "Candidates of the 2026 Victorian state election - Wikipedia.html"
DEFAULT_OUTPUT = "candidates.csv"

FIELDNAMES = ["Electorate", "Candidate", "Party", "House", "URL"]
# Base for resolving relative wiki links such as "./Nina_Taylor".
WIKI_BASE = "https://en.wikipedia.org/wiki/"

ASSEMBLY = "Legislative Assembly"
COUNCIL = "Legislative Council"

# Abbreviations used in brackets after a candidate's name, e.g. "Andrew Cook (L)".
PARTY_ABBREVIATIONS = {
    "ACP": "Australian Citizens Party",
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


def find_council_tables(soup: BeautifulSoup) -> list[tuple[str, Tag]]:
    """(electorate, table) for each region section under the 'Legislative Council' heading."""
    heading = soup.find(id="Legislative_Council")
    if heading is None:
        sys.exit("Could not find the 'Legislative Council' heading")
    council = heading.find_parent("section")
    if council is None:
        sys.exit("Could not find the <section> containing the 'Legislative Council' heading")
    tables = []
    for section in council.find_all("section", recursive=False):
        council_region = section.find("h3")
        table = section.find("table", class_="wikitable")
        if council_region and table:
            tables.append((council_region.get_text(" ", strip=True), table))
    if not tables:
        sys.exit("Could not find any tables under the 'Legislative Council' heading")
    return tables


def column_party(header: Tag) -> str:
    """Party for a column header like "Labor candidate"; returns "" for mixed columns."""
    text = header.get_text(" ", strip=True).replace("*", "")
    party = re.sub(r"\s*candidates?$", "", text, flags=re.IGNORECASE)
    return PARTY_ABBREVIATIONS.get(party, party)


@dataclass
class Line:
    """One candidate's line within a cell, with the links and footnotes that appear on it."""
    text: str = ""
    links: list[Tag] = field(default_factory=list)
    refs: list[Tag] = field(default_factory=list)


def clean_text(text: str) -> str:
    """Collapse whitespace and remove the asterisks that mark successful candidates."""
    return " ".join(text.replace("*", "").split())


def cell_lines(cell: Tag) -> list[Line]:
    """A cell's lines, split on <br> and <li>. Footnote markers are left out of the text but
    kept in `refs`; links (other than footnote markers) are kept in `links`."""
    lines = [Line()]

    def new_line() -> None:
        if lines[-1].text.strip() or lines[-1].links or lines[-1].refs:
            lines.append(Line())

    def walk(node: Tag) -> None:
        for child in node.children:
            if type(child) is NavigableString:  # skips comments, <style> contents etc.
                parts = str(child).split("\n")
                lines[-1].text += parts[0]
                for part in parts[1:]:
                    new_line()
                    lines[-1].text += part
            elif not isinstance(child, Tag) or child.name in ("style", "script"):
                continue
            elif child.name == "sup":
                if "reference" in (child.get("class") or []):
                    lines[-1].refs.append(child)
            elif child.name == "br":
                new_line()
            elif child.name == "li":
                new_line()
                walk(child)
                new_line()
            else:
                if child.name == "a":
                    lines[-1].links.append(child)
                walk(child)

    walk(cell)
    result = []
    for line in lines:
        line.text = clean_text(line.text)
        if line.text:
            result.append(line)
    return result


def document_root(tag: Tag) -> Tag:
    while tag.parent is not None:
        tag = tag.parent
    return tag


def name_link_url(line: Line, name: str) -> str:
    """URL of a link whose text is the candidate's name (not, say, a party abbreviation)."""
    for link in line.links:
        href = link.get("href", "")
        if href and not href.startswith("#") and clean_text(link.get_text()) == name:
            return urljoin(WIKI_BASE, href)
    return ""


def reference_url(sup: Tag) -> str:
    """First web link in the footnote that a footnote marker like "[71]" points to."""
    anchor = sup.find("a", href=True)
    if anchor is None or not anchor["href"].startswith("#"):
        return ""
    note = document_root(sup).find(id=anchor["href"][1:])
    if note is None:
        return ""
    body = note.find(class_="reference-text") or note
    for link in body.find_all("a", href=True):
        if link["href"].startswith(("http://", "https://", "//")):
            return urljoin("https:", link["href"])
    return ""


def candidate_url(line: Line, name: str) -> str:
    url = name_link_url(line, name)
    for sup in line.refs:
        if url:
            break
        url = reference_url(sup)
    return url


def resolve_party(abbreviation: str | None, default: str, electorate: str, line: str) -> str:
    if not abbreviation:
        return default
    if abbreviation in PARTY_ABBREVIATIONS:
        return PARTY_ABBREVIATIONS[abbreviation]
    print(f"Warning: unknown party abbreviation {abbreviation!r} in {electorate}: {line!r}",
          file=sys.stderr)
    return abbreviation


def parse_candidate_line(line: Line, default_party: str, electorate: str, house: str) -> dict:
    match = CANDIDATE_RE.match(line.text)
    party = resolve_party(match["party"], default_party, electorate, line.text)
    return {"Electorate": electorate, "Candidate": match["name"], "Party": party, "House": house,
            "URL": candidate_url(line, match["name"])}


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
                records.append(parse_candidate_line(line, parties[i], electorate, ASSEMBLY))
    return drop_partyless_duplicates(records)


def parse_council_table(table: Tag, electorate: str) -> list[dict]:
    """Parse a region's table, which repeats a pattern of three rows: party headers, colour
    swatches, then one cell per party listing its candidates."""
    records = []
    parties = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if cells and all(cell.name == "th" for cell in cells):
            parties = [column_party(cell) for cell in cells]
            continue
        columns = [cell_lines(cell) for cell in cells]
        if not any(columns):  # e.g. the row of party colour swatches
            continue
        if len(columns) != len(parties):
            print(f"Warning: {len(columns)} candidate cells under {len(parties)} party headers "
                  f"in {electorate}: {parties}", file=sys.stderr)
        for party, lines in zip(parties, columns):
            for line in lines:
                records.append(parse_candidate_line(line, party, electorate, COUNCIL))
    return records


def parse_council_tables(soup: BeautifulSoup) -> list[dict]:
    records = []
    for electorate, table in find_council_tables(soup):
        records.extend(parse_council_table(table, electorate))
    return records


def drop_partyless_duplicates(records: list[dict]) -> list[dict]:
    """Drop a party-less entry when the same person is also listed with a party in that
    electorate (e.g. Mornington lists "Adrian Maher" and "Adrian Maher (Ind)"). The kept entry
    takes the dropped one's URL if it has none of its own."""
    with_party = {(r["Electorate"], r["Candidate"]): r for r in records if r["Party"]}
    kept = []
    for r in records:
        duplicate_of = with_party.get((r["Electorate"], r["Candidate"]))
        if r["Party"] or duplicate_of is None:
            kept.append(r)
        elif not duplicate_of["URL"]:
            duplicate_of["URL"] = r["URL"]
    return kept


# VEC section headings, e.g. "Albert Park District" or "Eastern Victoria Region".
VEC_HOUSE_SUFFIXES = {" District": ASSEMBLY, " Region": COUNCIL}
# The line under a VEC section heading, e.g. "(1 vacancy, 7 candidates) ".
VEC_COUNT_RE = re.compile(r"^\(\d+ vacanc(?:y|ies), (?P<count>\d+) candidates?\)$")
VEC_COLUMN_HEADER = "Candidates"

# The VEC's registered party names, mapped to the shorter names the Wikipedia page uses, so that
# both sources produce the same Party for a candidate. A blank party (no registered party) is
# mapped to "Independent", as on the Wikipedia page.
VEC_PARTIES = {
    "": "Independent",
    "Affordable Housing Now – Sustainable Australia Party": "Sustainable",
    "Animal Justice Party": "Animal Justice",
    "Australian Citizens Party (Victorian Division)": "Australian Citizens Party",
    "Australian Democrats": "Democrats",
    "Australian Greens Victoria": "Greens",
    "Australian Labor Party - Victorian Branch": "Labor",
    "Christian Alliance Party – Reform AU": "Christian Alliance",
    "Democratic Labour Party (DLP)": "Democratic Labour",
    "Family First Victoria": "Family First",
    "Legalise Cannabis Victoria": "Legalise Cannabis",
    "Liberal Party of Australia - Victorian Division": "Liberal",
    "National Party of Australia - Victoria": "National",
    "One Nation Victoria": "One Nation",
    "Shooters, Fishers and Farmers Party Victoria": "Shooters, Fishers and Farmers",
    "Socialist Alliance": "Socialist Alliance",
    "The Republican Make Australia Great Again": "Republican",
    "The West Party": "The West Party",
    "Victorian Socialists": "Socialists",
    # The shorter names printed on the ballot paper, which the VEC's nominations web pages use.
    "Australian Labor Party": "Labor",
    "Citizens Party": "Australian Citizens Party",
    "Climate Action Now": "Climate Action Now",
    "Family First": "Family First",
    "Free Palestine": "Free Palestine",
    "I'm Voting to Avoid the Fine": "I'm Voting to Avoid the Fine",
    "Labour DLP": "Democratic Labour",
    "Liberal": "Liberal",
    "Libertarian (formerly Liberal Democrats)": "Libertarian",
    "Safety Victoria – Violent Crime Prevention": "Safety Victoria – Violent Crime Prevention",
    "The Greens": "Greens",
    "The Nationals": "National",
    "The Republican": "Republican",
}
# VEC electorate names that the Wikipedia page spells differently.
VEC_ELECTORATES = {
    "North-Eastern Metropolitan": "North Eastern Metropolitan",
    "South-Eastern Metropolitan": "South Eastern Metropolitan",
}
COALITION = "Coalition"
COALITION_PARTIES = {"Liberal", "National"}


def title_case_word(word: str) -> str:
    """Title-case one word of a VEC surname, e.g. "SMITH" -> "Smith". The VEC keeps any
    lowercase it was given ("McKEEMAN", "de VIETRI"), so a lowercase prefix is kept as is.
    All-caps "MC" names become "Mc..." ("MCRAE" -> "McRae")."""
    if word.islower():
        return word  # e.g. the "de" of "de VIETRI"
    prefix = re.match(r"^[a-z]*(?:[A-Z][a-z]+)?", word).group()
    rest = word[len(prefix):]
    if not prefix and rest.startswith("MC") and len(rest) > 2:
        prefix, rest = "Mc", rest[2:]
    if not prefix:
        return rest[:1].upper() + rest[1:].lower()
    return prefix + rest[:1].upper() + rest[1:].lower()


def title_case_surname(surname: str) -> str:
    """Title-case each part of a surname, splitting on spaces, hyphens and apostrophes:
    "MATTHEWS-WARD" -> "Matthews-Ward", "O'BRIEN" -> "O'Brien", "DE SILVA" -> "De Silva"."""
    return "".join(title_case_word(part) if part.strip(" -'’") else part
                   for part in re.split(r"([ \-'’]+)", surname))


def vec_candidate_name(text: str) -> str:
    """ "SURNAME, Given Names" -> "Given Names Surname". Given names are already in mixed case
    (and may contain deliberate capitals, such as "SM Zaberul"), so they're left alone."""
    surname, _, given = text.partition(",")
    return " ".join(part for part in (given.strip(), title_case_surname(surname.strip())) if part)


def vec_party(name: str, electorate: str) -> str:
    if name in VEC_PARTIES:
        return VEC_PARTIES[name]
    print(f"Warning: unknown VEC party {name!r} in {electorate}", file=sys.stderr)
    return name


def label_coalition_tickets(records: list[dict]) -> None:
    """In a Legislative Council region where the Liberals and Nationals run a joint ticket (both
    have candidates there), the Wikipedia page lists their candidates under "Coalition"."""
    parties_by_region: dict[str, set[str]] = {}
    for r in records:
        if r["House"] == COUNCIL:
            parties_by_region.setdefault(r["Electorate"], set()).add(r["Party"])
    joint = {e for e, parties in parties_by_region.items() if COALITION_PARTIES <= parties}
    for r in records:
        if r["House"] == COUNCIL and r["Electorate"] in joint and r["Party"] in COALITION_PARTIES:
            r["Party"] = COALITION


def parse_vec_sheet(rows: list[list]) -> list[dict]:
    """Parse the VEC report's rows. Each electorate is a heading row, a "(N vacancies, M
    candidates)" row, a column header row, then one row per candidate, with the candidate's
    name in the first column and their registered party (blank if none) in the last. Party and
    electorate names are converted to the ones the Wikipedia page uses."""
    records = []
    electorate = house = None
    expected: dict[str, int] = {}
    for row in rows:
        first = str(row[0]).strip()
        if not first:
            continue
        for suffix, suffix_house in VEC_HOUSE_SUFFIXES.items():
            if first.endswith(suffix) and not row[-1]:
                electorate, house = first.removesuffix(suffix), suffix_house
                electorate = VEC_ELECTORATES.get(electorate, electorate)
                break
        else:
            if match := VEC_COUNT_RE.match(first):
                expected[electorate] = int(match["count"])
            elif electorate is not None and first != VEC_COLUMN_HEADER:
                records.append({"Electorate": electorate, "Candidate": vec_candidate_name(first),
                                "Party": vec_party(str(row[-1]).strip(), electorate),
                                "House": house, "URL": ""})

    found = {e: 0 for e in expected}
    for r in records:
        found[r["Electorate"]] = found.get(r["Electorate"], 0) + 1
    for e in found:
        if found[e] != expected.get(e):
            print(f"Warning: {e} lists {expected.get(e)} candidates but {found[e]} were found",
                  file=sys.stderr)
    label_coalition_tickets(records)
    return records


def parse_vec_xls(path: Path) -> list[dict]:
    import xlrd  # only needed for the VEC report
    sheet = xlrd.open_workbook(path).sheet_by_index(0)
    return parse_vec_sheet([sheet.row_values(i) for i in range(sheet.nrows)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path(DEFAULT_INPUT),
                        help="Saved Wikipedia page (.html) or VEC report (.xls) (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help="CSV file to write (default: %(default)s)")
    args = parser.parse_args()

    suffix = args.input.suffix.lower()
    if suffix in (".html", ".htm"):
        soup = BeautifulSoup(args.input.read_text(encoding="utf-8"), "html.parser")
        records = parse_table(find_assembly_table(soup)) + parse_council_tables(soup)
    elif suffix == ".xls":
        records = parse_vec_xls(args.input)
    else:
        sys.exit(f"This file has an unsupported format for parsing: {args.input}")

    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)

    electorates = len({r["Electorate"] for r in records})
    print(f"Wrote {len(records)} candidates across {electorates} electorates to {args.output}")


if __name__ == "__main__":
    main()
