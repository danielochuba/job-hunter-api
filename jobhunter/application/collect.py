"""Collect new postings from company boards and aggregators."""
from ..domain.jobs import fingerprint, passes_filters
from .runs import RunContext


def search_queries(settings, user):
    return list(settings["search_queries"] or []) or list((user or {}).get("target_roles") or [])


def insert_job(repos, job):
    """Returns the new job id, or None if already seen (same key, or same company+title elsewhere)."""
    return repos.jobs.insert_if_new(job, fingerprint(job.get("company", ""), job.get("title", "")))


def collect(run: RunContext, params):
    r, sources = run.repos, run.app.sources
    s = r.settings.get()
    companies = r.companies.by_source()
    queries = search_queries(s, r.users.get())
    aggregators = params.get("aggregators") or [a for a in s["aggregators"] if a in sources.aggregators]
    filters = s["filters"] or {}
    total = sum(len(t) for t in companies.values()) + len(aggregators)
    state = {"i": 0, "new": 0, "errors": 0, "seen": 0}

    def on_source(name):
        run.progress(state["i"], total, name)
        state["i"] += 1

    for job, err in sources.collect(companies, queries, aggregators, keep=lambda j: passes_filters(j, filters),
                                    on_source=on_source):
        if err:
            state["errors"] += 1
            run.log(f"! {err}")
            continue
        state["seen"] += 1
        if insert_job(r, job):
            state["new"] += 1
            run.log(f"+ [{job['company']}] {job['title']} — {job['location']}")
    run.progress(total, total)
    run.log(f"{state['new']} new jobs saved from {state['seen']} matching postings ({state['errors']} errors).")
    return {"new": state["new"], "seen": state["seen"], "errors": state["errors"]}
