"""JobSources port adapter: runs the ATS boards, free aggregators and keyed sources; detects boards
from careers URLs."""
import time

import requests

from ...domain.jobs import match_ats
from .aggregators import AGGREGATORS
from .ats import BOARDS
from .http import BROWSER_UA, HEADERS, POLITE_DELAY, SESSION, TIMEOUT

SOURCE_INFO = {
    "remotive": "Remote jobs, searchable",
    "remoteok": "Remote tech jobs",
    "arbeitnow": "Europe-focused, many visa-friendly",
    "himalayas": "Remote jobs with region info",
    "jobicy": "Remote jobs by tag",
    "weworkremotely": "Remote dev & ops feeds",
    "hn_whoishiring": "Monthly Hacker News hiring thread",
    "workingnomads": "Curated remote jobs, many worldwide",
    "adzuna": "Big job search API (UK, South Africa, ...)",
    "google_jobs": "Google Jobs: LinkedIn, Indeed, Glassdoor & more",
    "reddit": "Hiring posts in job subreddits",
    "web_search": "Hiring posts across the web & discussions",
}


def _finish(job):
    """Some boards (SmartRecruiters) need a request per posting for the description: only done
    for jobs that passed the filters."""
    fetch = job.pop("_fetch_description", None)
    if fetch and not job.get("description"):
        job["description"] = fetch()
    return job


def _call(fn, queries, context):
    """Free aggregators are plain functions of (queries); keyed sources also get the user context."""
    return fn(queries, context) if hasattr(fn, "configured") else fn(queries)


class HttpJobSources:
    company_sources = tuple(BOARDS)

    def __init__(self, keyed=(), boards=None, aggregators=None, delay=POLITE_DELAY):
        self.boards = boards or BOARDS
        self.keyed = {k.name: k for k in keyed}
        self.aggs = {**(aggregators or AGGREGATORS), **self.keyed}
        self.aggregators = tuple(self.aggs)
        self.delay = delay

    def status(self):
        """Per-source availability for the UI: {name: {configured, needs, info}}."""
        out = {}
        for name in self.aggregators:
            k = self.keyed.get(name)
            out[name] = {"configured": k.configured if k else True, "needs": getattr(k, "needs", ""),
                         "info": SOURCE_INFO.get(name, ""), "keyed": bool(k)}
        return out

    def collect(self, companies, queries, aggregators, keep, on_source=None, context=None):
        for source, tokens in (companies or {}).items():
            fn = self.boards.get(source)
            if not fn:
                yield None, f"unknown source '{source}'"
                continue
            for token in tokens or []:
                if on_source:
                    on_source(f"{source}/{token}")
                try:
                    for job in fn(token):
                        if keep(job):
                            yield _finish(job), None
                except Exception as e:  # noqa: BLE001  one bad token doesn't stop the run
                    yield None, f"{source}/{token}: {e}"
                time.sleep(self.delay)
        for name in aggregators or []:
            fn = self.aggs.get(name)
            if not fn:
                yield None, f"unknown source '{name}'"
                continue
            if getattr(fn, "configured", True) is False:
                continue  # keyed source without a key: silently skipped (Settings shows what's missing)
            if on_source:
                on_source(name)
            try:
                for job in _call(fn, queries or [], context or {}):
                    if keep(job):
                        yield _finish(job), None
            except Exception as e:  # noqa: BLE001
                yield None, f"{name}: {e}"

    def fetch_posting(self, url):
        found = match_ats(url)
        if not found:
            return None
        source, token = found
        tail = url.rstrip("/").split("/")[-1].split("?")[0]
        if tail == token:
            return None  # a board URL, not a single posting
        for job in self.boards[source](token):
            if job["key"].rsplit(":", 1)[-1] == tail or tail in (job.get("url") or ""):
                return _finish(job)
        return None

    def detect(self, url):
        found = match_ats(url)
        if found:
            return found
        try:
            page = SESSION.get(url, headers={**HEADERS, "User-Agent": BROWSER_UA}, timeout=TIMEOUT).text
        except requests.RequestException:
            return None
        return match_ats(page)
