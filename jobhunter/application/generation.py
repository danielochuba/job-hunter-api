"""Tailored CV + cover letter per job, with versioned edits. Files go to Storage under
{job_id}/v{n}/ and the UI only ever gets short-lived signed URLs."""
import json
import re

from ..domain import stages
from ..domain.cv import as_text, with_contact
from ..domain.errors import InvalidInput, NotFound
from ..domain.truthfulness import build_cv_context, validate
from .context import AppContext
from .runs import RunContext
from .tracker import get_job

BULLET = {
    "type": "object", "additionalProperties": False, "required": ["source_id", "text"],
    "properties": {"source_id": {"type": "string"}, "text": {"type": "string"}},
}
SECTION = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "bullets"],
        "properties": {"id": {"type": "string"}, "bullets": {"type": "array", "items": BULLET}},
    },
}
GEN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "skills_priority", "experience", "projects", "cover_letter"],
    "properties": {
        "summary": {"type": "string"},
        "skills_priority": {"type": "array", "items": {"type": "string"}},
        "experience": SECTION,
        "projects": SECTION,
        "cover_letter": {"type": "string"},
    },
}

GEN_SYSTEM = """You tailor a candidate's CV and write a cover letter for one specific job.

ABSOLUTE RULES (truthfulness):
- Every bullet you output must come from exactly one CV bullet, referenced by its source_id.
- You may rephrase to mirror the job's wording, reorder, and shorten. You must NOT add
  technologies, numbers, employers, titles, or achievements that are not in that source bullet.
- Keep a role in `experience` only if at least one of its bullets is relevant; refer to roles and
  projects by their [id]. Order bullets within a role by relevance. 2-5 bullets per role.
- skills_priority: skills from the CV only, most relevant to this job first (max 15).

SUMMARY: 2-3 sentences, specific to this role, no clichés ("passionate", "results-driven").

COVER LETTER: 200-300 words, plain text, no placeholders like [Company]. Open with why this
specific role/company, then 2 concrete examples from the CV mapped to the job's needs, then a
short close. Confident and direct, not grovelling. Sign off with the candidate's name.
Do not claim knowledge about the company beyond what the job posting says."""


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")


def cv_for(ctx: AppContext, job, cv_id=None):
    """(cv_id, CV with contact overlay) to use for this job: explicit > matched > default."""
    r = ctx.repos
    cv_id = cv_id or job.get("cv_id") or (r.cvs.default() or {}).get("id")
    cv_row = r.cvs.get(cv_id) if cv_id else None
    if not cv_row:
        raise InvalidInput("No CV available: upload one first.")
    return cv_id, with_contact(cv_row["cv"], r.users.get())


def render(ctx: AppContext, result, cv):
    return ctx.renderer.cv_html(build_cv_context(result, cv))


def _store(ctx: AppContext, job, cv_id, result, warnings, cover_letter, cv):
    """Render + upload files for a new version and insert the applications row."""
    r, storage = ctx.repos, ctx.storage
    version = r.applications.next_version(job["id"])
    base = f"{job['id']}/v{version}"
    html = render(ctx, result, cv)
    paths = {"cv_html_path": storage.upload(f"{base}/cv.html", html, "text/html; charset=utf-8"),
             "cover_letter_path": storage.upload(f"{base}/cover_letter.txt", cover_letter.strip() + "\n",
                                                 "text/plain; charset=utf-8"),
             "cv_pdf_path": None}
    pdf = ctx.renderer.pdf(html)
    if pdf:
        paths["cv_pdf_path"] = storage.upload(f"{base}/cv.pdf", pdf, "application/pdf")
    return r.applications.create(job_id=job["id"], cv_id=cv_id, version=version, result=result,
                                 warnings=warnings, cover_letter=cover_letter.strip(), **paths)


