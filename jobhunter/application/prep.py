"""Interview prep pack for one job, grounded in the CV and the company's own site."""
import json

from ..domain.cv import as_text, with_contact
from ..domain.errors import InvalidInput
from ..domain.truthfulness import valid_bullet_ids
from .contacts import company_domain
from .runs import RunContext
from .tracker import get_job

_STR = {"type": "string"}
PREP_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["company_brief", "why_you", "likely_questions", "questions_to_ask", "red_flags", "study_topics"],
    "properties": {
        "company_brief": _STR,
        "why_you": {"type": "array", "items": _STR},
        "likely_questions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["question", "type", "answer_outline", "bullet_ids"],
            "properties": {"question": _STR,
                           "type": {"type": "string", "enum": ["technical", "behavioural", "role", "company"]},
                           "answer_outline": _STR, "bullet_ids": {"type": "array", "items": _STR}}}},
        "questions_to_ask": {"type": "array", "items": _STR},
        "red_flags": {"type": "array", "items": _STR},
        "study_topics": {"type": "array", "items": _STR},
    },
}
PREP_SYSTEM = """You are an interview coach preparing a candidate for one specific job.
- company_brief: 3-5 sentences using ONLY the job posting and the company website text given. If the
  site text is missing, say what is known from the posting and nothing more.
- why_you: 3-5 short points mapping the candidate's real experience to the job's needs.
- likely_questions: 8-12 questions this company would plausibly ask for this role (mix of technical,
  behavioural, role-specific). answer_outline: 2-4 sentences using the candidate's real experience;
  bullet_ids: the CV bullet ids that support the answer (only ids that exist in the CV).
- questions_to_ask: 5 sharp questions for the interviewer.
- red_flags: gaps or concerns the interviewer may probe, with how to address them honestly.
- study_topics: technologies/concepts from the posting worth revising before the interview."""


def prep(run: RunContext, params):
    ctx, r = run.app, run.repos
    job = get_job(ctx, params["job_id"])
    cv_row = (r.cvs.get(job["cv_id"]) if job["cv_id"] else None) or r.cvs.default()
    if not cv_row:
        raise InvalidInput("No CV available: upload one first.")
    cv = with_contact(cv_row["cv"], r.users.get())
    domain = company_domain(ctx, job)
    site = ctx.web.site_text(domain) if domain else ""
    msg = (f"CANDIDATE CV:\n{as_text(cv)}\n\n---\nJOB: {job['title']} at {job['company']} ({job['location']})\n"
           f"{job['description'][:12000]}\n\nFIT ANALYSIS: {json.dumps(job['fit'] or {})}\n\n---\n"
           f"COMPANY WEBSITE TEXT ({domain or 'unknown'}):\n{site or '(not available)'}")
    res = run.llm.structured(run.llm.strong_model, PREP_SYSTEM, msg, PREP_SCHEMA, "interview_prep", purpose="prep")
    for q in res["likely_questions"]:
        q["bullet_ids"] = valid_bullet_ids(q["bullet_ids"], cv)
    row = r.prep.create(job["id"], res)
    run.log(f"Prep pack ready for #{job['id']}")
    return {"prep_id": row["id"]}
