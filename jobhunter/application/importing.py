"""Import one job from any URL (or pasted text): ATS API -> JSON-LD JobPosting -> LLM extraction.
Then it goes straight through matching."""
import hashlib

from ..domain.errors import InvalidInput
from ..domain.jobs import company_domain_from_url, fingerprint
from .collect import insert_job
from .runs import RunContext

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_job_posting", "title", "company", "location", "description", "remote_policy", "salary",
                 "company_website"],
    "properties": {
        "is_job_posting": {"type": "boolean"},
        "title": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"},
        "description": {"type": "string", "description": "full job description text, verbatim, not summarised"},
        "remote_policy": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
        "salary": {"type": "string"}, "company_website": {"type": "string"},
    },
}
EXTRACT_SYSTEM = ("Extract the job posting from this web page text. Copy the description verbatim "
                  "(requirements, responsibilities, benefits). Use \"\" for anything not present.")


def import_key(url_or_text):
    return "import:" + hashlib.sha1(url_or_text.strip().encode()).hexdigest()[:16]


def from_text(run: RunContext, text, url=None):
    res = run.llm.structured(run.llm.fast_model, EXTRACT_SYSTEM, text[:30000], EXTRACT_SCHEMA, "job_extract",
                             purpose="import")
    if not res["is_job_posting"] or not res["title"]:
        raise InvalidInput("That doesn't look like a job posting. Paste the description text instead.")
    return {
        "key": import_key(url or text), "source": "import", "company": res["company"],
        "company_domain": company_domain_from_url(res["company_website"]) or company_domain_from_url(url),
        "title": res["title"], "location": res["location"], "url": url, "description": res["description"],
        "posted_at": None, "remote_policy": None if res["remote_policy"] == "unknown" else res["remote_policy"],
        "salary": res["salary"] or None,
    }


def from_url(run: RunContext, url):
    job = run.app.sources.fetch_posting(url)
    if job:
        return job
    job, text = run.app.web.job_posting(url)
    if job and job.get("title") and len(job.get("description") or "") > 200:
        return {**job, "key": import_key(url), "source": "import", "url": url}
    if len(text) < 300:
        raise InvalidInput("Couldn't read that page (it may need a login). Paste the job description instead.")
    return from_text(run, f"URL: {url}\n\n{text}", url)


def import_job(run: RunContext, params):
    from .matching import match
    r = run.repos
    url, text = params.get("url"), params.get("text")
    run.progress(0, 3, "Reading posting")
    job = from_text(run, text, url) if text else from_url(run, url)
    job_id = insert_job(r, job)
    if job_id:
        run.log(f"Imported #{job_id}: {job['title']} at {job['company']}")
    else:
        job_id = r.jobs.find_by_key_or_fingerprint(job["key"], fingerprint(job["company"], job["title"]))["id"]
        run.log(f"Already had this job as #{job_id}; re-scoring it.")
    run.progress(1, 3, "Matching")
    if r.cvs.any():
        match(run, {"job_ids": [job_id], "quiet": True})
    else:
        run.log("No CV yet, so the job was saved without a score. Upload a CV, then re-score it.")
    run.progress(3, 3)
    return {"job_id": job_id}
