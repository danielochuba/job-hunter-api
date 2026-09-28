"""HTTP + normalisation helpers shared by the job-source adapters."""
import html
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

TIMEOUT = 20
HEADERS = {"User-Agent": "jobhunter/0.2 (personal job search)"}
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36")
POLITE_DELAY = 0.5  # seconds between requests to the same source


def text_of(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(html.unescape(raw_html), "html.parser")
    return soup.get_text("\n", strip=True)


def get_json(url, params=None):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params=params)
    r.raise_for_status()
    return r.json()


def get_text(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def iso(value):
    """Normalise unix seconds/ms, RFC-822 or ISO strings to ISO-8601 UTC (or None)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    s = str(value).strip()
    if s.isdigit():
        return iso(int(s))
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return s


def salary(lo, hi, currency=""):
    if not lo and not hi:
        return None
    cur = f"{currency} " if currency else ""
    if lo and hi:
        return f"{cur}{int(lo):,}–{int(hi):,}"
    return f"{cur}{int(lo or hi):,}"


def remote(flag, location=""):
    if flag or "remote" in (location or "").lower():
        return "remote"
    return None
