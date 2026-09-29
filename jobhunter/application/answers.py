"""Write answers to application-form questions ("Message to the recruiter", "Why this company?"),
grounded in the CV and the posting, and following the posting's own instructions."""
import json

from ..domain.cv import as_text, bullet_index, with_contact
from ..domain.errors import InvalidInput, NotFound
from ..domain.truthfulness import valid_bullet_ids
from .context import AppContext
from .tracker import get_job
from .usage import metered_llm

TONES = {
    "direct": "direct and confident, plain language",
    "warm": "warm and personable, still concise",
    "formal": "formal and polished",
    "enthusiastic": "energetic and enthusiastic, without hype or clichés",
}
ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answer", "bullet_ids_used"],
    "properties": {"answer": {"type": "string"},
                   "bullet_ids_used": {"type": "array", "items": {"type": "string"},
                                       "description": "ids of the CV bullets the answer draws facts from"}},
}
ANSWER_SYSTEM = """You write one answer, in the candidate's voice (first person), for a job application form.

TRUTHFULNESS (absolute): use only facts from the CANDIDATE CV. Never invent employers, numbers, technologies,
titles or outcomes. You may rephrase and select. List the CV bullet ids you drew facts from.

Follow the QUESTION exactly, and any instructions the employer gives in the posting (e.g. "no cover letter
template", "tell us what you have built", word limits). Be specific to this company and role, using only
what the posting says about them. No greetings or sign-offs unless the question asks for a message or
letter. No placeholders. Avoid clichés ("passionate", "results-driven", "I am excited to apply").
Stay within the word limit."""

EDITABLE = {"answer", "question"}


def generate(ctx: AppContext, job_id, question, max_words=150, tone="direct", emphasis=None):
    question = (question or "").strip()
    if not question:
        raise InvalidInput("Paste the question or instructions you need an answer for.")
    if tone not in TONES:
        raise InvalidInput(f"tone must be one of {', '.join(TONES)}")
    max_words = max(20, min(int(max_words or 150), 800))
    r = ctx.repos
    job = get_job(ctx, job_id)
    app = r.applications.latest(job_id)
    cv_row = r.cvs.get((app or {}).get("cv_id") or job["cv_id"] or 0) or r.cvs.default()
    if not cv_row:
        raise InvalidInput("No CV available: upload one first.")
    cv = with_contact(cv_row["cv"], r.users.get())
    fit = job["fit"] or {}
    msg = (f"CANDIDATE CV:\n{as_text(cv)}\n\n---\nJOB: {job['title']} at {job['company']} ({job['location']})\n"
           f"{job['description'][:10000]}\n\n---\nFIT ANALYSIS: {json.dumps({k: fit.get(k) for k in ('summary', 'matched_requirements', 'gaps')})}\n"
           + (f"\nCOVER LETTER ALREADY WRITTEN (for consistency, don't copy it):\n{app['cover_letter'][:2500]}\n" if app else "")
           + f"\n---\nQUESTION / INSTRUCTIONS FROM THE FORM:\n{question}\n\nLENGTH: at most {max_words} words."
           f"\nTONE: {TONES[tone]}." + (f"\nEMPHASISE: {emphasis.strip()}" if emphasis and emphasis.strip() else ""))
    llm = metered_llm(ctx)
    res = llm.structured(llm.strong_model, ANSWER_SYSTEM, msg, ANSWER_SCHEMA, "form_answer", purpose="answer",
                         effort="low")
    evidence = valid_bullet_ids(res["bullet_ids_used"], cv)
    return r.answers.create(job_id=job_id, question=question, max_words=max_words, tone=tone,
                            emphasis=(emphasis or None), answer=res["answer"].strip(), evidence=evidence)


def with_evidence_text(ctx: AppContext, rows, job):
    """Attach the CV bullet text for each evidence id, so the UI can show what an answer is based on."""
    cv_row = ctx.repos.cvs.get(job["cv_id"] or 0) or ctx.repos.cvs.default()
    idx = bullet_index(cv_row["cv"]) if cv_row else {}
    return [{**a, "evidence_text": [{"id": b, "text": idx[b][2]} for b in a["evidence"] if b in idx]} for a in rows]


def list_for_job(ctx: AppContext, job_id):
    job = get_job(ctx, job_id)
    return with_evidence_text(ctx, ctx.repos.answers.for_job(job_id), job)


def edit(ctx: AppContext, answer_id, **fields):
    if not ctx.repos.answers.get(answer_id):
        raise NotFound("Answer not found")
    return ctx.repos.answers.update(answer_id, **{k: v for k, v in fields.items() if k in EDITABLE and v is not None})
