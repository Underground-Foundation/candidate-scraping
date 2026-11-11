"""Shared browser scraping helpers: a Firefox (Selenium) driver with an optional User-Agent
override and cookies loaded from a JSON export or Netscape cookies.txt file."""

import argparse
import http.cookiejar
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service


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
    # Prefer a geckodriver already on PATH. Passing an explicit driver path stops Selenium Manager
    # from also choosing a browser binary, which on Ubuntu is the /usr/bin/firefox shell wrapper for
    # the snap; geckodriver rejects that ("binary is not a Firefox executable") but finds the real
    # Firefox itself when left to its own devices.
    geckodriver = geckodriver or shutil.which("geckodriver")
    service = Service(executable_path=geckodriver) if geckodriver else Service()
    return webdriver.Firefox(options=options, service=service)


class Browser:
    """A Firefox session for loading several pages, with the cookies and User-Agent if given.

    Use as a context manager so that Firefox is closed afterwards:

        with Browser(cookies_file) as browser:
            html = browser.get(url)
    """

    def __init__(self, cookies_file: Path | None = None, user_agent: str | None = None,
                 headless: bool = True, geckodriver: str | None = None):
        self.cookies = load_cookies(cookies_file) if cookies_file else []
        self.driver = build_driver(user_agent, headless, geckodriver)
        self.cookie_hosts: set[str] = set()

    def get(self, url: str) -> str:
        """Load the URL and return its HTML."""
        self.driver.get(url)
        host = urlparse(url).hostname or ""
        if self.cookies and host not in self.cookie_hosts:
            # Cookies can only be added once the browser is on their host, so the first visit to
            # each host adds them and then reloads so the request is made with them attached.
            add_cookies(self.driver, url, self.cookies)
            self.cookie_hosts.add(host)
            self.driver.get(url)
        return self.driver.page_source

    def close(self) -> None:
        self.driver.quit()

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def fetch_html(url: str, cookies_file: Path | None = None, user_agent: str | None = None,
               headless: bool = True, geckodriver: str | None = None) -> str:
    """Load the URL in Firefox, with the cookies and User-Agent if given, and return its HTML."""
    with Browser(cookies_file, user_agent, headless, geckodriver) as browser:
        return browser.get(url)


def add_browser_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the --cookies, --user-agent, --no-headless and --geckodriver options to a parser."""
    parser.add_argument("-c", "--cookies", type=Path,
                        help="Optional cookies file (JSON export or Netscape cookies.txt)")
    parser.add_argument("-u", "--user-agent", help="Optional User-Agent string to send")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show the Firefox window instead of running headless")
    parser.add_argument("--geckodriver", help="Path to geckodriver, if Selenium can't find it itself")


def browser_from_args(args: argparse.Namespace) -> Browser:
    """Open a Browser with the options added by add_browser_arguments."""
    return Browser(args.cookies, args.user_agent, args.headless, args.geckodriver)


def fetch_html_from_args(url: str, args: argparse.Namespace) -> str:
    """Call fetch_html with the options added by add_browser_arguments."""
    return fetch_html(url, args.cookies, args.user_agent, args.headless, args.geckodriver)
