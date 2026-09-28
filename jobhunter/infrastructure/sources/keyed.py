"""Sources that need an API key (all have free tiers). Each is a callable `(queries, context) -> jobs`
with `configured` and `needs` so the UI can show what's missing. `context` carries the user's
country and regions so searches can include jobs open to where you actually live.

Two kinds of output:
  * structured jobs (Adzuna, Google Jobs): the normal job dict
  * leads (Reddit posts, web/discussion search results): {"lead": True, "text": ...}; the collect use
    case turns these into jobs (JSON-LD or LLM extraction) or discards them if they aren't job offers.
"""
import hashlib
import re
import time

from .http import HEADERS, POLITE_DELAY, SESSION, TIMEOUT, iso, relative_iso, remote, salary

# --------------------------------------------------------------------------- helpers


def _h(s):
    return hashlib.sha1(s.encode()).hexdigest()[:16]


class _Keyed:
    name = ""
    needs = ""

    @property
    def configured(self):
        return True


# --------------------------------------------------------------------------- Adzuna

class Adzuna(_Keyed):
    """Adzuna job search API (free key). Countries: gb, za, us, de, nl, fr, ca, au, in, ... (no Nigeria)."""
    name = "adzuna"
    needs = "ADZUNA_APP_ID + ADZUNA_APP_KEY"

    def __init__(self, app_id, app_key, countries=("gb", "za"), max_queries=4):
        self.app_id, self.app_key = app_id, app_key
        self.countries = [c.strip().lower() for c in countries if c.strip()]
        self.max_queries = max_queries

    @property
    def configured(self):
        return bool(self.app_id and self.app_key)

    def __call__(self, queries, context=None):
        for country in self.countries:
            for q in (queries or ["software developer"])[: self.max_queries]:
                r = SESSION.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", headers=HEADERS, timeout=TIMEOUT,
                                 params={"app_id": self.app_id, "app_key": self.app_key, "what": q, "results_per_page": 50,
                                         "max_days_old": 21, "content-type": "application/json"})
                r.raise_for_status()
                for j in r.json().get("results", []):
                    loc = (j.get("location") or {}).get("display_name", "")
                    title = j.get("title", "")
                    yield {
                        "key": f"adzuna:{country}:{j['id']}",
                        "source": "adzuna",
                        "company": (j.get("company") or {}).get("display_name", ""),
                        "title": re.sub(r"<[^>]+>", "", title),
                        "location": loc,
                        "url": j.get("redirect_url", ""),
                        "description": re.sub(r"<[^>]+>", "", j.get("description", "")),
                        "posted_at": j.get("created"),
                        "remote_policy": remote(False, f"{title} {loc} {j.get('description', '')[:200]}"),
                        "salary": salary(j.get("salary_min"), j.get("salary_max"), {"gb": "GBP", "za": "ZAR"}.get(country, "")),
                    }
                time.sleep(POLITE_DELAY)


# --------------------------------------------------------------------------- Google Jobs (SerpApi)

class GoogleJobs(_Keyed):
    """Google Jobs via SerpApi: listings Google aggregates from LinkedIn, Indeed, Glassdoor, company sites...
    Each query is one SerpApi search (free tier ~100/month), so queries per run are capped."""
    name = "google_jobs"
    needs = "SERPAPI_API_KEY"

    def __init__(self, api_key, max_queries=3):
        self.api_key = api_key
        self.max_queries = max_queries

    @property
    def configured(self):
        return bool(self.api_key)

    def _searches(self, queries, context):
        country = (context or {}).get("country")
        out = []
        for q in queries or ["software developer"]:
            out.append({"q": f"{q} remote"})
            if country:
                out.append({"q": q, "location": country})
        return out[: self.max_queries]

    def __call__(self, queries, context=None):
        for params in self._searches(queries, context):
            r = SESSION.get("https://serpapi.com/search.json", timeout=TIMEOUT,
                             params={"engine": "google_jobs", "hl": "en", "api_key": self.api_key, **params})
            r.raise_for_status()
            data = r.json()
            if data.get("error") and "hasn't returned any results" not in data["error"]:
                raise RuntimeError(data["error"])
            for j in data.get("jobs_results", []):
                ext = j.get("detected_extensions") or {}
                apply = (j.get("apply_options") or [{}])[0].get("link") or j.get("share_link", "")
                loc = j.get("location", "")
                yield {
                    "key": f"google_jobs:{_h(j.get('job_id') or apply)}",
                    "source": "google_jobs",
                    "company": j.get("company_name", ""),
                    "title": j.get("title", ""),
                    "location": f"{loc} (Remote)" if ext.get("work_from_home") and "remote" not in loc.lower() else loc,
                    "url": apply,
                    "description": j.get("description", ""),
                    "posted_at": relative_iso(ext.get("posted_at")),
                    "remote_policy": remote(ext.get("work_from_home"), loc),
                    "salary": ext.get("salary"),
                }
            time.sleep(POLITE_DELAY)


# --------------------------------------------------------------------------- Reddit

HIRING = re.compile(r"\[\s*hiring\s*\]|\bhiring\b|we'?re looking for|looking for an? |job opening|\bopen role|\bjoin (our|the) team", re.I)
NOT_HIRING = re.compile(r"\[\s*(for hire|fh)\s*\]|\bfor hire\b|seeking (work|job|role)|looking for (work|a job|job)|"
                        r"available for|hire me|my portfolio|resume review|\[\s*meta\s*\]", re.I)
