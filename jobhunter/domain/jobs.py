"""Job rules. A job (as produced by any source) is a dict:
    key, source, company, title, location, url, description, posted_at
    (+ optional company_domain, remote_policy, salary)
"""
import hashlib
import re
from urllib.parse import urlparse

# Hosts that are job boards/ATSs rather than the employer's own site.
BOARD_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com",
               "recruitee.com", "remotive.com", "remoteok.com", "arbeitnow.com", "himalayas.app",
               "jobicy.com", "weworkremotely.com", "ycombinator.com", "linkedin.com", "indeed.com")

ATS_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([\w.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.%-]+)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
    ("workable", r"//([\w-]+)\.workable\.com"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)"),
    ("recruitee", r"//([\w-]+)\.recruitee\.com"),
]
_IGNORED_TOKENS = {"www", "apply", "api", "jobs", "embed", "careers"}


def fingerprint(company, title):
    """Normalised company+title, used to drop the same posting seen via another source."""
    norm = re.sub(r"[^a-z0-9]+", " ", f"{company}|{title}".lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:20]


def passes_filters(job, filters):
    title = job["title"].lower()
    include = [k.lower() for k in filters.get("title_include", [])]
    exclude = [k.lower() for k in filters.get("title_exclude", [])]
    if include and not any(k in title for k in include):
        return False
    if any(k in title for k in exclude):
        return False
    locations = [l.lower() for l in filters.get("locations", [])]
    if locations and not any(l in (job["location"] or "").lower() for l in locations):
        return False
    return True


_SYNONYMS = [
    (r"\bfull[\s\-_/]*stack\b", "fullstack"), (r"\bback[\s\-_]*end\b", "backend"), (r"\bfront[\s\-_]*end\b", "frontend"),
    (r"\bnode(?:\.?js)?\b", "node"), (r"\breact(?:\.?js)?\b", "react"), (r"\bnext(?:\.?js)?\b", "nextjs"),
    (r"\b(?:engineer|developer|programmer|dev|swe)s?\b", "dev"), (r"\bml\b", "machine learning"),
    (r"\bdevops\b", "devops"), (r"\bsre\b", "site reliability"),
]
_NOISE = {"senior", "junior", "mid", "lead", "principal", "staff", "intern", "internship", "the", "and", "or",
          "a", "an", "of", "for", "with", "remote", "i", "ii", "iii", "sr", "jr"}


def normalize_text(text):
    t = f" {(text or '').lower()} "
    for pattern, repl in _SYNONYMS:
        t = re.sub(pattern, repl, t)
    return re.sub(r"[^a-z0-9+#]+", " ", t).strip()


def query_tokens(query):
    """Significant tokens of a search query, e.g. 'Full-Stack Engineer (AI automation)' -> ['fullstack', 'dev']."""
    q = re.sub(r"\(.*?\)", " ", query or "")
    return [w for w in normalize_text(q).split() if w not in _NOISE]


def query_match(text, queries):
    """True if every significant token of any query appears in `text`. Synonyms are folded, so
    'Full-Stack Developer' matches 'Full Stack Engineer' and 'Node.js dev' matches 'NodeJS Developer'."""
    if not queries:
        return True
    words = set(normalize_text(text).split())
    for q in queries:
        tokens = query_tokens(q)
        if tokens and all(t in words for t in tokens):
            return True
    return False


def search_terms(queries, limit=None):
    """Clean, de-duplicated search phrases for external search APIs (parentheticals dropped;
    'Full-Stack Engineer' and 'Full Stack Developer' collapse to one)."""
    seen, out = set(), []
    for q in queries or []:
        clean = re.sub(r"\s+", " ", re.sub(r"\(.*?\)", " ", q)).strip(" -,")
        key = " ".join(query_tokens(clean))
        if clean and key and key not in seen:
            seen.add(key)
            out.append(clean)
    return out[:limit] if limit else out


def domain_of(url):
    if not url:
        return None
    host = urlparse(url if "//" in url else f"https://{url}").netloc.lower()
    return (host[4:] if host.startswith("www.") else host) or None


def company_domain_from_url(url):
    """The employer's own domain, or None if the URL is on a job board."""
    d = domain_of(url)
    if not d or any(d == h or d.endswith("." + h) for h in BOARD_HOSTS):
        return None
    return d


def match_ats(text):
    """(source, token) if `text` (a URL or page HTML) references a supported ATS board."""
    for source, pattern in ATS_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m and m.group(1).lower() not in _IGNORED_TOKENS:
            return source, m.group(1)
    return None


def domain_guesses(company):
    slug = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    return [f"{slug}.{tld}" for tld in ("com", "io", "co", "ai")] if slug else []
