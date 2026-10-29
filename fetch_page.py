#!/usr/bin/env python3
"""Download a web page with a Firefox (Selenium) driver and save its HTML locally."""

import argparse
import http.cookiejar
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

DEFAULT_URL = "https://en.wikipedia.org/wiki/Candidates_of_the_2026_Victorian_state_election"
DEFAULT_OUTPUT = "Candidates of the 2026 Victorian state election - Wikipedia.html"


def load_cookies(path: Path) -> list[dict]:
    """Load cookies from either a JSON export or a Netscape/Mozilla cookies.txt file.

    JSON may be a list of cookie objects (as exported by most browser extensions), or
    an object with a "cookies" list. Each cookie needs at least "name" and "value".
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        jar = http.cookiejar.MozillaCookieJar()
        jar.load(str(path), ignore_discard=True, ignore_expires=True)
        return [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                **({"expiry": int(c.expires)} if c.expires else {}),
            }
            for c in jar
        ]

    if isinstance(data, dict):
        data = data.get("cookies", [])
    cookies = []
    for c in data:
        cookie = {"name": c["name"], "value": c["value"]}
        for key in ("domain", "path", "secure", "httpOnly", "sameSite"):
            if key in c:
                cookie[key] = c[key]
        # Browser extensions commonly call this "expirationDate"; Selenium wants "expiry".
        expiry = c.get("expiry", c.get("expirationDate"))
        if expiry is not None:
            cookie["expiry"] = int(expiry)
        if cookie.get("sameSite") not in (None, "Strict", "Lax", "None"):
            # Normalise values like "no_restriction" / "lax" from extension exports.
            cookie["sameSite"] = {"lax": "Lax", "strict": "Strict"}.get(
                str(cookie["sameSite"]).lower(), "None"
            )
        if cookie.get("sameSite") == "None" and not cookie.get("secure"):
            # Firefox rejects SameSite=None cookies that aren't marked secure.
            del cookie["sameSite"]
        cookies.append(cookie)
    return cookies


def add_cookies(driver: webdriver.Firefox, url: str, cookies: list[dict]) -> None:
    """Add cookies that apply to the URL's host. The driver must already be on that host."""
    host = urlparse(url).hostname or ""
    for cookie in cookies:
        domain = cookie.get("domain", host).lstrip(".")
        if not (host == domain or host.endswith("." + domain)):
            continue
        try:
            driver.add_cookie(cookie)
        except Exception as e:  # noqa: BLE001 - one bad cookie shouldn't abort the scrape
            reason = str(e).strip().splitlines()[0]
            print(f"Warning: could not add cookie {cookie['name']!r}: {reason}", file=sys.stderr)


def build_driver(user_agent: str | None, headless: bool, geckodriver: str | None) -> webdriver.Firefox:
    options = Options()
    if headless:
        options.add_argument("-headless")
    if user_agent:
        options.set_preference("general.useragent.override", user_agent)
    service = Service(executable_path=geckodriver) if geckodriver else Service()
    return webdriver.Firefox(options=options, service=service)


def scrape(url: str, output: Path, cookies_file: Path | None, user_agent: str | None,
           headless: bool, geckodriver: str | None) -> None:
    driver = build_driver(user_agent, headless, geckodriver)
    try:
        driver.get(url)
        if cookies_file:
            add_cookies(driver, url, load_cookies(cookies_file))
            # Reload so the request is made with the cookies attached.
            driver.get(url)
        output.write_text(driver.page_source, encoding="utf-8")
    finally:
        driver.quit()
    print(f"Saved {url} to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Page to download (default: %(default)s)")
    parser.add_argument("-o", "--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help="Where to save the HTML (default: %(default)s)")
    parser.add_argument("-c", "--cookies", type=Path,
                        help="Optional cookies file (JSON export or Netscape cookies.txt)")
    parser.add_argument("-u", "--user-agent", help="Optional User-Agent string to send")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show the Firefox window instead of running headless")
    parser.add_argument("--geckodriver", help="Path to geckodriver, if Selenium can't find it itself")
    args = parser.parse_args()

    scrape(args.url, args.output, args.cookies, args.user_agent, args.headless, args.geckodriver)


if __name__ == "__main__":
    main()