DEFAULT_SUBREDDITS = ("forhire", "hiring", "remotejs", "PythonJobs", "jobbit", "RemoteJobs", "techjobs", "DeveloperJobs")


class Reddit(_Keyed):
    """Hiring posts from job subreddits via Reddit's OAuth API (Reddit blocks anonymous access).
    Posts are leads: the LLM decides if a post is a real job offer."""
    name = "reddit"
    needs = "REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET"

    def __init__(self, client_id="", client_secret="", subreddits=DEFAULT_SUBREDDITS, per_sub=50, max_age_days=21):
        self.client_id, self.client_secret = client_id, client_secret
        self.subreddits = subreddits
        self.per_sub = per_sub
        self.max_age = max_age_days * 86400
        self._token = None
        self.headers = {"User-Agent": "jobhunter/0.2 (personal job search; by u/jobhunter)"}

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    def _auth(self):
        if not (self.client_id and self.client_secret):
            return None
        if not self._token:
            r = SESSION.post("https://www.reddit.com/api/v1/access_token", auth=(self.client_id, self.client_secret),
                              data={"grant_type": "client_credentials"}, headers=self.headers, timeout=TIMEOUT)
            r.raise_for_status()
            self._token = r.json()["access_token"]
        return self._token

    def _listing(self, sub):
        token = self._auth()
        if token:
            url, headers = f"https://oauth.reddit.com/r/{sub}/new", {**self.headers, "Authorization": f"bearer {token}"}
        else:
            url, headers = f"https://www.reddit.com/r/{sub}/new.json", self.headers
        r = SESSION.get(url, params={"limit": self.per_sub, "raw_json": 1}, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return [c["data"] for c in r.json().get("data", {}).get("children", [])]

    def __call__(self, queries, context=None):
        now = time.time()
        for sub in self.subreddits:
            for p in self._listing(sub):
                title, body = p.get("title", ""), p.get("selftext", "") or ""
                if now - p.get("created_utc", now) > self.max_age or p.get("stickied"):
                    continue
                if NOT_HIRING.search(title) or not (HIRING.search(title) or HIRING.search(body[:300])
                                                   or sub.lower() in ("remotejs", "pythonjobs", "developerjobs")):
                    continue
                yield {
                    "lead": True,
                    "key": f"reddit:{p['id']}",
                    "source": "reddit",
                    "title": title,
                    "url": f"https://www.reddit.com{p.get('permalink', '')}",
                    "text": f"r/{sub}: {title}\n\n{body[:6000]}",
                    "posted_at": iso(int(p.get("created_utc") or 0) or None),
                    "fetch": False,
                }
            time.sleep(1.0)  # Reddit is strict about request rates


# --------------------------------------------------------------------------- Web & discussion search (Brave)

DISCUSSION_SITES = "site:reddit.com OR site:news.ycombinator.com OR site:x.com OR site:linkedin.com/posts OR site:indiehackers.com OR site:dev.to"


class WebSearch(_Keyed):
    """Brave Search API over the open web, including forum/discussion results. Every result is a lead:
    the page is fetched and the actual job(s) extracted, or it's discarded if it isn't a job offer."""
    name = "web_search"
    needs = "BRAVE_API_KEY"

    def __init__(self, api_key, max_queries=8, freshness="pw"):
        self.api_key = api_key
        self.max_queries = max_queries
        self.freshness = freshness  # pd=day, pw=week, pm=month

    @property
    def configured(self):
        return bool(self.api_key)

    def searches(self, queries, context):
        ctx = context or {}
        where = " OR ".join(f'"{r}"' for r in (["Africa", "worldwide", "anywhere"] +
                                               ([ctx["country"]] if ctx.get("country") else [])))
        out = []
        for q in queries or ["software developer"]:
            out += [f'"hiring" "{q}" remote ({where})',
                    f'"{q}" hiring remote {DISCUSSION_SITES}']
        return out[: self.max_queries]

    def __call__(self, queries, context=None):
        seen = set()
        for q in self.searches(queries, context):
            r = SESSION.get("https://api.search.brave.com/res/v1/web/search", timeout=TIMEOUT,
                             headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                             params={"q": q, "count": 20, "freshness": self.freshness})
            r.raise_for_status()
            data = r.json()
            results = (data.get("web") or {}).get("results", []) + (data.get("discussions") or {}).get("results", [])
            for res in results:
                url = res.get("url") or ""
                if not url or url in seen or url.lower().endswith(".pdf"):
                    continue
                seen.add(url)
                extra = " ".join((res.get("data") or {}).get(k, "") for k in ("question", "top_comment")) \
                    if isinstance(res.get("data"), dict) else ""
                yield {
                    "lead": True,
                    "key": f"web:{_h(url)}",
                    "source": "web_search",
                    "title": res.get("title", ""),
                    "url": url,
                    "text": f"{res.get('title', '')}\n{res.get('description', '')}\n{extra}".strip(),
                    "posted_at": None,
                    "fetch": True,
                }
            time.sleep(1.1)  # Brave free tier: 1 request/second
