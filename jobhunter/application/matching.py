"""Rank jobs: embedding filter against every CV (best CV wins, feedback-boosted), then LLM fit scoring
with strict JSON structured outputs."""
from ..domain import eligibility, stages
from ..domain.cv import as_text, with_contact
from ..domain.errors import InvalidInput
from .notifications import notify
from .runs import RunContext

SCORE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fit_score", "summary", "matched_requirements", "gaps", "dealbreakers",
                 "relevant_bullet_ids", "eligible", "ineligible_reason", "remote_policy",
                 "visa_sponsorship", "location_restrictions", "salary", "required_skills",
                 "missing_skills", "seniority"],
    "properties": {
        "fit_score": {"type": "integer", "description": "0-100 overall fit"},
        "summary": {"type": "string", "description": "One or two sentences on the fit"},
        "matched_requirements": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "dealbreakers": {"type": "array", "items": {"type": "string"},
                         "description": "e.g. needs 8+ years, security clearance, wrong country"},
        "relevant_bullet_ids": {"type": "array", "items": {"type": "string"}},
        "eligible": {"type": "boolean",
                     "description": "false only if the candidate legally/practically cannot take this job "
                                    "(work authorisation, sponsorship, citizenship, clearance, region lock)"},
        "ineligible_reason": {"type": "string", "description": "empty when eligible"},
        "remote_policy": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
        "visa_sponsorship": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "location_restrictions": {"type": "array", "items": {"type": "string"},
                                  "description": "countries/regions/timezones the job is limited to"},
        "salary": {"type": "string", "description": "as stated in the posting, else empty"},
        "required_skills": {"type": "array", "items": {"type": "string"},
                            "description": "short canonical skill names the job asks for, e.g. 'Kubernetes'"},
        "missing_skills": {"type": "array", "items": {"type": "string"},
                           "description": "required_skills the candidate's CV does not show"},
        "seniority": {"type": "string", "description": "e.g. junior, mid, senior, staff"},
    },
}

SCORE_SYSTEM = """You are a strict technical recruiter. Compare the candidate CV to the job posting.
Score honestly: 90+ means an excellent match on core requirements and seniority, 70-89 a strong
match with minor gaps, 50-69 a stretch, below 50 a poor fit. Hard requirements the candidate
clearly lacks (years of experience, required citizenship/clearance, location) go in dealbreakers
and should pull the score down heavily. Only reference bullet ids that appear in the CV.

Eligibility: use the CANDIDATE CONSTRAINTS. Mark eligible=false only when the posting clearly
excludes the candidate (e.g. requires existing work authorisation they don't have and won't sponsor,
citizenship/clearance, or is remote-but-restricted to regions they are not in). When unclear, stay
eligible and use "unknown". Use short canonical names for skills (e.g. "PostgreSQL", "Kubernetes").
If PAST FEEDBACK is given, it shows what the candidate liked/disliked: weigh similar jobs accordingly."""


def ensure_cv_embeddings(run: RunContext):
    cvs = run.repos.cvs
    for cv in cvs.missing_embeddings():
        cvs.set_embedding(cv["id"], run.llm.embed([as_text(cv["cv"])], purpose="embed_cv")[0])


def embed_filter(run: RunContext, threshold, job_ids=None, boost_weight=0.5):
    """Embed new jobs, pick the best-matching CV for each, and drop those below `threshold`.
    Explicitly requested jobs (job_ids) are never filtered out."""
    r = run.repos
    ensure_cv_embeddings(run)
    if not r.cvs.any_embedded():
        raise InvalidInput("No CV yet: upload one before matching.")
    rows = r.jobs.needing_embedding(job_ids)
    if rows:
        vecs = run.llm.embed([f"{j['title']}\n{j['company']}\n{j['description']}" for j in rows], purpose="embed_jobs")
        for j, v in zip(rows, vecs):
            r.jobs.set_embedding(j["id"], v)
    ids = list(job_ids) if job_ids else [j["id"] for j in rows]
    if not ids:
        return 0, 0
    kept = 0
    for c in r.jobs.similarity_candidates(ids):
        sim = eligibility.boosted_similarity(c["sim"], c["up_sim"], c["dn_sim"], boost_weight)
        passed = sim >= threshold or bool(job_ids)
        kept += passed
        fields = {"similarity": sim, "cv_id": c["cv_id"]}
        if not job_ids:
            fields["stage"] = "new" if passed else "filtered_out"
        r.jobs.update(c["id"], **fields)
    run.log(f"Embedding filter: {kept}/{len(ids)} jobs passed (threshold {threshold}).")
    return len(ids), kept


