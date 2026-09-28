"""Query-driven public job aggregators (no token needed)."""
import html
import re
import time
import xml.etree.ElementTree as ET

from ...domain.jobs import query_match
from .http import POLITE_DELAY, get_json, get_text, iso, remote, salary, text_of


def remotive(queries):
    seen = set()
    for q in (queries or [""]):
        data = get_json("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 100})
        for j in data.get("jobs", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            yield {
                "key": f"remotive:{j['id']}",
                "source": "remotive",
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": f"Remote ({j.get('candidate_required_location') or 'Anywhere'})",
                "url": j.get("url", ""),
                "description": text_of(j.get("description")),
                "posted_at": j.get("publication_date"),
                "remote_policy": "remote",
                "salary": j.get("salary") or None,
            }
        time.sleep(POLITE_DELAY)


def remoteok(queries):
    data = get_json("https://remoteok.com/api")
    for j in data:
        if not isinstance(j, dict) or "id" not in j:
            continue  # first element is a legal notice
        blob = " ".join([j.get("position", ""), " ".join(j.get("tags") or [])])
        if not query_match(blob, queries):
            continue
        yield {
            "key": f"remoteok:{j['id']}",
            "source": "remoteok",
            "company": j.get("company", ""),
            "title": j.get("position", ""),
            "location": f"Remote ({j.get('location') or 'Anywhere'})",
            "url": j.get("url", ""),
            "description": text_of(j.get("description")),
            "posted_at": j.get("date"),
            "remote_policy": "remote",
            "salary": salary(j.get("salary_min"), j.get("salary_max"), "USD"),
        }


def arbeitnow(queries, max_pages=3):
    url = "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(max_pages):
        data = get_json(url)
        for j in data.get("data", []):
            blob = " ".join([j.get("title", ""), " ".join(j.get("tags") or [])])
            if not query_match(blob, queries):
                continue
            loc = j.get("location", "")
            yield {
                "key": f"arbeitnow:{j['slug']}",
                "source": "arbeitnow",
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": f"{loc} (Remote)" if j.get("remote") else loc,
                "url": j.get("url", ""),
                "description": text_of(j.get("description")),
                "posted_at": iso(j.get("created_at")),
                "remote_policy": remote(j.get("remote"), loc),
            }
        url = (data.get("links") or {}).get("next")
        if not url:
            break
        time.sleep(POLITE_DELAY)


def himalayas(queries):
    seen = set()
    for q in (queries or [""]):
        data = get_json("https://himalayas.app/jobs/api/search", params={"q": q, "limit": 50})
        for j in data.get("jobs", []):
            jid = j.get("guid") or j.get("applicationLink")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            regions = j.get("locationRestrictions") or []
            yield {
                "key": f"himalayas:{jid}",
                "source": "himalayas",
                "company": j.get("companyName", ""),
                "title": j.get("title", ""),
                "location": f"Remote ({', '.join(regions) if regions else 'Anywhere'})",
                "url": j.get("applicationLink") or jid,
                "description": text_of(j.get("description")) or j.get("excerpt", ""),
                "posted_at": iso(j.get("pubDate")),
                "remote_policy": "remote",
                "salary": salary(j.get("minSalary"), j.get("maxSalary"), j.get("currency", "")),
            }
        time.sleep(POLITE_DELAY)


def jobicy(queries):
    seen = set()
    for q in (queries or [""]):
        params = {"count": 50}
        if q:
            params["tag"] = q
        data = get_json("https://jobicy.com/api/v2/remote-jobs", params=params)
        for j in data.get("jobs", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            yield {
                "key": f"jobicy:{j['id']}",
                "source": "jobicy",
                "company": j.get("companyName", ""),
                "title": html.unescape(j.get("jobTitle", "")),
                "location": f"Remote ({j.get('jobGeo') or 'Anywhere'})",
                "url": j.get("url", ""),
                "description": text_of(j.get("jobDescription")),
                "posted_at": j.get("pubDate"),
                "remote_policy": "remote",
                "salary": salary(j.get("annualSalaryMin"), j.get("annualSalaryMax"), j.get("salaryCurrency", "")),
            }
        time.sleep(POLITE_DELAY)


WWR_FEEDS = ["https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
             "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
             "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"]


def weworkremotely(queries):
    for feed in WWR_FEEDS:
        root = ET.fromstring(get_text(feed))
        for item in root.iter("item"):
            raw_title = item.findtext("title") or ""
            company, _, title = raw_title.partition(":")
            if not title:
                company, title = "", raw_title
            title = title.strip()
            if not query_match(title, queries):
                continue
            link = item.findtext("link") or ""
            region = item.findtext("region") or "Anywhere"
            yield {
                "key": f"weworkremotely:{item.findtext('guid') or link}",
                "source": "weworkremotely",
                "company": company.strip(),
                "title": title,
                "location": f"Remote ({region})",
                "url": link,
                "description": text_of(item.findtext("description")),
                "posted_at": iso(item.findtext("pubDate")),
                "remote_policy": "remote",
            }
        time.sleep(POLITE_DELAY)


def hn_whoishiring(queries, max_comments=400):
    """Latest monthly 'Ask HN: Who is hiring?' thread; each top-level comment is a job."""
    hits = get_json("https://hn.algolia.com/api/v1/search_by_date",
                params={"tags": "story,author_whoishiring", "query": "who is hiring"}).get("hits", [])
    story = next((h for h in hits if "who is hiring" in (h.get("title") or "").lower()), None)
    if not story:
        return
    thread = get_json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}")
    for c in (thread.get("children") or [])[:max_comments]:
        text = text_of(c.get("text"))
        if not text or not query_match(text, queries):
            continue
        head = text.split("\n", 1)[0]
        parts = [p.strip() for p in head.split("|")]
        company = parts[0][:120] if parts else ""
        title = parts[1][:200] if len(parts) > 1 else head[:200]
        location = next((p for p in parts[2:] if re.search(r"remote|onsite|hybrid|[A-Z][a-z]+,", p, re.I)), "")
        yield {
            "key": f"hn:{c['id']}",
            "source": "hn_whoishiring",
            "company": company,
            "title": title,
            "location": location[:200],
            "url": f"https://news.ycombinator.com/item?id={c['id']}",
            "description": text,
            "posted_at": c.get("created_at"),
            "remote_policy": remote(False, head),
        }


AGGREGATORS = {"remotive": remotive, "remoteok": remoteok, "arbeitnow": arbeitnow,
               "himalayas": himalayas, "jobicy": jobicy, "weworkremotely": weworkremotely,
               "hn_whoishiring": hn_whoishiring}
