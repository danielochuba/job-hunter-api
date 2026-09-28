"""JobHunter CLI: same use cases as the API; settings, companies and CVs come from the database.

  python -m jobhunter collect              fetch + keyword-filter new postings
  python -m jobhunter match [--limit N]    embedding filter, then LLM fit scoring
  python -m jobhunter daily                collect + match + reminders + Gmail sync (for cron)
  python -m jobhunter list [--stage S]     show jobs (default: scored, best first)
  python -m jobhunter show ID              full fit analysis for one job
  python -m jobhunter generate ID...       tailored CV + cover letter for job(s)
  python -m jobhunter generate --top N     ... for the N best scored jobs
  python -m jobhunter import URL           import one job from any URL, then score it
  python -m jobhunter contacts ID...       find contact emails for job(s)
  python -m jobhunter prep ID              interview prep pack
  python -m jobhunter sync-gmail           check sent outreach for replies
  python -m jobhunter approve ID | reject ID | applied ID
  python -m jobhunter seed-yaml PATH       import a Phase 1 master_cv.yaml or config.yaml
"""
import argparse
import sys

import yaml

from ..application import jobs, mail, profile, runs, tracker
from ..application.tasks import TASKS
from ..domain.cv import contact_from_phase1
from ..domain.errors import JobHunterError


def _run(ctx, kind, params=None):
    runs.run_now(ctx, kind, TASKS[kind], params or {}, trigger="cli")


def cmd_list(ctx, a):
    stage = a.stage or "scored"
    page = jobs.list_jobs(ctx, page_size=a.limit or 50, stage=stage)
    if not page["items"]:
        print(f"No jobs with stage '{stage}'.")
    for r in page["items"]:
        score = r["fit_score"] if r["fit_score"] is not None else "-"
        print(f"{score!s:>4}  #{r['id']:<5} [{r['company']}] {r['title']} — {r['location']}")
    if page["total"] > len(page["items"]):
        print(f"... {page['total'] - len(page['items'])} more")


def cmd_show(ctx, a):
    r = jobs.detail(ctx, a.ids[0])
    print(f"#{r['id']} {r['title']} at {r['company']} ({r['location']})\n{r['url']}\nstage: {r['stage']}")
    fit = r["fit"]
    if fit:
        print(f"\nFit: {fit['fit_score']}/100 — {fit['summary']}")
        if not fit.get("eligible", True):
            print(f"Ineligible: {fit.get('ineligible_reason')}")
        for label in ("matched_requirements", "gaps", "dealbreakers", "missing_skills"):
            if fit.get(label):
                print(f"\n{label.replace('_', ' ').title()}:")
                for x in fit[label]:
                    print(f"  - {x}")
    app = ctx.repos.applications.latest(r["id"])
    if app:
        print(f"\nLatest application: v{app['version']} ({app['cv_pdf_path'] or app['cv_html_path']})")


def cmd_generate(ctx, a):
    if not a.ids and not a.top:
        sys.exit("No jobs to generate for. Pass IDs or --top N.")
    _run(ctx, "generate", {"job_ids": a.ids, "top": a.top})
    print("\nReview each job in the dashboard, edit if needed, then: approve ID or reject ID")


def cmd_seed_yaml(ctx, a):
    """Bring Phase 1 files across: master_cv.yaml becomes a CV; config.yaml fills settings/companies."""
    with open(a.path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    r = ctx.repos
    user = r.users.get()
    if not user:
        sys.exit("Sign in to the web app once first, so your user profile exists.")
    if "experience" in data:
        cv = profile.create_cv(ctx, user["id"], a.name or "Master CV", data, contact=contact_from_phase1(data))
        print(f"CV #{cv['id']} created")
    if "companies" in data:
        for source, tokens in data["companies"].items():
            for t in tokens or []:
                r.companies.upsert(source, t, t, None)
        fields = {k: data[k] for k in ("filters", "matching") if data.get(k)}
        if fields:
            from ..application import settings
            settings.update(ctx, fields)
        print("Settings and companies imported")


def _stage(stage):
    def fn(ctx, a):
        for jid in a.ids:
            tracker.set_stage(ctx, jid, stage)
            print(f"#{jid} → {stage}")
    return fn


COMMANDS = {
    "collect": lambda ctx, a: _run(ctx, "collect"),
    "match": lambda ctx, a: _run(ctx, "match", {"limit": a.limit} if a.limit else {}),
    "daily": lambda ctx, a: _run(ctx, "daily"),
    "list": cmd_list,
    "show": cmd_show,
    "generate": cmd_generate,
    "import": lambda ctx, a: _run(ctx, "import", {"url": a.path}),
    "contacts": lambda ctx, a: _run(ctx, "contacts", {"job_ids": a.ids}),
    "prep": lambda ctx, a: _run(ctx, "prep", {"job_id": a.ids[0]}),
    "sync-gmail": lambda ctx, a: print(f"{mail.sync_replies(ctx)} new replies"),
    "seed-yaml": cmd_seed_yaml,
    "approve": _stage("approved"),
    "reject": _stage("rejected"),
    "applied": _stage("applied"),
}
PATH_COMMANDS = {"import", "seed-yaml"}
NEEDS_ID = {"show", "prep", "contacts", "approve", "reject", "applied"}


def main(argv=None):
    p = argparse.ArgumentParser(prog="jobhunter", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("args", nargs="*")
    p.add_argument("--stage")
    p.add_argument("--limit", type=int)
    p.add_argument("--top", type=int)
    p.add_argument("--name", help="CV name for seed-yaml")
    a = p.parse_args(argv)
    a.path = a.args[0] if a.command in PATH_COMMANDS and a.args else None
    if a.command in PATH_COMMANDS and not a.path:
        p.error(f"{a.command} needs a URL/path")
    try:
        a.ids = [] if a.command in PATH_COMMANDS else [int(x) for x in a.args]
    except ValueError:
        p.error("job IDs must be integers")
    if a.command in NEEDS_ID and not a.ids:
        p.error(f"{a.command} needs a job ID")

    from ..config import Config
    from ..container import Container
    container = Container(Config.from_env())
    try:
        with container.session() as ctx:
            COMMANDS[a.command](ctx, a)
    except JobHunterError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