def score(run: RunContext, limit, job_ids=None):
    """LLM fit scoring. Returns [(row, result|None, error|None)]."""
    r = run.repos
    rows = r.jobs.to_score(limit, job_ids)
    user = r.users.get()
    constraints = eligibility.constraints_text(user)
    feedback = eligibility.feedback_text(r.jobs.feedback_examples())
    default_cv = r.cvs.default()
    cv_text = {}
    results = []
    for i, job in enumerate(rows):
        run.progress(i, len(rows), f"Scoring {job['title']} at {job['company']}")
        stage_ok = job["stage"] in stages.RESCORABLE
        reason = eligibility.precheck(job, user)
        if reason:
            res = eligibility.ineligible_fit(reason, job)
            r.jobs.update(job["id"], fit_score=0, fit=res, **({"stage": "ineligible"} if stage_ok else {}))
            results.append((job, res, None))
            continue
        cv_id = job["cv_id"] or (default_cv or {}).get("id")
        if cv_id not in cv_text:
            cv_row = r.cvs.get(cv_id) if cv_id else None
            cv_text[cv_id] = as_text(with_contact(cv_row["cv"], user)) if cv_row else ""
        # CV goes first so the repeated prefix benefits from OpenAI's automatic prompt caching.
        msg = (f"CANDIDATE CV:\n{cv_text[cv_id]}\n\n---\nCANDIDATE CONSTRAINTS:\n{constraints}\n\n"
               f"{feedback}\n\n---\nJOB: {job['title']} at {job['company']} ({job['location']})\n\n"
               f"{job['description'][:12000]}")
        try:
            res = run.llm.structured(run.llm.fast_model, SCORE_SYSTEM, msg, SCORE_SCHEMA, "job_fit", purpose="score")
        except Exception as e:  # noqa: BLE001
            results.append((job, None, str(e)))
            continue
        fields = {"fit_score": res["fit_score"], "fit": res, "cv_id": cv_id, "visa_sponsorship": res["visa_sponsorship"],
                  "remote_policy": job.get("remote_policy") or res["remote_policy"],
                  "salary": job.get("salary") or res["salary"] or None}
        if stage_ok:
            fields["stage"] = "scored" if res["eligible"] else "ineligible"
        r.jobs.update(job["id"], **fields)
        results.append((job, res, None))
    run.progress(len(rows), len(rows))
    return results


def match(run: RunContext, params):
    m = run.repos.settings.get()["matching"] or {}
    job_ids = params.get("job_ids")
    total, kept = embed_filter(run, m.get("similarity_threshold", 0.25), job_ids=job_ids)
    scored, alerts = 0, []
    for job, res, err in score(run, params.get("limit") or m.get("score_limit", 30), job_ids=job_ids):
        if err:
            run.log(f"! #{job['id']} {job['title']}: {err}")
            continue
        scored += 1
        flag = f" ⚠ {res['ineligible_reason']}" if not res["eligible"] else ""
        run.log(f"{res['fit_score']:>3}  #{job['id']} [{job['company']}] {job['title']}{flag}")
        if res["eligible"] and res["fit_score"] >= m.get("alert_min_fit", 80):
            alerts.append((job, res))
    if alerts and not params.get("quiet"):
        job, res = max(alerts, key=lambda a: a[1]["fit_score"])
        notify(run.app, "match", f"{len(alerts)} new top match{'es' if len(alerts) > 1 else ''}",
               f"Best: {job['title']} at {job['company']} ({res['fit_score']})", job_id=job["id"])
    return {"embedded": total, "kept": kept, "scored": scored, "alerts": len(alerts)}
