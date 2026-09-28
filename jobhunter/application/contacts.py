"""Find people to contact about a job. Sources, best first: emails in the posting, the email finder
(Hunter.io, if configured), emails on the company's own site, then generic inboxes.
No SMTP probing: it hurts sender reputation and is unreliable anyway."""
from ..domain import contacts as rules
from ..domain.errors import NotFound
from ..domain.jobs import company_domain_from_url, domain_guesses
from .context import AppContext
from .runs import RunContext
from .tracker import get_job


def company_domain(ctx: AppContext, job):
    if job.get("company_domain"):
        return job["company_domain"]
    domain = ctx.repos.companies.domain_for(job["company"]) or company_domain_from_url(job.get("url"))
    if not domain:
        domain = next((d for d in domain_guesses(job["company"]) if ctx.web.domain_exists(d)), None)
    if domain:
        ctx.repos.jobs.update(job["id"], company_domain=domain)
    return domain


def find_for_job(ctx: AppContext, job_id, log=print):
    job = get_job(ctx, job_id)
    candidates = rules.from_job_post(job["description"])
    domain = company_domain(ctx, job)
    log(f"#{job_id} {job['company']}: domain {domain or 'unknown'}")
    if ctx.finder.enabled:
        candidates += [rules.from_finder(e["email"], e.get("name"), e.get("role"), e.get("confidence"))
                       for e in ctx.finder.search(domain, job["company"])]
    if domain:
        candidates += [rules.from_website(e, domain) for e in ctx.web.site_emails(domain)]
        candidates += rules.generic(domain)
    best = rules.best_per_email(candidates)
    new = sum(ctx.repos.contacts.upsert(job_id, domain, c) for c in best)
    log(f"#{job_id}: {len(best)} contacts ({new} new)")
    return len(best)


def find(run: RunContext, params):
    ids = params.get("job_ids") or []
    n = 0
    for i, jid in enumerate(ids):
        run.progress(i, len(ids), f"Job #{jid}")
        n += find_for_job(run.app, jid, log=run.log)
    run.progress(len(ids), len(ids))
    return {"contacts": n}


def add_manual(ctx: AppContext, job_id, email, name=None, role=None):
    job = get_job(ctx, job_id)
    return ctx.repos.contacts.add_manual(job_id, job["company_domain"], email.strip().lower(), name, role)


def get_contact(ctx: AppContext, contact_id):
    c = ctx.repos.contacts.get(contact_id)
    if not c:
        raise NotFound("Contact not found")
    return c
