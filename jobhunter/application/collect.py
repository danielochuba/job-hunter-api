"""Collect new postings from company boards, job APIs, and leads (discussion posts, web results)."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..domain import pricing
from ..domain.jobs import company_domain_from_url, fingerprint, passes_filters, search_terms
from .runs import RunContext
from .usage import budget, month_spend

LEADS_PER_RUN = 40      # cap on posts/pages examined by the LLM per collect (cost control)
LEAD_WORKERS = 6        # parallel page fetches + LLM calls

LEAD_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["jobs"],
    "properties": {"jobs": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "company", "location", "remote_policy", "salary", "description", "apply_url",
                     "company_website"],
        "properties": {
            "title": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"},
            "remote_policy": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
            "salary": {"type": "string"},
            "description": {"type": "string", "description": "the posting's own words: role, requirements, how to apply"},
            "apply_url": {"type": "string"}, "company_website": {"type": "string"},
        }}}},
}
LEAD_SYSTEM = """You read a post or web page and extract concrete job openings being OFFERED by an employer.
Return an empty list when it is not a hiring post: people looking for work, [For Hire] posts, career
advice, news, course ads, job-board landing pages without a specific role, or scams (fees, crypto payment,
'no experience, earn $500/day'). One post may list several roles: return each. Copy details faithfully;
use "" when unknown. Keep description to the essentials in the post's own words (max ~250 words)."""


def search_queries(settings, user):
    """Cleaned search phrases: Settings queries, else target roles ('Full-Stack Engineer (AI)' -> 'Full-Stack Engineer')."""
    raw = list(settings["search_queries"] or []) or list((user or {}).get("target_roles") or [])
    return search_terms(raw)


def insert_job(repos, job):
    """Returns the new job id, or None if already seen (same key, or same company+title elsewhere)."""
    return repos.jobs.insert_if_new(job, fingerprint(job.get("company", ""), job.get("title", "")))


def _read_lead(run: RunContext, lead):
    """Turn one lead into job dicts. JSON-LD on the page wins (free); otherwise the fast LLM extracts."""
    text = lead["text"]
    if lead.get("fetch") and lead.get("url"):
        page_job, page_text = run.app.web.job_posting(lead["url"])
        if page_job and page_job.get("title") and len(page_job.get("description") or "") > 200:
            return [{**page_job, "url": lead["url"]}], False
        if page_text:
            text = f"{text}\n\n---\nPAGE TEXT:\n{page_text[:7000]}"
    res = run.llm.structured(run.llm.fast_model, LEAD_SYSTEM, f"SOURCE: {lead['url']}\n\n{text[:9000]}", LEAD_SCHEMA,
                             "lead_jobs", purpose="lead", effort="minimal")
    jobs = []
    for i, j in enumerate(res["jobs"][:5]):
        if not j["title"]:
            continue
        jobs.append({
            "key": f"{lead['key']}#{i}", "source": lead["source"], "company": j["company"], "title": j["title"],
            "location": j["location"] or ("Remote" if j["remote_policy"] == "remote" else ""),
            "url": j["apply_url"] or lead["url"], "description": j["description"] or text[:3000],
            "posted_at": lead.get("posted_at"),
            "remote_policy": None if j["remote_policy"] == "unknown" else j["remote_policy"],
            "salary": j["salary"] or None,
            "company_domain": company_domain_from_url(j["company_website"]) or company_domain_from_url(j["apply_url"]),
        })
    return jobs, True


def process_leads(run: RunContext, leads, filters, state):
    r = run.repos
    fresh = {l["key"]: l for l in leads}
    for k in r.leads.seen(list(fresh)):
        fresh.pop(k, None)
    todo = list(fresh.values())[:LEADS_PER_RUN]
    if not todo:
        return
    if pricing.over_budget(month_spend(run.app), budget(run.app)):
        run.log(f"Skipped {len(todo)} discussion/web leads: monthly LLM budget reached.")
        return
    run.log(f"Reading {len(todo)} new posts/pages for job offers ({len(leads) - len(todo)} already seen or over the cap)…")
    done = 0
    run.llm  # noqa: B018  create the (lazy) client once, before worker threads share it
    with ThreadPoolExecutor(LEAD_WORKERS) as pool:
        futures = {pool.submit(_read_lead, run, lead): lead for lead in todo}
        for fut in as_completed(futures):
            lead = futures[fut]
            done += 1
            run.progress(done, len(todo), f"Reading posts {done}/{len(todo)}")
            try:
                jobs, _ = fut.result()
            except Exception as e:  # noqa: BLE001  one bad page doesn't stop the run
                state["errors"] += 1
                run.log(f"! lead {lead['url']}: {str(e)[:160]}")
                continue
            r.leads.mark(lead["key"], len(jobs))
            for job in jobs:
                if not passes_filters(job, filters):
                    continue
                state["seen"] += 1
                if insert_job(r, job):
                    state["new"] += 1
                    run.log(f"+ [{job['company'] or '?'}] {job['title']} — {job['location']} ({lead['source']})")


def collect(run: RunContext, params):
    r, sources = run.repos, run.app.sources
    s = r.settings.get()
    user = r.users.get() or {}
    companies = r.companies.by_source()
    queries = search_queries(s, user)
    aggregators = params.get("aggregators") or [a for a in s["aggregators"] if a in sources.aggregators]
    filters = s["filters"] or {}
    context = {"country": user.get("country"), "regions": user.get("acceptable_regions") or []}
    total = sum(len(t) for t in companies.values()) + len(aggregators)
    state = {"i": 0, "new": 0, "errors": 0, "seen": 0}
    leads = []
    run.log(f"Searching for: {', '.join(queries) or 'everything (no roles or queries set)'}")

    def on_source(name):
        run.progress(state["i"], total, f"Checking {name}")
        state["i"] += 1

    keep = lambda j: j.get("lead") or passes_filters(j, filters)  # noqa: E731  leads are filtered after extraction
    for job, err in sources.collect(companies, queries, aggregators, keep=keep, on_source=on_source, context=context):
        if err:
            state["errors"] += 1
            run.log(f"! {err}")
            continue
        if job.get("lead"):
            leads.append(job)
            continue
        state["seen"] += 1
        if insert_job(r, job):
            state["new"] += 1
            run.log(f"+ [{job['company']}] {job['title']} — {job['location']}")
    if leads:
        process_leads(run, leads, filters, state)
    run.progress(1, 1)
    run.log(f"{state['new']} new jobs saved from {state['seen']} matching postings ({state['errors']} errors).")
    return {"new": state["new"], "seen": state["seen"], "errors": state["errors"], "leads": len(leads)}