def generate_for_job(run: RunContext, job_id, cv_id=None):
    ctx = run.app
    job = get_job(ctx, job_id)
    cv_id, cv = cv_for(ctx, job, cv_id)
    user_msg = (f"CANDIDATE CV:\n{as_text(cv)}\n\n---\nJOB: {job['title']} at {job['company']} "
                f"({job['location']})\n\n{job['description'][:12000]}\n\n---\nFIT ANALYSIS:\n"
                f"{json.dumps(job['fit'] or {}, indent=2)}")
    raw = run.llm.structured(run.llm.strong_model, GEN_SYSTEM, user_msg, GEN_SCHEMA, "tailored_application",
                             purpose="generate")
    result, warnings = validate(raw, cv)
    app = _store(ctx, job, cv_id, result, warnings, result["cover_letter"], cv)
    if job["stage"] in stages.PRE_GENERATED:
        ctx.repos.jobs.update(job_id, stage="generated")
    ctx.repos.events.add(job_id, "generated", f"Generated CV + cover letter v{app['version']}")
    return app, warnings


def generate(run: RunContext, params):
    """Task: generate for params.job_ids and/or the top N scored jobs."""
    r = run.repos
    ids = list(params.get("job_ids") or [])
    if params.get("top"):
        min_fit = (r.settings.get()["matching"] or {}).get("min_fit_for_generate", 70)
        ids += r.jobs.top_scored(min_fit, params["top"])
    if not ids:
        raise InvalidInput("No jobs to generate for.")
    done = []
    for i, jid in enumerate(ids):
        run.progress(i, len(ids), f"Job #{jid}")
        try:
            app, warnings = generate_for_job(run, jid, params.get("cv_id"))
            run.log(f"✓ #{jid} → v{app['version']}" + (f" ({len(warnings)} warnings)" if warnings else ""))
            for w in warnings:
                run.log(f"    warning: {w}")
            done.append(app["id"])
        except Exception as e:  # noqa: BLE001
            run.log(f"! #{jid}: {e}")
    run.progress(len(ids), len(ids))
    if not done:
        raise RuntimeError("Nothing was generated (see log).")
    return {"applications": done}


def get_application(ctx: AppContext, app_id):
    app = ctx.repos.applications.get(app_id)
    if not app:
        raise NotFound("Application not found")
    return app


def save_edit(ctx: AppContext, app_id, result=None, cover_letter=None):
    """Save user edits as a new version (re-validated against the CV and re-rendered)."""
    prev = get_application(ctx, app_id)
    job = get_job(ctx, prev["job_id"])
    cv_id, cv = cv_for(ctx, job, prev["cv_id"])
    merged = {**prev["result"], **(result or {})}
    try:
        merged, warnings = validate(merged, cv)
    except (KeyError, TypeError) as e:
        raise InvalidInput(f"Invalid CV edit: {e}") from e
    letter = cover_letter if cover_letter is not None else prev["cover_letter"]
    merged["cover_letter"] = letter
    return _store(ctx, job, cv_id, merged, warnings, letter, cv)


def preview(ctx: AppContext, app_id, result):
    """Live preview of unsaved edits: validated, rendered, not stored."""
    app = get_application(ctx, app_id)
    _, cv = cv_for(ctx, get_job(ctx, app["job_id"]), app["cv_id"])
    merged, warnings = validate({**app["result"], **result}, cv)
    return {"html": render(ctx, merged, cv), "warnings": warnings}


def html(ctx: AppContext, app_id):
    app = get_application(ctx, app_id)
    _, cv = cv_for(ctx, get_job(ctx, app["job_id"]), app["cv_id"])
    return {"html": render(ctx, app["result"], cv)}


def files(ctx: AppContext, app_id):
    app = get_application(ctx, app_id)
    job = get_job(ctx, app["job_id"])
    user = ctx.repos.users.get()
    base = f"{_slug((user or {}).get('full_name') or 'CV')}_{_slug(job['company'])}"
    out = {}
    for key, path, name in (("cv_pdf", app["cv_pdf_path"], f"{base}_CV.pdf"),
                            ("cv_html", app["cv_html_path"], f"{base}_CV.html"),
                            ("cover_letter", app["cover_letter_path"], f"{base}_Cover_Letter.txt")):
        out[key] = ctx.storage.signed_url(path, 300, download_name=name) if path else None
    return out
