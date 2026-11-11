#!/usr/bin/env python3
"""Download a web page with a Firefox (Selenium) driver and save its HTML locally."""

import argparse
from pathlib import Path

from user_agent import add_browser_arguments, fetch_html_from_args

DEFAULT_URL = "https://en.wikipedia.org/wiki/Candidates_of_the_2026_Victorian_state_election"
DEFAULT_OUTPUT = "Candidates of the 2026 Victorian state election - Wikipedia.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Page to download (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help="Where to save the HTML (default: %(default)s)")
    add_browser_arguments(parser)
    args = parser.parse_args()

    args.output.write_text(fetch_html_from_args(args.url, args), encoding="utf-8")
    print(f"Saved {args.url} to {args.output}")


if __name__ == "__main__":
    main()
