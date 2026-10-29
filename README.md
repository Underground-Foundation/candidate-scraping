# Candidate Scraping
This program is intended to scrape a Wikipedia page about an election,
eg <https://en.wikipedia.org/wiki/Candidates_of_the_2026_Victorian_state_election>

The parsed candidates are then written to a CSV file.

This is intended to be used in conjunction with
[underground-ballot](https://github.com/Underground-Foundation/underground-ballot).

The intended flow is:
1. `python fetch_page.py --url https://en.wikipedia.org/wiki/Candidates_of_the_2026_Victorian_state_election --output candidates.html`
2. `python parse_candidates.py candidates.html --output candidates.csv`
3. Use this spreadsheet elsewhere eg [underground-ballot](https://github.com/Underground-Foundation/underground-ballot). 