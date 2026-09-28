"""HTTP + normalisation helpers shared by the job-source adapters."""
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 20
HEADERS = {"User-Agent": "jobhunter/0.2 (personal job search)"}
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36")
POLITE_DELAY = 0.5  # seconds between requests to the same source


def _session():
    """Shared HTTP session that retries connection drops, DNS blips and 429/5xx with backoff."""
    retry = Retry(total=4, connect=4, read=2, status=3, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "POST"),
                  respect_retry_after_header=True)
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = _session()


def text_of(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(html.unescape(raw_html), "html.parser")
    return soup.get_text("\n", strip=True)


def get_json(url, params=None):
    r = SESSION.get(url, headers=HEADERS, timeout=TIMEOUT, params=params)
    r.raise_for_status()
    return r.json()


def get_text(url):
    r = SESSION.get(url, headers=HEADERS, timeout=TIMEOUT)
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


def relative_iso(text):
    """'3 days ago' / '5 hours ago' / '30+ days ago' -> ISO timestamp (approximate), else None."""
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month)", text or "", re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return (datetime.now(timezone.utc) - delta).isoformat()
