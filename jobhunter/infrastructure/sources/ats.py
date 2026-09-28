"""Per-company ATS job boards (token = the company slug in its careers URL).
Moved from Phase 1 collectors.py, plus Workable, SmartRecruiters and Recruitee."""
import time
from datetime import datetime, timezone

from .http import POLITE_DELAY, get_json, remote, salary, text_of


def greenhouse(token):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        yield {
            "key": f"greenhouse:{token}:{j['id']}",
            "source": "greenhouse",
            "company": token,
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("absolute_url", ""),
            "description": text_of(j.get("content")),
            "posted_at": j.get("updated_at"),
            "remote_policy": remote(False, loc),
        }


def lever(token):
    data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    for j in data:
        parts = [j.get("descriptionPlain", "")]
        for section in j.get("lists", []):
            parts.append(section.get("text", ""))
            parts.append(text_of(section.get("content")))
        parts.append(j.get("additionalPlain", ""))
        created = j.get("createdAt")
        loc = (j.get("categories") or {}).get("location", "") or ""
        wt = (j.get("workplaceType") or "").lower()
        yield {
            "key": f"lever:{token}:{j['id']}",
            "source": "lever",
            "company": token,
            "title": j.get("text", ""),
            "location": loc,
            "url": j.get("hostedUrl", ""),
            "description": "\n".join(p for p in parts if p),
            "posted_at": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else None,
            "remote_policy": {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(wt)
                             or remote(False, loc),
        }


def ashby(token):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    for j in data.get("jobs", []):
        loc = j.get("location", "") or ""
        if j.get("isRemote") and "remote" not in loc.lower():
            loc = f"{loc} (Remote)".strip()
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        yield {
            "key": f"ashby:{token}:{j['id']}",
            "source": "ashby",
            "company": token,
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("jobUrl", ""),
            "description": j.get("descriptionPlain") or text_of(j.get("descriptionHtml")),
            "posted_at": j.get("publishedAt"),
            "remote_policy": remote(j.get("isRemote"), loc),
            "salary": comp,
        }


def workable(token):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true")
    company = data.get("name") or token
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        if j.get("telecommuting"):
            loc = f"{loc} (Remote)".strip()
        yield {
            "key": f"workable:{token}:{j.get('shortcode') or j.get('id')}",
            "source": "workable",
            "company": company,
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("url") or j.get("shortlink") or j.get("application_url", ""),
            "description": text_of(j.get("description")),
            "posted_at": j.get("published_on") or j.get("created_at"),
            "remote_policy": remote(j.get("telecommuting"), loc),
        }


def smartrecruiters_description(token, posting_id):
    d = get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{posting_id}")
    sections = (d.get("jobAd") or {}).get("sections") or {}
    return "\n\n".join(text_of((sections.get(k) or {}).get("text")) for k in
                       ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))


def smartrecruiters(token):
    offset = 0
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                    params={"limit": 100, "offset": offset})
        content = data.get("content", [])
        for j in content:
            l = j.get("location") or {}
            loc = ", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x)
            if l.get("remote"):
                loc = f"{loc} (Remote)".strip()
            pid = j["id"]
            yield {
                "key": f"smartrecruiters:{token}:{pid}",
                "source": "smartrecruiters",
                "company": (j.get("company") or {}).get("name") or token,
                "title": j.get("name", ""),
                "location": loc,
                "url": f"https://jobs.smartrecruiters.com/{token}/{pid}",
                "description": "",
                "posted_at": j.get("releasedDate"),
                "remote_policy": remote(l.get("remote"), loc),
                # descriptions need one request per posting: only fetched for jobs that pass filters
                "_fetch_description": lambda t=token, p=pid: smartrecruiters_description(t, p),
            }
        offset += len(content)
        if not content or offset >= data.get("totalFound", 0):
            break
        time.sleep(POLITE_DELAY)


def recruitee(token):
    data = get_json(f"https://{token}.recruitee.com/api/offers/")
    for j in data.get("offers", []):
        loc = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        yield {
            "key": f"recruitee:{token}:{j['id']}",
            "source": "recruitee",
            "company": j.get("company_name") or token,
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("careers_url", ""),
            "description": text_of((j.get("description") or "") + (j.get("requirements") or "")),
            "posted_at": j.get("published_at") or j.get("created_at"),
            "remote_policy": remote(j.get("remote"), loc),
            "salary": salary((j.get("salary") or {}).get("min"), (j.get("salary") or {}).get("max"),
                              (j.get("salary") or {}).get("currency", "")),
        }


BOARDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby,
          "workable": workable, "smartrecruiters": smartrecruiters, "recruitee": recruitee}
