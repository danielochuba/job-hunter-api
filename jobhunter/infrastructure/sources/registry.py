"""JobSources port adapter: runs the ATS boards and aggregators, detects boards from careers URLs."""
import time

import requests

from ...domain.jobs import match_ats
from .aggregators import AGGREGATORS
from .ats import BOARDS
from .http import BROWSER_UA, HEADERS, POLITE_DELAY, TIMEOUT


def _finish(job):
    """Some boards (SmartRecruiters) need a request per posting for the description: only done
    for jobs that passed the filters."""
    fetch = job.pop("_fetch_description", None)
    if fetch and not job.get("description"):
        job["description"] = fetch()
    return job


class HttpJobSources:
    company_sources = tuple(BOARDS)
    aggregators = tuple(AGGREGATORS)

    def __init__(self, boards=None, aggregators=None, delay=POLITE_DELAY):
        self.boards = boards or BOARDS
        self.aggs = aggregators or AGGREGATORS
        self.delay = delay

    def collect(self, companies, queries, aggregators, keep, on_source=None):
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
                yield None, f"unknown aggregator '{name}'"
                continue
            if on_source:
                on_source(name)
            try:
                for job in fn(queries or []):
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
            page = requests.get(url, headers={**HEADERS, "User-Agent": BROWSER_UA}, timeout=TIMEOUT).text
        except requests.RequestException:
            return None
        return match_ats(page)
