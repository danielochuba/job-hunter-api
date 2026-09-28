"""Web page adapter: JSON-LD JobPosting extraction, readable text, company-site email scan."""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

from ...domain.contacts import extract_emails
from ...domain.jobs import company_domain_from_url
from ..sources.http import BROWSER_UA, SESSION, TIMEOUT, iso, text_of

SITE_EMAIL_PATHS = ("", "/careers", "/jobs", "/contact", "/about", "/company")


def _jsonld_postings(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    yield node
                if "@graph" in node:
                    stack.append(node["@graph"])


def _location(posting):
    locs = posting.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    out = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, str):
            out.append(a)
            continue
        country = a.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        out.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), country) if x))
    remote = posting.get("jobLocationType") == "TELECOMMUTE"
    s = "; ".join(x for x in out if x)
    return (f"{s} (Remote)".strip() if remote else s), ("remote" if remote else None)


def _salary(posting):
    base = posting.get("baseSalary") or {}
    if not isinstance(base, dict):
        return None
    v, cur = base.get("value") or {}, base.get("currency", "")
    if isinstance(v, dict):
        lo, hi, unit = v.get("minValue"), v.get("maxValue"), v.get("unitText") or ""
        if lo or hi or v.get("value"):
            rng = f"{lo}–{hi}" if lo and hi else str(lo or hi or v.get("value"))
            return f"{cur} {rng} {unit.lower()}".strip()
    return None


def jsonld_job(url, soup):
    posting = next(_jsonld_postings(soup), None)
    if not posting:
        return None
    org = posting.get("hiringOrganization") or {}
    org = org if isinstance(org, dict) else {"name": str(org)}
    location, remote = _location(posting)
    return {"company": org.get("name", ""),
            "company_domain": company_domain_from_url(org.get("sameAs") or org.get("url"))
            or company_domain_from_url(url),
            "title": text_of(posting.get("title", "")), "location": location,
            "description": text_of(posting.get("description", "")), "posted_at": iso(posting.get("datePosted")),
            "remote_policy": remote, "salary": _salary(posting)}


def readable_text(soup):
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


class HttpWebPages:
    def __init__(self, timeout=TIMEOUT):
        self.timeout = timeout
        self.headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en"}

    def _get(self, url, timeout=None):
        try:
            return SESSION.get(url, headers=self.headers, timeout=timeout or self.timeout)
        except requests.RequestException:
            return None

    def job_posting(self, url):
        r = self._get(url)
        if r is None or r.status_code >= 400:
            return None, ""
        soup = BeautifulSoup(r.text, "html.parser")
        job = jsonld_job(url, soup)
        return job, readable_text(soup)

    def site_text(self, domain, paths=("", "/about"), limit=6000):
        chunks = []
        for path in paths:
            r = self._get(f"https://{domain}{path}", timeout=10)
            if r is not None and r.status_code == 200:
                chunks.append(readable_text(BeautifulSoup(r.text, "html.parser"))[: limit // len(paths)])
        return "\n\n".join(chunks)

    def site_emails(self, domain):
        found = []
        for path in SITE_EMAIL_PATHS:
            r = self._get(f"https://{domain}{path}", timeout=10)
            if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            mailtos = [a["href"][7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')]
            for e in extract_emails(" ".join(mailtos) + " " + soup.get_text(" ")):
                if e.endswith("@" + domain) or e.endswith("." + domain):
                    if e not in found:
                        found.append(e)
            time.sleep(0.3)
        return found

    def domain_exists(self, domain):
        try:
            r = requests.head(f"https://{domain}", headers=self.headers, timeout=8, allow_redirects=True)
            return r.status_code < 500
        except requests.RequestException:
            return False
